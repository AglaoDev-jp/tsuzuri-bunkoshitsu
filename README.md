# 綴り文庫室 v4

**「選択で綴る、偶然の物語。」**  
**Ollama + VOICEVOXで遊ぶ、ローカルAIテキストアドベンチャーゲーム**  

「綴り文庫室（つづりぶんこしつ）」は、ローカル環境で動作するLLMがプレイごとに物語を生成する、全5場面の短編テキストアドベンチャーゲームです。  

30種類の登録ジャンル、または文章で希望を指定する「自由に綴る」から物語を始められます。各場面で2つの行動から1つを選び、AIがその場で作る物語をGOOD ENDまで導きます。  

物語生成には [Ollama](https://ollama.com/) を使用します。音声読み上げには、任意で [VOICEVOX](https://voicevox.hiroshiba.jp/) を使用できます。物語生成と読み上げは、どちらもローカル環境のAPIへ接続します。  

- 詳しい準備と操作方法：[利用マニュアル](./README_PLAY.md)
- 実行ファイルの配布先：[GitHub Releases](https://github.com/AglaoDev-jp/tsuzuri-bunkoshitsu/releases)（配布版のバージョンをご確認ください）
- 内部の仕組み：[綴り文庫室の仕組み](./docs/綴り文庫室の仕組み.md)
- 検証・診断：[testsの説明](./docs/tests_guide.md)／[toolsの説明](./docs/tools_guide.md)

このリポジトリのv4ソース一式には、Windows実行ファイルは含まれていません。

> [!NOTE]
> 本READMEは、アプリのソースコードおよび設定・素材をもとに、OpenAIの対話型AI「ChatGPT」の支援を受けて作成・整備しています。最終的な公開判断は作者が行います。
> 本ソフトウェアは、同名または類似名称の既存の商標・製品・サービスとは関係ありません。

---

## v2・v3の主な変更点

### 「自由に綴る」モード (v3)

- 遊びたい物語を文章で自由に指定可能
- 入力上限は1000文字
- 入力内容をAIが短編ゲーム向けの開始設定へ整理
- 整理や第1場面の生成に失敗した場合は、入力内容を保持したまま再試行可能
- 通常ウィンドウでも入力しやすい複数行入力画面

### 物語生成プロンプトの改善 (v3)

- ユーザーが指定したジャンル、舞台、主人公、目的を物語全体で優先
- 各場面に導入・中盤・決着直前・最終場面の役割を付与
- 探索や調査だけが連続しにくい生成方針
- 前の場面と似た出来事や行動の繰り返しを抑制
- GOOD ENDを必ずしも大団円に限定せず、物語に合った正規クリア結末として生成
- AI COMMENTの過剰な称賛や定型表現を抑え、実際のプレイ内容に沿った短評へ改善

### 背景・音楽・演出の拡充

- 背景タグを65種類へ拡充
- 背景画像を100枚収録
- 同じ背景タグへ複数画像を登録できる背景カタログ方式
- タイトル・通常場面・エピローグ・GAME CLEAR用のBGMを10曲収録 (v3)
- 正解・BAD END・GOOD END用の効果音を3種類収録 (v3)
- タイトル、正解、BAD END、GAME CLEAR、AI COMMENT、プレイ記録、終了案内用の画像を収録
- 使用した背景画像・結果画像・BGMを `game.log` へ記録

### 操作・記録機能の改善

- 正解結果のあとに「次のシナリオへ」を押して進む方式
- エンディングの各項目を専用ボタンで読み進める方式
- 現在までの物語を別画面で確認できるバックログ
- ゲームクリア後のプレイ記録テキスト保存
- VOICEVOXで生成した読み上げ音声の保存
- LLM生成中のキャンセルと初期画面への復帰
- BGM・SE・VOICEの個別音量調整

---

## v4の主な変更点

v4では、ローカルLLMによる物語生成の快適性を高めるため、生成処理の効率化、音声読み上げの先読み、動作状況の計測機能などを追加・改善しました。

### 物語生成・LLM処理の改善

- Ollamaとの通信処理を見直し、ローカルLLMによる物語生成の効率化を実施
- 通常場面と、正解後に使用する物語要約を1回のLLM応答でまとめて生成し、正解時に必要な追加のLLM呼び出しを削減
- 同時生成した要約が空・不正形式・文字数超過の場合は、従来どおり要約を別に生成する方式へ切り替え
- Ollamaの標準接続先を `http://127.0.0.1:11434` に変更

### VOICEVOX音声読み上げの待ち時間を軽減

- 次の場面で使用する音声の一部を事前生成する先読み機能を追加
- 正解時の文章を読み上げている間に、次場面の冒頭音声を準備することで待ち時間を軽減
- GOOD END以降のエンディング演出にも音声先読みを拡張
- 音声の生成・再生と本文表示の同期を維持しながら、処理を効率化
- ゲームの停止や再プレイ時に、不要になった音声先読み処理を取り消す仕組みを追加
- 通常場面とエンディングの音声先読みを個別に無効化できる設定を追加

### パフォーマンス計測・検証機能の追加

- LLMによる文章生成、音声処理、画面表示などの処理時間を計測する機能を追加
- VOICEVOXの音声合成時間、生成キューの待機時間、音声の長さを計測可能に
- ゲーム内の「音声計測」で、同じ固定文・話者による音声合成時間を比較可能に
- 高速化機能の有効・無効を比較できる仕組みを整備

### 安定性・メンテナンス性の改善

- 音声先読み処理と通常の読み上げ処理が競合しにくいよう、既存の音声生成キューを活用
- 先読みした文章や音声が、次の場面へ進む前に表示・再生されないよう制御
- 既存の画面遷移、続行ボタン、BGM、効果音などの演出との互換性を維持
- 処理の変更に伴う回帰テストや検証用ドキュメントを整備


---

## ガイドライン

ゲームプレイ・配信・動画投稿・二次創作などについては、[GUIDELINE.md](./GUIDELINE.md)をご確認ください。

---

## 主な機能

- Ollamaを利用したローカルAIストーリー生成
- 30種類の登録ジャンル
- 文章で物語を指定できる「自由に綴る」モード
- 全5場面で構成される短編テキストアドベンチャー
- 各場面に2つの選択肢ボタンを表示
- 正しい選択で次の場面へ進行、誤った選択でBAD END
- BAD END後に「直前の選択肢へ」戻って再挑戦
- 正解位置が片側へ偏りすぎないランダムな正解パターン（正解位置はアプリ側で決定）
- 本文を1文字ずつ表示するタイピングエフェクト
- Enterキーによる本文の即時表示と読み上げ停止
- Ollamaにインストールされているモデル一覧の取得・更新
- LLM生成中の「生成キャンセル」
- VOICEVOXによる順次読み上げ
- BGM・SE・VOICEの個別音量調整
- AIが選択する `background_tag` に応じた背景画像表示
- AIが選択する `bgm_tag` に応じたBGM再生
- BGMのループ再生と場面切り替え時のフェード
- 正解・BAD END・GOOD END用の効果音
- エピローグ、GAME CLEAR、AI COMMENT、プレイ記録、終了案内
- バックログの閲覧
- ゲームクリア後のテキスト・音声保存

---

## ゲームの流れ

1. ジャンル（または「自由に綴る」）とOllamaモデルを選びます。
2. 「自由に綴る」を選んだ場合は、遊びたい物語を入力します。
3. 「ゲーム開始」を押すと、AIが第1場面を生成します。
4. 本文と2つの選択肢を読み、行動を選びます。
5. 正解なら結果文が表示され、「次のシナリオへ」で次の場面へ進みます。
6. 不正解ならBAD ENDとなり、「直前の選択肢へ」で同じ場面へ戻れます。
7. 5場面目の正解でGOOD ENDとなります。
8. エピローグ、GAME CLEAR、AI COMMENT、プレイ記録、終了案内を順番に読み進めます。
9. クリア後は、必要に応じてプレイ記録や生成済み音声を保存できます。

ストーリーはプレイごとにAIが生成するため、同じジャンルとモデルを選んでも、登場人物や展開、結末が変化します。

---

> **ローカルでの利用と記録**
>
> 初期設定では、このPC上のOllamaとVOICEVOXへ接続します。モデルや外部ソフトウェアのダウンロードにはインターネット接続が必要です。Ollamaにはローカル実行するモデルを用意してください。接続先やモデルの種類を変更した場合の通信先まで、このアプリが保証するものではありません。
> ログ・音声キャッシュの保存先と取り扱いは、後述の「ログ・計測・診断」を参照してください。

---

## 動作環境

### 必須

- [Ollama](https://ollama.com/)
- Ollamaへダウンロード済みの対応モデル

Windows実行ファイル版ではPythonは不要です。Windows 11を想定していますが、配布exeの対応環境は作者のビルド・実機確認に従います。

Pythonソース版は、使用している構文上Python 3.10以上が必要です。今回の自動テストはLinux・Python 3.12.14で実施しました。WindowsのGUI・実音声・他のPythonバージョンは今回未検証です。必要なメモリ・VRAMは使用するモデルによって異なります。

### 音声読み上げを使用する場合

- [VOICEVOX](https://voicevox.hiroshiba.jp/)
- 音声を再生できる環境

VOICEVOXは任意です。起動していない場合でも、読み上げをOFFにしてテキストのみで遊べます。

---

## 必要なPythonライブラリ

この項目は、Pythonソース版から起動する場合に必要です。実行ファイル版では、別途インストールする必要はありません。

```bash
python -m pip install requests pygame
```

- `requests`：Ollama APIおよびVOICEVOX ENGINEとの通信
- `pygame`：VOICEVOX音声、BGM、効果音の再生

`tkinter` はPythonの標準GUIライブラリです。環境によっては、Pythonとは別にTcl/Tk関連パッケージの導入が必要になる場合があります。`python -m tkinter` で確認できます。

依存関係のバージョン固定ファイルは含まれていません。再現用には、実際にビルド・動作確認した環境のPython、requests、pygame、PyInstallerのバージョンを記録してください。

---

## セットアップ

### 1. Ollamaをインストールする

[Ollama公式サイト](https://ollama.com/)からインストールしてください。

### 2. 使用するモデルをダウンロードする

初期モデルは、`src/data/game_settings.json` で次のように設定されています。

```text
gemma3:4b
```

ダウンロード例：

```bash
ollama pull gemma3:4b
```

ほかのOllama対応モデルも使用できます。ただし、JSON形式の指示へ安定して応答でき、日本語の文章生成に向いたモデルを推奨します。

### 3. VOICEVOXを準備する（任意）

音声読み上げを使用する場合は、VOICEVOXをインストールし、本アプリより先に起動してください。

- [VOICEVOX公式サイト](https://voicevox.hiroshiba.jp/)
- [VOICEVOX GitHub](https://github.com/VOICEVOX/voicevox)

本アプリにVOICEVOX本体は含まれていません。

### 4. アプリを起動する

#### 実行ファイル版

1. GitHub ReleasesからWindows版のZIPファイルをダウンロードします。
2. ZIPファイルを任意の場所へ展開します。
3. Ollamaを起動します。
4. 読み上げを使用する場合は、VOICEVOXも起動します。
5. 展開したフォルダ内の `綴り文庫室.exe` をダブルクリックします。

```text
綴り文庫室/
├─ 綴り文庫室.exe
└─ _internal/
```

> [!IMPORTANT]
> `綴り文庫室.exe` だけを別の場所へ移動せず、`_internal` フォルダと同じ配布フォルダ内で起動してください。

初回起動時にWindowsやセキュリティソフトの確認画面が表示される場合があります。配布元とファイルを確認したうえで実行してください。

#### Pythonソース版

リポジトリのルートから `src` フォルダへ移動し、`main.py` を実行します。

```bash
cd src
python main.py
```

WindowsのPython Launcherを使用する場合：

```bat
cd src
py main.py
```

---

## 実行ファイルの作成（開発者向け）

Windows向け実行ファイルは、PyInstallerの `onedir` 形式で作成します。

### 1. PyInstallerをインストールする

```bash
python -m pip install pyinstaller
```

### 2. `src` フォルダへ移動する

```bat
cd src
```

### 3. `onedir` 形式でビルドする

以下はWindowsのコマンドプロンプト用です。`src` 内で実行してください。

```bat
rem dataとassetsを、実行時に参照する同じ相対パスへ同梱します。
python -m PyInstaller --clean --onedir --windowed --name "綴り文庫室" --icon "icon.ico" --add-data "data:data" --add-data "assets:assets" main.py
```

`--clean` はPyInstallerの一時キャッシュを消してビルドし、`--windowed` はコンソールを表示しない設定です。`build/` と `dist/` は自動生成されます。既存の出力先がある場合は、内容を確認してから置き換えてください。ビルド用 `.spec` は再現性のため保存できます。


### 4. 配布文書を同梱する

同じコマンドプロンプトで、`src` 内から次を実行します。

```bat
rem 利用マニュアルとガイドラインをexeの隣へ配置します。
copy /Y "..\README_PLAY.md" "dist\綴り文庫室\README_PLAY.md"
copy /Y "..\GUIDELINE.md" "dist\綴り文庫室\GUIDELINE.md"
rem 著作権・ライセンス表示は、既存の階層を保って丸ごと同梱します。
xcopy /E /I /Y "..\licenses" "dist\綴り文庫室\licenses"
```

想定する配布構成（PyInstaller 6系の標準 `onedir`）：

```text
src/dist/綴り文庫室/
├─ 綴り文庫室.exe
├─ _internal/           # data・assets・Pythonやライブラリの実行時ファイル
├─ README_PLAY.md
├─ GUIDELINE.md
└─ licenses/
```

### Device Guardで `pyinstaller.exe` がブロックされる場合

`pyinstaller` コマンドを直接実行できない場合は、次のようにPythonモジュールとして実行してください。

```bash
python -m PyInstaller --version
```

本READMEのビルドコマンドも、この方式を使用しています。

---

## ファイル構成


```text
tsuzuri-bunkoshitsu/
├─ src/
│  ├─ main.py
│  ├─ icon.ico
│  ├─ game_engine.py
│  ├─ game_prompts.py
│  ├─ llm_client.py
│  ├─ voicevox_client.py
│  ├─ audio_mixer.py
│  ├─ bgm_manager.py
│  ├─ background_manager.py
│  ├─ performance_monitor.py
│  ├─ voice_diagnostics.py
│  ├─ data/
│  │  └─ game_settings.json
│  ├─ assets/
│  │  ├─ backgrounds/
│  │  ├─ result_images/
│  │  ├─ bgm/          
│  │  └─ sfx/          
│  ├─ logs/             # 実行時に生成（Git管理外）
│  └─ voice_cache/       # 実行時に生成（Git管理外）
├─ tools/
│  ├─ summarize_performance.py
│  └─ diagnose_ollama.py
├─ tests/               # 自動テスト5本と単体VOICEVOX診断
│  └─ diagnose_voicevox.py
├─ docs/                # テスト・ツールの説明と過去の開発記録
├─ licenses/
├─ .gitignore
├─ GUIDELINE.md
├─ README.md
└─ README_PLAY.md
```

素材と初期設定はリポジトリ直下ではなく、**`src/assets/` と `src/data/`** にあります。上記の `logs/` と `voice_cache/` は、起動時に作成されます。

`tests/` と `tools/` は保守・回帰確認に再利用できるため公開対象として維持しています。**実行ファイル版に同梱する必要はありません。**

### 主なPythonファイル

-   `main.py`：Tkinter GUI、画面操作、ゲーム進行、画像・音声機能の連携  
-   `game_engine.py`：場面生成、選択結果、BAD END、GOOD END、再挑戦、要約    
-   `game_prompts.py`：AI生成用プロンプト、背景タグ、BGMタグの定義  
-   `llm_client.py`：Ollama APIとの通信、モデル一覧取得、生成キャンセル  
-   `voicevox_client.py`：VOICEVOX ENGINEとの通信、音声生成・再生・キャッシュ管理  
-   `audio_mixer.py`：VOICEVOX、BGM、SEが干渉しにくいようpygame mixerを管理  
-   `bgm_manager.py`：BGMタグから音源を選択し、ループ・フェード・音量を管理  
-   `background_manager.py`：背景タグに対応する画像候補の検索・ランダム選択を管理  
-   `performance_monitor.py`：処理時間の計測と計測ログの記録  
-   `voice_diagnostics.py`：固定文によるVOICEVOX音声合成の計測  


---

## 設定ファイル

`src/data/game_settings.json` の初期値は次のとおりです（`prefetch_ending_first_chunk` のみ未記載で、実装の省略時既定値を示しています）。

| 設定 | 初期値 | 内容 |
| --- | --- | --- |
| `game.total_scenes` | `5` | 1ゲームの場面数 |
| `game.max_retries` | `3` | AI生成データの取得・解析に失敗した場合の試行回数の上限 |
| `game.summary_max_characters` | `100` | 次の場面へ引き継ぐ物語要約の最大文字数 |
| `game.summary_in_scene` | `true` | 通常場面と正解後の要約をまとめて生成 |
| `ollama.base_url` | `http://127.0.0.1:11434` | Ollama APIの接続先 |
| `ollama.default_model` | `gemma3:4b` | 初期選択モデル |
| `ollama.timeout_seconds` | `120` | 生成APIに渡すrequestsのタイムアウト。操作全体の制限時間ではない |
| `voicevox.base_url` | `http://127.0.0.1:50021` | VOICEVOX ENGINEの接続先 |
| `voicevox.speaker_id` | `3` | 初期話者ID |
| `voicevox.volume` | `1.0` | VOICEの初期音量 |
| `voicevox.prefetch_next_scene_first_chunk` | `true` | 次場面の冒頭音声を先読み |
| `voicevox.prefetch_ending_first_chunk` | `true`（省略時） | エンディングの次区間の冒頭音声を先読み |
| `performance.enabled` | `true` | 通常プレイの処理時間を計測・記録 |
| `sfx.volume` | `0.2` | SEの初期音量 |
| `bgm.volume` | `0.2` | BGMの初期音量 |
| `bgm.fade_ms` | `800` | BGM切り替え時のフェード時間（ミリ秒） |

`voicevox.prefetch_ending_first_chunk` は、設定ファイルに項目がなくても有効です。無効にする場合は、既存の `voicevox` 内へ `"prefetch_ending_first_chunk": false` を追加してください。通常場面の先読みとは個別に切り替えられます。設定変更後はアプリを再起動してください。

| 設定 | 初期値 | 内容 |
| --- | --- | --- |
| `genres` | 30ジャンルの名前と生成方針 | 下記「収録ジャンル」を参照 |

実行ファイル版の設定ファイルは、標準の `onedir` 配布では `_internal/data/game_settings.json` です。編集する場合はアプリを終了し、バックアップ後にUTF-8（BOMなし）の正しいJSONとして保存してください。コメントは記述できません。必須項目の欠落や形式不正は起動失敗の原因になります。

画面で変更したジャンル、モデル、話者、読み上げON/OFF、音量は設定ファイルへ自動保存されません。起動直後の読み上げはOFF、ジャンルは登録順の先頭です。初期モデルが未導入の場合、取得した一覧の先頭へ切り替わる場合があります。

### Ollama・VOICEVOXとの接続

| 接続 | 初期接続先とAPI | 処理 |
| --- | --- | --- |
| Ollama | `http://127.0.0.1:11434` の `GET /api/tags`、`POST /api/chat` | モデル一覧と物語生成 |
| VOICEVOX | `http://127.0.0.1:50021` の `GET /version`、`POST /audio_query`、`POST /synthesis` | 接続確認と読み上げ生成 |

Ollamaには `format: "json"`、`stream: false`、`think: false` を渡し、完成したJSONをまとめて受け取ります。requests側の `stream=True` は通信中のResponseを保持してキャンセルに対応するためで、本文の逐次表示ではありません。`num_ctx`・`num_predict` はアプリから指定せず、モデル・Ollama側の設定に委ねます。`think: false` の効き方や対応可否はモデルとOllamaに依存します。

モデル一覧は5秒、VOICEVOXの接続確認は2秒、音声クエリは30秒、合成は60秒のタイムアウトです。診断用の追加APIは[toolsの説明](./docs/tools_guide.md)を参照してください。接続先URLの変更は設定ファイルで行い、画面からは変更できません。

---

## 収録ジャンル

v4の初期設定には、次の30ジャンルが登録されています。

- 王道ファンタジー
- 恋愛告白
- 明るいミステリー
- 怪談
- モンスターサバイバル
- 宇宙SF
- 異世界転生
- 刑事ドラマ
- シリアスドラマ
- コメディ
- ゾンビパニック
- 青春部活
- 無人島サバイバル
- 探検隊
- 海賊冒険
- 忍者
- スパイアクション
- タイムトラベル
- 昭和レトロ冒険
- 法廷ドラマ
- お仕事体験
- 学園七不思議
- 西部劇
- 日常の不思議
- 旅情ドラマ
- 時代劇
- 探偵ミステリー
- 料理チャレンジ
- 格闘アクション
- ラブコメ

ジャンル名と生成方針は、`src/data/game_settings.json` の `genres` から追加・編集できます。

---

## 「自由に綴る」モード

ジャンル欄の末尾にある「自由に綴る」を選ぶと、物語表示欄が専用の複数行入力欄へ切り替わります。

遊びたい物語を1000文字以内で入力し、「ゲーム開始」を押してください。AIが入力内容を短編ゲーム向けのジャンル名・舞台・主人公・目的などへ整理してから、第1場面を生成します。

入力原文は整理後の設定と一緒にAIへ渡されます。生成に失敗した場合や生成をキャンセルした場合は、入力内容を残したまま専用画面へ戻ります。

---

## 背景画像

各場面の生成結果に `background_tag` が含まれます。AIは65種類の場所タグ（および非表示の `none`）から現在地に合うものを選び、アプリは対応する画像を `src/assets/backgrounds/` から探して「情景窓」へ表示します。

同じタグへ複数画像を登録する場合は、タグ名のサブフォルダを使用できます。

```text
src/assets/backgrounds/cafe/
├─ quiet_interior_01.png
├─ retro_kissaten_01.jpg
└─ window_seating_02.jpg
```

画像の追加方法は [背景画像の説明](./docs/画像について.md)も参照してください。

複数候補がある場合は、直前に使用した画像をできるだけ避けながら選択します。画像は必要なときに読み込むため、多数の画像を追加することも想定した構成です。提供素材は背景100枚・結果画像7枚です。

背景は `.jpg`・`.jpeg`・`.png` に対応します。ルート直下の `タグ名__任意名.png` 形式でも追加できます。同名タグの形式違いはJPG→JPEG→PNGの順で1枚を候補にします。

---

## BGM・効果音

v4の提供ファイルには、BGM 10曲と効果音3種類を収録しています。音源が不足・削除されている場合でも、物語生成、背景表示、VOICEVOXなど、利用可能な機能でゲームを続行します。

### BGM

配置先：

```text
src/assets/bgm/
```

| ファイル名 | 用途 |
| --- | --- |
| `title.mp3` | タイトル画面 |
| `calm.mp3` | 静か・穏やかな場面 |
| `bright.mp3` | 明るい・楽しい場面 |
| `mystery.mp3` | 謎・調査・違和感 |
| `tension.mp3` | 緊迫・追跡・危機 |
| `battle.mp3` | 戦闘・対決 |
| `sad.mp3` | 悲しみ・別れ |
| `horror.mp3` | 怪異・恐怖 |
| `ending.mp3` | エピローグ |
| `game_clear.mp3` | GAME CLEAR以降 |

通常場面では、AIが `calm`、`bright`、`mystery`、`tension`、`battle`、`sad`、`horror` から1つを選びます。タイトル、エピローグ、GAME CLEARでは、アプリが専用BGMを指定します。

MP3を優先して読み込み、同名のMP3がない場合はOGGも候補にします。収録曲を差し替える場合は、同じファイル名で配置してください。

### 効果音

配置先：

```text
src/assets/sfx/
```

| ファイル名 | 用途 |
| --- | --- |
| `correct.mp3` | 正しい選択をしたとき |
| `bad_end.mp3` | BAD END |
| `good_end.mp3` | GOOD END |


### 収録音源について

収録BGMは、ローカル音楽生成モデル **ACE-Step 1.5** を利用して制作しています。  

収録音源には、アプリケーションコードのMIT Licenseや画像のCC BY 4.0が自動的に適用されるわけではありません。音源単体の再利用・再配布・改変物の公開を行う場合は、使用した生成モデルや関連ツールの利用条件を確認してください。  
利用者が別の音源へ差し替える場合は、その音源のライセンス、利用規約、クレジット表記、再配布可否を利用者自身で確認してください。  
ゲームの実況等は[GUIDELINE.md](./GUIDELINE.md)を参照してください。  

---

## タイピング表示と音声の同期

本文は1文字ずつ表示され、句読点や改行では少し長めの間を取ります。

- 表示中にEnterキーを押すと、残りの文章をすぐに全文表示し、現在の読み上げを停止します。
- 文章がすでに全文表示されている場合は、Enterキーで残っている読み上げを停止できます。
- 本文の表示が完了するまで、選択肢の決定操作は無効です。
- VOICEVOX読み上げがONの場合は、最初の音声チャンクが完成してからタイピング表示と再生を開始します。
- 後続の音声は、本文表示と並行して準備されます。

---

## BAD ENDと再挑戦

誤った選択肢を選ぶと、その場面の流れに沿ったBAD ENDが表示されます。

「直前の選択肢へ」を押すと、同じ場面・本文・選択肢へ戻ります。場面をAIで再生成しないため、直前の状況を保ったまま別の選択を試せます。

「最初から」を押した場合は、新しい物語を第1場面から生成します。

---

## GOOD END後の演出

5場面目で正しい選択肢を選ぶと、次の内容が順番に表示されます。

1. GOOD END
2. EPILOGUE
3. GAME CLEAR
4. AI COMMENT
5. PLAY RECORD
6. 終了案内

各項目は自動では進まず、「エピローグへ」「GAME CLEAR」「AI COMMENT」「PLAY RECORD」「最後に」の各ボタンで読み進めます。

PLAY RECORDには、バッドエンド到達回数、直前の選択肢へ戻った回数、総選択回数が表示されます。

追加生成に失敗した場合でも、固定のエピローグとメッセージを使用してゲームを終了できるようにしています。

---

## バックログと保存

### バックログ

「バックログ」を押すと、表示完了済みの本文、選択結果、エンディングなどを別ウィンドウで確認できます。

### テキスト保存

ゲームクリア後に「テキスト保存」を押すと、開始日時、ジャンル、使用モデルを含むプレイ記録をUTF-8のテキストファイルとして保存できます。

### 音声保存

VOICEVOX読み上げを使用してゲームをクリアした場合は、「音声保存」から今回生成したWAVファイルを任意のフォルダへ保存できます。ファイル名には場面・区間に基づく並び順の連番が付きます。厳密な再生履歴の書き出しではなく、生成済みWAVの保存なので、再挑戦時の音声や未再生の先読み音声が含まれる場合があります。BGM・効果音は含みません。

---

## ログ・計測・診断

| 生成先（ソース版） | 内容と扱い |
| --- | --- |
| `src/logs/game.log` | 進行、正解パターン、物語要約、参照した素材名等を追記。ネタバレや入力由来の情報を含み得る |
| `src/logs/error_*.log` | 例外と呼び出し履歴。環境のパス等を含む可能性がある |
| `src/logs/performance_*.jsonl` | LLM・音声・画面処理の時間、文字数、モデル名、接続先ホスト等。プロンプトや生成本文そのものは記録しない |
| `src/voice_cache/` | 生成したWAV。保存したい音声はクリア後に「音声保存」で別フォルダへ書き出す |

標準のPyInstaller 6系 `onedir` では、実装の `__file__` 基準により `logs/` と `voice_cache/` は通常 `_internal/` 内に作成されます。配布exeでの実際の保存先はビルド後に確認してください。書き込み可能な場所へ展開する必要があります。

ログは不要ならアプリ終了後に削除できます。音声キャッシュは起動時・新規ゲーム開始時・キャンセル時・終了時にクリアされます。ログは自動ローテーションしません。外部へ共有する前に本文やパスを確認してください。

`performance.enabled` を `false` にすると通常プレイの計測記録を停止します。画面の「音声計測」と単体音声診断は独立してログを記録します。計測結果の `app_version` は、現ソースの定数が **`3.1.5`** のため、v4でもその値になります。

### 診断・テストの実行

次のコマンドはリポジトリ直下で実行します。

```bat
rem 保存済みの最新ログを読みます。サーバーは不要です。
python tools/summarize_performance.py
rem Ollamaの軽量APIで接続先を比較します。物語は生成しません。
python tools/diagnose_ollama.py
rem VOICEVOXが起動済みの場合に、固定文を合成して計測します（再生なし）。
python tests/diagnose_voicevox.py --speaker 3 --samples 3
rem 外部通信・再生等を代替する既存の自動テストを実行します。
python -m unittest discover -s tests -v
```

画面の「音声計測」は開始前または終了案内まで完了した後に利用できます。話者IDを指定して固定文を合成し、結果を表示します。通常の読み上げON/OFFとは独立し、VOICEVOXは必要ですが、音声再生はしません。

現在の配置では単体音声診断は `tests/diagnose_voicevox.py` です。`unittest discover` は `tests/` も検索するため関連テストから読み込めます。一般利用者向けの操作は[README_PLAY.md](./README_PLAY.md)、計測項目と制約は[toolsの説明](./docs/tools_guide.md)、88件の確認内容は[testsの説明](./docs/tests_guide.md)を参照してください。

### 高速化の比較と制約

要約同時生成・通常場面先読み・エンディング先読みはそれぞれ独立した設定です。比較時は同じモデル・話者を使い、同条件で複数回計測してください。5場面を再試行なしでクリアし、通常4場面の要約がすべて有効な場合、場面5回＋追加エンディング1回の計6回のLLM呼び出しで進行します。別要約方式では最大4回分が加わり、「自由に綴る」は開始設定の整理が加わります。

先読みするのは次の音声区間の**先頭1チャンク**で、次場面全体の先行LLM生成ではありません。次場面は正解結果の表示前に生成済みです。先読みは待ち時間を既存の読み上げ中へ重ねる方式で、モデルやVOICEVOXの処理速度そのものを上げる保証はありません。`127.0.0.1` への変更も名前解決やIPv6接続試行の影響を避けられる場合がありますが、全環境での高速化を保証しません。


---

## 既知の制限事項

- AI生成のため、文章の品質、展開、固有名詞、選択肢の自然さにはばらつきがあります。
- 使用モデルによっては、指定したJSON形式を正しく返せず、生成を再試行する場合があります。
- PC性能やモデルサイズによって、場面生成に時間がかかります。
- 「自由に綴る」は、通常モードより開始設定の整理処理が1回増えます。
- VOICEVOXの初回音声生成や長い文章では、読み上げ開始まで待ち時間が発生する場合があります。
- 読み上げ停止後も、VOICEVOX ENGINEへ送信済みの処理が一時的に継続する場合があります。停止後に完成した音声は再生されません。
- OllamaまたはVOICEVOXの接続先を変更している場合は、`src/data/game_settings.json` の変更が必要です。
- 背景画像や音源が不足していても可能な範囲でゲームを続行しますが、その素材に対応する演出は行われません。

---

## 開発について

本プロジェクトの制作にあたり、OpenAIの対話型AI「ChatGPT」のサポートを受け、アイデア出し、コード設計、実装、検証、文章表現の改善などを行いました。

**使用した主なモデル・プラン：**

- GPT-6（通常チャット）
- GPT-6.1 Sol（ChatGPT Work・思考レベル：高／低）
- ChatGPT Plus

**主な利用内容は以下のとおりです。**

- 開発計画・設計方針の整理（Chat・Work）
- アプリ全体の構成検討（Chat・Work）
- Pythonコードの実装支援（Chat・Work）
- リファクタリングおよび改善提案（Chat）
- README・ドキュメントの作成支援（Chat・Work）
- プロンプト設計・改善（Chat）
- ゲーム仕様のアイデア出し（Chat）
- ストーリー構成のアイデア出し（Chat・Work）
- 不具合調査および原因分析（Chat・Work）


最終的な設計・実装・動作確認・公開判断は開発者本人が行っています。

開発に携わったすべての研究者、開発者、関係者の皆様に、心より感謝申し上げます。

### 制作期間

- **綴り文庫室 v1：2026年7月26日 ～ 2026年7月29日**
- **綴り文庫室 v2：2026年7月30日 ～ 2026年8月8日**
- **綴り文庫室 v3：2026年8月ごろ ～ 2026年9月2日**
- **綴り文庫室 v4：2026年10月ごろ ～ 2026年10月25日**

## コントリビューションについて

本リポジトリは個人学習・個人制作を目的としています。そのため、Pull Request（PR）はお受けできません。ご了承ください。

---

## 注意事項

本アプリの物語、選択肢、エンディング、AI COMMENTは、ローカルLLMによって自動生成されます。

出力内容の正確性、安全性、完全性は保証されません。実在する人物、団体、場所、出来事などと似た内容が生成された場合でも、原則として偶然によるものです。

各Ollamaモデルの利用条件については、モデル提供元のライセンスをご確認ください。

VOICEVOXで生成した音声を公開・配布する場合は、VOICEVOX本体と使用したキャラクター（話者）の利用規約・クレジット表記をご確認ください。

---

## 免責事項

本アプリの利用、設定変更、外部ソフトウェアとの連携、生成された文章・画像・音声の使用などによって生じた損害、不具合、データ損失その他の問題について、作者は責任を負いません。

利用者自身の責任においてご使用ください。

## このプロジェクトのライセンス

本プロジェクトでは、アプリケーションコードとプロンプト・画像などのコンテンツに、それぞれ異なるライセンスを設定しています。

### アプリケーションコード

* **ライセンス：MIT License**
* 商用利用：可能
* 改変：可能
* 再配布：可能

著作権表示とライセンス文の同梱が必要です。詳細は、[LICENSE-CODE](./licenses/application/LICENSE-CODE.txt)をご確認ください。

```text
Code by AglaoDev-jp © 2026, licensed under the MIT License.
```

### アイコン

本プロジェクトに含まれるアプリアイコンには、MIT Licenseを適用します。

```text
App icon by AglaoDev-jp © 2026, licensed under the MIT License.
```

### プロンプト関連データ

ジャンル説明やゲーム生成用プロンプトには、Creative Commons Attribution 4.0 International（CC BY 4.0）を適用します。

* **ライセンス：CC BY 4.0**
* 商用利用：可能
* 改変：可能
* 再配布：可能
* クレジット表記：必要

詳細は、[LICENSE-PROMPT](./licenses/application/LICENSE-PROMPT.txt)をご確認ください。

```text
Prompt Collection by AglaoDev-jp

Licensed under CC BY 4.0
```


### 画像素材

本プロジェクトに含まれる背景画像やゲーム内表示用画像には、Creative Commons Attribution 4.0 International（CC BY 4.0）を適用します。

* **ライセンス：CC BY 4.0**
* 商用利用：可能
* 改変：可能
* 再配布：可能
* クレジット表記：必要

CC BY 4.0の条件に従い、クレジットを表示することで、画像の加工・編集や、加工した画像の再配布にも利用できます。

詳細は、[LICENSE-IMAGE](./licenses/application/LICENSE-IMAGE.txt)をご確認ください。

```text
Image Collection by AglaoDev-jp

Licensed under CC BY 4.0
```


### 音源
本プロジェクトに収録されているBGM・効果音は、AI音楽生成モデル **ACE-Step 1.5** を使用して生成しています。

AI生成音源については、著作権をはじめとする権利関係に現時点で不明確な部分があるため、本プロジェクトでは収録音源に対してMIT LicenseやCC BY 4.0などのライセンスを**独自に付与していません。**  
利用時の注意は、[収録音源について](#収録音源について)をご確認ください。


---

## 第三者ソフトウェアの著作権・ライセンス

### ライセンスファイル一覧

* [Python License](./licenses/LICENSE-PSF.txt)
* [Tcl/Tk License](./licenses/third_party/LICENSE-TclTk.txt)
* [Pygame LGPL v2.1](./licenses/third_party/LGPL_v2.1.txt)
* [Requests Apache License 2.0](./licenses/third_party/requests_LICENSE.txt)
* [Requests NOTICE](./licenses/third_party/requests_NOTICE.txt)

### Python

* Copyright © 2001 Python Software Foundation. All rights reserved.
* Licensed under the PSF License Version 2.
* [Python公式ライセンス](https://docs.python.org/3/license.html)

### Tkinter / Tcl/Tk

TkinterはPythonに含まれるGUIライブラリですが、その動作にはTcl/Tkが使用されています。

* [Tcl/Tk License](https://www.tcl.tk/software/tcltk/license.html)

### Pygame

* License: LGPL v2.1
* [ライセンスファイル](./licenses/third_party/LGPL_v2.1.txt)

### Requests

* License: Apache License 2.0
* [ライセンスファイル](./licenses/third_party/requests_LICENSE.txt)
* [NOTICE](./licenses/third_party/requests_NOTICE.txt)

### 外部ソフトウェア・生成ツール

* [Ollama](https://ollama.com/)
* [VOICEVOX](https://voicevox.hiroshiba.jp/)
* [ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5)

これらのプロジェクトの開発者、貢献者、関係者の皆様に、心より感謝申し上げます。


---

© 2026 AglaoDev-jp
