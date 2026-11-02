# PAN-CAMERA

**選んだ被写体に、カメラがついてくる。**

YOLOの学習済みモデルで人物や物体を認識し、サーボでUSBカメラを左右に旋回させる自動追尾カメラです。M5Stack BASICを手元のモニター兼コントローラーとして使い、被写体の選択、追尾の開始・停止、録画を操作できます。

Physical AI応用編1の最終課題として制作しました。自分を撮影するときのフレーミング補助や、動く物体を画面中央に捉えながら録画する用途を想定しています。

![PAN-CAMERAの構成](docs/assets/architecture.svg)

## できること

- YOLO26nとByteTrackによる、人物・コップなどの検出と追跡。
- 80種類の学習済みクラスから、設定ファイルまたは起動引数で検出対象を選択。
- 画面上で選んだ対象を左右方向に追尾。ずれに応じて補正量を変え、サーボ指令を加減速。
- M5Stackに認識枠付きのプレビューと追尾・録画状態を表示。B長押しでPiアプリを起動・終了。
- 追尾と独立して録画を開始・停止。認識枠付きAVI、M5Stack画面の再現AVI、枠なし映像＋マイク音声のMP4をPiへ同時保存。
- 追尾停止・対象切り替え時の位置保持と、カメラ取得エラー時の終了処理。

## 使用機材と環境

| 項目 | 構成 |
|---|---|
| 計算機 | Raspberry Pi 5 Model B / 8 GB |
| OS | Debian GNU/Linux 12（bookworm）、64 bit / aarch64 |
| カメラ | Arducam 12MP USB Camera、1280×720 MJPEGで使用 |
| 旋回機構 | SG90サーボ、GPIO18のRP1ハードウェアPWM |
| 操作端末 | M5Stack BASIC（ESP32、320×240 LCD） |
| サーボ電源 | MOT-MB10001-BKの低電流モード、PiとGND共通 |
| Pi側ソフトウェア | Python 3.11、uv、Ultralytics、PyTorch CPU、OpenCV |
| M5Stack側 | PlatformIO、Arduino ESP32、M5Unified |

図で確認する：[追尾の流れ](docs/assets/tracking-loop.svg) · [電源と配線](docs/assets/power-wiring.svg) · [固定部と回転部](docs/assets/pan-mechanism.svg)

詳しいバージョンと実測値は[検証結果](docs/validation.md)、配線とPWM準備は[ハードウェア](docs/hardware.md)にまとめています。

## セットアップ

対象は **Raspberry Pi 5・64 bit OS（aarch64）** です。開発環境はDebian 12 / Python 3.11。PWM制御はPi 5のRP1・GPIO18専用のため、Pi 4以前にそのまま移して使うことはできません。同じPi 5でも、カメラ・マイク・ネットワーク・サーボの校正は設置先に合わせます。別の実機での最終動作は未検証です。

### 1. OSのツールとPython環境を用意

```sh
sudo apt update
sudo apt install -y git curl python3 python3-dev python3-venv build-essential ffmpeg alsa-utils v4l-utils
curl -LsSf https://astral.sh/uv/0.13.6/install.sh | sh
. "$HOME/.local/bin/env"
uv tool install --python 3.11 platformio==6.2.0
```

uvは[公式のインストール方法](https://docs.astral.sh/uv/getting-started/installation/)に従います。既に導入済みなら再インストールは不要です。初回はPythonパッケージとESP32のビルドツールをダウンロードするため、インターネット接続と数GB程度の空き容量が必要です。Pi側のGUIは不要です。

### 2. cloneして依存関係を復元

```sh
git clone https://github.com/shotalab/pan-camera.git
cd pan-camera
uv sync --locked
uv run --locked python -m pan_camera --list-classes
```

`.python-version` でPython 3.11を選び、`uv.lock` のバージョンで環境を構築します。モデル `models/yolo26n.pt` もGitに含めているため、別途探す必要はありません。`--list-classes` はモデルを読み込む確認で、カメラやサーボは動かしません。リポジトリのチェックアウトから実行してください。

OpenCVはheadless版に統一し、Ultralyticsの依存から入るGUI版をuvの設定で除外しています。`pip install .` 単体ではこの設定を使えないため、上記の `uv sync --locked` を使用します。既存の仮想環境にGUI版が入っていた場合は、共有ファイルを復元するため `uv sync --locked --reinstall-package opencv-python-headless` を実行してください。

### 3. 配線とデバイスの準備

[ハードウェア手順](docs/hardware.md#pwmの準備)に従って、外部電源・共通GND、GPIO18、PWMオーバーレイ、ユーザー権限を設定します。OS設定後の再起動やグループへの再ログインも必要です。サーボの校正範囲は `config/servo.toml` で確認します。

```sh
v4l2-ctl --list-devices
arecord -l
pio device list
```

- `config/recording.toml`：`camera_device` をカメラ番号または `/dev/v4l/by-id/…` に、`audio_device` を使用するALSAマイクに合わせる。既定はカメラ0とArducamのCameraカード。マイクを使わない場合は `raw_enabled = false`。
- `config/network.toml`：`m5stack_ip` を設置先のM5StackのIPへ変更する。初期値は開発環境の値。
- `config/detection.toml`：標準はコップのみ。人物などを追加する場合は該当項目を有効にする。

### 4. M5Stackへ書き込む

```sh
cp firmware/m5stack/include/wifi_secrets.example.h firmware/m5stack/include/wifi_secrets.h
```

`wifi_secrets.h` に設置先のSSID・パスワードを設定します。既に設定済みの場合はコピーを省きます。このファイルはGit管理対象外です。

```sh
pio run -d firmware/m5stack -t upload --upload-port /dev/ttyUSB0
pio device monitor --port /dev/ttyUSB0 --baud 115200
```

USBポートは `pio device list` の結果に合わせます。モニターを開いてM5Stackをリセットすると `PAN-CAMERA ready: IPアドレス` が出るので、`config/network.toml` に設定します。モニターの終了はCtrl+C。PiとM5Stackを同じLANに接続し、UDP 5005・5006・5007の相互通信を許可します。IPが変わらないようルーターのDHCP予約を利用できます。

## 起動と操作

まずサーボを動かさないプレビューで接続・認識を確認します。

```sh
uv run python -m pan_camera
```

追尾を許可し、処理速度の制限を外して起動する場合：

```sh
uv run python -m pan_camera --allow-servo --fps 0
```

| ボタン | 操作 |
|---|---|
| A / SELECT | 左から順に被写体を選択。最後の対象の次はFREE。追尾中なら停止して選択を切り替え |
| B / START・STOP | 短押しで追尾を開始・停止。FREEでは中央へ復帰。長押しでPiアプリの起動・終了メニュー |
| C / REC | 録画を開始・停止 |

[起動管理サービス](docs/usage.md#m5stackからpiプログラムを起動終了)を導入すると、Pi起動後はM5StackのB長押しメニューからプログラムを起動・終了できます。

`--allow-servo` 指定時は、カメラの画像取得と制御ポートの準備に成功してから中央位置へ初期化します。初回通電時の実際の位置は取得できないため、この最初の移動速度は保証できません。

追尾を停止してもサーボは現在位置を保持します。カメラ切断時も最後のPWM指令を保持したまま録画・通信を閉じて終了し、**プロセス終了後もサーボは通電状態**です。通常終了・通信タイムアウトとは動作が異なるため、[停止・障害時の挙動](docs/usage.md#停止障害時の挙動)も確認してください。

## 検出対象のON/OFF

`config/detection.toml` に80種類を一覧化しています。現在のデフォルトはコップのみです。人物も使う場合は `person = true` に変更します。変更後はPiプログラムを再起動します。

```toml
[classes]
person = false
cup = true
bottle = false
```

`--classes` を指定した起動では、設定ファイルの代わりに指定したクラスだけを使用します。ファイル自体は変更しません。

```sh
uv run python -m pan_camera --allow-servo --fps 0 --classes person
uv run python -m pan_camera --allow-servo --fps 0 --classes cup bottle
uv run python -m pan_camera --list-classes
```

## 録画と性能

REC操作では `outputs/recordings/` に、認識枠付き640×360 AVI、M5Stack画面を再現した320×240・4 FPSのAVI、枠なし720p映像＋音声のMP4を同時に保存します。MP4は録画中にH.264＋AACへ圧縮します。解像度・画質・CPUスレッド数・マイクは `config/recording.toml` で指定します。再エンコードしない大容量MKVも設定で選択できます。録画の再生速度、負荷、容量制限は[操作ガイド](docs/usage.md#録画)を参照してください。

コップ検出・サーボ無効の計測では、カメラ約16.5 FPS、全体約13 FPS、YOLO＋追跡約70～73 msでした。3種類の録画を併用した最新構成の性能は未測定です。測定条件と限界は[検証結果](docs/validation.md)に記載しています。

```sh
uv run python -m pan_camera --profile --fps 0 --frames 300
```

## ファイル構成

```text
apps/pi/src/pan_camera/   Pi側アプリ、撮影、追跡制御、描画、録画、通信
firmware/m5stack/         M5Stackファームウェアと書き込み設定
config/                  検出対象、サーボ校正値、追跡・通信設定
deploy/                  PWM準備・M5Stack起動管理サービスのテンプレート
models/                  使用する学習済みモデルと出典情報
scripts/                 PWM準備・実機可動域確認・動画タイトルの生成
tests/                   実機を動かさない自動テスト
docs/                    配線、操作、設計、検証、今後の課題
outputs/                 録画などの生成物（Git管理対象外）
```

## 開発とドキュメント

```sh
uv run python -m unittest discover -s tests -v
pio run -d firmware/m5stack
```

テストは実機のカメラ・マイク・サーボを使いません。FFmpegがある環境では、生成映像・音声による録画の結合テストも実行します。ビルドや自動テストの成功と、実機での動作確認は区別しています。

- [ハードウェア・PWM準備](docs/hardware.md)
- [操作・設定・トラブル対処](docs/usage.md)
- [設計・通信仕様](docs/architecture.md)
- [検証結果・確認範囲・今後の課題](docs/validation.md)
- [提出資料のHTML（A4・2ページ）](docs/report.html)
- [動画用タイトルのSVGアニメーション](docs/video-titles.html)
- [第三者ソフトウェアとモデル](THIRD_PARTY_NOTICES.md)

本リポジトリは実機での試作プロジェクトです。上下方向の旋回、長時間運転、遮蔽後の同一対象の確実な復帰は今後の課題です。

## ライセンス

本プロジェクトで作成したコード・設定・文書・SVG図は **AGPL-3.0-only** です。[LICENSE](LICENSE) と [NOTICE](NOTICE) を参照してください。学習済みモデルと第三者のソフトウェアには各配布元の条件が適用されます。出典、利用バージョン、ライセンス本文は [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) にまとめています。
