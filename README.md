# 綴り文庫室 v1  

**"AIが紡ぐ、新しい物語。選択肢で変える、あなただけの結末。"**  

**音声とともに楽しむ、AI生成テキストアドベンチャーゲーム。**  

「**綴り文庫室（つづりぶんこしつ）**」は、選択したジャンルに合わせてローカルLLMが毎回新しい物語を生成する、短編テキストアドベンチャーゲームです。  
プレイヤーの選択によって物語は変化し、VOICEVOXによる音声読み上げとともに、自分だけの物語を楽しめます。  

本アプリは、ローカル環境で動作する **Ollama API** および **VOICEVOX ENGINE** を利用します。  

本リポジトリでは、アプリケーションのソースコードおよび実行ファイルを公開しています。

全5場面の物語を進み、各場面で表示される `a`・`b` の二択から行動を選びます。片方は物語が続く選択肢、もう片方はその場で結末を迎えるBAD ENDです。  
最後の正しい選択までたどり着くと、GOOD ENDに加えて、エピローグやプレイ内容に応じたAIコメントが生成されます。  

詳しい準備と操作方法は、[利用マニュアル](./README_PLAY.md)をご確認ください。  
- 実行ファイルのダウンロードはこちら：[Releases](https://github.com/AglaoDev-jp/tsuzuri-bunkoshitsu/releases/download/v1/_v1.zip)   

> [!NOTE]
> 本READMEは、アプリのソースコードおよび仕様をもとに、OpenAIの対話型AI「ChatGPT」の支援を受けて草案を作成し、作者が内容の確認・編集を行っています。
> 本ソフトウェアは、同名または類似名称の既存の商標・製品・サービスとは関係ありません。

---

## ガイドライン

ゲームプレイ・配信・二次創作等については、
[GUIDELINE.md](./GUIDELINE.md)   をご確認ください。

---

## 主な機能

- Ollamaを利用したローカルAIストーリー生成
- 24種類のジャンルから物語を選択
- 全5場面で構成される短編テキストアドベンチャー
- 各場面に必ず `a`・`b` の二択を表示
- 正しい選択で次の場面へ進行
- 誤った選択で、その場面に対応したBAD ENDを生成
- BAD END後に「直前の選択肢へ」戻って再挑戦
- 「最初から」によるゲームの再スタート
- 本文を1文字ずつ表示するタイピングエフェクト
- タイピング中のEnterキーによる全文即時表示
- タイピング完了後に選択操作を有効化
- Ollamaにインストールされているモデル一覧の取得・更新
- ThinkingモードのON／OFF切り替え（対応モデルのみ）
- VOICEVOXによる文章の順次読み上げ
- VOICEVOXの話者ID指定
- 読み上げの途中停止
- 一時音声キャッシュの自動管理
- クリア後のエピローグ、クリアメッセージ、プレイ記録、AI COMMENT

---

## ゲームの流れ

1. ジャンルとOllamaモデルを選びます。
2. 「ゲーム開始」を押すと、AIが最初の場面を生成します。
3. 本文と `a`・`b` の選択肢を読み、どちらかを入力します。
4. 正解なら次の場面へ進み、不正解ならBAD ENDになります。
5. BAD END後は、同じ場面を生成し直さずに「直前の選択肢へ」戻れます。
6. 5場面目の正解でGOOD ENDとなり、追加のエンディング演出が生成されます。

ストーリーはプレイごとにAIが生成するため、同じジャンルでも登場人物や展開が変化します。

---

> **ログファイルについて**
>
> 現在はデバッグやプレイ内容の確認のため、`game.log` にゲーム進行の情報を記録しています。
> 本アプリは、動作状況やAIによるストーリー生成の情報を `game.log` に記録します。
> ログファイルは起動を重ねるごとに追記されますので、不要になった場合は削除していただいて問題ありません。

---

## 動作環境

### 必須

- [Ollama](https://ollama.com/)
- Ollamaにダウンロード済みの対応モデル

実行ファイル版ではPythonは不要です。Pythonソース版を使用する場合は、Python 3.10以上を推奨します。

### 音声読み上げを使用する場合

- [VOICEVOX](https://voicevox.hiroshiba.jp/)
- 音声を再生できる環境

VOICEVOXは任意です。起動していない場合でも、音声なしでゲームを遊べます。

本アプリは、ローカル環境で動作するOllama APIおよびVOICEVOX ENGINEを利用します。

> [!NOTE]
> 本ソフトウェアは、同名または類似名称の既存の商標・製品・サービスとは関係ありません。

---

## 必要なPythonライブラリ

この項目は、Pythonソース版から起動する場合に必要です。実行ファイル版では、別途インストールする必要はありません。

次の外部ライブラリを使用します。

```bash
python -m pip install requests pygame
```

- `requests`：Ollama APIおよびVOICEVOX ENGINEとの通信
- `pygame`：VOICEVOXで生成したWAV音声の再生

`tkinter`はPythonの標準GUIライブラリです。環境によっては、Pythonとは別にTcl/Tk関連パッケージの導入が必要になる場合があります。

---

## セットアップ

### 1. Ollamaをインストールする

[Ollama公式サイト](https://ollama.com/)からインストールしてください。

### 2. 使用するモデルをダウンロードする

初期モデルは、`data/game_settings.json`で次のように設定されています。

```text
gemma3:4b
```

ダウンロード例：

```bash
ollama pull gemma3:4b
```

ほかのOllama対応モデルも使用できます。ただし、JSON形式の指示に安定して応答でき、日本語の文章生成に向いたモデルを推奨します。

### 3. VOICEVOXを準備する（任意）

音声読み上げを使用する場合は、VOICEVOXをインストールし、本アプリより先に起動してください。

- [VOICEVOX公式サイト](https://voicevox.hiroshiba.jp/)
- [VOICEVOX GitHub](https://github.com/VOICEVOX/voicevox)

本アプリにVOICEVOX本体は含まれていません。

### 4. アプリを起動する

#### 実行ファイル版から起動する

1. GitHub ReleasesからWindows版のZIPファイルをダウンロードします。
2. ZIPファイルを任意の場所へ展開します。
3. Ollamaを起動します。
4. 音声読み上げを使用する場合は、VOICEVOXも起動します。
5. 展開したフォルダ内の `綴り文庫室.exe` をダブルクリックします。

```text
綴り文庫室/
├─ 綴り文庫室.exe
└─ _internal/
```

> [!IMPORTANT]
> `綴り文庫室.exe`だけを別の場所へ移動せず、`_internal`フォルダと同じ配布フォルダ内で起動してください。  

> 実行ファイル版では、PythonおよびPythonライブラリを別途インストールする必要はありません。  
> ただし、物語生成にはOllamaとダウンロード済みモデルが必要です。  
> VOICEVOXは任意です。  

> 初回起動時にWindowsやセキュリティソフトの確認画面が表示される場合があります。配布元とファイルを確認したうえで実行してください。  

#### Pythonソース版から起動する

リポジトリのフォルダで次のコマンドを実行します。

```bash
python main.py
```

WindowsのPython Launcherを使用する場合：

```bash
py main.py
```

---

## 実行ファイルの作成（開発者向け）

Windows向け実行ファイルは、PyInstallerの`onedir`形式で作成します。`onedir`形式では、実行ファイルと必要なライブラリが1つのフォルダへまとめられます。

### 1. PyInstallerをインストールする

```bash
python -m pip install pyinstaller
```

WindowsのPython Launcherを使用する場合：

```bash
py -m pip install pyinstaller
```

インストール確認：

```bash
python -m PyInstaller --version
```

### 2. 古いビルド結果を削除する（失敗したときなど）

コマンドプロンプトでプロジェクトフォルダへ移動し、次を実行します。

```bat
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
del "綴り文庫室.spec" 2>nul
```

### 3. `onedir`形式でビルドする

```bat
python -m PyInstaller --clean --noconfirm --onedir --windowed --name "綴り文庫室" --icon "icon.ico" --add-data "data;data" main.py
```

主なオプション：

| オプション | 内容 |
| --- | --- |
| `--clean` | PyInstallerの一時キャッシュを削除してからビルドします |
| `--noconfirm` | 既存の出力フォルダを確認なしで置き換えます |
| `--onedir` | 実行ファイルと依存ファイルを1つのフォルダへ出力します |
| `--windowed` | 起動時にコンソール画面を表示しません |
| `--name` | 出力するアプリ名を指定します |
| `--icon` | Windows実行ファイルへ使用するICOアイコンを指定します |
| `--add-data` | `data`フォルダを配布物へ含めます |

> [!NOTE]
> Windowsでは`--add-data`のコピー元とコピー先をセミコロン`;`で区切ります。

### 4. 出力を確認する

ビルドに成功すると、次のフォルダが作成されます。

```text
dist/
└─ 綴り文庫室/
   ├─ 綴り文庫室.exe
   └─ _internal/
```

配布するときは、`dist/綴り文庫室/`をフォルダごとZIP形式へ圧縮します。実行ファイルだけを取り出して配布しないでください。

### Device Guardで`pyinstaller.exe`がブロックされる場合

環境によっては、`pyinstaller`コマンドを直接実行すると、Device Guardによって`pyinstaller.exe`がブロックされることがあります。その場合は、Pythonからモジュールとして実行します。

```bash
python -m PyInstaller --version
```

本READMEのビルドコマンドも、この方式を使用しています。

### アイコンがすぐに変わらない場合

Windowsのアイコンキャッシュに古い表示が残ることがあります。実行ファイルや配布フォルダの名前を一時的に変更する、別の場所へコピーする、またはエクスプローラーを再起動すると、新しいアイコンが表示される場合があります。

---

## ファイル構成

```text
プロジェクトフォルダ/
├─ main.py
├─ game_engine.py
├─ game_prompts.py
├─ llm_client.py
├─ voicevox_client.py
├─ data/
│  └─ game_settings.json
├─ logs/
├─ voice_cache/
├─ README.md
└─ README_PLAY.md
```

### `main.py`

TkinterによるGUI、画面操作、タイピング表示、ゲーム進行と各機能の連携を担当する起動スクリプトです。

### `game_engine.py`

場面生成、選択結果、BAD END、GOOD END、再挑戦、物語要約などのゲーム進行を管理します。

### `game_prompts.py`

場面、選択肢、要約、エンディングをAIに生成させるためのプロンプトを定義します。

### `llm_client.py`

Ollama APIとの通信、モデル一覧の取得、ストーリー生成結果の受信を担当します。

### `voicevox_client.py`

VOICEVOX ENGINEとの通信、文章分割、音声生成、再生、一時音声キャッシュを管理します。

### `data/game_settings.json`

場面数、OllamaとVOICEVOXの接続先、初期モデル、話者ID、ジャンルなどを設定します。

### `logs/`

アプリのログを保存するためのフォルダです。存在しない場合は実行時に作成されます。

### `voice_cache/`

VOICEVOXで生成した一時WAVファイルの保存先です。アプリによって自動管理されます。

---

## 設定ファイル

`data/game_settings.json`の主な初期値は次のとおりです。

| 設定 | 初期値 | 内容 |
| --- | ---: | --- |
| `game.total_scenes` | `5` | 1ゲームの場面数 |
| `game.max_retries` | `3` | AI生成データの取得・解析に失敗した場合の再試行上限 |
| `game.summary_max_characters` | `100` | 次の場面へ引き継ぐ物語要約の最大文字数 |
| `ollama.base_url` | `http://localhost:11434` | Ollama APIの接続先 |
| `ollama.default_model` | `gemma3:4b` | 初期選択モデル |
| `ollama.timeout_seconds` | `120` | Ollama通信のタイムアウト秒数 |
| `voicevox.base_url` | `http://127.0.0.1:50021` | VOICEVOX ENGINEの接続先 |
| `voicevox.speaker_id` | `3` | 初期話者ID |

---

## 収録ジャンル

v1の初期設定には、次の24ジャンルが登録されています。

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
- ホテル脱出コメディ
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

ジャンル名と説明は、`data/game_settings.json`の`genres`から追加・編集できます。

---

## タイピング表示と音声の同期

本文は1文字ずつ表示され、句読点や改行では少し長めの間を取ります。

- 表示中にEnterキーを押すと、その文章をすぐに全文表示します。
- 本文の表示が完了するまで、選択肢の決定操作は無効です。
- VOICEVOX読み上げがONの場合は、最初の音声チャンクが完成してからタイピング表示と音声再生を開始します。
- 後続の音声は、本文生成と並行して準備されます。

待機中は、「物語を生成しています」のメッセージが、点の増減する簡単なアニメーション付きで表示されます。

---

## BAD ENDと再挑戦

誤った選択肢を選ぶと、その場面の流れに沿ったBAD ENDが表示されます。  

「直前の選択肢へ」を選ぶと、同じ場面、本文、選択肢へ戻ります。場面をAIで再生成しないため、直前の状況を保ったまま別の選択を試せます。  

「最初から」を選ぶと、最初の場面から新しいゲームを開始できます。  

---

## GOOD END後の追加生成

5場面目で正しい選択肢を選ぶと、通常のGOOD ENDに続いて、次の内容を追加生成します。  

- 物語を締めくくるエピローグ
- ゲームクリアを祝う短いメッセージ
- バッドエンド到達回数
- 「直前の選択肢へ」戻った回数
- 総選択回数
- プレイ記録から判定した攻略の様子
- プレイヤーへのAI COMMENT

追加生成に失敗した場合でも、固定のエピローグとメッセージを表示してゲームを終了できるようにしています。

---

## VOICEVOXについて

本アプリは、音声合成ソフトウェアVOICEVOXおよびローカルで動作するVOICEVOX ENGINEを利用します。  

- 読み上げのON／OFF
- 話者IDの指定
- 生成済み音声の順次再生
- 読み上げの途中停止
- 一時WAVファイルの自動管理
- VOICEVOX未起動時のテキストのみでの続行

> [!IMPORTANT]
> 生成した音声を公開・配布する場合は、VOICEVOX本体と使用したキャラクター（話者）の利用規約・クレジット表記をご確認ください。

---

## 既知の制限事項

- AI生成のため、文章の品質、展開、固有名詞、選択肢の自然さにはばらつきがあります。
- 使用モデルによっては、指定したJSON形式を正しく返せず、生成を再試行する場合があります。
- PC性能やモデルサイズによって、場面生成に時間がかかります。
- VOICEVOXの初回音声生成や長い文章では、読み上げ開始まで待ち時間が発生する場合があります。
- 読み上げ停止後も、VOICEVOX ENGINEへ送信済みの処理が一時的に継続する場合があります。停止後に完成した音声は再生されません。
- OllamaまたはVOICEVOXの接続先を変更している場合は、`data/game_settings.json`の設定変更が必要です。

---

## 開発について

本プロジェクトの制作にあたり、OpenAIの対話型AI「ChatGPT」のサポートを受け、アイデア出し、コード設計、実装、検証、文章表現の改善などを行いました。

使用した主なモデル・プラン：

- GPT-5.6（Chat・Work）
- ChatGPT Plus

主な利用内容は以下のとおりです。

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

- **綴り文庫室 v1：2026年7月26日 ~ 2026年7月29日**

---

## コントリビューションについて

本リポジトリは個人学習・個人制作を目的としています。そのため、Pull Request（PR）はお受けできません。ご了承ください。

---

## 注意事項

本アプリの物語、選択肢、エンディング、AI COMMENTは、ローカルLLMによって自動生成されます。

出力内容の正確性、安全性、完全性は保証されません。実在する人物、団体、場所、出来事などと似た内容が生成された場合でも、原則として偶然によるものです。

各Ollamaモデルの利用条件については、モデル提供元のライセンスをご確認ください。

---

## 免責事項

本アプリの利用、設定変更、外部ソフトウェアとの連携、生成された文章や音声の使用などによって生じた損害、不具合、データ損失その他の問題について、作者は責任を負いません。

利用者自身の責任においてご使用ください。

---

## このプロジェクトのライセンス

本プロジェクトでは、アプリケーションコード、アイコン、およびプロンプト関連データに、それぞれ次のライセンスを適用しています。

### アプリケーションコード

- **ライセンス：MIT License**
- 商用利用：可能
- 改変：可能
- 再配布：可能

著作権表示とライセンス文の同梱が必要です。詳細は、[LICENSE-CODE](./licenses/application/LICENSE-CODE.txt)をご確認ください。

クレジット例：

```text
Code by AglaoDev-jp © 2026, licensed under the MIT License.
```

### アイコン

本プロジェクトに含まれるアプリアイコンは、MIT Licenseを適用します。

- **ライセンス：MIT License**
- 商用利用：可能
- 改変：可能
- 再配布：可能

著作権表示とライセンス文の同梱が必要です。

クレジット例：

```text
App icon by AglaoDev-jp © 2026, licensed under the MIT License.
```

### プロンプト関連データ

ジャンル説明やゲーム生成用プロンプトには、Creative Commons Attribution 4.0 International（CC BY 4.0）を適用します。

- 商用利用：可能
- 改変：可能
- 再配布：可能
- クレジット表記：必要

詳細は、[LICENSE-PROMPT](./licenses/application/LICENSE-PROMPT.txt)をご確認ください。

クレジット例：

```text
Prompt Collection by AglaoDev-jp
Licensed under CC BY 4.0
```

---

## 第三者ソフトウェアの著作権・ライセンス

### ライセンスファイル一覧

- [Python License](./licenses/LICENSE-PSF.txt)
- [Tcl/Tk License](./licenses/third_party/LICENSE-TclTk.txt)
- [Pygame LGPL v2.1](./licenses/third_party/LGPL_v2.1.txt)
- [Requests Apache License 2.0](./licenses/third_party/requests_LICENSE.txt)
- [Requests NOTICE](./licenses/third_party/requests_NOTICE.txt)

### Python

- Copyright © 2001 Python Software Foundation. All rights reserved.
- Licensed under the PSF License Version 2.
- [Python 公式ライセンス](https://docs.python.org/3/license.html)

### Tkinter / Tcl/Tk

Tkinter は Python に含まれる GUI ライブラリですが、その動作には Tcl/Tk が使用されています。

- [Tcl/Tk License](https://www.tcl.tk/software/tcltk/license.html)

### Pygame

- License: LGPL v2.1
- [ライセンスファイル](./licenses/third_party/LGPL_v2.1.txt)

### Requests

- License: Apache License 2.0
- [ライセンスファイル](./licenses/third_party/requests_LICENSE.txt)
- [NOTICE](./licenses/third_party/requests_NOTICE.txt)

### 外部ソフトウェア

- [Ollama](https://ollama.com/)
- [VOICEVOX](https://voicevox.hiroshiba.jp/)

これらのプロジェクトの開発者、貢献者、関係者の皆様に、心より感謝申し上げます。

---


© 2026 AglaoDev-jp
