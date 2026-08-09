# 綴り文庫室 v2
**"選択で綴る、偶然の物語。"**  
**Ollama + VOICEVOXで遊ぶ、ローカルAIテキストアドベンチャーゲーム**
本アプリは、ローカル環境で動作する **Ollama API** および **VOICEVOX
ENGINE** を利用します。\
本リポジトリでは、アプリケーションのソースコードと実行ファイルを公開しています。\
**綴り文庫室（つづりぶんこしつ）は、選んだジャンルに合わせてローカルLLMが物語を自動生成する、短編テキストアドベンチャーゲームです。**

全5場面の物語を進み、各場面で表示される `a`・`b`
の二択から行動を選びます。片方は物語が続く選択肢、もう片方はその場で結末を迎えるBAD
ENDです。\
v2では、AIが物語だけでなく場面に合う**背景タグ**と**BGMタグ**も選択します。登録済みの背景画像から情景に合うものを表示し、ユーザーが用意したBGMがある場合は場面の雰囲気に合わせて再生します。\
最後の正しい選択までたどり着くと、GOOD
ENDに加えて、エピローグやプレイ内容に応じたAIコメントが生成されます。

詳しい準備と操作方法は、[利用マニュアル](./README_PLAY.md)をご確認ください。
- 実行ファイルのダウンロードはこちら：[Releases](https://github.com/AglaoDev-jp/tsuzuri-bunkoshitsu/releases/download/v2/tsuzuri-bunkoshitsu_v2.zip)

> \[!NOTE\]
> 本READMEは、アプリのソースコードおよび仕様をもとに、OpenAIの対話型AI「ChatGPT」の支援を受けて草案を作成し、作者が内容の確認・編集を行っています。
> 本ソフトウェアは、同名または類似名称の既存の商標・製品・サービスとは関係ありません。

---

## v2の主な変更点

* 場面に合わせてAIが背景画像タグを選択
* 同じ背景タグへ複数画像を登録できる背景カタログ方式
* 場面の雰囲気に合わせてAIがBGMタグを選択
* タイトル、エピローグ、GAME CLEAR用BGM
* 正解・BAD END・GOOD ENDの効果音
* BGM・SE・VOICEの個別音量調整
* LLM生成中のキャンセル機能
* タイトル、GAME CLEAR、AI COMMENT、プレイ記録などの結果画像
* 使用した画像・BGMを `game.log` へ記録
* 選択できるシナリオジャンルを30種類に拡充

  * 「日常の不思議」「旅情ドラマ」「時代劇」「探偵ミステリー」「料理チャレンジ」「格闘アクション」「ラブコメ」を追加
  * 「ホテル脱出コメディ」をラインナップから削除

なお、**BGM・効果音の音源ファイルは、配布物に含まれておりません。**
必要な場合は、利用者自身が使用可能な音源を用意し、READMEで指定するファイル名へ変更して配置してください。

---

## ガイドライン

ゲームプレイ・配信・二次創作等については、
[GUIDELINE.md](./GUIDELINE.md) をご確認ください。

---

## 主な機能

-   Ollamaを利用したローカルAIストーリー生成
-   24種類のジャンルから物語を選択
-   全5場面で構成される短編テキストアドベンチャー
-   各場面に `a`・`b` の二択を表示
-   正しい選択で次の場面へ進行、誤った選択でBAD END
-   BAD END後に「直前の選択肢へ」戻って再挑戦
-   本文を1文字ずつ表示するタイピングエフェクト
-   Enterキーによる本文の即時表示
-   Ollamaにインストールされているモデル一覧の取得・更新
-   LLM生成中の「生成キャンセル」と初期画面への復帰
-   VOICEVOXによる文章の順次読み上げ
-   BGM・SE・VOICEの個別音量調整
-   AIが選択する `background_tag` に応じた背景画像表示
-   同じ背景タグへ複数画像を登録し、候補から切り替えて表示
-   AIが選択する `bgm_tag` に応じたBGM再生
-   BGMのループ再生と場面切り替え時のフェード
-   正解・BAD END・GOOD END用の効果音
-   タイトル、正解、BAD END、GAME CLEAR、AI
    COMMENT、プレイ記録などの結果画像表示
-   クリア後のエピローグ、GAME CLEAR、プレイ記録、AI COMMENT
-   プレイ中のバックログ保存、音声の保存

---

## ゲームの流れ

1.  ジャンルとOllamaモデルを選びます。
2.  「ゲーム開始」を押すと、AIが最初の場面を生成します。
3.  本文と `a`・`b` の選択肢を読み、どちらかを入力します。
4.  正解なら次の場面へ進み、不正解ならBAD ENDになります。
5.  BAD END後は、同じ場面を生成し直さずに「直前の選択肢へ」戻れます。
6.  5場面目の正解でGOOD
    ENDとなり、追加のエンディング演出が生成されます。

ストーリーはプレイごとにAIが生成するため、同じジャンルでも登場人物や展開が変化します。

---

> **ログファイルについて**
>
> 現在はデバッグやプレイ内容の確認のため、`game.log`
> にゲーム進行の情報を記録しています。
> 本アプリは、動作状況やAIによるストーリー生成の情報に加え、実際に参照した背景画像・結果画像・BGMのファイル名を
> `game.log` に記録します。
> ログファイルは起動を重ねるごとに追記されますので、不要になった場合は削除していただいて問題ありません。

---

## 動作環境

### 必須

-   [Ollama](https://ollama.com/)
-   Ollamaにダウンロード済みの対応モデル

実行ファイル版ではPythonは不要です。Pythonソース版を使用する場合は、Python
3.10以上を推奨します。

### 音声読み上げを使用する場合

-   [VOICEVOX](https://voicevox.hiroshiba.jp/)
-   音声を再生できる環境

VOICEVOXは任意です。起動していない場合でも、音声なしでゲームを遊べます。

本アプリは、ローカル環境で動作するOllama APIおよびVOICEVOX
ENGINEを利用します。

> \[!NOTE\]
> 本ソフトウェアは、同名または類似名称の既存の商標・製品・サービスとは関係ありません。

---

## 必要なPythonライブラリ

この項目は、Pythonソース版から起動する場合に必要です。実行ファイル版では、別途インストールする必要はありません。

次の外部ライブラリを使用します。

``` bash
python -m pip install requests pygame
```

-   `requests`：Ollama APIおよびVOICEVOX ENGINEとの通信
-   `pygame`：VOICEVOX音声、BGM、効果音の再生

`tkinter`はPythonの標準GUIライブラリです。環境によっては、Pythonとは別にTcl/Tk関連パッケージの導入が必要になる場合があります。

---

## セットアップ

### 1. Ollamaをインストールする

[Ollama公式サイト](https://ollama.com/)からインストールしてください。

### 2. 使用するモデルをダウンロードする

初期モデルは、`data/game_settings.json`で次のように設定されています。

``` text
gemma3:4b
```

ダウンロード例：

``` bash
ollama pull gemma3:4b
```

ほかのOllama対応モデルも使用できます。ただし、JSON形式の指示に安定して応答でき、日本語の文章生成に向いたモデルを推奨します。

### 3. VOICEVOXを準備する（任意）

音声読み上げを使用する場合は、VOICEVOXをインストールし、本アプリより先に起動してください。

-   [VOICEVOX公式サイト](https://voicevox.hiroshiba.jp/)
-   [VOICEVOX GitHub](https://github.com/VOICEVOX/voicevox)

本アプリにVOICEVOX本体は含まれていません。

### 4. アプリを起動する

#### 実行ファイル版から起動する

1.  GitHub ReleasesからWindows版のZIPファイルをダウンロードします。
2.  ZIPファイルを任意の場所へ展開します。
3.  Ollamaを起動します。
4.  音声読み上げを使用する場合は、VOICEVOXも起動します。
5.  展開したフォルダ内の `綴り文庫室.exe` をダブルクリックします。

``` text
綴り文庫室/
├─ 綴り文庫室.exe
└─ _internal/
```

> \[!IMPORTANT\]
> `綴り文庫室.exe`だけを別の場所へ移動せず、`_internal`フォルダと同じ配布フォルダ内で起動してください。

実行ファイル版では、PythonおよびPythonライブラリを別途インストールする必要はありません。ただし、物語生成にはOllamaとダウンロード済みモデルが必要です。VOICEVOXは任意です。

初回起動時にWindowsやセキュリティソフトの確認画面が表示される場合があります。配布元とファイルを確認したうえで実行してください。

#### Pythonソース版から起動する

リポジトリのフォルダで次のコマンドを実行します。

``` bash
python main.py
```

WindowsのPython Launcherを使用する場合：

``` bash
py main.py
```

---

## 実行ファイルの作成（開発者向け）

Windows向け実行ファイルは、PyInstallerの`onedir`形式で作成します。`onedir`形式では、実行ファイルと必要なライブラリが1つのフォルダへまとめられます。

### 1. PyInstallerをインストールする

``` bash
python -m pip install pyinstaller
```

WindowsのPython Launcherを使用する場合：

``` bash
py -m pip install pyinstaller
```

インストール確認：

``` bash
python -m PyInstaller --version
```

### 2. 古いビルド結果を削除する

コマンドプロンプトでプロジェクトフォルダへ移動し、次を実行します。

``` bat
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
del "綴り文庫室.spec" 2>nul
```

### 3. `onedir`形式でビルドする

``` bat
python -m PyInstaller --clean --noconfirm --onedir --windowed --name "綴り文庫室" --icon "icon.ico" --add-data "data;data" --add-data "assets;assets" main.py
```

主なオプション：

| オプション         | 内容                                     |
| ------------- | -------------------------------------- |
| `--clean`     | PyInstallerの一時キャッシュを削除してからビルドします       |
| `--noconfirm` | 既存の出力フォルダを確認なしで置き換えます                  |
| `--onedir`    | 実行ファイルと依存ファイルを1つのフォルダへ出力します            |
| `--windowed`  | 起動時にコンソール画面を表示しません                     |
| `--name`      | 出力するアプリ名を指定します                         |
| `--icon`      | Windows実行ファイルへ使用するICOアイコンを指定します        |
| `--add-data`  | `data`や`assets`など、実行時に必要なファイルを配布物へ含めます |

このビルドでは、次の2つのフォルダを配布物へ含めています。

* `data`：ゲーム設定ファイルなど
* `assets`：背景画像、結果画面画像、BGM・効果音用フォルダなど

> \[!NOTE\]
> Windowsでは`--add-data`のコピー元とコピー先をセミコロン`;`で区切ります。

### 4. 出力を確認する

ビルドに成功すると、次のフォルダが作成されます。

``` text
dist/
└─ 綴り文庫室/
   ├─ 綴り文庫室.exe
   └─ _internal/
```

配布するときは、`dist/綴り文庫室/`をフォルダごとZIP形式へ圧縮します。実行ファイルだけを取り出して配布しないでください。

### Device Guardで`pyinstaller.exe`がブロックされる場合

環境によっては、`pyinstaller`コマンドを直接実行すると、Device
Guardによって`pyinstaller.exe`がブロックされることがあります。その場合は、Pythonからモジュールとして実行します。

``` bash
python -m PyInstaller --version
```

本READMEのビルドコマンドも、この方式を使用しています。

### アイコンがすぐに変わらない場合

Windowsのアイコンキャッシュに古い表示が残ることがあります。実行ファイルや配布フォルダの名前を一時的に変更する、別の場所へコピーする、またはエクスプローラーを再起動すると、新しいアイコンが表示される場合があります。

---

## ファイル構成

``` text
プロジェクトフォルダ/
├─ main.py
├─ game_engine.py
├─ game_prompts.py
├─ llm_client.py
├─ voicevox_client.py
├─ audio_mixer.py
├─ bgm_manager.py
├─ background_manager.py
├─ icon.ico
├─ data/
│  └─ game_settings.json
├─ assets/
│  ├─ backgrounds/
│  ├─ result_images/
│  ├─ bgm/          ← BGMの用意
│  └─ sfx/          ← 効果音の用意
├─ logs/
├─ voice_cache/
├─ README.md
└─ README_PLAY.md
```

### 主なPythonファイル

-   `main.py`：Tkinter GUI、画面操作、ゲーム進行、画像・音声機能の連携  
-   `game_engine.py`：場面生成、選択結果、BAD END、GOOD END、再挑戦、要約    
-   `game_prompts.py`：AI生成用プロンプト、背景タグ、BGMタグの定義  
-   `llm_client.py`：Ollama APIとの通信、モデル一覧取得、生成キャンセル  
-   `voicevox_client.py`：VOICEVOX  
    ENGINEとの通信、音声生成・再生・キャッシュ管理  
-   `audio_mixer.py`：VOICEVOX、BGM、SEが干渉しにくいようpygame mixerを管理  
-   `bgm_manager.py`：BGMタグから音源を選択し、ループ・フェード・音量を管理  
-   `background_manager.py`：背景タグに対応する画像候補の検索・ランダム選択を管理  

### 素材フォルダ

`assets/backgrounds/`
には背景画像を配置します。同じタグ名のサブフォルダへ複数画像を追加できるため、画像数を増やす場合でもPythonコードの変更を最小限にできます。

`assets/result_images/` にはタイトル画面やGAME
CLEARなど、ゲーム進行に使用する固定画像を配置します。

`assets/bgm/` と `assets/sfx/`
は音源配置用です。**本リポジトリ／配布物には音源を収録していません。**
利用者自身が使用権を持つ音源を用意し、下記の指定ファイル名へ変更して配置してください。
**※ BGMと効果音は、配置していなくても起動できます。**  
`logs/` は `game.log` の保存先、`voice_cache/`
はVOICEVOXで生成した一時音声の保存先です。

---

## 設定ファイル

`data/game_settings.json`の主な初期値は次のとおりです。

  -----------------------------------------------------------------------------------------------------------------
  設定                                                  初期値 内容
  ------------------------------- ---------------------------- ----------------------------------------------------
  `game.total_scenes`                                      `5` 1ゲームの場面数

  `game.max_retries`                                       `3` AI生成データの取得・解析に失敗した場合の再試行上限

  `game.summary_max_characters`                          `100` 次の場面へ引き継ぐ物語要約の最大文字数

  `ollama.base_url`                   `http://localhost:11434` Ollama APIの接続先

  `ollama.default_model`                           `gemma3:4b` 初期選択モデル

  `ollama.timeout_seconds`                               `120` Ollama通信のタイムアウト秒数

  `voicevox.base_url`                 `http://127.0.0.1:50021` VOICEVOX ENGINEの接続先

  `voicevox.speaker_id`                                    `3` 初期話者ID

  `voicevox.volume`                                      `1.0` VOICEの初期音量

  `sfx.volume`                                           `0.2` SEの初期音量

  `bgm.volume`                                           `0.2` BGMの初期音量

  `bgm.fade_ms`                                          `800` BGM切り替え時のフェード時間（ミリ秒）
  -----------------------------------------------------------------------------------------------------------------

---

## BGM・効果音について

v2はBGMと効果音の再生機能を備えていますが、**音源ファイル自体は本リポジトリ／配布物へ収録していません。**

利用する場合は、利用者自身が権利・利用条件を確認した音源を用意し、次のファイル名へ変更して配置してください。音源が見つからない場合でも、ゲーム本体・背景表示・VOICEVOXは継続して利用できます。

### BGM

配置先：

``` text
assets/bgm/
```

通常はMP3を使用します。OGGも第2候補として読み込みます。  

  ファイル名         用途  
  ------------------ --------------------
  `title.mp3`        タイトル画面  
  `calm.mp3`         静か・穏やかな場面  
  `bright.mp3`       明るい・楽しい場面  
  `mystery.mp3`      謎・調査・違和感  
  `tension.mp3`      緊迫・追跡・危機  
  `battle.mp3`       戦闘・対決  
  `sad.mp3`          悲しみ・別れ  
  `horror.mp3`       怪異・恐怖  
  `ending.mp3`       エピローグ  
  `game_clear.mp3`   GAME CLEAR以降  

たとえば、手元の音源 `my_calm_music.mp3`  
を穏やかな場面で使いたい場合は、`calm.mp3` に名前を変更して  
`assets/bgm/` へ配置します。  

### 効果音（SE） 

配置先：  

``` text
assets/sfx/
```

  ファイル名       用途  
  ---------------- ----------------------
  `correct.mp3`    正しい選択をしたとき  
  `bad_end.mp3`    BAD END  
  `good_end.mp3`   GOOD END  

### 音源の権利について  

本プロジェクトは、利用者が追加した音源の利用許諾を提供するものではありません。第三者が制作した音源を使用する場合は、各音源のライセンス、利用規約、クレジット表記、再配布可否などを必ず確認してください。  

特に、本アプリを再配布・配信・動画投稿などに使用する場合は、使用する音源がその用途を許可しているかをご自身で確認してください。  

---

## 収録ジャンル

v2の初期設定には、次の30ジャンルが登録されています。

* 王道ファンタジー
* 恋愛告白
* 明るいミステリー
* 怪談
* モンスターサバイバル
* 宇宙SF
* 異世界転生
* 刑事ドラマ
* シリアスドラマ
* コメディ
* ゾンビパニック
* 青春部活
* 無人島サバイバル
* 探検隊
* 海賊冒険
* 忍者
* スパイアクション
* タイムトラベル
* 昭和レトロ冒険
* 法廷ドラマ
* お仕事体験
* 学園七不思議
* 西部劇
* 日常の不思議
* 旅情ドラマ
* 時代劇
* 探偵ミステリー
* 料理チャレンジ
* 格闘アクション
* ラブコメ

ジャンル名と説明は、`data/game_settings.json`の`genres`から追加・編集できます。

---

## 背景画像とBGMタグ

v2では、各Sceneの生成結果に `background_tag` と `bgm_tag` が含まれます。

`background_tag`
は「現在いる場所」を表し、`room`、`forest`、`school`、`cafe`、`spaceship_bridge`
などの候補からAIが選択します。アプリはタグに対応する画像を
`assets/backgrounds/` から探して表示します。

同じタグに複数画像を登録する場合は、タグ名のサブフォルダを使用できます。

``` text
assets/backgrounds/cafe/
├─ quiet_interior_01.jpg
├─ retro_kissaten_01.jpg
└─ window_seating_02.jpg
```

複数候補がある場合は、直前に使用した画像をできるだけ避けながら候補を選択します。画像データをすべて起動時に読み込む方式ではないため、背景画像を100枚以上へ増やすことも想定した構成です。

`bgm_tag` は場所ではなく場面の雰囲気を表します。通常Sceneでは
`calm`、`bright`、`mystery`、`tension`、`battle`、`sad`、`horror`
からAIが選択し、対応する音源が存在する場合だけ再生します。

タイトル・エピローグ・GAME CLEARでは、ゲーム進行側がそれぞれ
`title`、`ending`、`game_clear` を使用します。

---

## タイピング表示と音声の同期

本文は1文字ずつ表示され、句読点や改行では少し長めの間を取ります。

-   表示中にEnterキーを押すと、その文章をすぐに全文表示します。
-   本文の表示が完了するまで、選択肢の決定操作は無効です。
-   VOICEVOX読み上げがONの場合は、最初の音声チャンクが完成してからタイピング表示と音声再生を開始します。
-   後続の音声は、本文生成と並行して準備されます。

待機中は、「物語を生成しています」のメッセージが、点の増減する簡単なアニメーション付きで表示されます。

---

## BAD ENDと再挑戦

誤った選択肢を選ぶと、その場面の流れに沿ったBAD ENDが表示されます。

「直前の選択肢へ」を選ぶと、同じ場面、本文、選択肢へ戻ります。場面をAIで再生成しないため、直前の状況を保ったまま別の選択を試せます。

「最初から」を選ぶと、最初の場面から新しいゲームを開始できます。

---

## GOOD END後の追加生成

5場面目で正しい選択肢を選ぶと、通常のGOOD
ENDに続いて、次の内容を追加生成します。

1. 最終選択の結果
2. GOOD END
3. エピローグ
4. ゲームクリアメッセージ
5. AI COMMENT
6. プレイ記録


追加生成に失敗した場合でも、固定のエピローグとメッセージを表示してゲームを終了できるようにしています。

---

## VOICEVOXについて

本アプリは、音声合成ソフトウェアVOICEVOXおよびローカルで動作するVOICEVOX
ENGINEを利用します。

-   読み上げのON／OFF
-   話者IDの指定
-   生成済み音声の順次再生
-   読み上げの途中停止
-   一時WAVファイルの自動管理
-   VOICEVOX未起動時のテキストのみでの続行

> \[!IMPORTANT\]
> 生成した音声を公開・配布する場合は、VOICEVOX本体と使用したキャラクター（話者）の利用規約・クレジット表記をご確認ください。

---

## 既知の制限事項

-   AI生成のため、文章の品質、展開、固有名詞、選択肢の自然さにはばらつきがあります。
-   使用モデルによっては、指定したJSON形式を正しく返せず、生成を再試行する場合があります。
-   PC性能やモデルサイズによって、場面生成に時間がかかります。
-   VOICEVOXの初回音声生成や長い文章では、読み上げ開始まで待ち時間が発生する場合があります。
-   読み上げ停止後も、VOICEVOX ENGINEへ送信済みの処理が一時的に継続する場合があります。停止後に完成した音声は再生されません。
-   OllamaまたはVOICEVOXの接続先を変更している場合は、`data/game_settings.json`の設定変更が必要です。
-   BGM・効果音は同梱していません。使用する場合は利用者側で指定ファイル名の音源を用意する必要があります。
-   背景画像や音源が不足していても可能な範囲でゲームを続行しますが、その素材に対応する演出は行われません。

---

## 開発について

本プロジェクトの制作にあたり、OpenAIの対話型AI「ChatGPT」のサポートを受け、アイデア出し、コード設計、実装、検証、文章表現の改善などを行いました。

使用した主なモデル・プラン：

-   GPT-5.6（Chat・Work）
-   ChatGPT Plus

主な利用内容は以下のとおりです。

-   開発計画・設計方針の整理（Chat・Work）
-   アプリ全体の構成検討（Chat・Work）
-   Pythonコードの実装支援（Chat・Work）
-   リファクタリングおよび改善提案（Chat）
-   README・ドキュメントの作成支援（Chat・Work）
-   プロンプト設計・改善（Chat）
-   ゲーム仕様のアイデア出し（Chat）
-   ストーリー構成のアイデア出し（Chat・Work）
-   不具合調査および原因分析（Chat・Work）
-   画像生成、画像の追加（Chat・Work）
-   画像と音源へのタグ付け（Work）

最終的な設計・実装・動作確認・公開判断は開発者本人が行っています。

開発に携わったすべての研究者、開発者、関係者の皆様に、心より感謝申し上げます。

### 制作期間

-   **綴り文庫室 v1：2026年7月26日 ~ 2026年7月29日**
-   **綴り文庫室 v2：2026年7月30日 ~ 2026年8月8日**

---

## コントリビューションについて

本リポジトリは個人学習・個人制作を目的としています。そのため、Pull
Request（PR）はお受けできません。ご了承ください。

---

## 注意事項

本アプリの物語、選択肢、エンディング、AI
COMMENTは、ローカルLLMによって自動生成されます。

出力内容の正確性、安全性、完全性は保証されません。実在する人物、団体、場所、出来事などと似た内容が生成された場合でも、原則として偶然によるものです。

各Ollamaモデルの利用条件については、モデル提供元のライセンスをご確認ください。

---

## 免責事項

本アプリの利用、設定変更、外部ソフトウェアとの連携、生成された文章や音声の使用などによって生じた損害、不具合、データ損失その他の問題について、作者は責任を負いません。

利用者自身の責任においてご使用ください。

---

## このプロジェクトのライセンス

本プロジェクトでは、アプリケーションコードとプロンプト・画像などのコンテンツに異なるライセンスを設定しています。

### アプリケーションコード

* **ライセンス：MIT License**
* 商用利用：可能
* 改変：可能
* 再配布：可能

著作権表示とライセンス文の同梱が必要です。詳細は、[LICENSE-CODE](./licenses/application/LICENSE-CODE.txt)をご確認ください。

クレジット例：

```text
Code by AglaoDev-jp © 2026, licensed under the MIT License.
```

### アイコン

本プロジェクトに含まれるアプリアイコンは、MIT Licenseを適用します。

* **ライセンス：MIT License**
* 商用利用：可能
* 改変：可能
* 再配布：可能

著作権表示とライセンス文の同梱が必要です。

クレジット例：

```text
App icon by AglaoDev-jp © 2026, licensed under the MIT License.
```

### プロンプト関連データ

ジャンル説明やゲーム生成用プロンプトには、Creative Commons Attribution
4.0 International（CC BY 4.0）を適用します。

* 商用利用：可能
* 改変：可能
* 再配布：可能
* クレジット表記：必要

詳細は、[LICENSE-PROMPT](./licenses/application/LICENSE-PROMPT.txt)をご確認ください。

クレジット例：

```text
Prompt Collection by AglaoDev-jp
Licensed under CC BY 4.0
```

### 画像素材

本プロジェクトに含まれる背景画像やゲーム内表示用画像には、Creative Commons Attribution
4.0 International（CC BY 4.0）を適用します。

* **ライセンス：CC BY 4.0**
* 商用利用：可能
* 改変：可能
* 再配布：可能
* クレジット表記：必要

詳細は、[LICENSE-IMAGE](./licenses/application/LICENSE-IMAGE.txt)をご確認ください。

クレジット例：

```text
Image Collection by AglaoDev-jp
Licensed under CC BY 4.0
```

---

※ BGM・効果音など、利用者が別途用意する外部素材には、それぞれの素材提供元が定めるライセンスが適用されます。

---

## 第三者ソフトウェアの著作権・ライセンス

### ライセンスファイル一覧

-   [Python License](./licenses/LICENSE-PSF.txt)
-   [Tcl/Tk License](./licenses/third_party/LICENSE-TclTk.txt)
-   [Pygame LGPL v2.1](./licenses/third_party/LGPL_v2.1.txt)
-   [Requests Apache License 2.0](./licenses/third_party/requests_LICENSE.txt)
-   [Requests NOTICE](./licenses/third_party/requests_NOTICE.txt)

### Python

-   Copyright © 2001 Python Software Foundation. All rights reserved.
-   Licensed under the PSF License Version 2.
-   [Python 公式ライセンス](https://docs.python.org/3/license.html)

### Tkinter / Tcl/Tk

Tkinter は Python に含まれる GUI ライブラリですが、その動作には Tcl/Tk
が使用されています。

-   [Tcl/Tk License](https://www.tcl.tk/software/tcltk/license.html)

### Pygame

-   License: LGPL v2.1
-   [ライセンスファイル](./licenses/third_party/LGPL_v2.1.txt)

### Requests

-   License: Apache License 2.0
-   [ライセンスファイル](./licenses/third_party/requests_LICENSE.txt)
-   [NOTICE](./licenses/third_party/requests_NOTICE.txt)

### 外部ソフトウェア

-   [Ollama](https://ollama.com/)
-   [VOICEVOX](https://voicevox.hiroshiba.jp/)

これらのプロジェクトの開発者、貢献者、関係者の皆様に、心より感謝申し上げます。

---

© 2026 AglaoDev-jp
