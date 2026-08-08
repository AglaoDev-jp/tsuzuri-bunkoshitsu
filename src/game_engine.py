"""
ゲームルールと進行状態を管理するモジュール。

この層はTkinterの画面表示やVOICEVOX再生を知らず、純粋に次のことだけを扱う。

- ゲーム開始時の初期化
- a / bの正誤判定と場面遷移
- LLMを使った場面・要約・エンディング生成
- AI出力の検証と、生成失敗時のフォールバック
- Bad End回数など、プレイ記録の集計

画面層とは ``Scene`` と ``{"status": ...}`` 形式の辞書でやり取りする。
この分離により、将来GUIを変更してもゲームルールを再利用しやすい。
"""

from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any, Callable

from game_prompts import (
    BACKGROUND_TAG_VALUES,
    SCENE_BGM_TAG_VALUES,
    BASE_SYSTEM_PROMPT,
    SUMMARY_SYSTEM_PROMPT,
    ENDING_SYSTEM_PROMPT,
    build_final_scene_prompt,
    build_scene_prompt,
    build_summary_prompt,
    build_ending_package_prompt,
)
from llm_client import LLMClientError, LLMGenerationCancelled, OllamaClient


class GameDataError(RuntimeError):
    """AIが返したゲームデータの不足・矛盾・形式不正を表す例外。"""


@dataclass
class Scene:
    """
    画面へ表示する1場面分のデータ。

    通常場面では ``correct_result``、最終場面では ``good_end_*`` を使う。
    場面の種類によって使わない項目は、空文字を既定値として保持する。
    """

    # すべての場面に共通する情報。
    number: int
    title: str
    scene_text: str
    choice_a: str
    choice_b: str
    correct_choice: str
    bad_end_title: str
    bad_end_text: str

    # 情景窓へ表示する画像を選ぶ内部分類。画面本文やバックログには表示しない。
    # 旧形式のデータから作る場合も安全に扱えるよう、既定値はnoneにする。
    background_tag: str = "none"

    # 本編Sceneで再生するBGMの雰囲気分類。LLMが旧形式を返した場合でも
    # 無音や生成失敗にせず、文章を邪魔しにくいcalmへ安全に戻す。
    bgm_tag: str = "calm"

    # 通常場面の正解後に表示する「次へつながる結果」。
    correct_result: str = ""

    # 最終場面の正解時だけ使うGood End情報。
    good_end_title: str = ""
    good_end_text: str = ""

    # 将来の拡張や旧データとの互換用。現時点の進行処理では参照していない。
    final_summary: str = ""


class GameEngine:
    """
    1回のゲームプレイを表す状態付きエンジン。

    ``start()`` で最初のSceneを作り、その後は ``choose()`` の戻り値にある
    statusを見て画面側が表示を切り替える。状態の主な流れは次のとおり。

    ``未開始 -> 場面表示 -> 正解なら次場面 / 不正解ならBad End
    -> 再挑戦または最終場面のGood End``

    LLMは文章作成を担当するが、正解位置、入力値の検証、プレイ評価などの
    重要なルールはPython側で決定する。
    """

    def __init__(
        self,
        *,
        llm_client: OllamaClient,
        genre_name: str,
        genre_prompt: str,
        total_scenes: int = 5,
        max_retries: int = 3,
        summary_max_characters: int = 100,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        """ゲーム設定と依存オブジェクトを受け取り、未開始状態を作る。"""
        # 外部サービスとゲーム設定。logger未指定時は何もしない関数を使い、
        # 各所で「loggerがNoneか」を確認せず呼び出せるようにする。
        self.llm_client = llm_client
        self.genre_name = genre_name
        self.genre_prompt = genre_prompt
        self.total_scenes = total_scenes
        self.max_retries = max_retries
        # 設定ミスで0以下になっても空要約を量産しないよう、最低1文字を保証する。
        self.summary_max_characters = max(1, int(summary_max_characters))
        self.logger = logger or (lambda _message: None)

        # ゲーム中に更新される進行状態。
        # scene_number=0は、まだstart()されていないって意味。
        self.scene_number = 0
        self.story_summary = ""
        self.current_scene: Scene | None = None
        self.finished = False
        self.answer_pattern: list[str] = []

        # 今回のゲームプレイをPython側で客観的に記録する。
        # 評価自体をAI任せにしないことで、同じ記録なら同じ判定になる。
        self.bad_end_count = 0
        self.retry_count = 0
        self.choice_count = 0

    def start(self) -> Scene:
        """
        すべての進行状態を初期化し、第1場面を生成して返す。

        「最初から」で同じGameEngineを再利用する場合にも、前回の要約や
        プレイ記録が残らないよう、ゲーム単位の状態をここでまとめてリセットする。
        """
        self.scene_number = 1
        self.story_summary = ""
        self.finished = False
        # AIへ場面を書かせる前に、全場面の正解位置をアプリ側で確定する。
        self.answer_pattern = self._create_answer_pattern()
        self.bad_end_count = 0
        self.retry_count = 0
        self.choice_count = 0
        self.logger(f"今回の正解パターン: {self.answer_pattern}")
        self.current_scene = self._generate_scene()
        return self.current_scene

    def choose(self, choice: str) -> dict[str, Any]:
        """
        プレイヤーの選択を判定し、画面層へ次の処理をstatus付きで返す。

        主なstatus:
            ``invalid``: a / b以外
            ``bad_end``: 不正解
            ``next_scene``: 正解し、次場面を生成済み
            ``good_end``: 最終場面を正解
            ``finished``: 終了後に再度呼ばれた

        戻り値を辞書にして、GUI固有の処理をこのクラスへ持ち込まずに
        必要なデータだけを渡す。
        """
        if self.finished:
            return {"status": "finished"}

        if self.current_scene is None:
            raise RuntimeError("ゲームが開始されていません。")

        # 大文字や前後の空白を許容し、内部ではa / bへ正規化する。
        choice = choice.lower().strip()
        if choice not in {"a", "b"}:
            return {"status": "invalid"}

        self.choice_count += 1

        # 不正解は即座にBad End。ただしcurrent_sceneは保持するため、
        # retry_current_scene()で同じ問題へ戻れる。
        if choice != self.current_scene.correct_choice:
            self.bad_end_count += 1
            self.finished = True
            return {
                "status": "bad_end",
                "title": self.current_scene.bad_end_title,
                "text": self.current_scene.bad_end_text,
            }

        # 最終場面の正解時だけ、追加のクリア演出を生成する。
        if self.scene_number >= self.total_scenes:
            self.finished = True
            ending_package = self._generate_ending_package(
                scene=self.current_scene,
                selected_choice=choice,
            )
            return {
                "status": "good_end",
                "title": self.current_scene.good_end_title,
                "text": self.current_scene.good_end_text,
                "epilogue": ending_package["epilogue"],
                "clear_message": ending_package["clear_message"],
                "ai_comment": ending_package["ai_comment"],
                "play_judgement": self._judge_play_style(),
                "bad_end_count": self.bad_end_count,
                "retry_count": self.retry_count,
                "choice_count": self.choice_count,
            }

        # 通常場面の正解では、今回の結果を要約へ統合してから次場面を作る。
        # 「要約更新 -> 場面番号更新 -> 次場面生成」の順序が重要。
        result_text = self.current_scene.correct_result
        self.story_summary = self._update_story_summary(
            scene=self.current_scene,
            selected_choice=choice,
        )
        self.scene_number += 1
        self.current_scene = self._generate_scene()

        return {
            "status": "next_scene",
            "result_text": result_text,
            "scene": self.current_scene,
        }

    def _update_story_summary(
        self,
        *,
        scene: Scene,
        selected_choice: str,
    ) -> str:
        """
        正解後、別のLLM呼び出しで設定文字数以内のローリング要約を作ってもらう。

        この要約は次場面のプロンプトへ渡す「物語の記憶」として使う。場面全文を
        蓄積する方式より入力を小さく保てる一方、重要情報を落とし得るため、
        専用プロンプトで人物・証拠・目的を優先させている。
        """
        selected_choice_text = (
            scene.choice_a if selected_choice == "a" else scene.choice_b
        )
        prompt = build_summary_prompt(
            previous_summary=self.story_summary,
            scene_number=scene.number,
            title=scene.title,
            scene_text=scene.scene_text,
            selected_choice=selected_choice,
            selected_choice_text=selected_choice_text,
            correct_result=scene.correct_result,
            max_characters=self.summary_max_characters,
        )

        try:
            data = self.llm_client.generate_json(
                system_prompt=SUMMARY_SYSTEM_PROMPT,
                user_prompt=prompt,
                think=False,
                # 要約は創造性より事実の安定性を優先するため低めにする。
                temperature=0.2,
            )
            summary = str(data.get("summary", "")).strip()
            if not summary:
                raise GameDataError("要約が空です。")

            # プロンプトの文字数指示だけでは保証にならないため、Python側でも制限する。
            # 改行は1行へ整え、次回プロンプトへ埋め込みやすくする。
            summary = summary.replace("\n", " ").strip()
            if len(summary) > self.summary_max_characters:
                summary = summary[: self.summary_max_characters]

            self.logger(f"場面{scene.number}終了時の要約: {summary}")
            return summary
        except LLMGenerationCancelled:
            # キャンセルは生成失敗ではないため、簡易要約へ進まず画面層へ伝える。
            raise
        except (LLMClientError, GameDataError) as exc:
            # 要約は補助処理なので、失敗だけでゲーム全体を止めない。
            # 前回要約と今回の確定事実から、LLMを使わない簡易要約を作る。
            self.logger(f"要約生成に失敗したため簡易要約を使用します: {exc}")
            fallback = (
                f"{self.story_summary} "
                f"場面{scene.number}で{selected_choice_text}を選び、"
                f"{scene.correct_result}"
            ).strip()
            # 末尾には最新の出来事があるため、超過時は後ろ側を設定文字数だけ残す。
            return fallback[-self.summary_max_characters :]

    def retry_current_scene(self) -> Scene:
        """
        Bad End後に、同じ場面・同じ選択肢から再挑戦する。

        場面を再生成しないため、文章や正解は変わらない。
        """
        if self.current_scene is None:
            raise RuntimeError("再挑戦できる場面がありません。")

        self.finished = False
        self.retry_count += 1
        return self.current_scene

    def _judge_play_style(self) -> str:
        """
        Bad End回数から、再現可能なルールで攻略傾向を決める。

        AIへ回数だけを渡して評価まで任せると、同じ記録でも判定が揺れる。
        そこで評価はPython、温かい文章表現はAIという役割分担にしている。
        """
        if self.bad_end_count == 0:
            return "一度もバッドエンドにならず、非常にスムーズに攻略した"
        if self.bad_end_count <= 2:
            return "少し苦戦したが、試行錯誤しながら攻略した"
        return "何度も苦戦したが、諦めずに最後まで攻略した"

    def _generate_ending_package(
        self,
        *,
        scene: Scene,
        selected_choice: str,
    ) -> dict[str, str]:
        """
        クリア後のエピローグ・お祝いメッセージ・AIコメントをまとめて生成。
        
        これらはゲームを盛り上げるための「追加演出」なので、
        LLMとの通信やJSONの解析に失敗した場合でも
        ゲームクリア自体は正常に完了できるように
        生成に失敗したときは固定メッセージへ切り替え。
        こんな感じで一部の機能が使えなくても全体は動き続けるよう設計する考え方を
        「グレースフル デグラデーション（Graceful Degradation）」
        と呼ぶそうな。

        """
        selected_choice_text = (
            scene.choice_a if selected_choice == "a" else scene.choice_b
        )
        judgement = self._judge_play_style()
        prompt = build_ending_package_prompt(
            genre_name=self.genre_name,
            story_summary=self.story_summary,
            final_title=scene.title,
            final_scene_text=scene.scene_text,
            selected_choice=selected_choice,
            selected_choice_text=selected_choice_text,
            good_end_title=scene.good_end_title,
            good_end_text=scene.good_end_text,
            play_judgement=judgement,
            bad_end_count=self.bad_end_count,
            retry_count=self.retry_count,
            choice_count=self.choice_count,
        )

        try:
            data = self.llm_client.generate_json(
                system_prompt=ENDING_SYSTEM_PROMPT,
                user_prompt=prompt,
                think=False,
                # 要約より少し高くし、事実を守りつつ表現には幅を持たせる。
                temperature=0.6,
            )
            result = {
                "epilogue": str(data.get("epilogue", "")).strip(),
                "clear_message": str(data.get("clear_message", "")).strip(),
                "ai_comment": str(data.get("ai_comment", "")).strip(),
            }
            # JSONオブジェクトであっても、必要な本文が空なら利用可能とはみなさない。
            for key, value in result.items():
                if not value:
                    raise GameDataError(f"エンディング生成の{key}が空です。")
            return result
        except LLMGenerationCancelled:
            # ユーザーが生成を中止した場合は固定文へ進まず、初期画面へ戻す。
            raise
        except (LLMClientError, GameDataError) as exc:
            self.logger(f"追加エンディング生成に失敗したため固定文を使用します: {exc}")
            return {
                "epilogue": (
                    "事件のあと、登場人物たちは少しずつ日常を取り戻していった。"
                    "今回の出来事は、忘れられない一つの物語として静かに心へ残った。"
                ),
                "clear_message": "ゲームクリア、おめでとうございます！ 最後まで物語を導きました。",
                "ai_comment": (
                    f"今回のプレイは、{judgement}展開でした。"
                    "選択を重ねて結末へたどり着いたこと自体が、見事な成果です。"
                ),
            }

    def _create_answer_pattern(self) -> list[str]:
        """
        5場面の正解がaまたはbへ偏りすぎないようにする。

        5場面の場合:
        - aが3回、bが2回
        または
        - aが2回、bが3回

        並び順はゲーム開始ごとにシャッフルする。
        """
        # 偶数分をaとbへ均等に配る。
        a_count = self.total_scenes // 2
        b_count = self.total_scenes // 2

        # 奇数場面の余り1つは、ゲーム開始ごとにaまたはbへランダム配分する。
        if self.total_scenes % 2:
            if random.choice(("a", "b")) == "a":
                a_count += 1
            else:
                b_count += 1

        # 個数を確定してから並びだけをシャッフルするので、偏りの上限を保てる。
        pattern = ["a"] * a_count + ["b"] * b_count
        random.shuffle(pattern)

        # 同じ答えが3回以上連続する並びは避ける。
        # 無限ループを防ぐため再試行は20回までとし、見つからなくても
        # 個数バランス自体は保たれた現在のpatternを採用する。
        for _ in range(20):
            if not any(
                pattern[i] == pattern[i + 1] == pattern[i + 2]
                for i in range(len(pattern) - 2)
            ):
                break
            random.shuffle(pattern)

        return pattern

    def _generate_scene(self) -> Scene:
        """
        現在の場面番号に対応するプロンプトを作り、検証済みSceneを返す。

        ``max_retries`` は「Bad End後の再挑戦回数」ではなく、AIの通信失敗や
        不正JSONを内部で再生成する回数である。最後の例外をログ・エラー文へ
        残すことで、全試行失敗時の原因を追いやすくしている。
        """
        last_error: Exception | None = None

        # リストは0始まり、場面番号は1始まりなので1を引いて対応させる。
        required_correct_choice = self.answer_pattern[self.scene_number - 1]

        for attempt in range(1, self.max_retries + 1):
            try:
                # 最終場面だけ必要なJSON項目が違うため、専用プロンプトを使う。
                if self.scene_number == self.total_scenes:
                    prompt = build_final_scene_prompt(
                        genre_name=self.genre_name,
                        genre_prompt=self.genre_prompt,
                        scene_number=self.scene_number,
                        total_scenes=self.total_scenes,
                        story_summary=self.story_summary,
                        required_correct_choice=required_correct_choice,
                    )
                else:
                    prompt = build_scene_prompt(
                        genre_name=self.genre_name,
                        genre_prompt=self.genre_prompt,
                        scene_number=self.scene_number,
                        total_scenes=self.total_scenes,
                        story_summary=self.story_summary,
                        required_correct_choice=required_correct_choice,
                    )

                data = self.llm_client.generate_json(
                    system_prompt=BASE_SYSTEM_PROMPT,
                    user_prompt=prompt,
                    think=False,
                )
                # LLMの返答をそのまま信用せず、境界で検証してSceneへ変換する。
                return self._parse_scene(data, required_correct_choice)
            except LLMGenerationCancelled:
                # 通信・JSON失敗用の再試行とは区別し、キャンセルは直ちに終了する。
                raise
            except (LLMClientError, GameDataError) as exc:
                last_error = exc
                self.logger(
                    f"場面生成に失敗しました（{attempt}/{self.max_retries}）: {exc}"
                )

        raise GameDataError(
            f"場面生成に{self.max_retries}回失敗しました: {last_error}"
        )

    def _parse_scene(
        self,
        data: dict[str, Any],
        required_correct_choice: str,
    ) -> Scene:
        """
        AIの辞書を検証し、安全に扱える ``Scene`` へ変換する。

        外部入力は型ヒントどおりとは限らないため、必須値を ``str`` へ
        変換して空文字を検査する。通常場面と最終場面で異なる必須項目も
        ここで確認し、不正データをGUIへ流さない。
        """
        # どの種類の場面にも必要な共通キー。
        common_fields = [
            "title",
            "scene_text",
            "choice_a",
            "choice_b",
            "correct_choice",
            "bad_end_title",
            "bad_end_text",
        ]
        for field in common_fields:
            if not str(data.get(field, "")).strip():
                raise GameDataError(f"必須項目がありません: {field}")

        # 大文字のA/Bは許容するが、それ以外の値は拒否する。
        correct_choice = str(data["correct_choice"]).lower().strip()
        if correct_choice not in {"a", "b"}:
            raise GameDataError("correct_choiceはaまたはbである必要があります。")
        # 正解位置はアプリ側のanswer_patternを正とし、AIによる変更を許さない。
        if correct_choice != required_correct_choice:
            raise GameDataError(
                f"この場面の正解は{required_correct_choice}指定ですが、"
                f"AIは{correct_choice}を返しました。"
            )

        # 2択が同文ではゲームにならないため、内容の最低限の整合性も確認する。
        if str(data["choice_a"]).strip() == str(data["choice_b"]).strip():
            raise GameDataError("aとbの選択肢が同じです。")

        # background_tagは、画像機能を追加する前から旧形式の応答を受け入れられるよう、
        # 必須項目にはしない。欠落・空文字・一覧外の値はすべてnoneへ安全に戻す。
        background_tag = str(data.get("background_tag", "")).lower().strip()
        if background_tag not in BACKGROUND_TAG_VALUES:
            background_tag = "none"

        # title / ending / game_clearは画面進行側だけが使う予約タグである。
        # Sceneでは7種類の本編タグだけを許可し、欠落・空文字・一覧外の値は
        # 小さなローカルLLMでもゲームを継続できるようcalmへフォールバックする。
        bgm_tag = str(data.get("bgm_tag", "")).lower().strip()
        if bgm_tag not in SCENE_BGM_TAG_VALUES:
            bgm_tag = "calm"

        # 場面種別ごとの追加必須項目を検証する。
        if self.scene_number == self.total_scenes:
            for field in ["good_end_title", "good_end_text"]:
                if not str(data.get(field, "")).strip():
                    raise GameDataError(f"最終場面の必須項目がありません: {field}")
        else:
            if not str(data.get("correct_result", "")).strip():
                raise GameDataError("通常場面の必須項目がありません: correct_result")

        # 検証後に初めて、上位層が扱うSceneオブジェクトへ詰め替える。
        return Scene(
            number=self.scene_number,
            title=str(data["title"]).strip(),
            scene_text=str(data["scene_text"]).strip(),
            choice_a=str(data["choice_a"]).strip(),
            choice_b=str(data["choice_b"]).strip(),
            correct_choice=correct_choice,
            bad_end_title=str(data["bad_end_title"]).strip(),
            bad_end_text=str(data["bad_end_text"]).strip(),
            background_tag=background_tag,
            bgm_tag=bgm_tag,
            correct_result=str(data.get("correct_result", "")).strip(),
            good_end_title=str(data.get("good_end_title", "")).strip(),
            good_end_text=str(data.get("good_end_text", "")).strip(),
            final_summary=str(data.get("final_summary", "")).strip(),
        )
