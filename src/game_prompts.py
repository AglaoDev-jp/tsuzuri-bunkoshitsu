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


# 「自由に綴る」で受け付ける文章量の上限。
# GUIの案内・入力検証・GameEngine側の防御処理で同じ値を共有することで、
# 表示上は受け付けたのに内部では拒否される、といった不一致を防ぐ。
FREE_STORY_REQUEST_MAX_CHARACTERS = 1000


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
    "calm": "安全で静かな場面・穏やかな会話・落ち着いた日常",
    "bright": "楽しい出来事・コミカルな展開・明るく軽快な行動",
    "mystery": "謎の発見・調査・推理・違和感を考える場面",
    "tension": "戦闘開始前の危機・追跡・逃走・潜入・緊迫した判断",
    "battle": "敵との戦闘中・武器や格闘による攻防・直接対決・激しいアクション",
    "sad": "悲しみ・別れ・喪失・後悔・しんみりした場面",
    "horror": "怪異そのものが中心の恐怖・不気味な存在・逃げ場のない恐怖",
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
    "- bgm_tagは場所ではなく、現在のSceneでプレイヤーが体験している中心的な展開に合うものを1つだけ選ぶ。\n"
    "- 実際に戦闘・格闘・武器による攻防・敵との直接対決が始まっている場合はbattleを優先する。\n"
    "- tensionは戦闘開始前の危機、追跡、逃走、潜入、敵とのにらみ合いなどに使い、実際の戦闘中には原則使わない。\n"
    "- mysteryは調査や推理そのものが中心の場合に使い、危機や戦闘が中心ならtensionまたはbattleを優先する。\n"
    "- horrorは怪異や恐怖そのものが中心の場合に使う。単に危険なだけならtensionと区別する。\n"
    "- 一瞬の台詞や効果音ではなく、そのSceneの中心となる出来事を基準にする。\n"
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

物語設定について:
- 「ジャンル設定」は物語全体を通して守る最上位の設定である。
- 「これまでの物語要約」は過去の出来事を引き継ぐための記録であり、ジャンル設定を上書きしてはならない。
- ジャンル設定に書かれた主人公の立場、舞台、目的、中心となる出来事、作品の方向性を途中で別のものへ変えない。
- 「これまでの物語要約」に書かれている主人公、職業、人物、場所、証拠、目的を理由なく変更しない。
- 要約にない重要設定を突然追加せず、必要な新要素は現在の場面で自然に登場させる。
- 物語を進めるためだけに、ジャンル設定にない秘密組織、黒幕、超能力、古代遺物などを安易に追加しない。

展開について:
- 毎場面を探索、調査、手がかり探し、扉を開ける、道を選ぶ展開にしない。
- ジャンルに応じて、会話、交渉、対決、仕事、恋愛、競技、移動、戦闘、救助、日常の出来事なども使う。
- 前の場面と似た行動や出来事を必要以上に繰り返さず、物語に変化を付ける。
- 探索や調査がジャンル上自然な場合は使ってよい。探索そのものを禁止するのではなく、単調な連続を避ける。
- 選択肢は「調べる／調べない」「右へ行く／左へ行く」のような単調な形ばかりにせず、その場面ならではの判断にする。

表現について:
- 怖すぎる残酷描写、過度な暴力、性的表現は避ける。
- 文章は日本語で、読みやすく簡潔にする。
""".strip()
# エンディングは場面生成と目的が異なるため、専用の役割を与える。
# 「プレイヤーを責めない」は、Bad End回数が多い場合にも優しい感想にするため。
ENDING_SYSTEM_PROMPT = """
あなたは、短編テキストアドベンチャーのエンディング演出担当です。
出力はJSONのみとし、説明文やMarkdownを付けないでください。
与えられた物語とプレイ判定だけを使い、存在しない事件や人物を追加しないでください。

プレイヤーを責めたり、不快な皮肉を言ったりしないでください。
ただし、必要以上に褒める必要もありません。
AIコメントではプレイヤーの人格・才能・知性・勇気などを評価せず、
実際の選択傾向、Bad End、やり直し、物語の展開について、
親しみのあるゲームマスターが短く振り返る程度の温度感にしてください。
""".strip()

# 要約は次の場面へ設定を引き継ぐ、AIの「短期記憶」として使用。
# 新しい事実を作らせず、固有名詞・目的・証拠を優先してもらうように指示する。
SUMMARY_SYSTEM_PROMPT = """
あなたは、テキストアドベンチャーの物語記録係です。
出力はJSONのみとし、説明文やMarkdownを付けないでください。
事実を創作せず、与えられた内容だけを要約してください。
主人公の名前・立場、主要人物、重要な証拠、現在の目的、
物語の中心となっている設定・対立・未解決の問題を優先してください。
""".strip()


# 自由入力はそのまま第1場面へ流さず、既存のgenre_name / genre_promptへ
# 変換してから使う。ここではゲーム本文を書かせず、開始条件の整理だけを行う。
FREE_STORY_SETUP_SYSTEM_PROMPT = """
あなたは、短編テキストアドベンチャーの企画整理担当です。
出力はJSONのみとし、説明文やMarkdownを付けないでください。
ユーザーが希望したジャンル・舞台・主人公・雰囲気・目的・中心となる出来事を尊重し、
勝手に別ジャンルや探索中心の物語へ変更しないでください。
ユーザーが指定していない限り、ミステリー、遺跡探索、秘密組織、古代遺物などを
物語を動かすための便利な定番設定として追加しないでください。
ゲーム本文や結末はまだ書かず、ゲーム開始に必要な設定だけを整理してください。
""".strip()


def build_free_story_setup_prompt(
    *,
    user_request: str,
    total_scenes: int,
) -> str:
    """
    自由文を既存GameEngineへ渡せる開始設定に整理するプロンプトを作る。

    ``genre_name`` と ``genre_prompt`` は既存エンジンがもともと受け取る値である。
    背景・BGMは第1場面の候補として同時に選ばせるが、最終的にはPython側と
    通常Scene側の両方で既存の有効タグへ検証する。
    """

    schema: dict[str, Any] = {
        "genre_name": "物語を表す簡潔な日本語名（20文字程度まで）",
        "genre_prompt": (
            "舞台、主人公の立場、雰囲気、当面の目的をまとめたゲーム設定"
        ),
        "background_tag": "第1場面に適した既存の背景分類名から1つ",
        "bgm_tag": "第1場面に適した既存のBGM分類名から1つ",
    }

    return f"""
ユーザーが遊びたい物語:
{user_request}

整理のルール:
- ユーザーの希望を最優先し、ジャンル・舞台・主人公・雰囲気・目的・中心となる出来事を大きく変えない。
- 全{total_scenes}場面程度で完結できる、短編ゲーム向けの設定にする。
- 主人公が自分で行動し、a / bの選択を重ねられる状況にする。
- 選択肢を作りやすくするためだけに、探索・調査・謎解き中心の設定へ変換しない。
- ユーザーが探索やミステリーを希望していない場合、会話、仕事、対決、恋愛、競技、日常、戦闘など元の題材に合う展開を想定する。
- 最初から真相や結末を決め切らず、物語の途中で展開できる余地を残す。
- genre_promptには舞台、主人公の立場、作品の雰囲気、当面の目的、物語の中心となる出来事を自然な文章で含める。
- ユーザーが明示していない固有名詞や重大設定を増やしすぎない。
- 怖すぎる残酷描写、過度な暴力、性的表現を前提にしない。
{BACKGROUND_TAG_INSTRUCTION}
{BGM_TAG_INSTRUCTION}

次のJSON形式で返す:
{json.dumps(schema, ensure_ascii=False, indent=2)}
""".strip()


def _build_scene_role_instruction(
    scene_number: int,
    total_scenes: int,
) -> str:
    """
    現在のSceneが物語全体で担う役割を、LLM向けの短い指示として返す。

    役割を細かく固定しすぎると「偶然の物語」という自由さが失われるため、
    具体的な出来事ではなく「この場面でどれくらい物語を進めるか」だけを示す。
    5場面以外の設定でも使えるよう、先頭・中盤・決着直前・最終場面で分ける。
    """
    if scene_number <= 1:
        return (
            "- この場面は導入。主人公の立場、舞台、当面の目的を分かりやすく示し、"
            "物語が動き出す出来事を起こす。"
        )

    if scene_number >= total_scenes:
        return (
            "- この場面は最終場面。これまで積み上げた人物・出来事・目的を使い、"
            "新設定に頼らず決着させる。"
        )

    if scene_number == total_scenes - 1:
        return (
            "- この場面は決着直前。最終判断につながる危機、対立、決断、発見などを起こし、"
            "物語を大きく前へ進める。"
        )

    return (
        "- この場面は中盤。前の場面から状況を一段進め、"
        "新しい対立、会話、行動、発見、関係の変化などを起こす。"
        "単なる探索や移動だけで1場面を終えない。"
    )


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

    改善版では、ジャンル設定を要約より上位に置き、各Sceneに軽い役割を与える。
    これにより、設定が途中で薄れたり、探索だけが連続したりする傾向を抑える。
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

    # Scene番号だけで展開を固定せず、物語上の役割だけを補助的に伝える。
    scene_role = _build_scene_role_instruction(scene_number, total_scenes)

    return f"""
ジャンル名:
{genre_name}

ジャンル設定:
{genre_prompt}

重要:
- 上記の「ジャンル設定」は、この物語全体で守る最上位設定である。
- これまでの要約に書かれていないからという理由で、ジャンル設定を無視しない。

現在の場面:
{scene_number} / {total_scenes}

これまでの物語要約:
{story_summary or "まだ物語は始まっていません。第1場面で主人公の名前と立場を明確にしてください。"}

今回の役割:
{scene_role}
- 場面{scene_number}を作る。
- ジャンル設定と要約の両方に矛盾させない。
- 前の場面と同じ種類の行動を必要以上に繰り返さない。
- 探索・調査・手がかり探しは、ジャンルや現在の状況に必要な場合だけ使う。
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

    ``good_end_*`` という既存キー名は互換性のため維持する。
    ただしプロンプト上では Good End を「幸福な結末」ではなく、
    「正解側の正規クリアエンディング」と定義し、結末の幅を広げる。
    """

    schema: dict[str, Any] = {
        "title": "最終場面タイトル",
        "scene_text": "最終判断を迫る状況説明",
        "background_tag": "上記の背景分類名から1つ",
        "bgm_tag": "上記のBGM分類名から1つ",
        "choice_a": "aの選択肢本文",
        "choice_b": "bの選択肢本文",
        "correct_choice": "指定された a または b",
        "good_end_title": "正解時の正規クリアエンディングタイトル",
        "good_end_text": "正解側の選択内容と一致する正規クリアの結末",
        "bad_end_title": "不正解時のBad Endタイトル",
        "bad_end_text": "不正解側の選択内容と一致する結末",
    }

    return f"""
ジャンル名:
{genre_name}

ジャンル設定:
{genre_prompt}

重要:
- 上記の「ジャンル設定」は、この物語全体で守る最上位設定である。
- 最終場面でもジャンル設定を別ジャンルへ変えない。

現在の場面:
{scene_number} / {total_scenes}

これまでの物語要約:
{story_summary}

今回の役割:
- 最終場面を作る。
- ジャンル設定と、要約にある人物・証拠・目的・出来事を使って物語を決着させる。
- 新しい黒幕、超能力、重要人物、便利な道具などを突然追加して解決しない。
- aとbの2択を作る。
- correct_choiceは必ず {required_correct_choice} にする。
- {required_correct_choice}側が、状況から納得できる正解になるように選択肢を作る。
- 正解側には、ゲームクリアとなるGood Endを用意する。
- ここでいうGood Endは「正解側の正規クリアエンディング」という意味であり、必ずしも幸福な結末である必要はない。
- ジャンルと物語の流れに応じて、大団円、ほろ苦い結末、静かな別れ、代償を伴う勝利、謎や余韻を残す結末、コミカルな結末などを自然に選んでよい。
- ただし正解を選んだのに、単なる失敗・死亡・ゲームオーバーだけになる結末にはしない。
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

    既定の100文字はv3の既存設定との互換性を保つため変更せず、
    限られた文字数の中で「現在の目的」「未解決の問題」「中心設定」を
    優先して残すよう指示を強化する。
    """

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
- 主要人物、現在の目的、重要な証拠や情報を優先する。
- 物語の中心となっている設定、対立、未解決の問題を可能な限り残す。
- 雰囲気だけの描写や、次の展開に不要な細部は削ってよい。
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
    クリア後のエピローグ・お祝いメッセージ・AI感想を一度に生成する。

    ``clear_message`` がゲームクリアそのものを祝う役を担当し、
    ``ai_comment`` は今回のプレイを振り返る短評として役割を分ける。
    これにより「見事な判断力」「諦めない姿勢」といった
    毎回同じ過剰な称賛が出にくくなる。
    """

    schema = {
        "epilogue": "物語のその後を描く、180〜300文字程度の短いエピローグ",
        "clear_message": "ゲームクリアを祝う、1〜2文の明るいフレーズ",
        "ai_comment": "プレイ判定と物語を踏まえた、2〜4文の簡潔で率直なゲームマスター短評",
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
- Good Endがほろ苦い、静かな、あるいは余韻の残る結末なら、その雰囲気を無理に明るく変えない。
- 主要人物のその後や、事件後の変化を描く。
- clear_messageは短く、ゲームをクリアした達成感が出る言葉にする。

ai_commentのルール:
- 攻略評価は必ず「アプリが判定した今回のプレイ」に従う。
- 物語要約、結末、実際のプレイ記録に触れ、今回ならではの短評にする。
- プレイヤーの人格、才能、知性、勇気などを根拠なく評価しない。
- 「素晴らしい」「見事」「完璧」「卓越した」「さすが」など、大げさな称賛を連発しない。
- Bad Endややり直しがあった場合、それを責めず、事実として軽く触れてよい。
- 褒める場合も、具体的な選択や展開について控えめに述べる。
- 毎回「諦めない姿勢」「見事な判断力」のような定型的な褒め言葉で締めない。
- 親しみのあるゲームマスターがプレイ後に一言振り返る程度の温度感にする。

共通ルール:
- バッドエンド回数をAI自身で再判定しない。
- 入力にない新しい黒幕、重要人物、真相を追加しない。
- epilogue、clear_message、ai_commentの内容を重複させすぎない。

次のJSON形式で返す:
{json.dumps(schema, ensure_ascii=False, indent=2)}
""".strip()

