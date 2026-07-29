"""
LLMへ渡すプロンプトを組み立てるためのモジュール。

このファイルではゲームの進行そのものは扱わず、
「AIへ何を、どのような形式で依頼するか」をまとめています。

ゲームの処理とプロンプトを分けておくことで、
ゲームロジックを変更せずに、文章の雰囲気や出力ルールだけを
調整しやすくなります。

プロンプトは次の2つで構成しています。

- システムプロンプト
    AIの役割や禁止事項、出力形式など、毎回共通で守ってほしい内容
- ユーザープロンプト
    現在の場面やこれまでの要約、今回生成してほしい内容

LLMは毎回同じ形式で返してくれるとは限りません。
そのため、ここではJSON形式をできるだけ分かりやすく指示し、
最終的な形式チェックは ``game_engine.py`` の ``_parse_scene()`` で行います。

このように「生成」と「検証」を分けることで、
万が一AIが想定外の文章を返しても、ゲーム全体が壊れにくくなります。
"""

from __future__ import annotations

import json
from typing import Any


# 通常場面と最終場面で共通して使う、ゲームマスターとしての基本ルール。
# 物語の一貫性だけでなく、JSON以外を返さないことも明示。
BASE_SYSTEM_PROMPT = """
あなたは、短編テキストアドベンチャーのゲームマスターです。

必ず守るルール:
- 出力はJSONのみとし、前後に説明文やMarkdownを付けない。
- プレイヤーへ提示する選択肢は必ず a と b の2つだけ。
- 片方は次の場面へ進む正解、もう片方は即座にBad Endへ進む不正解。
- 選択肢の正解・不正解には、場面の状況から納得できる理由を持たせる。
- 「これまでの物語要約」に書かれている主人公、職業、人物、場所、証拠、目的を変更しない。
- 要約にない重要設定を突然追加せず、必要な新要素は現在の場面で自然に登場させる。
- 怖すぎる残酷描写、過度な暴力、性的表現は避ける。
- 文章は日本語で、読みやすく簡潔にする。
""".strip()
# エンディングは場面生成と目的が異なるため、専用の役割を与える。
# 「プレイヤーを責めない」は、Bad End回数が多い場合にも優しい感想にするため。
ENDING_SYSTEM_PROMPT = """
あなたは、短編テキストアドベンチャーのエンディング演出担当です。
出力はJSONのみとし、説明文やMarkdownを付けないでください。
与えられた物語とプレイ判定だけを使い、存在しない事件や人物を追加しないでください。
プレイヤーを責めたり皮肉ったりせず、温かく自然な言葉で締めくくってください。
""".strip()

# 要約は次の場面へ設定を引き継ぐ、AIの「短期記憶」として使用。
# 新しい事実を作らせず、固有名詞・目的・証拠を優先してもらうように指示する。
SUMMARY_SYSTEM_PROMPT = """
あなたは、テキストアドベンチャーの物語記録係です。
出力はJSONのみとし、説明文やMarkdownを付けないでください。
事実を創作せず、与えられた内容だけを要約してください。
主人公の名前・立場、主要人物、重要な証拠、現在の目的を優先してください。
""".strip()


def build_scene_prompt(
    *,
    genre_name: str,
    genre_prompt: str,
    scene_number: int,
    total_scenes: int,
    story_summary: str,
    required_correct_choice: str,
) -> str:
    """
    最終場面ではない通常場面を1つ生成させるプロンプトを作る。

    ``required_correct_choice`` は、AIに自由決定させずアプリ側で先に決めた
    正解位置である。これにより、正解がa側ばかりに偏ることを防いでいる。
    ``story_summary`` は、それまでの物語を次の生成へ引き継ぐための情報になる。
    """

    # schemaはPython側の検証定義ではなく、LLMへ見本として提示するJSON構造。
    # 実際の必須項目・値の検証はGameEngine._parse_scene()が担当する。
    schema: dict[str, Any] = {
        "title": "場面タイトル",
        "scene_text": "状況説明",
        "choice_a": "aの選択肢本文",
        "choice_b": "bの選択肢本文",
        "correct_choice": "指定された a または b",
        "correct_result": "正解を選んだ直後の短い結果",
        "bad_end_title": "不正解時のBad Endタイトル",
        "bad_end_text": "不正解の選択内容と一致する短い結末",
    }

    # ensure_ascii=Falseにより、日本語を「\uXXXX」へ変換せず読みやすく提示する。
    # indent=2は構造を明確にし、モデルが同じ形式を模倣しやすくするため。
    return f"""
ジャンル名:
{genre_name}

ジャンル設定:
{genre_prompt}

現在の場面:
{scene_number} / {total_scenes}

これまでの物語要約:
{story_summary or "まだ物語は始まっていません。第1場面で主人公の名前と立場を明確にしてください。"}

今回の役割:
- 場面{scene_number}を作る。
- 要約にある設定と矛盾させない。
- aとbの2択を作る。
- correct_choiceは必ず {required_correct_choice} にする。
- {required_correct_choice}側が、状況から納得できる正解になるように選択肢を作る。
- もう片方を選んだ場合のBad Endも同時に作る。
- Bad Endは、実際の不正解側の行動を選んだ結果として書く。
- 場面{scene_number}は最終場面ではないため、正解側は次へ続けられる内容にする。

次のJSON形式で返す:
{json.dumps(schema, ensure_ascii=False, indent=2)}
""".strip()


def build_final_scene_prompt(
    *,
    genre_name: str,
    genre_prompt: str,
    scene_number: int,
    total_scenes: int,
    story_summary: str,
    required_correct_choice: str,
) -> str:
    """
    Good EndとBad Endを含む最終場面用プロンプトを作る。

    通常場面との主な違いは、``correct_result`` で次へつなぐ代わりに、
    正解側の ``good_end_*`` を必須とする点である。突然の新設定による解決を
    防ぐため、これまでの要約にある材料で決着させるよう明示している。
    """

    # 最終場面専用の出力見本。通常場面とは必要なキーが異なる。
    schema: dict[str, Any] = {
        "title": "最終場面タイトル",
        "scene_text": "最終判断を迫る状況説明",
        "choice_a": "aの選択肢本文",
        "choice_b": "bの選択肢本文",
        "correct_choice": "指定された a または b",
        "good_end_title": "正解時のGood Endingタイトル",
        "good_end_text": "正解側の選択内容と一致する結末",
        "bad_end_title": "不正解時のBad Endタイトル",
        "bad_end_text": "不正解側の選択内容と一致する結末",
    }

    return f"""
ジャンル名:
{genre_name}

ジャンル設定:
{genre_prompt}

現在の場面:
{scene_number} / {total_scenes}

これまでの物語要約:
{story_summary}

今回の役割:
- 最終場面を作る。
- 要約にある設定・人物・証拠・目的を使って物語を決着させる。
- 新しい黒幕、超能力、重要人物などを突然追加しない。
- aとbの2択を作る。
- correct_choiceは必ず {required_correct_choice} にする。
- {required_correct_choice}側が、状況から納得できる正解になるように選択肢を作る。
- 正解側にはGood Endingを用意する。
- 不正解側にはBad Endを用意する。
- それぞれの結末を、実際に選んだ行動と一致させる。

次のJSON形式で返す:
{json.dumps(schema, ensure_ascii=False, indent=2)}
""".strip()


def build_summary_prompt(
    *,
    previous_summary: str,
    scene_number: int,
    title: str,
    scene_text: str,
    selected_choice: str,
    selected_choice_text: str,
    correct_result: str,
    max_characters: int = 100,
) -> str:
    """
    正解後、次の場面へ渡す短い物語要約の生成プロンプトを作る。

    全場面の原文を毎回LLMへ渡すと入力が長くなり、設定の見落としも起きやすい。
    そこで、前回の要約へ今回の出来事を統合する「ローリング要約」を採用する。
    ``max_characters`` はプロンプト上の指示であり、最終的な文字数保証は
    GameEngine側でも行う。
    """

    # 返答を単純な1キーのオブジェクトに限定し、解析を安定させる。
    schema = {"summary": f"ここまでの内容を{max_characters}文字以内で要約"}

    return f"""
前回までの要約:
{previous_summary or "なし"}

今回完了した場面:
場面{scene_number}「{title}」
{scene_text}

プレイヤーが選んだ正解:
{selected_choice}. {selected_choice_text}

正解後に起きたこと:
{correct_result}

指示:
- ここまでの内容を日本語で{max_characters}文字以内に要約する。
- 前回までの要約を今回の事実で更新する。
- 主人公の名前と立場を維持する。
- 主要人物、証拠、現在の目的を優先する。
- 箇条書きではなく、短い文章にする。
- 入力にない設定を追加しない。

次のJSON形式で返す:
{json.dumps(schema, ensure_ascii=False, indent=2)}
""".strip()


def build_ending_package_prompt(
    *,
    genre_name: str,
    story_summary: str,
    final_title: str,
    final_scene_text: str,
    selected_choice: str,
    selected_choice_text: str,
    good_end_title: str,
    good_end_text: str,
    play_judgement: str,
    bad_end_count: int,
    retry_count: int,
    choice_count: int,
) -> str:
    """
    クリア後のエピローグ・おめでとうメッセージ・AI感想を一度に生成するプロンプトを作る。

    攻略の評価はAIに推測させず、アプリが実数から決定した
    ``play_judgement`` を渡す。これにより、同じプレイ記録に対する評価が
    モデルの気分で変わることを防ぎつつ、文章表現だけをAIに任せられる。
    """

    # 3項目を一度の通信で取得し、追加の待ち時間を抑える。
    schema = {
        "epilogue": "物語のその後を描く、180〜300文字程度の短いエピローグ",
        "clear_message": "ゲームクリアを祝う、1〜2文の明るいフレーズ",
        "ai_comment": "プレイ判定と物語を踏まえた、2〜4文の温かい感想",
    }

    return f"""
ジャンル:
{genre_name}

これまでの物語要約:
{story_summary or "要約なし"}

最終場面:
「{final_title}」
{final_scene_text}

プレイヤーが選んだ正解:
{selected_choice}. {selected_choice_text}

Good End:
「{good_end_title}」
{good_end_text}

アプリが判定した今回のプレイ:
{play_judgement}

プレイ記録:
- バッドエンド到達回数: {bad_end_count}
- 直前の選択肢へ戻った回数: {retry_count}
- 総選択回数: {choice_count}

作成ルール:
- epilogueはGood Endの後日談として書く。
- 主要人物のその後や、事件後の穏やかな変化を描く。
- clear_messageは短く、ゲームをクリアした達成感が出る言葉にする。
- ai_commentでは、攻略評価は必ず「アプリが判定した今回のプレイ」に従う。
- ai_commentでは、物語要約や結末に触れ、今回ならではの感想にする。
- バッドエンド回数をAI自身で再判定しない。
- 入力にない新しい黒幕、重要人物、真相を追加しない。
- 3項目の内容を重複させすぎない。

次のJSON形式で返す:
{json.dumps(schema, ensure_ascii=False, indent=2)}
""".strip()
