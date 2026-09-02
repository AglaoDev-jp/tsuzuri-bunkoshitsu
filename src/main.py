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
import shutil
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

import pygame

from background_manager import BackgroundImageCatalog
from bgm_manager import BGMManager
from game_engine import GameDataError, GameEngine, Scene
from game_prompts import (
    BACKGROUND_TAG_VALUES,
    BGM_TAG_VALUES,
    FREE_STORY_REQUEST_MAX_CHARACTERS,
)
from llm_client import (
    LLMClientError,
    LLMGenerationCancelled,
    OllamaClient,
    OllamaModelInfo,
)
from voicevox_client import VoicePipeline, VoicevoxClient, VoicevoxError


# 実行時のカレントディレクトリではなく、このPythonファイルの場所を基準にする。
# これにより、どのフォルダから起動しても同じログ保存先を参照できる。
BASE_DIR = Path(__file__).resolve().parent


def resource_path(relative_path: str | Path) -> Path:
    """
    開発中とPyInstaller実行時の両方で、同梱した読み取り素材の場所を返す。

    通常実行ではmain.pyのあるフォルダ、PyInstallerでは展開先として用意される
    ``sys._MEIPASS`` を基準にする。カレントディレクトリへ依存させないことで、
    ショートカットや別フォルダから起動してもassetsを見つけられる。
    """
    bundle_dir = Path(getattr(sys, "_MEIPASS", BASE_DIR))
    return bundle_dir / Path(relative_path)


# 設定と配布素材はresource_path()を通し、PyInstaller同梱時にも参照できるようにする。
SETTINGS_PATH = resource_path(Path("data") / "game_settings.json")

# mkdir(exist_ok=True)は、既存フォルダがあってもエラーにしない。
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
VOICE_CACHE_DIR = BASE_DIR / "voice_cache"
VOICE_CACHE_DIR.mkdir(exist_ok=True)

# 効果音はVOICEVOXの作業キャッシュとは分け、配布素材としてassetsに置く。
# この3ファイルは読み込むだけで、クリア後の音声保存対象には含めない。
SFX_DIR = resource_path(Path("assets") / "sfx")
CORRECT_SFX_PATH = SFX_DIR / "correct.mp3"
BAD_END_SFX_PATH = SFX_DIR / "bad_end.mp3"
GOOD_END_SFX_PATH = SFX_DIR / "good_end.mp3"

# BGMはタグ名と同じMP3ファイルをassets/bgmから探す。
# すでにOGG素材を用意している場合も無駄にならないよう、第2候補として残す。
# WAVなど、ほかの形式の音楽ファイルに対応したい場合は、候補に f"{tag}.wav" のように追加できます。
# 値をtupleにしておくことで、将来は同じタグへ複数ファイルを登録し、
# BGMManager側の曲決定処理だけでランダム選曲へ拡張できる。
BGM_DIR = resource_path(Path("assets") / "bgm")
BGM_TRACK_FILES = {
    tag: (f"{tag}.mp3", f"{tag}.ogg")
    for tag in BGM_TAG_VALUES
}

# 背景画像の登録規則と複数候補の選択はBackgroundImageCatalogへ集約する。
# main.pyは画像フォルダの場所だけを渡すため、画像を追加するたびに画面処理を
# 修正する必要がなく、表示・VOICEVOX・BGMなどの責務も混ざらない。
BACKGROUND_DIR = resource_path(Path("assets") / "backgrounds")

# 選択結果と本編後の演出画像は、場所を表す背景画像とは役割が異なるため
# 別フォルダへ置く。JPGを基本としつつPNGも候補に残し、画像の作成・
# 差し替え途中でも扱いやすくする。
RESULT_IMAGE_DIR = resource_path(Path("assets") / "result_images")
RESULT_IMAGE_FILES = {
    # 起動時と再プレイ開始時に表示する、物語へ入る前の案内画像。
    # title.jpgまたはtitle.pngを差し替えるだけで、コード変更なしに更新できる。
    "title": ("title.jpg", "title.png"),
    "correct": ("correct.jpg", "correct.png"),
    "bad_end": ("bad_end.jpg", "bad_end.png"),
    "game_clear": ("game_clear.jpg", "game_clear.png"),
    "ai_comment": ("ai_comment.jpg", "ai_comment.png"),
    "play_record": ("play_record.jpg", "play_record.png"),
    "thank_you": ("thank_you.jpg", "thank_you.png"),
}
SCENE_WINDOW_WIDTH = 720
SCENE_WINDOW_HEIGHT = 240
SCENE_WINDOW_ASPECT_RATIO = SCENE_WINDOW_WIDTH / SCENE_WINDOW_HEIGHT
# 横長比率を保ったまま画面へ広げつつ、画像だけで縦方向を占有しすぎないよう
# ウィンドウ高の36%を上限。
SCENE_WINDOW_MAX_HEIGHT_RATIO = 0.36
SCENE_WINDOW_HORIZONTAL_MARGIN = 40
SCENE_RESIZE_DELAY_MS = 80
SCENE_WINDOW_BG = "#242a30"

# Tkinterのafter()へ渡す時間はミリ秒単位。
# 値を小さくすると速くなるが、0に近づけすぎると画面更新が慌ただしくなる。
WAITING_ANIMATION_INTERVAL_MS = 450
TYPING_INTERVAL_MS = 30
TYPING_COMMA_INTERVAL_MS = 90
TYPING_SENTENCE_INTERVAL_MS = 180
TYPING_NEWLINE_INTERVAL_MS = 120
# 正解結果の表示・読み上げが終わってから次の場面へ移るまでの「余韻」。
CHAPTER_TRANSITION_PAUSE_MS = 600
# エンディング各項目の間は、流れを止めすぎない半秒にする。
ENDING_SECTION_PAUSE_MS = 500
# 効果音の頭を聞き取りやすくしてから、本文表示とVOICEVOXの準備へ進む。
# sleepではなくafter()を使うため、この250ミリ秒も画面操作や再描画は止まらない。
SFX_NARRATIVE_DELAY_MS = 250

# 選択肢は通常時を落ち着いた白、ホバー時を淡い青にして判別しやすくする。
CHOICE_BUTTON_BG = "#f7f7f7"
CHOICE_BUTTON_HOVER_BG = "#dcecff"

# 既存ジャンルと同じ選択欄へ加える、新しい物語の入口。
# GameEngineへは最終的に従来どおりgenre_name / genre_promptを渡すため、
# この名前がゲーム進行側の新しい分岐を増やすことはない。
FREE_STORY_MODE_NAME = "自由に綴る"

# LLMの生成結果ではなく、アプリが必ず同じ言葉で伝える終了案内。
# 画面用と音声用を分けると、引用符をVOICEVOXに読ませず自然に案内できる。
ENDING_THANK_YOU_TEXT = (
    "最後まで遊んでいただき、ありがとうございました。\n"
    "「最初から」ボタンで、また新しい物語を始められます。"
)
ENDING_THANK_YOU_VOICE = (
    "最後まで遊んでいただき、ありがとうございました。"
    "最初からボタンで、また新しい物語を始められます。"
)

# エンディングは各項目を自動送りせず、次に開く内容が分かるボタンを表示する。
# キーは「次に表示するending_stagesのインデックス」で、最終項目の後には
# 次段階がないためボタンを出さない。
ENDING_CONTINUE_BUTTON_TEXTS = {
    1: "エピローグへ",
    2: "GAME CLEAR",
    3: "AI COMMENT",
    4: "PLAY RECORD",
    5: "最後に",
}


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
        # 初期表示でも画像・本文・選択肢を同時に見渡せる縦幅を確保する。
        self.root.geometry("850x890")
        self.root.minsize(760, 720)

        # ゲーム全体の状態。開始前はengineが存在しない。
        self.engine: GameEngine | None = None
        self.busy = False

        # LLM生成はワーカースレッドで動くため、キャンセル後もOS側の終了処理が
        # ごく短時間残る場合がある。generation_idで現在の依頼だけを識別し、
        # 古いワーカーの結果やエラーが初期画面へ戻ってこないようにする。
        self.generation_id = 0
        self.generation_active = False
        self.active_llm_client: OllamaClient | None = None

        # 現在場面の音声キャッシュ群を識別する。WAVはゲーム中保持し、
        # クリア後にプレイヤーが任意のフォルダへ保存できるようにする。
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

        # 現在の場面が選択可能かを明示的に管理する。
        # GameEngineには次場面が先に入るため、engine.finishedだけでは
        # 「選択肢を画面へ出してよい瞬間」を正しく判断できない。
        self.choice_buttons_ready = False
        self.current_choice_texts: dict[str, str] = {"a": "", "b": ""}
        # 通常章とエンディングの続行ボタンが、クリック時に実行する処理を保持する。
        # ボタン1個を共用することで、選択肢欄の配置や見た目を増やさずに済む。
        self.pending_continue_action: Callable[[], None] | None = None

        # 音声の先行生成や章間待機は非同期で完了する。
        # presentation_idが古い処理を見分け、最初からやり直したあとに
        # 前の場面が突然表示されることを防ぐ。
        self.presentation_id = 0
        self.narrative_typing_done = False
        self.narrative_voice_done = True
        self.narrative_complete_callback: Callable[[], None] | None = None
        self.transition_after_id: str | None = None
        # 効果音後に本文を始めるafter()予約もIDを保持し、最初から・終了時に
        # 古いゲームの予約だけが後から実行されないよう取り消す。
        self.sfx_narrative_after_id: str | None = None
        self.voice_cancelled_presentation_id: int | None = None

        # 画面には現在の場面だけを表示しつつ、完了済みの文章を別に蓄積する。
        # タイピング途中の文章や未表示の選択肢は、先に読めないよう記録しない。
        self.backlog_entries: list[str] = []
        self.backlog_window: tk.Toplevel | None = None
        self.backlog_text_area: scrolledtext.ScrolledText | None = None

        # テキスト・音声の保存可否と、保存ファイルへ付けるゲーム情報。
        self.game_clear_complete = False
        self.backlog_exported = False
        self.voice_cache_exported = False
        self.current_game_started_at: datetime | None = None
        self.current_game_genre = ""
        self.current_game_model = ""
        # 自由入力から開始中の依頼原文を、最初のScene表示まで保持する。
        # LLMエラーや生成キャンセル時はこの値を使って入力画面へ復帰する。
        self.active_free_story_request: str | None = None

        # PhotoImageをインスタンス変数へ保持しないと、Tkinter側で表示中でも
        # Pythonのガベージコレクションに回収され、画像だけ消えることがある。
        self.scene_image: tk.PhotoImage | None = None
        # 元画像も保持し、ウィンドウサイズが変わったときに読み直さず
        # 表示領域に合わせて再描画できるようにする。
        self.scene_source_surface: pygame.Surface | None = None
        self.current_background_tag = "none"
        self.scene_resize_after_id: str | None = None
        # 同じ不足素材を場面ごとに警告しないよう、通知済みのタグを記録する。
        self.background_warning_tags: set[str] = set()
        # ファイル検索と候補選択を専用クラスへ任せる。同じタグの画像を増やしても
        # main.py側の辞書や分岐を追加する必要はない。
        self.background_catalog = BackgroundImageCatalog(
            background_dir=BACKGROUND_DIR,
            valid_tags=BACKGROUND_TAG_VALUES,
        )

        # 各音量の既定値は設定ファイルから取得する。既存設定ファイルに項目が
        # ない場合も、BGM・SE 20%、VOICEVOX 100%で動作する。
        voicevox_settings = SETTINGS.get("voicevox", {})
        sfx_settings = SETTINGS.get("sfx", {})
        bgm_settings = SETTINGS.get("bgm", {})
        voice_volume = float(voicevox_settings.get("volume", 1.0))
        sfx_volume = float(sfx_settings.get("volume", 0.2))
        bgm_volume = float(bgm_settings.get("volume", 0.2))

        # 音声用の2本のワーカースレッドはアプリ起動中ずっと再利用する。
        self.voice_pipeline = VoicePipeline(
            base_url=SETTINGS["voicevox"]["base_url"],
            cache_dir=VOICE_CACHE_DIR,
            voice_volume=voice_volume,
            sfx_volume=sfx_volume,
            on_error=self._on_voice_error,
            on_sfx_warning=self._on_sfx_warning,
        )

        # BGMはVOICEVOX・効果音とは別の専用チャンネルで管理する。
        # 音量は文章と読み上げを主役にするため低めの0.2を既定値とし、
        # 起動後は設定欄の専用スライダーからいつでも変更できる。
        self.bgm_manager = BGMManager(
            bgm_dir=BGM_DIR,
            tracks_by_tag=BGM_TRACK_FILES,
            volume=bgm_volume,
            fade_ms=int(bgm_settings.get("fade_ms", 800)),
            on_warning=self._on_bgm_warning,
            on_track_reference=self._on_bgm_track_reference,
        )

        # StringVar / BooleanVarは、GUI部品とPython値を同期するTkinter変数。
        self.genre_var = tk.StringVar(value=next(iter(GENRES)))
        self.model_var = tk.StringVar(value=SETTINGS["ollama"]["default_model"])
        self.free_story_count_var = tk.StringVar(
            value=f"0 / {FREE_STORY_REQUEST_MAX_CHARACTERS}文字"
        )
        self.free_story_feedback_var = tk.StringVar(value="")
        self.voice_enabled_var = tk.BooleanVar(value=False)
        self.speaker_var = tk.StringVar(
            value=str(SETTINGS["voicevox"]["speaker_id"])
        )
        # Scaleは0～100の百分率で見せ、再生側へ渡すときだけ0.0～1.0へ戻す。
        # 設定値が範囲外でも、画面上では安全な端値へ収める。
        self.bgm_volume_var = tk.DoubleVar(
            value=max(0.0, min(100.0, bgm_volume * 100.0))
        )
        self.sfx_volume_var = tk.DoubleVar(
            value=max(0.0, min(100.0, sfx_volume * 100.0))
        )
        self.voice_volume_var = tk.DoubleVar(
            value=max(0.0, min(100.0, voice_volume * 100.0))
        )

        self._build_ui()
        self._show_title_image()
        # 前回クラッシュ時などに残った一時WAVを、起動直後に持ち越さない。
        self._clear_all_voice_cache()
        # 枠の高さは維持しつつ、物語を読み終えるまでボタン本体だけを隠す。
        self._reset_choice_buttons()
        # 入力欄が無効なタイピング中でもEnterを受け取れるよう、rootへ登録する。
        self.root.bind("<Return>", self._on_enter)
        self._write(
            "ジャンル（または「自由に綴る」）とモデルを選び、"
            "「ゲーム開始」を押してください。\n"
            "ゲーム中は、画面下のAまたはBボタンで選択します。\n"
            "Enterを押すと、全文表示または現在の音声停止を行います。\n"
        )
        # 起動時はタイトル曲をループ再生する。素材不足でもBGMManagerが警告へ
        # 変換するため、音源をまだ配置していない開発途中でも画面は起動できる。
        self.bgm_manager.play("title")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        # 画面表示後にOllamaからモデル一覧を自動取得する。
        self.root.after(300, self.refresh_models)

    def _build_ui(self) -> None:
        """設定欄、操作バー、情景窓、物語欄、選択肢を整理して配置する。"""
        # 選択肢の高さは保ち、本文欄は残りの領域を受け取る。画像欄は後述の
        # リサイズ処理で横長比率を保ちながら画面サイズへ追従する。
        self.root.grid_rowconfigure(3, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        # 上段: 作品生成と読み上げに関する「設定」だけをまとめる。
        settings_frame = tk.LabelFrame(self.root, text="設定", padx=8, pady=7)
        settings_frame.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=10,
            pady=(10, 5),
        )
        settings_frame.grid_columnconfigure(3, weight=1)

        tk.Label(settings_frame, text="ジャンル:").grid(
            row=0, column=0, sticky="w"
        )
        self.genre_combo = ttk.Combobox(
            settings_frame,
            textvariable=self.genre_var,
            # 既存ジャンルの末尾へ追加し、通常モードの並び順を変えない。
            values=[*GENRES.keys(), FREE_STORY_MODE_NAME],
            state="readonly",
            width=20,
        )
        self.genre_combo.grid(row=0, column=1, padx=(5, 15), sticky="w")
        self.genre_combo.bind("<<ComboboxSelected>>", self._on_genre_selected)

        tk.Label(settings_frame, text="モデル:").grid(
            row=0, column=2, sticky="w"
        )
        self.model_combo = ttk.Combobox(
            settings_frame,
            textvariable=self.model_var,
            values=[self.model_var.get()],
            state="readonly",
            width=30,
        )
        self.model_combo.grid(row=0, column=3, padx=5, sticky="ew")

        self.refresh_button = tk.Button(
            settings_frame,
            text="モデル更新",
            command=self.refresh_models,
        )
        self.refresh_button.grid(row=0, column=4, padx=(5, 0))

        self.voice_check = tk.Checkbutton(
            settings_frame,
            text="VOICEVOX読み上げ",
            variable=self.voice_enabled_var,
        )
        self.voice_check.grid(
            row=1,
            column=0,
            columnspan=2,
            pady=(7, 0),
            sticky="w",
        )

        tk.Label(settings_frame, text="話者ID:").grid(
            row=1, column=2, pady=(7, 0), sticky="e"
        )
        self.speaker_entry = tk.Entry(
            settings_frame,
            textvariable=self.speaker_var,
            width=7,
        )
        self.speaker_entry.grid(row=1, column=3, pady=(7, 0), sticky="w")

        # BGM・効果音・VOICEVOXは別々の再生先を使っているため、音量も個別に
        # 調整できる。画面では分かりやすい0～100、内部では0.0～1.0を使う。
        volume_frame = tk.Frame(settings_frame)
        volume_frame.grid(
            row=2,
            column=0,
            columnspan=5,
            sticky="ew",
            pady=(7, 0),
        )
        for column in (1, 3, 5):
            volume_frame.grid_columnconfigure(column, weight=1)

        tk.Label(volume_frame, text="BGM音量:").grid(
            row=0, column=0, sticky="w"
        )
        self.bgm_volume_scale = tk.Scale(
            volume_frame,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            resolution=1,
            showvalue=True,
            variable=self.bgm_volume_var,
            command=self._on_bgm_volume_changed,
            length=145,
            highlightthickness=0,
        )
        self.bgm_volume_scale.grid(
            row=0, column=1, padx=(3, 12), sticky="ew"
        )

        tk.Label(volume_frame, text="SE音量:").grid(
            row=0, column=2, sticky="w"
        )
        self.sfx_volume_scale = tk.Scale(
            volume_frame,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            resolution=1,
            showvalue=True,
            variable=self.sfx_volume_var,
            command=self._on_sfx_volume_changed,
            length=145,
            highlightthickness=0,
        )
        self.sfx_volume_scale.grid(
            row=0, column=3, padx=(3, 12), sticky="ew"
        )

        tk.Label(volume_frame, text="VOICE音量:").grid(
            row=0, column=4, sticky="w"
        )
        self.voice_volume_scale = tk.Scale(
            volume_frame,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            resolution=1,
            showvalue=True,
            variable=self.voice_volume_var,
            command=self._on_voice_volume_changed,
            length=145,
            highlightthickness=0,
        )
        self.voice_volume_scale.grid(
            row=0, column=5, padx=(3, 0), sticky="ew"
        )

        # 設定と混在していたゲーム操作を、独立した横一列のバーへ集約する。
        controls_frame = tk.LabelFrame(
            self.root,
            text="ゲーム操作",
            padx=8,
            pady=7,
        )
        controls_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        controls_frame.grid_columnconfigure(6, weight=1)

        # 開始後は同じボタンの表示を「最初から」へ変える。
        # 同じ働きのボタンを2個置かず、誤操作しにくい画面にする。
        self.start_button = tk.Button(
            controls_frame,
            text="ゲーム開始",
            command=self.start_game,
        )
        self.start_button.grid(row=0, column=0, sticky="w")

        self.retry_button = tk.Button(
            controls_frame,
            text="直前の選択肢へ",
            command=self.retry_last_choice,
            state=tk.DISABLED,
        )
        self.retry_button.grid(row=0, column=1, padx=(6, 0), sticky="w")

        # LLM応答が止まった場合でも、タイムアウトまで待たず初期画面へ戻せる。
        # 通常時は無効にし、実際に物語を生成している間だけ押せるようにする。
        self.cancel_generation_button = tk.Button(
            controls_frame,
            text="生成キャンセル",
            command=self.cancel_generation,
            state=tk.DISABLED,
        )
        self.cancel_generation_button.grid(
            row=0,
            column=2,
            padx=(6, 0),
            sticky="w",
        )

        self.backlog_button = tk.Button(
            controls_frame,
            text="バックログ",
            command=self.show_backlog,
        )
        self.backlog_button.grid(row=0, column=3, padx=(6, 0), sticky="w")

        self.export_text_button = tk.Button(
            controls_frame,
            text="テキスト保存",
            command=self.export_backlog_text,
            state=tk.DISABLED,
        )
        self.export_text_button.grid(row=0, column=4, padx=(6, 0), sticky="w")

        self.export_voice_button = tk.Button(
            controls_frame,
            text="音声保存",
            command=self.export_voice_cache,
            state=tk.DISABLED,
        )
        self.export_voice_button.grid(row=0, column=5, padx=(6, 0), sticky="w")

        self.stop_voice_button = tk.Button(
            controls_frame,
            text="音声停止",
            command=self.stop_voice,
        )
        self.stop_voice_button.grid(row=0, column=7, sticky="e")

        # 中央上部: 場面に対応する汎用画像だけを見せる領域。
        # 画像がない場合もCanvas自体を残すため、本文と選択肢の位置は動かない。
        scene_window_frame = tk.Frame(
            self.root,
            padx=5,
            pady=5,
        )
        scene_window_frame.grid(
            row=2,
            column=0,
            sticky="ew",
            padx=10,
            pady=5,
        )
        scene_window_frame.grid_columnconfigure(0, weight=1)

        self.scene_canvas = tk.Canvas(
            scene_window_frame,
            width=SCENE_WINDOW_WIDTH,
            height=SCENE_WINDOW_HEIGHT,
            background=SCENE_WINDOW_BG,
            borderwidth=0,
            highlightthickness=0,
        )
        # CanvasはFrame中央に置き、実寸はルートウィンドウの大きさから計算する。
        self.scene_canvas.grid(row=0, column=0)
        # Canvas上の同じ項目へ画像だけを差し替えると、切り替え時の点滅を抑えられる。
        self.scene_image_item = self.scene_canvas.create_image(
            SCENE_WINDOW_WIDTH // 2,
            SCENE_WINDOW_HEIGHT // 2,
            anchor=tk.CENTER,
        )
        # 連続リサイズ中は短く間引いて再描画し、画像変換がGUI操作を重くしないようにする。
        self.root.bind("<Configure>", self._on_root_configure, add="+")

        # 中央下部: 現在の場面を見せる「場面カード」。
        # 場面ごとに表示を入れ替えるため、長い履歴の最下部を追い続けずに済む。
        self.text_area = scrolledtext.ScrolledText(
            self.root,
            wrap=tk.WORD,
            font=("", 12),
            state=tk.DISABLED,
            padx=22,
            pady=18,
        )
        self.text_area.grid(
            row=3,
            column=0,
            sticky="nsew",
            padx=10,
            pady=5,
        )

        # 「自由に綴る」専用の入力画面。通常の本文欄とは別ウィジェットにし、
        # 同じgridセルで切り替える。これにより、本文欄に結び付いたタイピング・
        # Enter・VOICEVOX・待機表示の処理を変更せず、そのまま維持できる。
        self.free_story_frame = tk.Frame(
            self.root,
            background="#f7f7f7",
            padx=22,
            pady=18,
        )
        self.free_story_frame.grid(
            row=3,
            column=0,
            sticky="nsew",
            padx=10,
            pady=5,
        )
        self.free_story_frame.grid_columnconfigure(0, weight=1)
        # 説明文の直下に置く入力欄へ、画面内の余った高さをすべて渡す。
        # 通常ウィンドウでも複数行を見渡せる高さを確保し、画面を広げた場合は
        # その増加分も入力欄が自然に受け取るようにする。
        self.free_story_frame.grid_rowconfigure(2, weight=1)

        tk.Label(
            self.free_story_frame,
            text="どんな物語で遊びたいですか？",
            font=("", 15, "bold"),
            anchor="w",
            background="#f7f7f7",
        ).grid(row=0, column=0, sticky="ew")
        tk.Label(
            self.free_story_frame,
            text="下の入力欄に、遊んでみたい物語を自由に入力してください。",
            font=("", 11),
            anchor="w",
            background="#f7f7f7",
        ).grid(row=1, column=0, sticky="ew", pady=(10, 10))

        self.free_story_input = scrolledtext.ScrolledText(
            self.free_story_frame,
            wrap=tk.WORD,
            font=("", 12),
            height=8,
            padx=12,
            pady=10,
        )
        self.free_story_input.grid(row=2, column=0, sticky="nsew")
        self.free_story_input.bind(
            "<KeyRelease>",
            self._on_free_story_input_changed,
        )
        # マウス操作の貼り付け・切り取りではKeyReleaseが発生しない場合がある。
        # virtual eventの処理後に数え直すことで、文字数表示も実内容へ追従する。
        self.free_story_input.bind(
            "<<Paste>>",
            lambda _event: self.root.after(
                0, self._on_free_story_input_changed
            ),
            add="+",
        )
        self.free_story_input.bind(
            "<<Cut>>",
            lambda _event: self.root.after(
                0, self._on_free_story_input_changed
            ),
            add="+",
        )

        free_story_footer = tk.Frame(
            self.free_story_frame,
            background="#f7f7f7",
        )
        free_story_footer.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        free_story_footer.grid_columnconfigure(0, weight=1)
        tk.Label(
            free_story_footer,
            textvariable=self.free_story_feedback_var,
            foreground="#b00020",
            anchor="w",
            background="#f7f7f7",
        ).grid(row=0, column=0, sticky="ew")
        tk.Label(
            free_story_footer,
            textvariable=self.free_story_count_var,
            foreground="#555555",
            anchor="e",
            background="#f7f7f7",
        ).grid(row=0, column=1, sticky="e", padx=(12, 0))
        tk.Label(
            self.free_story_frame,
            text="入力したら「ゲーム開始」をクリックしてください。",
            font=("", 11, "bold"),
            anchor="w",
            background="#f7f7f7",
        ).grid(row=4, column=0, sticky="ew", pady=(8, 0))

        # 起動時は従来どおり本文欄を表示する。grid_remove()なら配置情報が
        # 保持されるため、選択時に引数なしのgrid()で同じ位置へ戻せる。
        self.free_story_frame.grid_remove()

        # 下段: 長い文章でも読める、横幅いっぱいのA・B選択肢ボタン。
        self.choice_frame = tk.LabelFrame(
            self.root,
            text="選択肢",
            padx=8,
            pady=7,
            height=150,
        )
        self.choice_frame.grid(
            row=4,
            column=0,
            sticky="ew",
            padx=10,
            pady=(5, 10),
        )
        # ボタンをgrid_remove()しても枠が縮まないよう、必要な高さを維持する。
        self.choice_frame.grid_propagate(False)
        self.choice_frame.grid_columnconfigure(0, weight=1)

        self.choice_a_button = tk.Button(
            self.choice_frame,
            text="A",
            command=lambda: self.submit_choice("a"),
            state=tk.DISABLED,
            anchor="w",
            justify=tk.LEFT,
            wraplength=650,
            padx=12,
            pady=7,
            font=("", 11),
            background=CHOICE_BUTTON_BG,
            activebackground=CHOICE_BUTTON_HOVER_BG,
        )
        self.choice_a_button.grid(row=0, column=0, sticky="ew")

        self.choice_b_button = tk.Button(
            self.choice_frame,
            text="B",
            command=lambda: self.submit_choice("b"),
            state=tk.DISABLED,
            anchor="w",
            justify=tk.LEFT,
            wraplength=650,
            padx=12,
            pady=7,
            font=("", 11),
            background=CHOICE_BUTTON_BG,
            activebackground=CHOICE_BUTTON_HOVER_BG,
        )
        self.choice_b_button.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        # 正解結果やエンディング項目の表示後、A・Bボタンと同じ枠内に表示する。
        # grid_remove()で隠すため、ボタンがない間も選択肢枠の高さは変わらない。
        self.next_scene_button = tk.Button(
            self.choice_frame,
            text="次のシナリオへ",
            command=self._advance_from_continue_button,
            state=tk.DISABLED,
            anchor="center",
            justify=tk.CENTER,
            padx=12,
            pady=12,
            font=("", 11),
            background=CHOICE_BUTTON_BG,
            activebackground=CHOICE_BUTTON_HOVER_BG,
        )
        self.next_scene_button.grid(
            row=0,
            column=0,
            rowspan=2,
            sticky="ew",
            pady=20,
        )

        # Tkのテーマ差に左右されず、マウスが乗ったことを明確に伝える。
        self._bind_choice_hover(self.choice_a_button)
        self._bind_choice_hover(self.choice_b_button)
        self._bind_choice_hover(self.next_scene_button)

    def _is_free_story_mode(self) -> bool:
        """現在のジャンル選択が「自由に綴る」かを返す。"""
        return self.genre_var.get() == FREE_STORY_MODE_NAME

    def _on_genre_selected(self, _event: tk.Event | None = None) -> None:
        """ジャンル選択に合わせ、本文欄と自由入力欄を同じ場所で切り替える。"""
        if self._is_free_story_mode():
            self._show_free_story_input()
        else:
            self._show_story_text_area()

    def _show_free_story_input(self) -> None:
        """本文欄を隠し、保持中の自由入力欄を同じ表示領域へ戻す。"""
        self.text_area.grid_remove()
        # 自由入力中は選択肢をまだ使わないため、空の固定枠を一時的に隠す。
        # その150px分も可変行へ戻り、通常サイズのウィンドウでも入力欄が
        # 一行程度まで押しつぶされず、十分な編集領域を確保できる。
        self.choice_frame.grid_remove()
        self.free_story_frame.grid()
        self._update_free_story_count()
        self.free_story_input.focus_set()

    def _show_story_text_area(self) -> None:
        """自由入力欄を隠し、既存の読み取り専用本文欄を復元する。"""
        self.free_story_frame.grid_remove()
        self.text_area.grid()
        # 通常ジャンルへ戻した場合やゲーム開始後は、従来どおり選択肢枠を
        # 復元する。grid()だけなら最初に指定した配置設定がそのまま使われる。
        self.choice_frame.grid()

    def _on_free_story_input_changed(self, _event: tk.Event | None = None) -> None:
        """入力中の文字数を表示し、修正後は古い案内エラーを消す。"""
        length = self._update_free_story_count()
        if length > FREE_STORY_REQUEST_MAX_CHARACTERS:
            self.free_story_feedback_var.set(
                f"{FREE_STORY_REQUEST_MAX_CHARACTERS}文字以内で入力してください。"
            )
        elif self.free_story_input.get("1.0", "end-1c").strip():
            self.free_story_feedback_var.set("")

    def _update_free_story_count(self) -> int:
        """自由入力の現在文字数を数え、画面表示を更新して返す。"""
        length = len(self.free_story_input.get("1.0", "end-1c"))
        self.free_story_count_var.set(
            f"{length} / {FREE_STORY_REQUEST_MAX_CHARACTERS}文字"
        )
        return length

    @staticmethod
    def _scale_value_to_volume(value: str) -> float:
        """Scaleから渡される0～100の文字列を、pygame用0.0～1.0へ変換する。"""
        try:
            percentage = float(value)
        except (TypeError, ValueError):
            percentage = 0.0
        return max(0.0, min(1.0, percentage / 100.0))

    def _on_bgm_volume_changed(self, value: str) -> None:
        """BGMスライダーの変更を、再生中の曲を含めて即時反映する。"""
        self.bgm_manager.set_volume(self._scale_value_to_volume(value))

    def _on_sfx_volume_changed(self, value: str) -> None:
        """SEスライダーの変更を、再生中と次回の効果音へ即時反映する。"""
        self.voice_pipeline.set_sfx_volume(self._scale_value_to_volume(value))

    def _on_voice_volume_changed(self, value: str) -> None:
        """VOICEスライダーの変更を、再生中と次回の読み上げへ即時反映する。"""
        self.voice_pipeline.set_voice_volume(
            self._scale_value_to_volume(value)
        )

    def _show_background(self, background_tag: str) -> None:
        """場面タグの候補画像を選び、読み込めたものを画像領域へ表示する。"""
        normalized_tag = self.background_catalog.normalize_tag(background_tag)

        # noneや想定外の値では画像検索を行わず、従来どおりCanvasの地色を見せる。
        if not self.background_catalog.is_supported_tag(normalized_tag):
            self._reset_background_window()
            return

        # 複数候補では直前の画像を避けたランダム順になる。
        image_paths = self.background_catalog.selection_order(normalized_tag)
        if not image_paths:
            self._warn_background_once(
                normalized_tag,
                (
                    f"背景画像が見つかりません: {BACKGROUND_DIR / normalized_tag}.jpg / "
                    f".jpeg / .png、{normalized_tag}__任意名、または "
                    f"{BACKGROUND_DIR / normalized_tag} フォルダを確認してください。"
                ),
            )
            self._reset_background_window()
            return

        load_errors: list[str] = []
        for image_path in image_paths:
            try:
                source_surface = self._load_scene_surface(image_path)
                self.scene_source_surface = source_surface
                self._render_scene_image()
            except (OSError, pygame.error, tk.TclError) as exc:
                # 1枚が壊れていても、同じタグの別画像があれば続けて試す。
                # 大量の素材を追加した際に、一部の不良画像だけで無地になりにくい。
                load_errors.append(f"{image_path.name} ({exc})")
                continue

            self.background_catalog.mark_selected(normalized_tag, image_path)
            self.current_background_tag = normalized_tag
            try:
                relative_path = image_path.relative_to(BACKGROUND_DIR).as_posix()
            except ValueError:
                relative_path = image_path.name
            self._log_internal(
                f"背景画像参照: tag={normalized_tag}, "
                f"file=assets/backgrounds/{relative_path}"
            )
            return

        # すべての候補が読み込めなかった場合だけ無地へ戻す。警告文は長くなり
        # すぎないよう先頭3件に絞り、ゲーム進行自体は従来どおり継続する。
        error_summary = "; ".join(load_errors[:3])
        if len(load_errors) > 3:
            error_summary += f"; ほか{len(load_errors) - 3}件"
        self._warn_background_once(
            normalized_tag,
            f"背景画像を読み込めません: {error_summary}",
        )
        self._reset_background_window()

    @staticmethod
    def _load_scene_surface(image_path: Path) -> pygame.Surface:
        """JPG／JPEG／PNGを、拡大縮小可能なSurfaceとして読み込む。"""
        # 既存依存のpygameへ画像形式を集約することで、Pillowなどの追加導入を
        # 必要とせず、対応画像を同じリサイズ処理へ通せる。
        return pygame.image.load(str(image_path))

    def _render_scene_image(self) -> None:
        """元画像をアスペクト比維持のcover方式で現在のCanvasへ描画する。"""
        source = self.scene_source_surface
        if source is None:
            self.scene_image = None
            self.scene_canvas.itemconfigure(self.scene_image_item, image="")
            return

        canvas_width = max(1, int(float(self.scene_canvas.cget("width"))))
        canvas_height = max(1, int(float(self.scene_canvas.cget("height"))))
        source_width, source_height = source.get_size()
        if source_width <= 0 or source_height <= 0:
            raise pygame.error("画像サイズが不正です。")

        # cover方式では、縦横のうち大きい倍率を採用して表示領域を必ず満たす。
        # はみ出した中央部分だけを必要最小限に切り取るため、黒帯や余白が出ない。
        scale = max(
            canvas_width / source_width,
            canvas_height / source_height,
        )
        scaled_width = max(canvas_width, round(source_width * scale))
        scaled_height = max(canvas_height, round(source_height * scale))
        scaled_surface = pygame.transform.smoothscale(
            source,
            (scaled_width, scaled_height),
        )
        crop_x = (scaled_width - canvas_width) // 2
        crop_y = (scaled_height - canvas_height) // 2
        fitted_surface = scaled_surface.subsurface(
            pygame.Rect(crop_x, crop_y, canvas_width, canvas_height)
        ).copy()

        # Tkinterへは標準対応のPPMをメモリ上で渡す。中間画像ファイルは作らない。
        rgb_pixels = pygame.image.tostring(fitted_surface, "RGB")
        ppm_header = (
            f"P6\n{canvas_width} {canvas_height}\n255\n".encode("ascii")
        )
        self.scene_image = tk.PhotoImage(
            data=ppm_header + rgb_pixels,
            format="PPM",
        )
        self.scene_canvas.itemconfigure(
            self.scene_image_item,
            image=self.scene_image,
        )

    def _on_root_configure(self, event: tk.Event) -> None:
        """ルートのサイズ変更を間引き、画像領域の再計算を予約する。"""
        if event.widget is not self.root:
            return
        if self.scene_resize_after_id is not None:
            self.root.after_cancel(self.scene_resize_after_id)
        window_width = int(event.width)
        window_height = int(event.height)
        self.scene_resize_after_id = self.root.after(
            SCENE_RESIZE_DELAY_MS,
            lambda: self._resize_scene_window(window_width, window_height),
        )

    def _resize_scene_window(self, window_width: int, window_height: int) -> None:
        """横長比率と本文スペースを両立するCanvas寸法へ更新する。"""
        self.scene_resize_after_id = None
        available_width = max(
            1,
            window_width - SCENE_WINDOW_HORIZONTAL_MARGIN,
        )
        height_from_width = round(available_width / SCENE_WINDOW_ASPECT_RATIO)
        height_limit = max(1, round(window_height * SCENE_WINDOW_MAX_HEIGHT_RATIO))
        target_height = max(1, min(height_from_width, height_limit))
        target_width = max(
            1,
            min(
                available_width,
                round(target_height * SCENE_WINDOW_ASPECT_RATIO),
            ),
        )

        current_width = int(float(self.scene_canvas.cget("width")))
        current_height = int(float(self.scene_canvas.cget("height")))
        if (target_width, target_height) == (current_width, current_height):
            return

        try:
            self.scene_canvas.configure(width=target_width, height=target_height)
            self.scene_canvas.coords(
                self.scene_image_item,
                target_width // 2,
                target_height // 2,
            )
            self._render_scene_image()
        except (OSError, pygame.error, tk.TclError) as exc:
            # リサイズ描画だけが失敗しても、物語進行や音声処理は止めない。
            self._warn_background_once(
                f"resize:{self.current_background_tag}",
                f"画像のサイズ調整に失敗しました: {exc}",
            )

    def _show_result_image(self, result_image_key: str) -> None:
        """選択結果または本編後の演出に対応する固定画像を表示する。"""
        normalized_key = str(result_image_key).lower().strip()
        candidate_names = RESULT_IMAGE_FILES.get(normalized_key)
        if candidate_names is None:
            return

        # 結果画像もJPGを優先し、同名JPGがなければPNGを探す。
        image_path = next(
            (
                RESULT_IMAGE_DIR / file_name
                for file_name in candidate_names
                if (RESULT_IMAGE_DIR / file_name).is_file()
            ),
            None,
        )
        if image_path is None:
            expected_paths = ", ".join(
                str(RESULT_IMAGE_DIR / file_name)
                for file_name in candidate_names
            )
            self._warn_background_once(
                f"result:{normalized_key}",
                f"結果画像が見つかりません: {expected_paths}",
            )
            # 結果画像は追加演出なので、素材がなければ直前の情景をそのまま残す。
            return

        previous_surface = self.scene_source_surface
        previous_image = self.scene_image
        previous_tag = self.current_background_tag
        try:
            source_surface = self._load_scene_surface(image_path)
            self.scene_source_surface = source_surface
            self._render_scene_image()
        except (OSError, pygame.error, tk.TclError) as exc:
            # 結果画像は任意素材なので、失敗時は直前の情景を復元して継続する。
            self.scene_source_surface = previous_surface
            self.scene_image = previous_image
            self.current_background_tag = previous_tag
            self.scene_canvas.itemconfigure(
                self.scene_image_item,
                image=self.scene_image if self.scene_image is not None else "",
            )
            self._warn_background_once(
                f"result:{normalized_key}",
                f"結果画像を読み込めません: {image_path} ({exc})",
            )
            # 読込失敗でも無地へ戻さず、ゲーム本編の表示と進行を継続する。
            return

        self.current_background_tag = f"result:{normalized_key}"
        self._log_internal(
            f"結果画像参照: key={normalized_key}, "
            f"file=assets/result_images/{image_path.name}"
        )

    def _show_title_image(self) -> None:
        """起動時・再プレイ準備時に、result_imagesのタイトル画像を表示する。"""
        # 前の物語や終了画面を確実に消してからtitle.jpg／title.pngを探す。
        # 任意素材なので、見つからない場合だけ従来どおり無地表示になる。
        self._reset_background_window()
        self._show_result_image("title")

    def _reset_background_window(self) -> None:
        """情景窓の大きさを保ったまま、初期状態の無地表示へ戻す。"""
        self.scene_image = None
        self.scene_source_surface = None
        self.current_background_tag = "none"
        # 空文字を設定すると画像項目だけが消え、Canvasの背景色と寸法は残る。
        self.scene_canvas.itemconfigure(self.scene_image_item, image="")

    def _warn_background_once(self, background_tag: str, message: str) -> None:
        """同じ背景タグの素材警告を、アプリ起動中に一度だけ内部ログへ残す。"""
        if background_tag in self.background_warning_tags:
            return
        self.background_warning_tags.add(background_tag)
        self._log_internal(f"背景画像警告: {message}")

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

    def _begin_generation(self, client: OllamaClient) -> int:
        """新しいLLM生成を現在の依頼として登録し、キャンセル操作を有効にする。"""
        self.generation_id += 1
        self.generation_active = True
        self.active_llm_client = client
        self.cancel_generation_button.config(state=tk.NORMAL)
        return self.generation_id

    def _complete_generation(
        self,
        generation_id: int,
        engine: GameEngine,
    ) -> bool:
        """現在の依頼だけを完了扱いにし、古いワーカー結果は受け付けない。"""
        if (
            not self.generation_active
            or generation_id != self.generation_id
            or self.engine is not engine
        ):
            return False

        self.generation_active = False
        self.active_llm_client = None
        self.cancel_generation_button.config(state=tk.DISABLED)
        return True

    def _finish_start_generation(
        self,
        scene: Scene,
        engine: GameEngine,
        generation_id: int,
    ) -> None:
        """有効な第1場面だけを受け取り、通常の場面表示へ進める。"""
        if not self._complete_generation(generation_id, engine):
            return
        # 開始設定と第1場面の両方が完成した時点で、復帰用の原文は不要になる。
        self.active_free_story_request = None
        self._show_story_text_area()
        self._show_scene(scene)

    def _finish_choice_generation(
        self,
        result: dict[str, object],
        engine: GameEngine,
        generation_id: int,
    ) -> None:
        """有効な選択処理の結果だけを、status別の表示へ引き渡す。"""
        if not self._complete_generation(generation_id, engine):
            return
        self._handle_result(result)

    def _finish_generation_error(
        self,
        message: str,
        engine: GameEngine,
        generation_id: int,
    ) -> None:
        """キャンセル後の古いエラーを無視し、現在の生成エラーだけを通知する。"""
        if not self._complete_generation(generation_id, engine):
            return

        # 通常モードは従来のエラー表示をそのまま使う。自由入力からの開始だけは
        # 原文を保持した入力画面へ戻し、そのまま修正・再試行できるようにする。
        if self.active_free_story_request is None:
            self._finish_with_error(message)
            return

        self.active_free_story_request = None
        self.engine = None
        self._cancel_typing()
        self._stop_waiting_animation()
        self._show_title_image()
        self.game_clear_complete = False
        self.backlog_exported = False
        self.voice_cache_exported = False
        self.current_game_started_at = None
        self.current_game_genre = ""
        self.current_game_model = ""
        self.export_text_button.config(state=tk.DISABLED)
        self.export_voice_button.config(state=tk.DISABLED)
        self.retry_button.config(state=tk.DISABLED)
        self.start_button.config(text="ゲーム開始")
        self._reset_choice_buttons()
        self._clear_backlog()
        # 入力画面の背後にある本文欄も初期案内へ戻す。エラー後に通常ジャンルへ
        # 切り替えた場合、失敗時の待機表示や見出しが残らないようにする。
        self._clear_text_area()
        self._write(
            "ジャンル（または「自由に綴る」）とモデルを選び、"
            "「ゲーム開始」を押してください。\n"
            "ゲーム中は、画面下のAまたはBボタンで選択します。\n"
            "Enterを押すと、全文表示または現在の音声停止を行います。\n"
        )
        self.genre_var.set(FREE_STORY_MODE_NAME)
        self.free_story_feedback_var.set(
            "物語の準備に失敗しました。入力内容を確認して再試行できます。"
        )
        self._show_free_story_input()
        self._set_busy(False)
        messagebox.showerror("エラー", message)

    def cancel_generation(self) -> None:
        """
        進行中のLLM生成を中止し、起動直後と同じゲーム未開始状態へ戻す。

        先にgeneration_idとengineを無効化するため、通信スレッドの終了と
        Tkinterコールバックが競合しても、古い場面やエラーは表示されない。
        """
        if not self.generation_active:
            return

        was_free_story_start = self.active_free_story_request is not None
        client = self.active_llm_client
        self.generation_id += 1
        self.generation_active = False
        self.active_llm_client = None
        self.active_free_story_request = None
        self.engine = None
        self.cancel_generation_button.config(state=tk.DISABLED)

        # Event通知とResponse.close()により、Ollama待機中の通信も終了へ向かわせる。
        # 画面状態は通信スレッドの終了を待たず、直ちに初期状態へ戻す。
        if client is not None:
            client.cancel_current_request()

        self._invalidate_presentation()
        self._cancel_typing()
        self._stop_waiting_animation()
        self.voice_pipeline.stop()
        self.voice_pipeline.stop_sound_effect()
        self.bgm_manager.play("title")
        self._clear_all_voice_cache()
        self.current_voice_cache_key = None
        self._show_title_image()

        self.game_clear_complete = False
        self.backlog_exported = False
        self.voice_cache_exported = False
        self.current_game_started_at = None
        self.current_game_genre = ""
        self.current_game_model = ""
        self.export_text_button.config(state=tk.DISABLED)
        self.export_voice_button.config(state=tk.DISABLED)
        self.retry_button.config(state=tk.DISABLED)
        self.start_button.config(text="ゲーム開始")
        self._reset_choice_buttons()
        self._clear_backlog()
        self._clear_text_area()
        if was_free_story_start:
            # 自由入力の文章は専用ウィジェット内に残っているため、削除せず
            # そのまま再試行できる画面へ戻す。
            self.genre_var.set(FREE_STORY_MODE_NAME)
            self.free_story_feedback_var.set(
                "物語の準備をキャンセルしました。入力内容は保持されています。"
            )
            self._show_free_story_input()
        else:
            self._show_story_text_area()
            self._write(
                "物語の生成をキャンセルしました。\n\n"
                "ジャンル（または「自由に綴る」）とモデルを選び、"
                "「ゲーム開始」を押してください。\n"
                "ゲーム中は、画面下のAまたはBボタンで選択します。\n"
                "Enterを押すと、全文表示または現在の音声停止を行います。\n"
            )
        self._set_busy(False)

    def start_game(self) -> None:
        """
        選択中のジャンル・モデルで、新しいゲームを非同期に開始する。

        前回の表示予約・音声・キャッシュを片付けてからGameEngineを作り直すため、
        開始後は同じボタンが「最初から」へ変わるが、処理は常にここへ集約する。
        """
        if self.busy:
            return

        # GUIの装飾付き表示名ではなく、Ollamaが認識する実モデル名を使う。
        # ゲーム状態を片付ける前に検証し、不足時に現在の表示を失わないようにする。
        model = self._selected_model_name()
        if not model:
            self._show_error("モデル名を入力してください。")
            return

        free_story_request: str | None = None
        if self._is_free_story_mode():
            input_text = self.free_story_input.get("1.0", "end-1c")
            normalized_input = input_text.strip()
            if not normalized_input:
                # 空欄ではOllamaへ一切送らず、入力場所のすぐ下で案内する。
                self.free_story_feedback_var.set(
                    "遊びたい物語を入力してください。"
                )
                self.free_story_input.focus_set()
                self.root.bell()
                return
            if len(input_text) > FREE_STORY_REQUEST_MAX_CHARACTERS:
                self.free_story_feedback_var.set(
                    f"{FREE_STORY_REQUEST_MAX_CHARACTERS}文字以内で入力してください。"
                )
                self.free_story_input.focus_set()
                self.root.bell()
                return
            free_story_request = normalized_input
            self.free_story_feedback_var.set("")

        # プレイ途中の押し間違いだけは確認する。エンディング後は確認せず、
        # すぐ次の物語へ進めるほうが繰り返し遊びやすい。
        if (
            self.engine is not None
            and not self.engine.finished
            and not messagebox.askyesno(
                "最初から",
                "現在の物語を終了して、最初から始めますか？",
            )
        ):
            return

        # 古いゲームの非同期表示・音声が新しいゲームへ混ざらないよう先に停止する。
        self._invalidate_presentation()
        self._cancel_typing()
        self._stop_waiting_animation()
        self.voice_pipeline.stop()
        self.voice_pipeline.stop_sound_effect()
        # 再プレイ準備中はタイトル画面の曲へ戻す。すでにtitleが再生中なら
        # BGMManagerが同一タグと判定し、曲頭へ戻さずそのまま継続する。
        self.bgm_manager.play("title")
        self._clear_all_voice_cache()
        self.current_voice_cache_key = None
        # 再プレイでは前の物語の情景を残さず、生成中からタイトル画像へ戻す。
        self._show_title_image()
        self.choice_buttons_ready = False
        self._reset_choice_buttons()

        if free_story_request is not None:
            # 整理処理が完了するまでは仮の既存形式を入れ、同じGameEngineを
            # 生成管理へ登録する。worker内でLLMが整理した値へ安全に置き換える。
            genre_name = FREE_STORY_MODE_NAME
            genre_prompt = free_story_request
        else:
            genre_name = self.genre_var.get()
            genre_prompt = GENRES[genre_name]

        # 新しいゲーム単位で、閲覧・書き出し対象の記録を初期化する。
        self.game_clear_complete = False
        self.backlog_exported = False
        self.voice_cache_exported = False
        self.export_text_button.config(state=tk.DISABLED)
        self.export_voice_button.config(state=tk.DISABLED)
        self.current_game_started_at = datetime.now()
        self.current_game_genre = genre_name
        self.current_game_model = model
        self._clear_backlog()
        self._append_backlog(f"=== {genre_name} ===\n")

        # 1ゲームで使うクライアントとエンジンを、現在の設定から組み立てる。
        client = OllamaClient(
            base_url=SETTINGS["ollama"]["base_url"],
            model=model,
            timeout=SETTINGS["ollama"]["timeout_seconds"],
        )
        engine = GameEngine(
            llm_client=client,
            genre_name=genre_name,
            genre_prompt=genre_prompt,
            total_scenes=SETTINGS["game"]["total_scenes"],
            max_retries=SETTINGS["game"]["max_retries"],
            summary_max_characters=SETTINGS["game"].get(
                "summary_max_characters",
                100,
            ),
            logger=self._log_internal,
        )
        self.engine = engine
        self.active_free_story_request = free_story_request

        # 専用入力欄は開始時点で隠し、既存の待機表示・本文表示へ戻す。
        # 入力ウィジェット自体は破棄しないため、失敗時には原文を復元できる。
        self._show_story_text_area()
        self._clear()
        self.retry_button.config(state=tk.DISABLED)
        self._write(f"=== {genre_name} ===\n")
        self.start_button.config(text="最初から")
        # LLM生成中は入力を無効化し、待機アニメーションだけを動かす。
        self._set_busy(True)
        self._start_waiting_animation()
        generation_id = self._begin_generation(client)
        threading.Thread(
            target=self._start_game_worker,
            args=(engine, generation_id, free_story_request),
            daemon=True,
        ).start()

    def _start_game_worker(
        self,
        engine: GameEngine,
        generation_id: int,
        free_story_request: str | None,
    ) -> None:
        """必要なら自由文を整理し、第1場面を生成してメインスレッドへ戻す。"""
        try:
            if free_story_request is not None:
                engine.prepare_free_story(free_story_request)
            scene = engine.start()
            self.root.after(
                0,
                lambda: self._finish_start_generation(
                    scene,
                    engine,
                    generation_id,
                ),
            )
        except LLMGenerationCancelled:
            # 画面はcancel_generation()がすでに初期化しているため何も戻さない。
            return
        except Exception as exc:
            # 予期した生成エラーに加え、ログを残すため想定外例外も最終的に捕捉する。
            self._log_exception(exc)
            message = f"ゲーム開始に失敗しました。\n{exc}"
            self.root.after(
                0,
                lambda message=message: self._finish_generation_error(
                    message,
                    engine,
                    generation_id,
                ),
            )

    def submit_choice(self, choice: str) -> None:
        """A・Bボタンで選ばれた値を検証し、正誤判定へ渡す。"""
        if (
            self.busy
            or self.typing_active
            or not self.choice_buttons_ready
            or self.engine is None
        ):
            return

        choice = choice.strip().lower()

        if choice not in {"a", "b"}:
            return

        # 上のガードで確認済みだが、以降はローカル変数に固定してワーカーへ渡す。
        # これにより、キャンセル時にself.engineがNoneへ戻っても、古いスレッドと
        # 新しい画面状態を混在させずgeneration_idで結果を破棄できる。
        engine = self.engine
        if engine is None:
            return

        # 選択が確定したら、まだ読み上げ中だった現在場面の音声も止める。
        # 先にボタンを無効化するため、素早い連打でも二重送信されない。
        self.choice_buttons_ready = False
        self._disable_choice()
        self.stop_voice()

        choice_text = self.current_choice_texts.get(choice, "")
        choice_record = f"\n\nあなたの選択：{choice.upper()}　{choice_text}\n"
        self._write(choice_record)
        self._append_backlog(choice_record)
        self._set_busy(True)
        self._start_waiting_animation()
        generation_id = self._begin_generation(engine.llm_client)
        threading.Thread(
            target=self._choice_worker,
            args=(engine, choice, generation_id),
            daemon=True,
        ).start()

    def _choice_worker(
        self,
        engine: GameEngine,
        choice: str,
        generation_id: int,
    ) -> None:
        """GameEngineの選択処理を実行し、status別表示へ引き渡す。"""
        try:
            result = engine.choose(choice)
            self.root.after(
                0,
                lambda: self._finish_choice_generation(
                    result,
                    engine,
                    generation_id,
                ),
            )
        except LLMGenerationCancelled:
            # 画面はcancel_generation()がすでに初期化しているため何も戻さない。
            return
        except Exception as exc:
            self._log_exception(exc)
            message = f"ゲーム進行中にエラーが発生しました。\n{exc}"
            self.root.after(
                0,
                lambda message=message: self._finish_generation_error(
                    message,
                    engine,
                    generation_id,
                ),
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
            # 正解結果と次場面を別々の演出として見せる。
            # 次場面はすでに生成済みだが、専用ボタンが押されるまで表示しない。
            self.voice_pipeline.stop()
            self.choice_buttons_ready = False
            self._reset_choice_buttons()

            result_text = str(result.get("result_text", ""))
            scene = result["scene"]
            if not isinstance(scene, Scene):
                self._finish_with_error("次の場面データを読み取れませんでした。")
                return

            # 正解SE以降の結果文では本編BGMを流さず、次章の本文開始時に
            # 新しいSceneのbgm_tagが改めて曲を選ぶ。VOICEVOXと効果音は維持する。
            self.bgm_manager.stop(fade_ms=0)

            # 文字表示と音声の「両方」が終わったら、次場面へ自動遷移せず
            # 選択肢欄へ専用ボタンを出す。Enterや音声停止で読み上げを中断した
            # 場合も、従来どおり音声完了扱いとなり、ボタン表示へ進める。
            self._play_sound_effect_then(
                CORRECT_SFX_PATH,
                lambda: self._prepare_narrative(
                    display_text=f"\n\n{result_text}\n",
                    voice_parts=[
                        (
                            result_text,
                            f"scene_{scene.number}_transition",
                        )
                    ],
                    on_narrative_complete=lambda scene=scene: (
                        self._show_next_scene_button(scene)
                    ),
                ),
                result_image_key="correct",
            )
            return

        if status == "bad_end":
            # タイピング完了までは再挑戦ボタンを無効にし、表示途中の操作できなくする。
            self.choice_buttons_ready = False
            self._reset_choice_buttons()
            # BAD ENDは専用曲を持たず、効果音だけを明確に聞かせる仕様のため、
            # BGM専用チャンネルだけを即時停止する。VOICEVOXには触れない。
            self.bgm_manager.stop(fade_ms=0)
            text = (
                f"\n\n=== BAD END ===\n"
                f"{result['title']}\n\n"
                f"{result['text']}\n\n"
                "「直前の選択肢へ」で同じ場面から再挑戦できます。\n"
                "「最初から」で最初の場面からやり直せます。\n"
            )
            self.retry_button.config(state=tk.DISABLED)
            self._play_sound_effect_then(
                BAD_END_SFX_PATH,
                lambda: self._prepare_narrative(
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
                ),
                result_image_key="bad_end",
            )
            self._disable_choice()
            return

        if status == "good_end":
            # クリア後は選択入力を閉じ、終了情報を少しずつ順番に見せる。
            self.voice_pipeline.stop()
            # 最終選択の確定時点で本編BGMを止め、GOOD END本文は無音にする。
            # 後続のエピローグではendingタグが改めて曲を開始するため、
            # BGM専用チャンネル以外のVOICEVOX・効果音には触れない。
            self.bgm_manager.stop(fade_ms=0)
            self.choice_buttons_ready = False
            self._reset_choice_buttons()
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

            # JSON仕様を増やさず、最終場面がすでに持っているbackground_tagを
            # GOOD ENDとエピローグの各表示開始時に改めて適用する。
            # これにより、固定の終了画像へ置き換えず物語側の情景画像を使用する。
            ending_background_tag = "none"
            if self.engine is not None and self.engine.current_scene is not None:
                ending_background_tag = self.engine.current_scene.background_tag

            # 1つの長文へ結合せず、各セクションの文字・音声完了後に
            # ENDING_SECTION_PAUSE_MSだけ待ってから次へ進める。
            ending_stages: list[
                tuple[
                    str,
                    list[tuple[str, str]],
                    str | None,
                    str | None,
                    str | None,
                ]
            ] = [
                (
                    (
                        f"\n\n=== GOOD END ===\n"
                        f"{result['title']}\n\n"
                        f"{good_end_text}\n"
                    ),
                    [
                        (
                            f"グッドエンド。{result['title']}。{good_end_text}",
                            "good_ending_main",
                        )
                    ],
                    ending_background_tag,
                    None,
                    None,
                ),
                (
                    f"\n\n=== EPILOGUE ===\n{epilogue}\n",
                    [(f"エピローグ。{epilogue}", "good_ending_epilogue")],
                    ending_background_tag,
                    None,
                    "ending",
                ),
                (
                    f"\n\n=== GAME CLEAR ===\n{clear_message}\n",
                    [
                        (
                            f"ゲームクリア。{clear_message}",
                            "good_ending_clear",
                        )
                    ],
                    None,
                    "game_clear",
                    "game_clear",
                ),
                (
                    f"\n\n=== AI COMMENT ===\n{ai_comment}\n",
                    [(f"AIコメント。{ai_comment}", "good_ending_comment")],
                    None,
                    "ai_comment",
                    "game_clear",
                ),
                (
                    (
                        "\n\n=== PLAY RECORD ===\n"
                        f"判定: {play_judgement}\n"
                        f"バッドエンド到達回数: {bad_end_count}\n"
                        f"直前の選択肢へ戻った回数: {retry_count}\n"
                        f"総選択回数: {choice_count}\n"
                    ),
                    [],
                    None,
                    "play_record",
                    "game_clear",
                ),
                (
                    f"\n\n{ENDING_THANK_YOU_TEXT}\n",
                    [(ENDING_THANK_YOU_VOICE, "good_ending_thanks")],
                    None,
                    "thank_you",
                    "game_clear",
                ),
            ]
            self._play_sound_effect_then(
                GOOD_END_SFX_PATH,
                lambda: self._play_ending_sequence(ending_stages),
            )
            self._disable_choice()

    def _show_scene(self, scene: Scene) -> None:
        """
        Sceneを画面表示用文字列と読み上げ用文字列へ整形する。

        画面用には記号や改行を残し、音声用には「選択肢a」のような読みを
        補っている。
        """
        self.retry_button.config(state=tk.DISABLED)
        self.current_voice_cache_key = f"scene_{scene.number}"
        self.choice_buttons_ready = False
        self._reset_choice_buttons()

        # 選択肢本文は画面下の大きなボタンへ移し、物語欄には場面本文だけを置く。
        # 読み進める目線を中央の場面カードへ保ちやすくなる。
        display_text = (
            f"\n\n--- 場面 {scene.number} / "
            f"{SETTINGS['game']['total_scenes']} ---\n"
            f"【{scene.title}】\n\n"
            f"{scene.scene_text}\n"
        )

        # scene_voice_textはVOICEVOXが自然に読み分けられる句読点を補う。
        scene_voice_text = (
            f"{scene.title}。{scene.scene_text}。"
            f"選択肢a、{scene.choice_a}。"
            f"選択肢b、{scene.choice_b}。"
        )

        self._prepare_narrative(
            display_text=display_text,
            voice_parts=[(scene_voice_text, self.current_voice_cache_key)],
            # 音声先行生成が終わり、本文表示が始まる瞬間にだけ画像を切り替える。
            background_tag=scene.background_tag,
            # 画像と同じタイミングでSceneの曲へ切り替える。同じタグなら
            # BGMManager側で何もせず、前Sceneからループ再生を継続する。
            bgm_tag=scene.bgm_tag,
            # 本文の最後の文字が出るまで、分岐文をボタンへ設定しない。
            on_typing_complete=lambda scene=scene: (
                self._set_choice_buttons(scene)
            ),
            backlog_text=(
                display_text
                + f"\nA　{scene.choice_a}\n"
                + f"B　{scene.choice_b}\n"
            ),
        )

    def _prepare_narrative(
        self,
        *,
        display_text: str,
        voice_parts: list[tuple[str, str]],
        on_typing_complete: Callable[[], None] | None = None,
        on_narrative_complete: Callable[[], None] | None = None,
        backlog_text: str | None = None,
        replace_display: bool = True,
        background_tag: str | None = None,
        result_image_key: str | None = None,
        bgm_tag: str | None = None,
    ) -> None:
        """
        最初の音声チャンクを準備してから、本文表示と音声再生を開始する。

        音声が無効な場合や話者IDが不正な場合は、音声を待たずに本文を表示する。
        """
        # 新しい表示世代を発行する。先行生成中の古いスレッドが完了しても、
        # _begin_narrative側で世代不一致として破棄できる。
        self.presentation_id += 1
        presentation_id = self.presentation_id
        self.voice_cancelled_presentation_id = None
        self.narrative_typing_done = False
        self.narrative_voice_done = not bool(voice_parts)
        self.narrative_complete_callback = on_narrative_complete

        self._cancel_typing()
        self._disable_choice()
        # 前の場面の再生・待機ジョブを止める。生成済みキャッシュは残る。
        self.voice_pipeline.stop()

        # 読み上げOFF、または画面表示だけの項目なら、音声準備スレッドを作らない。
        if not self.voice_enabled_var.get() or not voice_parts:
            self._begin_narrative(
                display_text=display_text,
                voice_parts=[],
                speaker_id=None,
                on_typing_complete=on_typing_complete,
                on_narrative_complete=on_narrative_complete,
                backlog_text=backlog_text,
                replace_display=replace_display,
                background_tag=background_tag,
                result_image_key=result_image_key,
                bgm_tag=bgm_tag,
                presentation_id=presentation_id,
            )
            return

        # GUI入力は文字列なので、APIへ渡す前に整数へ変換・検証する。
        try:
            speaker_id = int(self.speaker_var.get())
        except ValueError:
            self._begin_narrative(
                display_text=display_text,
                voice_parts=[],
                speaker_id=None,
                on_typing_complete=on_typing_complete,
                on_narrative_complete=on_narrative_complete,
                backlog_text=backlog_text,
                replace_display=replace_display,
                background_tag=background_tag,
                result_image_key=result_image_key,
                bgm_tag=bgm_tag,
                presentation_id=presentation_id,
                voice_error="話者IDは数字で入力してください。",
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
                on_narrative_complete,
                backlog_text,
                replace_display,
                background_tag,
                result_image_key,
                bgm_tag,
                presentation_id,
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
        on_narrative_complete: Callable[[], None] | None,
        backlog_text: str | None,
        replace_display: bool,
        background_tag: str | None,
        result_image_key: str | None,
        bgm_tag: str | None,
        presentation_id: int,
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
                on_narrative_complete=on_narrative_complete,
                backlog_text=backlog_text,
                replace_display=replace_display,
                background_tag=background_tag,
                result_image_key=result_image_key,
                bgm_tag=bgm_tag,
                presentation_id=presentation_id,
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
        on_narrative_complete: Callable[[], None] | None,
        backlog_text: str | None,
        replace_display: bool,
        background_tag: str | None,
        result_image_key: str | None,
        bgm_tag: str | None,
        presentation_id: int,
        voice_error: str | None = None,
    ) -> None:
        """
        待機表示を消し、タイピングと音声再生をほぼ同時に始める。

        VOICEVOX失敗時はエラーを表示しつつ ``voice_parts`` を空にしているため、
        音声機能だけを切り離し、ゲーム本文は通常どおり進行できる。
        """
        # 「最初から」などで別の表示が始まっていれば、古い先行生成結果は捨てる。
        if presentation_id != self.presentation_id:
            return

        self._stop_waiting_animation()
        # BGMも本文が実際に始まる瞬間にだけ切り替える。VOICEVOXの先行生成中は
        # 直前の曲を維持するため、待ち時間中の不自然な無音や先走りを避けられる。
        if bgm_tag is not None:
            self.bgm_manager.play(bgm_tag)
        # background_tag=Noneの正解結果・各エンディングでは、直前の画像を維持する。
        # Sceneを表示するときだけタグが渡り、本文タイピング開始直前に切り替わる。
        if background_tag is not None:
            self._show_background(background_tag)
        # AIコメント以降の固定画像も、VOICEVOX先行生成の前ではなく、対応する
        # セクションの本文表示が実際に始まるこの瞬間に切り替える。
        if result_image_key is not None:
            self._show_result_image(result_image_key)
        if replace_display:
            self._clear_text_area()

        # 先頭チャンクの生成待ち中に「音声停止」が押されていた場合も、
        # 完成直後に読み上げが始まらないよう、この表示だけ音声なしへ切り替える。
        if self.voice_cancelled_presentation_id == presentation_id:
            voice_parts = []
            speaker_id = None

        has_voice = bool(voice_parts and speaker_id is not None)
        self.narrative_typing_done = False
        self.narrative_voice_done = not has_voice
        self.narrative_complete_callback = on_narrative_complete

        if voice_error:
            self._write(f"\n--- VOICEVOXエラー: {voice_error} ---\n")

        def typing_finished() -> None:
            # バックログへは、全文が画面に出た時点で初めて完成形を追加する。
            # これにより、閲覧画面から未表示の文章や分岐を先読みできない。
            self._append_backlog(
                backlog_text if backlog_text is not None else display_text
            )
            # 場面固有の処理（選択肢の有効化など）を先に済ませてから、
            # 音声を含む物語全体の完了判定へ進む。
            if on_typing_complete is not None:
                on_typing_complete()
            self._mark_narrative_typing_done(presentation_id)

        self._start_typing(
            display_text,
            on_complete=typing_finished,
        )

        if has_voice and speaker_id is not None:
            self.voice_pipeline.speak_sequence(
                voice_parts,
                speaker_id=speaker_id,
                # 音声ワーカーからTkinterを直接触らず、メインスレッドへ戻す。
                on_complete=lambda: self.root.after(
                    0,
                    lambda: self._mark_narrative_voice_done(
                        presentation_id
                    ),
                ),
            )

    def _set_choice_buttons(self, scene: Scene) -> None:
        """本文完了後、現在場面の選択肢を設定して画面へ表示する。"""
        self.pending_continue_action = None
        self.next_scene_button.config(state=tk.DISABLED)
        self.next_scene_button.grid_remove()
        self.current_choice_texts = {
            "a": scene.choice_a,
            "b": scene.choice_b,
        }
        self.choice_a_button.config(
            text=f"A　{scene.choice_a}",
            background=CHOICE_BUTTON_BG,
        )
        self.choice_b_button.config(
            text=f"B　{scene.choice_b}",
            background=CHOICE_BUTTON_BG,
        )
        # grid_remove()で隠したボタンは、引数なしのgrid()で元の位置へ戻せる。
        self.choice_a_button.grid()
        self.choice_b_button.grid()
        self.choice_buttons_ready = True

    def _show_next_scene_button(self, scene: Scene) -> None:
        """正解結果の完了後、次場面へ進むための専用ボタンだけを表示する。"""
        # 次場面はLLM生成済みだが、クリックされるまでは表示処理へ渡さない。
        self._show_continue_button(
            button_text="次のシナリオへ",
            action=lambda scene=scene: self._schedule_next_scene(scene),
        )

    def _show_continue_button(
        self,
        *,
        button_text: str,
        action: Callable[[], None],
    ) -> None:
        """通常章とエンディングで共用する、1回限りの続行ボタンを表示する。"""
        self.choice_buttons_ready = False
        self.current_choice_texts = {"a": "", "b": ""}
        self.choice_a_button.grid_remove()
        self.choice_b_button.grid_remove()

        # actionはクリック時に取り外してから実行するため、連打されても同じ
        # Sceneやエンディング項目が二重に開始されない。
        self.pending_continue_action = action
        self.next_scene_button.config(
            text=button_text,
            state=(
                tk.DISABLED
                if self.busy or self.typing_active
                else tk.NORMAL
            ),
            background=CHOICE_BUTTON_BG,
        )
        self.next_scene_button.grid()

    def _advance_from_continue_button(self) -> None:
        """続行ボタンを1回だけ確定し、登録済みの次処理を実行する。"""
        if (
            self.busy
            or self.typing_active
            or self.pending_continue_action is None
        ):
            return

        action = self.pending_continue_action
        self.pending_continue_action = None
        # 連打による二重遷移を防ぐため、予約を作る前にボタンを無効化して隠す。
        self.next_scene_button.config(
            state=tk.DISABLED,
            background=CHOICE_BUTTON_BG,
        )
        self.next_scene_button.grid_remove()
        # 次Sceneそのものが生成済みでも、VOICEVOXの先頭チャンク準備や章間の
        # 余韻に時間がかかることがある。通常のLLM生成時と同じ待機表示を出し、
        # 次の本文が実際に始まる_begin_narrative()で自動的に消す。
        self._set_busy(True)
        self._start_waiting_animation()
        action()

    def _reset_choice_buttons(self) -> None:
        """場面本文の表示中や場面外では、選択肢関連ボタンをすべて隠す。"""
        self.choice_buttons_ready = False
        self.pending_continue_action = None
        self.current_choice_texts = {"a": "", "b": ""}
        self.choice_a_button.config(text="A")
        self.choice_b_button.config(text="B")
        self.next_scene_button.config(
            text="次のシナリオへ",
            state=tk.DISABLED,
            background=CHOICE_BUTTON_BG,
        )
        self._disable_choice()
        self.choice_a_button.grid_remove()
        self.choice_b_button.grid_remove()
        self.next_scene_button.grid_remove()

    def _bind_choice_hover(self, button: tk.Button) -> None:
        """有効な選択肢へマウスが入った・出たときの色変更を登録する。"""
        button.bind(
            "<Enter>",
            lambda _event, target=button: self._set_choice_hover(
                target,
                hovering=True,
            ),
        )
        button.bind(
            "<Leave>",
            lambda _event, target=button: self._set_choice_hover(
                target,
                hovering=False,
            ),
        )

    @staticmethod
    def _set_choice_hover(button: tk.Button, *, hovering: bool) -> None:
        """無効ボタンは変えず、有効なボタンだけ背景色を切り替える。"""
        if str(button.cget("state")) == str(tk.DISABLED):
            return
        button.config(
            background=(
                CHOICE_BUTTON_HOVER_BG if hovering else CHOICE_BUTTON_BG
            )
        )

    def _mark_narrative_typing_done(self, presentation_id: int) -> None:
        """現在表示の文字演出が完了したことを記録する。"""
        if presentation_id != self.presentation_id:
            return
        self.narrative_typing_done = True
        self._try_complete_narrative(presentation_id)

    def _mark_narrative_voice_done(self, presentation_id: int) -> None:
        """現在表示の読み上げが完了または停止したことを記録する。"""
        if presentation_id != self.presentation_id:
            return
        self.narrative_voice_done = True
        self._try_complete_narrative(presentation_id)

    def _try_complete_narrative(self, presentation_id: int) -> None:
        """文字と音声が両方終わったとき、完了処理を一度だけ実行する。"""
        if (
            presentation_id != self.presentation_id
            or not self.narrative_typing_done
            or not self.narrative_voice_done
        ):
            return

        callback = self.narrative_complete_callback
        # コールバック内で次の表示を始めても二重実行されないよう、先に参照を外す。
        self.narrative_complete_callback = None
        if callback is not None:
            callback()

    def _play_ending_sequence(
        self,
        stages: list[
            tuple[
                str,
                list[tuple[str, str]],
                str | None,
                str | None,
                str | None,
            ]
        ],
        index: int = 0,
    ) -> None:
        """エンディングを独立画面で1項目ずつ表示する。"""
        if index >= len(stages):
            self._finish_game_clear_sequence()
            return

        (
            display_text,
            voice_parts,
            background_tag,
            result_image_key,
            bgm_tag,
        ) = stages[index]
        self._prepare_narrative(
            display_text=display_text,
            voice_parts=voice_parts,
            # 各項目を「別シーン」として扱い、直前の終了文へ追記しない。
            replace_display=True,
            background_tag=background_tag,
            result_image_key=result_image_key,
            bgm_tag=bgm_tag,
            on_narrative_complete=lambda: self._complete_ending_stage(
                stages,
                index,
            ),
        )

    def _complete_ending_stage(
        self,
        stages: list[
            tuple[
                str,
                list[tuple[str, str]],
                str | None,
                str | None,
                str | None,
            ]
        ],
        current_index: int,
    ) -> None:
        """現在項目の完了後、次項目があれば手動続行ボタンを表示する。"""
        next_index = current_index + 1
        if next_index >= len(stages):
            self._finish_game_clear_sequence()
            return

        button_text = ENDING_CONTINUE_BUTTON_TEXTS.get(next_index, "次へ")
        self._show_continue_button(
            button_text=button_text,
            # クリック後の短い余韻は従来どおり残すが、クリックされるまでは
            # 何分待っても次項目へ進まない。
            action=lambda: self._schedule_presentation_action(
                ENDING_SECTION_PAUSE_MS,
                lambda: self._play_ending_sequence(stages, next_index),
            ),
        )

    def _finish_game_clear_sequence(self) -> None:
        """エンディング完了後、テキストと生成済み音声の保存を許可する。"""
        self.game_clear_complete = True
        self.export_text_button.config(state=tk.NORMAL)

        # 読み上げOFFや全生成失敗の場合は、押しても保存対象がないため無効のまま。
        if any(VOICE_CACHE_DIR.glob("*.wav")):
            self.export_voice_button.config(state=tk.NORMAL)

    def _schedule_next_scene(self, scene: Scene) -> None:
        """専用ボタンのクリック後に章間の余韻を置き、次の場面を表示する。"""
        self._schedule_presentation_action(
            CHAPTER_TRANSITION_PAUSE_MS,
            lambda: self._show_scene(scene),
        )

    def _schedule_presentation_action(
        self,
        delay_ms: int,
        action: Callable[[], None],
    ) -> None:
        """現在の表示世代に属する処理だけを、指定時間後に実行する。"""
        self._cancel_scheduled_transition()
        presentation_id = self.presentation_id

        def run_if_current() -> None:
            self.transition_after_id = None
            if presentation_id != self.presentation_id:
                return
            action()

        self.transition_after_id = self.root.after(
            delay_ms,
            run_if_current,
        )

    def _play_sound_effect_then(
        self,
        wav_path: Path,
        action: Callable[[], None],
        *,
        result_image_key: str | None = None,
    ) -> None:
        """
        必要なら結果画像へ切り替え、効果音開始後250ミリ秒で表示処理を実行する。

        WAVが存在しない場合もplay_sound_effect()はFalseを返すだけなので、
        after()予約は通常どおり作られ、ゲーム本文とVOICEVOXは続行できる。
        結果画像が存在しない場合も、直前の情景画像を保ったまま同様に続行する。
        表示世代も確認し、「最初から」のあとに古い結末が出ることを防ぐ。
        """
        self._cancel_scheduled_sfx_narrative()
        # LLM生成中は以前の情景を維持し、結果が確定したこの時点でだけ切り替える。
        # 効果音より先に設定することで、目と耳で同時に正解・結末を受け取れる。
        if result_image_key is not None:
            self._show_result_image(result_image_key)
        self.voice_pipeline.play_sound_effect(wav_path)
        presentation_id = self.presentation_id

        def run_if_current() -> None:
            self.sfx_narrative_after_id = None
            if presentation_id != self.presentation_id:
                return
            action()

        self.sfx_narrative_after_id = self.root.after(
            SFX_NARRATIVE_DELAY_MS,
            run_if_current,
        )

    def _cancel_scheduled_sfx_narrative(self) -> None:
        """効果音後に予約された古い本文・エンディング開始を取り消す。"""
        if self.sfx_narrative_after_id is not None:
            self.root.after_cancel(self.sfx_narrative_after_id)
            self.sfx_narrative_after_id = None

    def _cancel_scheduled_transition(self) -> None:
        """「最初から」や終了時に、予約済みの次場面表示を取り消す。"""
        if self.transition_after_id is not None:
            self.root.after_cancel(self.transition_after_id)
            self.transition_after_id = None

    def _invalidate_presentation(self) -> None:
        """非同期で戻ってくる古い表示・音声完了通知をまとめて無効化する。"""
        self._cancel_scheduled_transition()
        self._cancel_scheduled_sfx_narrative()
        self.presentation_id += 1
        self.narrative_typing_done = False
        self.narrative_voice_done = True
        self.narrative_complete_callback = None
        self.voice_cancelled_presentation_id = None

    def stop_voice(self) -> None:
        """現在の読み上げを止め、章間処理では音声完了として扱う。"""
        presentation_id = self.presentation_id
        self.voice_cancelled_presentation_id = presentation_id
        self.voice_pipeline.stop()
        self._mark_narrative_voice_done(presentation_id)

    def show_backlog(self) -> None:
        """現在までに表示が完了したゲーム文章を、別ウィンドウで閲覧する。"""
        if self.backlog_window is not None:
            try:
                if self.backlog_window.winfo_exists():
                    self.backlog_window.lift()
                    return
            except tk.TclError:
                pass

        window = tk.Toplevel(self.root)
        window.title("綴り文庫室 - バックログ")
        window.geometry("760x560")
        window.minsize(560, 400)
        window.grid_rowconfigure(0, weight=1)
        window.grid_columnconfigure(0, weight=1)

        text_area = scrolledtext.ScrolledText(
            window,
            wrap=tk.WORD,
            font=("", 11),
            padx=18,
            pady=14,
            state=tk.DISABLED,
        )
        text_area.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        close_button = tk.Button(
            window,
            text="閉じる",
            command=self._close_backlog_window,
        )
        close_button.grid(row=1, column=0, pady=(0, 10))

        self.backlog_window = window
        self.backlog_text_area = text_area
        window.protocol("WM_DELETE_WINDOW", self._close_backlog_window)
        self._refresh_backlog_window(follow_end=False)

    def _close_backlog_window(self) -> None:
        """バックログ画面を閉じ、破棄済み部品への参照を残さない。"""
        window = self.backlog_window
        self.backlog_window = None
        self.backlog_text_area = None
        if window is not None:
            try:
                window.destroy()
            except tk.TclError:
                pass

    def _append_backlog(self, text: str) -> None:
        """表示完了済みのゲーム文章を記録し、閲覧中なら画面も更新する。"""
        if not text:
            return
        self.backlog_entries.append(text)
        self._refresh_backlog_window(follow_end=True)

    def _clear_backlog(self) -> None:
        """新しいゲーム開始時に、前回の物語記録を空にする。"""
        self.backlog_entries.clear()
        self._refresh_backlog_window(follow_end=False)

    def _refresh_backlog_window(self, *, follow_end: bool) -> None:
        """バックログ画面が開いている場合だけ、現在の記録を反映する。"""
        text_area = self.backlog_text_area
        if text_area is None:
            return

        try:
            text_area.config(state=tk.NORMAL)
            text_area.delete("1.0", tk.END)
            text_area.insert(tk.END, self._build_backlog_text())
            if follow_end:
                text_area.see(tk.END)
            else:
                text_area.yview_moveto(0.0)
            text_area.config(state=tk.DISABLED)
        except tk.TclError:
            # ユーザーがウィンドウを閉じた直後なら、次回表示時に作り直す。
            self.backlog_window = None
            self.backlog_text_area = None

    def _build_backlog_text(self) -> str:
        """画面閲覧とテキスト保存で共通利用する、プレイ記録全文を作る。"""
        if not self.backlog_entries:
            return "まだゲームの記録はありません。\n"

        started_at = (
            self.current_game_started_at.strftime("%Y-%m-%d %H:%M:%S")
            if self.current_game_started_at is not None
            else "記録なし"
        )
        header = (
            "綴り文庫室 プレイ記録\n"
            f"開始日時: {started_at}\n"
            f"ジャンル: {self.current_game_genre or '記録なし'}\n"
            f"モデル: {self.current_game_model or '記録なし'}\n"
            "\n"
        )
        return header + "".join(self.backlog_entries)

    def export_backlog_text(self) -> None:
        """ゲームクリア後、バックログ全文をUTF-8のテキストとして保存する。"""
        if not self.game_clear_complete:
            messagebox.showinfo(
                "テキスト保存",
                "テキストはゲームクリア後に保存できます。",
            )
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = filedialog.asksaveasfilename(
            parent=self.root,
            title="プレイ記録を保存",
            defaultextension=".txt",
            initialfile=f"綴り文庫室_プレイ記録_{timestamp}.txt",
            filetypes=[("テキストファイル", "*.txt"), ("すべてのファイル", "*.*")],
        )
        if not output_path:
            return

        try:
            Path(output_path).write_text(
                self._build_backlog_text(),
                encoding="utf-8",
            )
        except OSError as exc:
            messagebox.showerror(
                "テキスト保存エラー",
                f"プレイ記録を保存できませんでした。\n{exc}",
            )
            return

        self.backlog_exported = True
        messagebox.showinfo("テキスト保存", "プレイ記録を保存しました。")

    def export_voice_cache(self) -> None:
        """ゲームクリア後、今回生成したWAVを任意名のフォルダへコピーする。"""
        if not self.game_clear_complete:
            messagebox.showinfo(
                "音声保存",
                "音声はゲームクリア後に保存できます。",
            )
            return

        wav_paths = sorted(
            VOICE_CACHE_DIR.glob("*.wav"),
            key=self._voice_cache_sort_key,
        )
        if not wav_paths:
            messagebox.showinfo(
                "音声保存",
                "保存できる音声キャッシュがありません。",
            )
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_name = simpledialog.askstring(
            "音声保存",
            "保存するフォルダ名を入力してください。",
            initialvalue=f"綴り文庫室_音声_{timestamp}",
            parent=self.root,
        )
        if folder_name is None:
            return
        folder_name = folder_name.strip()
        if not self._is_valid_folder_name(folder_name):
            messagebox.showerror(
                "フォルダ名エラー",
                "そのフォルダ名は使用できません。\n"
                "記号 < > : \" / \\ | ? * や、Windowsの予約名は避けてください。",
            )
            return

        parent_directory = filedialog.askdirectory(
            parent=self.root,
            title="音声フォルダの保存先を選択",
        )
        if not parent_directory:
            return

        output_directory = Path(parent_directory) / folder_name
        if output_directory.exists():
            messagebox.showerror(
                "音声保存エラー",
                "同じ名前のフォルダがすでにあります。別の名前を指定してください。",
            )
            return

        try:
            output_directory.mkdir()
            # 001、002…を付け、エクスプローラーでも再生順に並ぶようにする。
            for index, source_path in enumerate(wav_paths, start=1):
                destination = output_directory / f"{index:03d}_{source_path.name}"
                shutil.copy2(source_path, destination)
        except OSError as exc:
            messagebox.showerror(
                "音声保存エラー",
                f"音声ファイルを保存できませんでした。\n{exc}",
            )
            return

        self.voice_cache_exported = True
        messagebox.showinfo(
            "音声保存",
            f"{len(wav_paths)}個の音声ファイルを保存しました。",
        )

    @staticmethod
    def _is_valid_folder_name(folder_name: str) -> bool:
        """Windowsでも安全に作れる、空でないフォルダ名かを判定する。"""
        if (
            not folder_name
            or folder_name in {".", ".."}
            or folder_name.endswith((" ", "."))
            or any(character in '<>:"/\\|?*' for character in folder_name)
        ):
            return False

        reserved_names = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{number}" for number in range(1, 10)),
            *(f"LPT{number}" for number in range(1, 10)),
        }
        base_name = folder_name.split(".", maxsplit=1)[0].upper()
        return base_name not in reserved_names

    @staticmethod
    def _voice_cache_sort_key(path: Path) -> tuple[int, int, int, str]:
        """場面→エンディングの順になるよう、音声キャッシュの並び順を作る。"""
        name = path.name
        if name.startswith("scene_"):
            parts = name.split("_")
            try:
                scene_number = int(parts[1])
            except (IndexError, ValueError):
                scene_number = 9999

            if "transition" in parts:
                phase = 0
            elif "bad" in parts:
                phase = 2
            else:
                phase = 1
            return (0, scene_number, phase, name)

        ending_order = {
            "good_ending_main": 0,
            "good_ending_epilogue": 1,
            "good_ending_clear": 2,
            "good_ending_comment": 3,
            "good_ending_thanks": 4,
        }
        for prefix, order in ending_order.items():
            if name.startswith(prefix):
                return (1, order, 0, name)
        return (2, 0, 0, name)

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
        # 通常はすでに鳴り終わっているが、長い仮素材でも前のBad End音を残さない。
        self.voice_pipeline.stop_sound_effect()
        retry_message = (
            "\n\n=== 直前の選択肢へ戻ります ===\n"
            "同じ場面を、もう一度選び直してください。\n"
        )
        self._write(retry_message)
        self._append_backlog(retry_message)
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
        presentation_id = self.presentation_id

        def show_error_and_continue() -> None:
            if presentation_id != self.presentation_id:
                return
            self._write(f"\n--- VOICEVOXエラー: {message} ---\n")
            # 後続チャンクの生成失敗でも、章間処理を待ち続けないよう完了扱いにする。
            self._mark_narrative_voice_done(presentation_id)

        self.root.after(0, show_error_and_continue)

    def _on_sfx_warning(self, message: str) -> None:
        """
        効果音の素材不足・再生失敗を、ゲームを止めず診断ログへ残す。

        同じ素材の重複抑制はVoicePipeline側で行われるため、ここでは表示欄へ
        警告を何度も差し込まず、必要なときにlogs/game.logで確認できる形にする。
        """
        self._log_internal(f"効果音警告: {message}")

    def _on_bgm_warning(self, message: str) -> None:
        """
        BGM素材の不足・読込失敗を、ゲームを止めず診断ログへ残す。

        開発途中でassets/bgmが空でも本文・VOICEVOX・効果音は通常どおり使える。
        同じ警告の重複抑制はBGMManager側が担当する。
        """
        self._log_internal(f"BGM警告: {message}")

    def _on_bgm_track_reference(self, bgm_tag: str, track_path: Path) -> None:
        """BGMタグから解決された実ファイル名を診断ログへ残す。"""
        try:
            relative_path = track_path.relative_to(BGM_DIR).as_posix()
        except ValueError:
            relative_path = track_path.name
        self._log_internal(
            f"BGM参照: tag={bgm_tag}, file=assets/bgm/{relative_path}"
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

    def _clear_all_voice_cache(self) -> None:
        """新しいゲーム開始時とアプリ終了時に、作業用WAVだけを削除する。"""
        self._make_voice_client_for_cache().clear_all_cache()

    def _set_busy(self, busy: bool) -> None:
        """
        重い処理中かどうかを記録し、関連する操作部品を一括更新する。

        選択肢ボタンは「busyでない」「現在場面の表示完了」など、
        必要な条件がそろった場合だけ有効になる。
        """
        self.busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        self.start_button.config(state=state)
        self.refresh_button.config(state=state)
        self.cancel_generation_button.config(
            state=tk.NORMAL if self.generation_active else tk.DISABLED
        )

        if busy:
            self._disable_choice()
            self.next_scene_button.config(state=tk.DISABLED)
        elif self.choice_buttons_ready:
            self._enable_choice()
        elif self.pending_continue_action is not None and not self.typing_active:
            self.next_scene_button.config(
                state=tk.NORMAL,
                background=CHOICE_BUTTON_BG,
            )

    def _enable_choice(self) -> None:
        """条件を再確認したうえで、A・Bの選択肢ボタンを有効にする。"""
        if (
            self.busy
            or self.typing_active
            or not self.choice_buttons_ready
            or self.engine is None
            or self.engine.finished
        ):
            return
        self.choice_a_button.config(
            state=tk.NORMAL,
            background=CHOICE_BUTTON_BG,
        )
        self.choice_b_button.config(
            state=tk.NORMAL,
            background=CHOICE_BUTTON_BG,
        )

    def _disable_choice(self) -> None:
        """A・Bボタンを同時に無効化し、二重選択を防ぐ。"""
        self.choice_a_button.config(
            state=tk.DISABLED,
            background=CHOICE_BUTTON_BG,
        )
        self.choice_b_button.config(
            state=tk.DISABLED,
            background=CHOICE_BUTTON_BG,
        )

    def _on_enter(self, _event: tk.Event) -> str | None:
        """
        Enterキーを「全文表示＋音声停止」または「残っている音声停止」に使う。

        ``"break"`` を返すとTkinterの既定処理へのイベント伝播を止められ、
        同じEnterが二重に処理されるのを防げる。
        """
        # 自由入力欄は複数行入力を前提とするため、ここだけは通常の改行として
        # Tkinterへ渡す。ゲーム中の全文表示・音声停止とは混同しない。
        if self.root.focus_get() is self.free_story_input:
            return None

        if self.typing_active:
            # stop()は再生中だけでなく、生成・再生待ちのチャンクも無効化する。
            self.stop_voice()
            self._finish_typing()
        else:
            # 文字がすでに全文表示され、読み上げだけが続いている場合にも対応する。
            # 音声が流れていないときに呼んでも、stop()は安全に何もしない。
            self.stop_voice()
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
        「物語を生成しています」の末尾の点を0～3個で循環表示する。

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

    def _clear_text_area(self) -> None:
        """予約状態は変えず、現在の場面カードに表示された文字だけを消す。"""
        self.text_area.config(state=tk.NORMAL)
        self.text_area.delete("1.0", tk.END)
        self.text_area.yview_moveto(0.0)
        self.text_area.config(state=tk.DISABLED)

    def _clear(self) -> None:
        """保留中の表示処理を止めてから、本文欄を空にする。"""
        self._cancel_typing()
        self._stop_waiting_animation()
        self._clear_text_area()

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
        # 生成中に閉じた場合も、Ollamaとの接続と古いワーカー結果を無効化する。
        active_client = self.active_llm_client
        self.generation_id += 1
        self.generation_active = False
        self.active_llm_client = None
        self.engine = None
        if active_client is not None:
            active_client.cancel_current_request()

        self._invalidate_presentation()
        self._cancel_typing()
        self._stop_waiting_animation()
        if self.scene_resize_after_id is not None:
            self.root.after_cancel(self.scene_resize_after_id)
            self.scene_resize_after_id = None
        # mixer自体を終了するVoicePipelineより先に、BGM専用チャンネルを片付ける。
        self.bgm_manager.shutdown()
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
