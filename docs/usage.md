# 操作と設定

## 起動オプション

全コマンドはリポジトリルートで実行します。

| オプション | デフォルト | 内容 |
|---|---|---|
| `--allow-servo` | 無効 | サーボの初期化と追尾操作を許可 |
| `--fps` | 8 | 追尾ループの目標FPS。`0` は待ち時間による制限なし。指定範囲0～30 |
| `--preview-fps` | 4 | M5Stackへの映像送信目標FPS。0より大きく10以下 |
| `--frames` | 0 | 処理するフレーム数。`0` はCtrl+Cまで継続 |
| `--profile` | 無効 | 5秒ごとの速度・処理時間の表示 |
| `--classes` | 設定ファイル | 検出クラス名を空白区切りで指定。設定ファイル全体より優先 |
| `--list-classes` | 無効 | 学習済みモデルのクラス一覧を出力して終了 |

複数語のクラス名は引用符で囲みます。

```sh
uv run python -m pan_camera --classes person "cell phone"
```

## 設定ファイル

| ファイル | 設定対象 |
|---|---|
| `config/detection.toml` | 全80クラスのON/OFF。最低1つを有効にする |
| `config/network.toml` | M5StackのIP、受信ポート5005、Piの制御ポート5006、起動管理ポート5007 |
| `config/recording.toml` | 枠なし映像＋音声と画面録画のON/OFF、圧縮方式・画質・CPUスレッド数、解像度、ALSAマイク |
| `config/servo.toml` | PWM割り当て、校正範囲、速度・加速度上限、実機調整の移動設定 |
| `config/bytetrack_pan.yaml` | 対象の対応付け、新規ID、見失い後の保持期間 |

検出対象の標準はコップのみです。人物などは `config/detection.toml` で有効にできます。設定は起動時に読み込みます。クラス指定が不明な場合や全対象OFFの場合は、サーボを動かす前にエラー終了します。`track_buffer: 60` は60追跡フレームであり、保持秒数は実際のFPSで変わります。位置の対応付けが崩れると、保持期間内でも新しいIDになることがあります。

## M5Stackの操作

Aは有効なクラスの対象を、画面上の左から右の順に選択します。右端の対象の次はFREEです。選択中の対象が見えなくなった状態でAを押すとFREEに戻ります。

追尾中にAを押すと、その位置を保持してSTANDBYへ移り、次の対象に選択を切り替えます。Bで追尾を再開します。Cの録画操作は追尾とは独立しています。

| 表示 | 意味 |
|---|---|
| STANDBY | 追尾停止中。サーボ保持中の場合も含む |
| TRACK | 選択対象を検出し、追尾中 |
| LOST | 追尾中の選択対象を検出できず、位置保持 |
| WAIT / OFFLINE | 映像や状態の待機、またはWi-Fi未接続 |
| APP OFF / STARTING / STOPPING / APP ERROR | 起動管理サービスが通知するPiアプリの状態 |
| FREE | 対象未選択。B短押しは中央復帰 |
| シアンの枠 | 選択中の対象 |
| 上下の三角 | 映像の中心軸 |

## M5StackからPiプログラムを起動・終了

**Bを約1秒長押し**するとPI APPLICATIONメニューを開きます。

| ボタン | メニューでの操作 |
|---|---|
| A | Piの追尾・録画プログラムを起動 |
| B（短押し） | 通常画面に戻る |
| C | 録画を閉じ、Piプログラムを終了。通常終了のためPWMもOFF |

起動時は `--allow-servo --fps 0` を指定し、それ以外は設定ファイルの既定値を使います。初期状態はSTANDBYで、追尾・録画は通常画面のB/Cから開始します。起動処理中もRUNNING / STARTINGと表示し、映像が届くと通常画面が有効になります。すでに起動中のAは二重起動せず、終了処理中の起動要求は受け付けません。

終了後もPiと小さな起動管理サービスは動き続けます。カメラ異常で終了した場合のPWM保持は従来どおりで、停止済みアプリにCを押しても保持を解除しません。再起動時は保持位置を引き継いで中央へ戻します。

### 起動管理サービスの導入

先にハードウェア手順の `pan-camera-pwm.service` を導入し、`uv sync --locked` とM5Stackへの書き込みを完了します。リポジトリルートで以下を実行します。設置パスに空白・`|`・`&`を含めないでください。

```sh
sed -e "s|@PROJECT_ROOT@|$PWD|g" -e "s|@USER@|$(id -un)|g" \
  deploy/pan-camera-launcher.service > /tmp/pan-camera-launcher.service
sudo install -m 644 /tmp/pan-camera-launcher.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pan-camera-launcher.service
```

サービス自体はPi起動時に待機します。追尾プログラムはM5StackのAを押すまで起動しません。手動起動とは同時に使わず、手動実行する場合は先にサービスを停止します。

```sh
sudo systemctl stop pan-camera-launcher.service
journalctl -u pan-camera-launcher.service -n 60 --no-pager
```

サービスを停止すると、そこから起動したアプリも終了します。実行ログはsystemd journalに残ります。`APP ERROR`の場合は上記ログでカメラやマイクなどのエラーを確認してください。

## 録画

C / RECで同じ開始・停止操作から3種類のファイルを保存します。保存先はPiの `outputs/recordings/` です。

| ファイル | 映像 | 音声 |
|---|---|---|
| `pancamera_日時_annotated.avi` | 認識枠・ラベル付き、640×360 MJPEG | なし |
| `pancamera_日時_display.avi` | M5Stackの通常画面をPi側で再現、320×240・4 FPS MJPEG | なし |
| `pancamera_日時_clean.mp4` | 枠なし映像をH.264に圧縮、既定1280×720 | カメラ内蔵マイク、48 kHz・モノラルAAC、96 kbps |

### M5Stack画面の再現録画

`display.avi` はM5Stackへ送ったJPEGを再利用し、ヘッダー、追尾状態、選択対象、PWM、FPS、REC時間、ボタン表示をPiで描画します。4 FPSで記録し、処理の遅れた区間は直前の画面で補って実時間に合わせます。保存時間の刻みは0.25秒です。

LCDの読み取りではなく通常画面の再現です。文字の描画は近似で、Piが送った映像と状態を使います。M5Stackの受信遅延・欠落、長押しメニュー、一時通知は再現せず、受信枚数・欠落数は `RX:-- D:--` と表示します。画面録画には音声を重複保存しません。

`config/recording.toml` の `display_enabled = false` で画面録画だけを無効にできます。変更はPiプログラムの次回起動から反映されます。

### 枠なし映像＋音声の設定

```toml
# config/recording.toml
[recording]
raw_enabled = true
display_enabled = true
video_codec = "h264"
video_crf = 26
encoding_threads = 2
width = 1280
height = 720
camera_fps = 30
audio_device = "plughw:CARD=Camera,DEV=0"
audio_rate = 48000
audio_channels = 1
```

- `width` / `height` は1280×720または1920×1080。変更後は再起動する。
- 撮影と枠なし録画は同じ解像度を使用する。認識枠付きAVIはどちらの場合も640×360。
- `video_codec = "h264"` は録画中にH.264＋AACへ圧縮してMP4保存。低負荷のultrafast設定を使用し、エンコードのCPUスレッド数を `encoding_threads`（1～4、既定2）で指定する。
- `video_crf` は18～35、既定26。小さい値ほど高画質・大容量、大きい値ほど低画質・小容量になる。H.264は非可逆圧縮。枠やラベルは加えないが、元JPEGとの画素の完全一致を目的としない。
- `video_codec = "copy"` では再エンコードせず、MJPEG＋PCMを `_clean.mkv` として保存。圧縮負荷を抑えられる一方、容量は大きくなる。
- `camera_fps` はカメラへの要求値。取得FPSの保証値ではない。
- `raw_enabled = false` は枠なし映像＋音声を無効にする。認識枠付きAVIと画面再現AVIは引き続き保存する。画面再現AVIも不要なら `display_enabled = false` を指定する。
- マイクは `arecord -l` で確認したArducamの `Camera` カードを名前で指定する。カード番号が変わっても同じ名前で指定できる。
- 必要なツール：`ffmpeg`。マイクの確認は `arecord -l`（alsa-utils）。

カメラを二重に開かずに撮影経路からJPEGを分岐し、別スレッドでFFmpeg子プロセスへ渡します。既定では録画中にH.264＋AACへ圧縮します。圧縮と推論は同じPiのCPUを使うため、実際の追尾FPSへの影響を確認してください。

映像は取得側の時刻を付けてFFmpegへ渡し、音声も同じ開始時刻を基準に格納します。保存処理の待ち時間を映像のフレーム間隔に置き換えないための処理ですが、カメラの露光時刻やマイク内部の遅延は取得していません。短い実機確認では音声開始が約1秒遅れる例があり、長時間の同期は未検証です。詳しくは[録画の検証結果](validation.md#録画と音声)を参照してください。

### 録画の制限とエラー

- 認識枠付きAVIの固定FPSは `--fps` の値。`--fps 0` の場合は8 FPS。処理速度と異なると実時間と再生時間は一致しない。
- 枠なし録画は取得側の時刻を使用する。認識枠付きAVIと同一のフレーム数・長さになるとは限らない。
- copyモードのMKVはMJPEG＋PCMのため、H.264＋AACのMP4より大きくなる場合がある。
- 1回の録画は最大600秒。開始時の空き容量100 MiB未満では開始せず、録画中は定期確認で50 MiB未満になると停止する。
- 元映像の受け渡しキューは要求カメラFPSの2倍（既定60フレーム）かつ32 MiB以内。開始時の入力準備待ちを吸収する。溢れた場合やFFmpeg・マイクのエラーは、録画エラーとして各ファイルを閉じる。カメラ取得スレッドを保存待ちで止めない。
- REC停止時はFFmpegの終了も待ち、コンテナを確定する。必要時は段階的に終了を要求するため、数秒かかる場合がある。最終的な強制終了ではファイルの完成を保証できない。
- 電源の突然の切断やプロセスの強制終了での録画ファイル完成も保証しない。

### 動作確認

まずサーボを動かさない状態で起動し、Cで短く録画して停止します。

```sh
uv run python -m pan_camera --fps 0
ffprobe -v error -show_streams -show_format outputs/recordings/対象_clean.mp4
```

出力に720pの `h264` 映像と `aac` 音声があることを確認し、再生して映像・音声・同期を確かめます。画質・音ずれ・追尾速度への影響の最終確認は実機で行います。

## 停止・障害時の挙動

| 状況 | サーボとプログラム |
|---|---|
| Bで追尾停止、Aで対象変更 | PWMを維持して現在位置を保持 |
| 対象を見失う | その位置で保持。対応するIDを再検出すれば追尾を継続 |
| FREEでB | 現在の指令位置から中央へ加減速して移動 |
| カメラ未接続で起動 | サーボを初期化せず終了。以前のプロセスが残した保持信号には触れない |
| 動作中の画像取得エラー・タイムアウト | サーボの移動スレッドを止め、最後のPWMを維持。録画・通信を閉じて終了コード1で終了 |
| M5Stackの通信途絶 | 約2秒のハートビートタイムアウトをループで検知するとPWMを停止。検出処理自体は継続 |
| Ctrl+C・通常の処理終了 | PWMを停止し、録画を閉じて終了 |

PWM停止は位置保持の解除を伴います。実機ではPWM停止時に機構が大きく動く現象があったため、カメラ取得エラー時は保持を残す設計です。通常終了時のPWM停止にも注意してください。通電・保持中の温度や、カメラ・USBケーブルの力を確認します。

カメラ取得エラー後はカメラを再接続し、`--allow-servo` で起動すると保持位置から中央へ戻します。同じPWMを他のプロセスが制御している場合は引き継ぎません。保持状態は `/tmp/pan-camera-pwm-*.lock` に記録します。このファイルを保持中に削除しないでください。Piの電源断や再起動をまたぐ実位置は取得できません。

## トラブル対処

| 症状 | 確認事項 |
|---|---|
| `Camera open failed` | USB接続、他プロセスによる使用、`/dev/video0` の存在 |
| 解像度エラー | カメラが設定した解像度（既定1280×720）のMJPEGを提供するか |
| `PWM not prepared` | ハードウェアPWM設定と準備スクリプト |
| `PWM channel already in use` | 別プログラムが有効化していないか。保持状態の管理ファイルを削除していないか |
| M5Stackに映像が来ない | 同じLAN、SSIDとパスワード、M5StackのIP、ポート、ファームウェアの世代 |
| `NO TARGET` | 選択IDが現在検出されているか |
| REC開始に失敗 | 空き容量、出力先の権限、FFmpegの有無、ALSAの録音デバイス |
| APP ERROR / LAUNCHER OFFLINE | `systemctl status pan-camera-launcher.service` と `journalctl -u pan-camera-launcher.service` |

デバイス確認は `ls -l /dev/video* /dev/ttyUSB*`、対応形式は `v4l2-ctl --list-formats-ext -d /dev/video0`（v4l-utils導入時）で確認できます。

## 動画用タイトルの書き出し

[SVGアニメーションのプレビュー](video-titles.html)に冒頭タイトル、4種類の章タイトル、エンディングを収録しています。OSのlibrsvg・CairoとFFmpegを利用して、以下で3840×2160・30 FPSのH.264 MP4を書き出します。Pythonの追加パッケージは不要です。

```sh
python scripts/render_video_titles.py
```

保存先は `outputs/video-titles/`。冒頭とエンディングは各4秒、章タイトルは各1.5秒です。生成したMP4を動画編集ソフトへ読み込めます。プレビューHTMLと書き出し用SVGも同じスクリプトから生成します。
