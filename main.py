"""
===============================================================================
綴り文庫室（つづりぶんこしつ）
Copyright (c) 2026 AglaoDev-jp

Licensed under the MIT License.
See LICENSE-CODE.txt for the full license text.

This project uses the following third-party libraries:

- Tkinter
  Copyright © Regents of the University of California,
  Sun Microsystems, Inc., Scriptics Corporation,
  and other contributors.
  Licensed under the Tcl/Tk License.
  https://www.tcl.tk/software/tcltk/license.html

- Requests
  Copyright © 2025 Kenneth Reitz and contributors.
  Licensed under the Apache License 2.0.
  See the LICENSE and NOTICE files for details.

- pygame
  Copyright © 2000–2025 Pygame developers.
  Licensed under the GNU LGPL v2.1.
  https://www.pygame.org/docs/license.html

Development of this file was supported by OpenAI's ChatGPT
(including Chat and Work) for design discussions, implementation
assistance, code review, documentation, and refinement.

Special thanks to the developers and contributors of Python,
Tkinter, Requests, pygame, Ollama, VOICEVOX, and all related
open-source projects that made this application possible.
===============================================================================

"""

# main.py

from __future__ import annotations

import json
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from game_engine import GameDataError, GameEngine, Scene
from llm_client import LLMClientError, OllamaClient, OllamaModelInfo
from voicevox_client import VoicePipeline, VoicevoxClient, VoicevoxError


# 実行時のカレントディレクトリではなく、このPythonファイルの場所を基準に。
# これにより、どのフォルダから起動しても同じ設定・ログ保存先を参照できる。
BASE_DIR = Path(__file__).parent
SETTINGS_PATH = BASE_DIR / "data" / "game_settings.json"

# mkdir(exist_ok=True)は、既存フォルダがあってもエラーにしない。
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
VOICE_CACHE_DIR = BASE_DIR / "voice_cache"
VOICE_CACHE_DIR.mkdir(exist_ok=True)

# Tkinterのafter()へ渡す時間はミリ秒単位。
# 値を小さくすると速くなるが、0に近づけすぎると画面更新が慌ただしくなる。
WAITING_ANIMATION_INTERVAL_MS = 450
TYPING_INTERVAL_MS = 30
TYPING_COMMA_INTERVAL_MS = 90
TYPING_SENTENCE_INTERVAL_MS = 180
TYPING_NEWLINE_INTERVAL_MS = 120


def load_settings() -> dict[str, Any]:
    """
    JSON設定ファイルをUTF-8で読み込み、Pythonの辞書として返す。

    起動に必須の設定なので、ファイル不在やJSON不正はここでは握りつぶさず、
    起動時エラーとして知らせる。
    """
    with SETTINGS_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


# 設定は起動時に1回だけ読み込む。GENRESは画面の選択肢とプロンプトの対応表。
SETTINGS = load_settings()
GENRES = SETTINGS["genres"]


class AdventureApp:
    """
    画面状態と各バックエンド処理を結びつけるTkinterアプリ。

    ``busy`` と ``typing_active`` を別々に持つ点が重要。
    ``busy`` はLLM生成などの重い処理中、``typing_active`` は生成済み文章の
    演出表示中って意味。どちらか一方でも操作可能にすると、二重送信や
    表示途中の選択が起こるため、入力欄の有効化条件を両方から判断。
    """

    def __init__(self, root: tk.Tk) -> None:
        """ウィンドウ状態、進行状態、音声処理、画面部品を初期化する。"""
        self.root = root
        self.root.title("綴り文庫室")
        self.root.geometry("850x650")
        self.root.minsize(720, 520)

        # ゲーム全体の状態。開始前はengineが存在しない。
        self.engine: GameEngine | None = None
        self.busy = False

        # 現在場面の音声キャッシュ群を識別し、場面通過時の削除に使う。
        self.current_voice_cache_key: str | None = None

        # コンボボックスの「詳しい表示名」から、APIへ渡す実モデル名へ戻す辞書。
        self.model_name_by_display: dict[str, str] = {}

        # after()のIDと表示位置を保持し、待機表示を安全に更新・停止する。
        self.waiting_after_id: str | None = None
        self.waiting_dot_count = 0

        # タイピング表示はafter()で1文字ずつ予約する小さな状態機械。
        # IDを保持しておくと、場面切り替え時に未実行の予約を取り消せる。
        self.typing_after_id: str | None = None
        self.typing_text = ""
        self.typing_index = 0
        self.typing_active = False
        self.typing_complete_callback: Callable[[], None] | None = None

        # 音声用の2本のワーカースレッドはアプリ起動中ずっと再利用する。
        self.voice_pipeline = VoicePipeline(
            base_url=SETTINGS["voicevox"]["base_url"],
            cache_dir=VOICE_CACHE_DIR,
            on_error=self._on_voice_error,
        )

        # StringVar / BooleanVarは、GUI部品とPython値を同期するTkinter変数。
        self.genre_var = tk.StringVar(value=next(iter(GENRES)))
        self.model_var = tk.StringVar(value=SETTINGS["ollama"]["default_model"])
        self.voice_enabled_var = tk.BooleanVar(value=False)
        self.speaker_var = tk.StringVar(
            value=str(SETTINGS["voicevox"]["speaker_id"])
        )

        self._build_ui()
        # 入力欄が無効なタイピング中でもEnterを受け取れるよう、rootへ登録する。
        self.root.bind("<Return>", self._on_enter)
        self._write(
            "ジャンルとモデルを選び、「ゲーム開始」を押してください。\n"
            "ゲーム中は入力欄へ a または b を入力します。\n"
            "本文の表示中にEnterを押すと、全文をすぐに表示します。\n"
        )
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        # 画面表示後にOllamaからモデル一覧を自動取得する。
        self.root.after(300, self.refresh_models)

    def _build_ui(self) -> None:
        """設定欄、本文欄、選択入力欄を作り、gridで配置する。"""
        # 本文欄の行・列だけを可変にし、ウィンドウ拡大分を受け取らせる。
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        # 上段: ジャンル、モデル、ゲーム・音声設定。
        settings_frame = tk.Frame(self.root)
        settings_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        settings_frame.grid_columnconfigure(3, weight=1)

        tk.Label(settings_frame, text="ジャンル:").grid(
            row=0, column=0, sticky="w"
        )
        self.genre_combo = ttk.Combobox(
            settings_frame,
            textvariable=self.genre_var,
            values=list(GENRES.keys()),
            state="readonly",
            width=22,
        )
        self.genre_combo.grid(row=0, column=1, padx=(5, 15), sticky="w")

        tk.Label(settings_frame, text="モデル:").grid(
            row=0, column=2, sticky="w"
        )
        self.model_combo = ttk.Combobox(
            settings_frame,
            textvariable=self.model_var,
            values=[self.model_var.get()],
            state="readonly",
            width=36,
        )
        self.model_combo.grid(row=0, column=3, padx=5, sticky="ew")

        self.refresh_button = tk.Button(
            settings_frame,
            text="モデル更新",
            command=self.refresh_models,
        )
        self.refresh_button.grid(row=0, column=4, padx=(5, 0))

        self.start_button = tk.Button(
            settings_frame,
            text="ゲーム開始",
            command=self.start_game,
        )
        self.start_button.grid(row=1, column=0, pady=(8, 0), sticky="w")

        self.restart_button = tk.Button(
            settings_frame,
            text="最初から",
            command=self.start_game,
            state=tk.DISABLED,
        )
        self.restart_button.grid(row=1, column=1, pady=(8, 0), sticky="w")

        self.retry_button = tk.Button(
            settings_frame,
            text="直前の選択肢へ",
            command=self.retry_last_choice,
            state=tk.DISABLED,
        )
        self.retry_button.grid(row=1, column=2, pady=(8, 0), sticky="w")

        self.voice_check = tk.Checkbutton(
            settings_frame,
            text="VOICEVOX読み上げ",
            variable=self.voice_enabled_var,
        )
        self.voice_check.grid(
            row=1, column=3, pady=(8, 0), sticky="w"
        )

        tk.Label(settings_frame, text="話者ID:").grid(
            row=1, column=4, pady=(8, 0), sticky="e"
        )
        self.speaker_entry = tk.Entry(
            settings_frame,
            textvariable=self.speaker_var,
            width=7,
        )
        self.speaker_entry.grid(
            row=1, column=5, pady=(8, 0), sticky="w"
        )

        # 中段: スクロール可能な物語表示。ユーザー編集を防ぐため通常はDISABLED。
        self.text_area = scrolledtext.ScrolledText(
            self.root,
            wrap=tk.WORD,
            font=("", 11),
            state=tk.DISABLED,
        )
        self.text_area.grid(
            row=1, column=0, sticky="nsew", padx=10, pady=(0, 10)
        )

        # 下段: a / b入力、決定、音声停止。
        input_frame = tk.Frame(self.root)
        input_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        input_frame.grid_columnconfigure(0, weight=1)

        self.entry = tk.Entry(input_frame, font=("", 12), state=tk.DISABLED)
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        self.send_button = tk.Button(
            input_frame,
            text="決定",
            command=self.submit_choice,
            state=tk.DISABLED,
        )
        self.send_button.grid(row=0, column=1)

        self.stop_voice_button = tk.Button(
            input_frame,
            text="音声停止",
            command=self.voice_pipeline.stop,
        )
        self.stop_voice_button.grid(row=0, column=2, padx=(5, 0))

    def refresh_models(self) -> None:
        """Ollamaのモデル一覧取得をバックグラウンドで開始する。"""
        if self.busy:
            return

        # 通信中の多重クリックを防ぎ、GUIを止めないようdaemonスレッドへ渡す。
        self._set_busy(True)
        threading.Thread(target=self._refresh_models_worker, daemon=True).start()

    def _refresh_models_worker(self) -> None:
        """
        モデル一覧を取得するワーカースレッド。

        Tkinter部品をこのスレッドから直接更新せず、成功・失敗・終了処理を
        すべて ``root.after(0, ...)`` でメインスレッドへ予約する。
        """
        client = OllamaClient(
            base_url=SETTINGS["ollama"]["base_url"],
            model=self._selected_model_name(),
        )
        try:
            models = client.list_models()
            if not models:
                raise LLMClientError("利用できるモデルが見つかりません。")
            # lambdaに結果を閉じ込め、メインループの次の機会に画面へ反映する。
            self.root.after(0, lambda: self._apply_models(models))
        except LLMClientError as exc:
            self.root.after(0, lambda: self._show_error(str(exc)))
        finally:
            self.root.after(0, lambda: self._set_busy(False))

    def _apply_models(self, models: list[OllamaModelInfo]) -> None:
        """取得したモデルをコンボボックスへ反映し、可能なら現在選択を維持する。"""
        current_model_name = self._selected_model_name()

        # 画面にはサイズ等を含むdisplay_name、APIには短いmodel.nameを使う。
        self.model_name_by_display = {
            model.display_name: model.name for model in models
        }
        display_values = list(self.model_name_by_display.keys())
        self.model_combo["values"] = display_values

        # 更新前と同じ実モデル名を探す。削除済みなら一覧の先頭へフォールバック。
        selected_display = next(
            (
                display
                for display, name in self.model_name_by_display.items()
                if name == current_model_name
            ),
            display_values[0],
        )
        self.model_var.set(selected_display)
        self._write(
            f"\n--- Ollamaから{len(models)}個のモデルを取得しました ---\n"
        )

    def _selected_model_name(self) -> str:
        """コンボボックスの表示文字列から実際のOllamaモデル名を返す。"""
        selected = self.model_var.get().strip()
        return self.model_name_by_display.get(selected, selected)

    def start_game(self) -> None:
        """
        選択中のジャンル・モデルで、新しいゲームを非同期に開始する。

        前回の表示予約・音声・キャッシュを片付けてからGameEngineを作り直すため、
        「ゲーム開始」と「最初から」の両方から安全に呼び出せる。
        """
        if self.busy:
            return

        # 古いゲームの非同期表示・音声が新しいゲームへ混ざらないよう先に停止する。
        self._cancel_typing()
        self._stop_waiting_animation()
        self.voice_pipeline.stop()
        self._clear_all_voice_cache()
        self.current_voice_cache_key = None

        # GUIの装飾付き表示名ではなく、Ollamaが認識する実モデル名を使う。
        model = self._selected_model_name()
        if not model:
            self._show_error("モデル名を入力してください。")
            return

        genre_name = self.genre_var.get()
        genre_prompt = GENRES[genre_name]

        # 1ゲームで使うクライアントとエンジンを、現在の設定から組み立てる。
        client = OllamaClient(
            base_url=SETTINGS["ollama"]["base_url"],
            model=model,
            timeout=SETTINGS["ollama"]["timeout_seconds"],
        )
        self.engine = GameEngine(
            llm_client=client,
            genre_name=genre_name,
            genre_prompt=genre_prompt,
            total_scenes=SETTINGS["game"]["total_scenes"],
            max_retries=SETTINGS["game"]["max_retries"],
            logger=self._log_internal,
        )

        self._clear()
        self.retry_button.config(state=tk.DISABLED)
        self._write(f"=== {genre_name} ===\n")
        self.restart_button.config(state=tk.NORMAL)
        # LLM生成中は入力を無効化し、待機アニメーションだけを動かす。
        self._set_busy(True)
        self._start_waiting_animation()
        threading.Thread(target=self._start_game_worker, daemon=True).start()

    def _start_game_worker(self) -> None:
        """第1場面を生成し、結果をTkinterのメインスレッドへ戻す。"""
        try:
            if self.engine is None:
                return
            scene = self.engine.start()
            self.root.after(0, lambda: self._show_scene(scene))
        except (LLMClientError, GameDataError, Exception) as exc:
            # 予期した生成エラーに加え、ログを残すため想定外例外も最終的に捕捉する。
            self._log_exception(exc)
            message = f"ゲーム開始に失敗しました。\n{exc}"
            self.root.after(
                0,
                lambda message=message: self._finish_with_error(message),
            )

    def submit_choice(self) -> None:
        """入力欄のa / bを検証し、正誤判定をワーカースレッドへ渡す。"""
        if self.busy or self.engine is None:
            return

        choice = self.entry.get().strip().lower()
        self.entry.delete(0, tk.END)

        if choice not in {"a", "b"}:
            self._write("\n「a」または「b」を入力してください。\n")
            return

        # 有効な入力だけを履歴へ確定表示する。
        self._write(f"\nあなたの選択: {choice}\n")
        self._set_busy(True)
        self._start_waiting_animation()
        threading.Thread(
            target=self._choice_worker,
            args=(choice,),
            daemon=True,
        ).start()

    def _choice_worker(self, choice: str) -> None:
        """GameEngineの選択処理を実行し、status別表示へ引き渡す。"""
        try:
            if self.engine is None:
                return
            result = self.engine.choose(choice)
            self.root.after(0, lambda: self._handle_result(result))
        except Exception as exc:
            self._log_exception(exc)
            message = f"ゲーム進行中にエラーが発生しました。\n{exc}"
            self.root.after(
                0,
                lambda message=message: self._finish_with_error(message),
            )

    def _handle_result(self, result: dict[str, object]) -> None:
        """
        GameEngineから返ったstatusに応じて、次に表示する内容を決める。

        ゲームルールの判定はGameEngine、見せ方と音声はこのメソッドという
        分担になっている。
        """
        status = result.get("status")

        # 現在のGUIでは送信前にも検証するが、エンジン側の防御結果にも対応。
        if status == "invalid":
            self._stop_waiting_animation()
            self._write("\n「a」または「b」を入力してください。\n")
            self._set_busy(False)
            return

        if status == "next_scene":
            # 通過済み場面の音声は削除し、正解結果と次場面を連続表示・再生。
            self.voice_pipeline.stop()
            self._delete_current_scene_voice_cache()

            result_text = str(result.get("result_text", ""))
            scene = result["scene"]
            if not isinstance(scene, Scene):
                self._finish_with_error("次の場面データを読み取れませんでした。")
                return
            self._show_scene(
                scene,
                transition_voice_text=result_text,
            )
            return

        if status == "bad_end":
            # タイピング完了までは再挑戦ボタンを無効にし、表示途中の操作できなくする。
            text = (
                f"\n\n=== BAD END ===\n"
                f"{result['title']}\n\n"
                f"{result['text']}\n\n"
                "「直前の選択肢へ」で同じ場面から再挑戦できます。\n"
                "「最初から」で最初の場面からやり直せます。\n"
            )
            self.retry_button.config(state=tk.DISABLED)
            self._prepare_narrative(
                display_text=text,
                voice_parts=[
                    (
                        f"バッドエンド。{result['title']}。{result['text']}",
                        f"{self.current_voice_cache_key}_bad",
                    )
                ],
                on_typing_complete=lambda: self.retry_button.config(
                    state=tk.NORMAL
                ),
            )
            self._disable_choice()
            return

        if status == "good_end":
            # クリア後は選択入力を閉じ、複数の終了情報を1つの表示へまとめる。
            self.voice_pipeline.stop()
            self._delete_current_scene_voice_cache()
            self.retry_button.config(state=tk.DISABLED)

            # GameEngineが作った4種類の終了情報を、読みやすい順番で表示する。
            good_end_text = str(result.get("text", ""))
            epilogue = str(result.get("epilogue", ""))
            clear_message = str(result.get("clear_message", ""))
            ai_comment = str(result.get("ai_comment", ""))
            play_judgement = str(result.get("play_judgement", ""))
            bad_end_count = int(result.get("bad_end_count", 0))
            retry_count = int(result.get("retry_count", 0))
            choice_count = int(result.get("choice_count", 0))

            text = (
                f"\n\n=== GOOD END ===\n"
                f"{result['title']}\n\n"
                f"{good_end_text}\n\n"
                "=== EPILOGUE ===\n"
                f"{epilogue}\n\n"
                "=== GAME CLEAR ===\n"
                f"{clear_message}\n\n"
                "=== PLAY RECORD ===\n"
                f"判定: {play_judgement}\n"
                f"バッドエンド到達回数: {bad_end_count}\n"
                f"直前の選択肢へ戻った回数: {retry_count}\n"
                f"総選択回数: {choice_count}\n\n"
                "=== AI COMMENT ===\n"
                f"{ai_comment}\n\n"
                "「最初から」ボタンで新しい物語を始められます。\n"
            )
            self._prepare_narrative(
                display_text=text,
                voice_parts=[
                    (
                        f"グッドエンド。{result['title']}。{good_end_text}",
                        "good_ending_main",
                    ),
                    (f"エピローグ。{epilogue}", "good_ending_epilogue"),
                    (clear_message, "good_ending_clear"),
                    (f"AIコメント。{ai_comment}", "good_ending_comment"),
                ],
            )
            self._disable_choice()

    def _show_scene(
        self,
        scene: Scene,
        *,
        transition_voice_text: str = "",
    ) -> None:
        """
        Sceneを画面表示用文字列と読み上げ用文字列へ整形する。

        画面用には記号や改行を残し、音声用には「選択肢a」のような読みを
        補っている。同じ内容でも出力先に合わせて表現を分ける考え方である。
        """
        self.retry_button.config(state=tk.DISABLED)
        self.current_voice_cache_key = f"scene_{scene.number}"

        # display_textはユーザーが目で読むためのレイアウトを優先する。
        display_text = (
            f"\n\n--- 場面 {scene.number} / "
            f"{SETTINGS['game']['total_scenes']} ---\n"
            f"【{scene.title}】\n\n"
            f"{scene.scene_text}\n\n"
            f"a. {scene.choice_a}\n"
            f"b. {scene.choice_b}\n"
        )
        if transition_voice_text:
            display_text = f"\n{transition_voice_text}\n" + display_text

        # scene_voice_textはVOICEVOXが自然に読み分けられる句読点を補う。
        scene_voice_text = (
            f"{scene.title}。{scene.scene_text}。"
            f"選択肢a、{scene.choice_a}。"
            f"選択肢b、{scene.choice_b}。"
        )

        if transition_voice_text:
            # 前場面の正解結果と次場面を1要求にまとめ、途中で音声を止めない。
            voice_parts = [
                (
                    transition_voice_text,
                    f"{self.current_voice_cache_key}_transition",
                ),
                (scene_voice_text, self.current_voice_cache_key),
            ]
        else:
            voice_parts = [(scene_voice_text, self.current_voice_cache_key)]

        self._prepare_narrative(
            display_text=display_text,
            voice_parts=voice_parts,
        )

    def _prepare_narrative(
        self,
        *,
        display_text: str,
        voice_parts: list[tuple[str, str]],
        on_typing_complete: Callable[[], None] | None = None,
    ) -> None:
        """
        最初の音声チャンクを準備してから、本文表示と音声再生を開始する。

        音声が無効な場合や話者IDが不正な場合は、音声を待たずに本文を表示する。
        """
        self._disable_choice()
        # 前の場面の再生・待機ジョブを止める。生成済みキャッシュは残る。
        self.voice_pipeline.stop()

        # 読み上げOFFなら、音声準備スレッドを作らず直ちに本文表示へ進む。
        if not self.voice_enabled_var.get():
            self._begin_narrative(
                display_text=display_text,
                voice_parts=[],
                speaker_id=None,
                on_typing_complete=on_typing_complete,
            )
            return

        # GUI入力は文字列なので、APIへ渡す前に整数へ変換・検証する。
        try:
            speaker_id = int(self.speaker_var.get())
        except ValueError:
            self._write("\n--- 話者IDは数字で入力してください ---\n")
            self._begin_narrative(
                display_text=display_text,
                voice_parts=[],
                speaker_id=None,
                on_typing_complete=on_typing_complete,
            )
            return

        # 最初のWAV生成は通信処理なので、Tkinterを固めないよう別スレッドで行う。
        threading.Thread(
            target=self._prepare_first_voice_chunk_worker,
            args=(
                display_text,
                voice_parts,
                speaker_id,
                on_typing_complete,
            ),
            daemon=True,
            name="first-voice-preparer",
        ).start()

    def _prepare_first_voice_chunk_worker(
        self,
        display_text: str,
        voice_parts: list[tuple[str, str]],
        speaker_id: int,
        on_typing_complete: Callable[[], None] | None,
    ) -> None:
        """
        最初の音声チャンクだけを、画面を止めずに先行生成する。

        最初のWAVが完成してから本文と再生を同時に始めることで、
        文字だけが大きく先行する体感を抑える。後続チャンクはVoicePipelineが
        再生と並行して生成する。
        """
        voice_error: str | None = None
        try:
            self.voice_pipeline.prepare_first_chunk(
                voice_parts,
                speaker_id=speaker_id,
            )
        except VoicevoxError as exc:
            # VOICEVOXが使えなくても、物語の本文は続けて表示する。
            voice_error = str(exc)

        # voice_errorも値としてメインスレッドへ渡し、GUI操作は_begin_narrativeに任せる。
        self.root.after(
            0,
            lambda: self._begin_narrative(
                display_text=display_text,
                voice_parts=voice_parts if voice_error is None else [],
                speaker_id=speaker_id if voice_error is None else None,
                on_typing_complete=on_typing_complete,
                voice_error=voice_error,
            ),
        )

    def _begin_narrative(
        self,
        *,
        display_text: str,
        voice_parts: list[tuple[str, str]],
        speaker_id: int | None,
        on_typing_complete: Callable[[], None] | None,
        voice_error: str | None = None,
    ) -> None:
        """
        待機表示を消し、タイピングと音声再生をほぼ同時に始める。

        VOICEVOX失敗時はエラーを表示しつつ ``voice_parts`` を空にしているため、
        音声機能だけを切り離し、ゲーム本文は通常どおり進行できる。
        """
        self._stop_waiting_animation()

        if voice_error:
            self._write(f"\n--- VOICEVOXエラー: {voice_error} ---\n")

        self._start_typing(
            display_text,
            on_complete=on_typing_complete,
        )

        if voice_parts and speaker_id is not None:
            self.voice_pipeline.speak_sequence(
                voice_parts,
                speaker_id=speaker_id,
            )

    def retry_last_choice(self) -> None:
        """
        Bad Endになった場面を再生成せず、そのまま選び直せる状態へ戻す。

        同じSceneを再利用するため、文章や正解が変化せず、公平に再挑戦できる。
        """
        if self.busy or self.engine is None:
            return

        try:
            scene = self.engine.retry_current_scene()
        except RuntimeError as exc:
            self._show_error(str(exc))
            return

        self.retry_button.config(state=tk.DISABLED)
        self._write(
            "\n\n=== 直前の選択肢へ戻ります ===\n"
            "同じ場面を、もう一度選び直してください。\n"
        )
        self._set_busy(True)
        self._start_waiting_animation()
        self._show_scene(scene)

    def _speak_async(
        self,
        text: str,
        *,
        cache_key: str | None = None,
    ) -> None:
        """
        1つの文章を常駐パイプラインへ渡し、生成済みチャンクから再生する。

        この補助メソッドは、呼び出し側に話者IDの変換処理を重複させない。
        """
        if not self.voice_enabled_var.get():
            return

        try:
            speaker_id = int(self.speaker_var.get())
        except ValueError:
            self._write("\n--- 話者IDは数字で入力してください ---\n")
            return

        self.voice_pipeline.speak(
            text,
            cache_key=cache_key or "ending",
            speaker_id=speaker_id,
        )

    def _speak_sequence_async(
        self,
        parts: list[tuple[str, str]],
    ) -> None:
        """複数文章を1要求として渡し、後の文章が前の再生を中断しないようにする。"""
        if not self.voice_enabled_var.get():
            return

        try:
            speaker_id = int(self.speaker_var.get())
        except ValueError:
            self._write("\n--- 話者IDは数字で入力してください ---\n")
            return

        self.voice_pipeline.speak_sequence(
            parts,
            speaker_id=speaker_id,
        )

    def _on_voice_error(self, message: str) -> None:
        """
        音声ワーカーからのエラーをTkinterのメインスレッドへ戻す。

        コールバック自体は音声スレッドから呼ばれる可能性があるため、
        ここでも直接ウィジェットを触らずafter()を経由する。
        """
        self.root.after(
            0,
            lambda: self._write(f"\n--- VOICEVOXエラー: {message} ---\n"),
        )

    def _make_voice_client_for_cache(self) -> VoicevoxClient:
        """現在の話者設定で、キャッシュ操作専用の軽量クライアントを作る。"""
        try:
            speaker_id = int(self.speaker_var.get())
        except ValueError:
            # キャッシュ削除は話者入力エラーで止めず、設定ファイルの既定値を使う。
            speaker_id = int(SETTINGS["voicevox"]["speaker_id"])

        return VoicevoxClient(
            base_url=SETTINGS["voicevox"]["base_url"],
            speaker_id=speaker_id,
            cache_dir=VOICE_CACHE_DIR,
        )

    def _delete_current_scene_voice_cache(self) -> None:
        """正解して通過した場面のWAVを削除する。"""
        if not self.current_voice_cache_key:
            return

        self._make_voice_client_for_cache().delete_cache_group(
            self.current_voice_cache_key
        )
        self.current_voice_cache_key = None

    def _clear_all_voice_cache(self) -> None:
        """新規ゲーム開始時と終了時に全WAVを削除する。"""
        self._make_voice_client_for_cache().clear_all_cache()

    def _set_busy(self, busy: bool) -> None:
        """
        重い処理中かどうかを記録し、関連する操作部品を一括更新する。

        入力欄は「busyでない」「ゲーム継続中」「タイピング完了」の
        3条件がそろった場合だけ有効になる。
        """
        self.busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        self.start_button.config(state=state)
        self.refresh_button.config(state=state)

        if busy:
            self.entry.config(state=tk.DISABLED)
            self.send_button.config(state=tk.DISABLED)
        elif (
            self.engine is not None
            and not self.engine.finished
            and not self.typing_active
        ):
            self._enable_choice()

    def _enable_choice(self) -> None:
        """条件を再確認したうえで選択入力を有効にし、キーボードフォーカスを移す。"""
        if self.busy or self.typing_active:
            return
        self.entry.config(state=tk.NORMAL)
        self.send_button.config(state=tk.NORMAL)
        self.entry.focus_set()

    def _disable_choice(self) -> None:
        """入力欄と決定ボタンを同時に無効化する。"""
        self.entry.config(state=tk.DISABLED)
        self.send_button.config(state=tk.DISABLED)

    def _on_enter(self, _event: tk.Event) -> str:
        """
        Enterキーを現在状態に応じて「全文表示」または「選択決定」へ振り分ける。

        ``"break"`` を返すとTkinterの既定処理へのイベント伝播を止められ、
        同じEnterが二重に処理されるのを防げる。
        """
        if self.typing_active:
            self._finish_typing()
        elif (
            not self.busy
            and self.engine is not None
            and not self.engine.finished
        ):
            self.submit_choice()
        return "break"

    def _start_typing(
        self,
        text: str,
        *,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        """
        新しい文章のタイピング表示状態を初期化し、最初の1文字を開始する。

        先に ``_cancel_typing()`` することで、前の文章が予約したafter()と
        新しい文章の予約が同時に走ることを防ぐ。
        """
        self._cancel_typing()
        self.typing_text = text
        self.typing_index = 0
        self.typing_active = True
        self.typing_complete_callback = on_complete
        self._type_next_character()

    def _type_next_character(self) -> None:
        """現在位置の1文字を書き、文字種に応じた遅延で次回処理を予約する。"""
        if not self.typing_active:
            return

        if self.typing_index >= len(self.typing_text):
            self._complete_typing()
            return

        # 1文字進めて表示したあと、自分自身をafter()で再予約する。
        # ループやsleepを使わないため、表示中もTkinterが操作・再描画できる。
        character = self.typing_text[self.typing_index]
        self.typing_index += 1
        self._write(character)
        self.typing_after_id = self.root.after(
            self._typing_delay(character),
            self._type_next_character,
        )

    def _finish_typing(self) -> None:
        """Enterが押されたとき、未表示部分を一度に表示する。"""
        if not self.typing_active:
            return

        if self.typing_after_id is not None:
            self.root.after_cancel(self.typing_after_id)
            self.typing_after_id = None

        remaining_text = self.typing_text[self.typing_index:]
        if remaining_text:
            self._write(remaining_text)
        self.typing_index = len(self.typing_text)
        self._complete_typing()

    def _complete_typing(self) -> None:
        """
        タイピング状態を終了し、完了コールバックと入力状態を更新する。

        callbackを呼ぶ前にインスタンス側の参照をNoneへ戻すため、
        コールバックが別の表示を始めても古い処理が再利用されにくい。
        """
        if not self.typing_active:
            return

        self.typing_active = False
        self.typing_after_id = None
        callback = self.typing_complete_callback
        self.typing_complete_callback = None

        if callback is not None:
            callback()

        # _set_busy(False)内で、ゲーム継続中だけ選択肢が有効になる。
        self._set_busy(False)

    def _cancel_typing(self) -> None:
        """
        場面切り替えや終了時に、実行中のafter()予約と状態を安全に解除する。

        after_cancel()には、after()が返したIDを渡す。IDを失うと予約だけが残り、
        後から古い文章が突然表示される原因になる。
        """
        if self.typing_after_id is not None:
            self.root.after_cancel(self.typing_after_id)
        self.typing_after_id = None
        self.typing_text = ""
        self.typing_index = 0
        self.typing_active = False
        self.typing_complete_callback = None

    @staticmethod
    def _typing_delay(character: str) -> int:
        """句読点と改行だけ少し長く間を取り、読みやすくする。"""
        if character == "\n":
            return TYPING_NEWLINE_INTERVAL_MS
        if character in "。！？!?":
            return TYPING_SENTENCE_INTERVAL_MS
        if character in "、，,":
            return TYPING_COMMA_INTERVAL_MS
        return TYPING_INTERVAL_MS

    def _start_waiting_animation(self) -> None:
        """
        「物語を生成しています」の末尾の点を0～3個で循環表示する。（プログレスバーがうまくできなかったため苦肉の策。）

        新規開始前に必ず既存予約を止め、アニメーションの二重起動を防ぐ。
        
        """
        self._stop_waiting_animation()
        self.waiting_dot_count = 0
        self._write_waiting_text()

    def _write_waiting_text(self) -> None:
        """タグ付き待機文だけを差し替え、次のアニメーション更新を予約する。"""
        # この関数がafter()から呼ばれた時点で、直前の予約は実行済み。
        # 実行済みIDをafter_cancel()するとTclErrorになり得るため、参照だけ外す。
        self.waiting_after_id = None

        # タグで待機文の範囲だけを識別し、物語本文を消さずに差し替える。
        self.text_area.config(state=tk.NORMAL)
        ranges = self.text_area.tag_ranges("waiting_message")
        if ranges:
            start_index = str(ranges[0])
            self.text_area.delete(ranges[0], ranges[-1])
        else:
            start_index = self.text_area.index(tk.END)
            self.text_area.insert(tk.END, "\n")

        message = "物語を生成しています" + "." * self.waiting_dot_count
        self.text_area.insert(start_index, message, ("waiting_message",))
        self.text_area.see(tk.END)
        self.text_area.config(state=tk.DISABLED)

        # 剰余演算により 0 -> 1 -> 2 -> 3 -> 0 と循環させる。
        self.waiting_dot_count = (self.waiting_dot_count + 1) % 4
        self.waiting_after_id = self.root.after(
            WAITING_ANIMATION_INTERVAL_MS,
            self._write_waiting_text,
        )

    def _stop_waiting_animation(self) -> None:
        """待機表示の更新を止め、現在表示中の待機メッセージを消す。"""
        if self.waiting_after_id is not None:
            self.root.after_cancel(self.waiting_after_id)
            self.waiting_after_id = None

        if not hasattr(self, "text_area"):
            return

        self.text_area.config(state=tk.NORMAL)
        ranges = self.text_area.tag_ranges("waiting_message")
        if ranges:
            self.text_area.delete(ranges[0], ranges[-1])
        self.text_area.config(state=tk.DISABLED)

    def _write(self, text: str) -> None:
        """読み取り専用の本文欄を一時的に編集可能にし、末尾へ文字を追加する。"""
        self.text_area.config(state=tk.NORMAL)
        self.text_area.insert(tk.END, text)
        self.text_area.see(tk.END)
        self.text_area.config(state=tk.DISABLED)

    def _clear(self) -> None:
        """保留中の表示処理を止めてから、本文欄を空にする。"""
        self._cancel_typing()
        self._stop_waiting_animation()
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)
        self.text_area.config(state=tk.DISABLED)

    def _finish_with_error(self, message: str) -> None:
        """バックグラウンド処理の待機表示とbusy状態を戻してから通知する。"""
        self._stop_waiting_animation()
        self._set_busy(False)
        self._show_error(message)

    def _show_error(self, message: str) -> None:
        """本文履歴とダイアログの両方でエラーを知らせ、選択入力を止める。"""
        self._write(f"\n--- エラー ---\n{message}\n")
        messagebox.showerror("エラー", message)
        self._disable_choice()

    def _log_internal(self, message: str) -> None:
        """ゲーム進行の診断情報を、日時付きで追記保存する。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with (LOG_DIR / "game.log").open("a", encoding="utf-8") as file:
            file.write(f"[{now}] {message}\n")

    def _log_exception(self, exc: BaseException) -> None:
        """例外の種類・本文・呼び出し履歴を、個別のログファイルへ保存する。"""
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = LOG_DIR / f"error_{now}.log"
        with path.open("w", encoding="utf-8") as file:
            file.write("".join(traceback.format_exception(exc)))

    def on_closing(self) -> None:
        """
        ウィンドウ終了時に、予約処理・音声スレッド・一時キャッシュを片付ける。

        ``destroy()`` より先にshutdownすることで、破棄済みGUIへワーカーが
        コールバックし続ける状態を避ける。
        """
        self._cancel_typing()
        self._stop_waiting_animation()
        self.voice_pipeline.shutdown()
        self._clear_all_voice_cache()
        self.root.destroy()


def main() -> None:
    """Tkinterのルートを作成し、イベントループを開始する。"""
    root = tk.Tk()
    AdventureApp(root)
    root.mainloop()


if __name__ == "__main__":
    # importされたときは自動起動せず、このファイルを直接実行した場合だけ開始する。
    main()
