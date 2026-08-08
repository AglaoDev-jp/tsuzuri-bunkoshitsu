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


# 場面生成で使える背景分類と、その意味を1か所にまとめる。
# この辞書のキーは次の3か所で共通して使われる。
#
# - LLMへ提示する選択肢
# - game_engine.pyでAIの返答を検証するときの許可値
# - background_manager.pyが画像を検索するときの許可タグ
#
# 説明文も同じ場所に置くことで、タグだけ追加してプロンプトの説明を
# 書き忘れる、といった不一致を防ぎやすくしている。新しいタグを増やす場合は
# ここへ1行追加し、同名画像または同名フォルダを用意すればよい。
BACKGROUND_TAG_DESCRIPTIONS = {
    # 従来からある汎用分類。
    "room": "一般的な室内",
    "town": "町・市街地・商店街",
    "forest": "森・林・自然の中",
    "road": "道・旅路・屋外の移動場面",
    "castle": "城・屋敷・宮殿",
    "cave": "洞窟・地下空間・鉱山",
    "school": "学校・教室・校内",
    "waterside": "海・港・川・湖",
    "ruins": "廃墟・遺跡・荒れた建物",
    "shop": "店舗・売店・書店・雑貨店・食堂",
    "village": "小さな村・集落・農村",
    "field": "草原・平原・畑・開けた自然",
    "mountain": "山・崖・高原・険しい山道",
    "garden": "庭園・公園・中庭",
    "library": "図書館・書斎・資料室・静かな研究室",

    # 王道ファンタジー・異世界・探検で使いやすい場所。
    "tavern_inn": "宿酒場・旅人向けの宿屋",
    "throne_hall": "謁見の間・宮殿の大広間",
    "dungeon_corridor": "地下牢・石造りの地下通路",
    "ancient_temple": "古代神殿・聖堂・祭壇のある空間",
    "stone_bridge": "古い石橋・峡谷や川に架かる橋",

    # 恋愛・現代劇・日常ミステリーで使いやすい場所。
    "office": "オフィス・職場",
    "cafe": "喫茶店・カフェ",
    "station_platform": "鉄道駅・駅のホーム",
    "hotel_lobby": "ホテルのロビー・受付周辺",
    "observation_deck": "展望台・見晴らし台",

    # 刑事・法廷・ミステリーで使いやすい場所。
    "detective_office": "探偵事務所・調査事務所",
    "police_station": "警察署・交番・捜査拠点",
    "courtroom": "法廷・裁判所の法廷内",
    "evidence_room": "証拠保管室・記録保管室",
    "back_alley": "都市の裏路地・建物の間の細道",

    # 怪談・七不思議・静かなホラーで使いやすい場所。
    "japanese_inn_corridor": "和風旅館の廊下",
    "shrine_approach": "神社の参道・石段",
    "old_cemetery": "古い墓地・静かな墓所",
    "dark_tunnel": "暗いトンネル・長い地下道",
    "abandoned_house": "空き家・長く使われていない家",

    # サバイバル・逃走劇・都市の危機で使いやすい場所。
    "city_intersection": "市街地の大きな交差点",
    "emergency_shelter": "避難所・臨時の安全施設",
    "warehouse": "倉庫・荷物の保管施設",
    "rooftop": "ビルや建物の屋上",
    "highway": "高速道路・郊外の幹線道路",

    # 宇宙SFで使いやすい場所。
    "spaceship_bridge": "宇宙船の操縦室・ブリッジ",
    "spaceship_corridor": "宇宙船・宇宙ステーションの通路",
    "spaceport": "宇宙港・宇宙船の発着施設",
    "alien_plain": "未知の惑星の平原",
    "orbital_observatory": "軌道施設の展望室・観測室",

    # 無人島・探検・海賊冒険で使いやすい場所。
    "tropical_beach": "無人島・南国の海岸",
    "jungle": "密生したジャングル・熱帯林",
    "campsite": "野営地・キャンプ地",
    "sailing_ship_deck": "帆船の甲板",
    "ship_cabin": "帆船や木造船の船室",

    # 忍者・スパイ・潜入劇で使いやすい場所。
    "bamboo_grove": "竹林・竹に囲まれた道",
    "traditional_mansion": "和風屋敷・日本家屋の広間",
    "underground_base": "地下基地・秘密拠点",
    "surveillance_room": "監視室・警備管制室",
    "border_checkpoint": "検問所・国境や道路の関門",

    # 昭和レトロ・仕事・シリアスドラマで使いやすい場所。
    "retro_arcade": "昭和風のアーケード商店街",
    "train_carriage": "列車・鉄道車両の客室",
    "factory_floor": "工場・作業場",
    "commercial_kitchen": "ホテルや飲食店の業務用厨房",
    "hospital_corridor": "病院の廊下・医療施設内",

    # 西部劇で使いやすい場所。
    "frontier_street": "西部開拓時代風の町の大通り",
    "western_saloon": "西部劇風の酒場",
    "desert_canyon": "乾燥した荒野・岩の峡谷",
    "ranch": "牧場・農場の建物周辺",
    "railway_depot": "西部劇風の小さな駅舎",
}

# ``none`` は実画像を持たない特別な値なので、説明辞書とは分けて末尾へ追加する。
# 辞書は追加順を保持するため、プロンプトの並び順も上の分類順になる。
BACKGROUND_TAG_VALUES = (*BACKGROUND_TAG_DESCRIPTIONS, "none")

# 小さなローカルLLMでも選びやすいよう、タグと短い意味を機械的に連結する。
# 似た分類がある場合は専用タグを優先し、該当しなければ従来の汎用タグへ戻す。
_BACKGROUND_TAG_CHOICES = ", ".join(
    f"{tag}={description}"
    for tag, description in BACKGROUND_TAG_DESCRIPTIONS.items()
)
BACKGROUND_TAG_INSTRUCTION = (
    "- background_tagは場面全体の主な場所に合うものを次から1つだけ選ぶ。\n"
    "- 複数が当てはまる場合は、roomやtownなどの汎用タグより専用タグを優先する。\n"
    "- 人物や一時的な出来事ではなく、現在いる場所を基準に選ぶ。\n"
    f"- 選択可能なタグ: {_BACKGROUND_TAG_CHOICES}, "
    "none=どの背景にも当てはまらない。"
)


# BGMタグは場所ではなく、場面全体の感情・緊張度を表す。
# title / ending / game_clearは画面進行側が確実に指定する予約タグであり、
# LLMが生成する通常Sceneでは残り7種類だけを選ばせる。
BGM_TAG_DESCRIPTIONS = {
    "title": "タイトル画面",
    "calm": "静かで穏やかな場面・日常・会話",
    "bright": "明るい場面・楽しい展開・軽快な行動",
    "mystery": "謎・調査・違和感・考える場面",
    "tension": "危機が近い場面・追跡・緊迫した判断",
    "battle": "戦闘・対決・激しいアクション",
    "sad": "悲しみ・別れ・喪失・しんみりした場面",
    "horror": "怪異・恐怖・不気味な場面",
    "ending": "エピローグ",
    "game_clear": "GAME CLEAR以降",
}
BGM_TAG_VALUES = tuple(BGM_TAG_DESCRIPTIONS)
SCENE_BGM_TAG_VALUES = (
    "calm",
    "bright",
    "mystery",
    "tension",
    "battle",
    "sad",
    "horror",
)

_SCENE_BGM_TAG_CHOICES = ", ".join(
    f"{tag}={BGM_TAG_DESCRIPTIONS[tag]}" for tag in SCENE_BGM_TAG_VALUES
)
BGM_TAG_INSTRUCTION = (
    "- bgm_tagは場所ではなく、場面全体の雰囲気に合うものを1つだけ選ぶ。\n"
    "- 一瞬の台詞や効果音ではなく、Scene本文全体で最も長く続く感情を基準にする。\n"
    "- title、ending、game_clearはアプリ側の予約タグなのでSceneでは使わない。\n"
    f"- 選択可能なタグ: {_SCENE_BGM_TAG_CHOICES}。"
)


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
        "background_tag": "上記の背景分類名から1つ",
        "bgm_tag": "上記のBGM分類名から1つ",
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
{BACKGROUND_TAG_INSTRUCTION}
{BGM_TAG_INSTRUCTION}

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
        "background_tag": "上記の背景分類名から1つ",
        "bgm_tag": "上記のBGM分類名から1つ",
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
{BACKGROUND_TAG_INSTRUCTION}
{BGM_TAG_INSTRUCTION}

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
- 主要人物のその後や、事件後の変化を描く。
- clear_messageは短く、ゲームをクリアした達成感が出る言葉にする。
- ai_commentでは、攻略評価は必ず「アプリが判定した今回のプレイ」に従う。
- ai_commentでは、物語要約や結末に触れ、今回ならではの感想にする。
- バッドエンド回数をAI自身で再判定しない。
- 入力にない新しい黒幕、重要人物、真相を追加しない。
- 3項目の内容を重複させすぎない。

次のJSON形式で返す:
{json.dumps(schema, ensure_ascii=False, indent=2)}
""".strip()
