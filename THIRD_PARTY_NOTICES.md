# ライセンスと第三者ソフトウェア

確認日：2026-11-02

## PAN-CAMERAの公開ライセンス

本プロジェクトで作成したソースコード、設定例、文書、SVG図は **GNU Affero General Public License version 3 only（SPDX: `AGPL-3.0-only`）** で公開します。全文は [LICENSE](LICENSE)、権利表示は [NOTICE](NOTICE) に収録しています。LICENSE本文は、使用しているUltralytics配布物に含まれるAGPL v3本文とも一致するため、同文の別ファイルは設けていません。第三者のコード・モデル・ライセンス本文には、それぞれの元の条件が適用されます。

最終課題は使用コード一式のGitHubでのpublic公開を求めていますが、特定のライセンスを指定していません。AGPL-3.0-onlyは、利用しているUltralyticsのコード・モデルの公開方針に合わせ、本プロジェクトで選択したものです。

AGPLは利用・改変・再配布を認めるライセンスです。再配布や改変版の提供では、ライセンス・著作権表示の保持や対応するソースコードの提供などの条件に従います。ネットワーク越しに利用させる改変版については第13条も適用されます。単に「教育用途限定」や「商用利用禁止」という条件ではありません。実際の条件はLICENSE本文を正とします。

## 検出モデルと追跡の出典

物体検出にはUltralyticsの学習済み **YOLO26n** を使用し、追加学習は行っていません。PAN-CAMERAで実装した部分は、対象選択、追尾制御、PWMの操作、描画、3種類の録画、M5Stackとの通信・操作・起動管理の統合です。

- モデル：[`models/yolo26n.pt`](models/yolo26n.pt)
- モデル情報とSHA-256：[`models/README.md`](models/README.md)
- 配布元：[Ultralytics](https://github.com/ultralytics/ultralytics)
- コード・モデルのライセンス案内：[Ultralytics License](https://www.ultralytics.com/license)
- ライセンス本文：[AGPL v3](LICENSE)

重みの公開・利用には配布元の条件を適用します。本プロジェクト独自の学習成果や独占的な権利を主張するものではありません。COCOの画像データセット自体はリポジトリに含めません。

追跡アルゴリズムは **ByteTrack** です。[原著者の実装](https://github.com/FoundationVision/ByteTrack)はMITですが、本プロジェクトが呼び出すのは **Ultralyticsパッケージ内の実装（AGPL-3.0）** です。原著実装のMIT表記を、そのまま利用中の実装のライセンスとして扱いません。`config/bytetrack_pan.yaml` はUltralytics 8.4.197の `ultralytics/cfg/trackers/bytetrack.yaml` を基に、新規IDの閾値・保持期間・照合コストを変更した設定です。元のライセンス表示を同ファイルに保持しています。

## 主な依存ソフトウェア

バージョンは検証環境の値です。Pythonは `uv.lock`、M5Stackは `platformio.ini` を参照してください。下記は主な依存関係の一覧であり、全推移依存や配布バイナリ内の全コンポーネントを列挙したSBOMではありません。

| コンポーネント | 確認バージョン | 用途 | ライセンス・出典 |
|---|---|---|---|
| Ultralytics | 8.4.197 | YOLO推論、ByteTrack実装 | AGPL-3.0。[配布物の本文](LICENSE)・[公式案内](https://www.ultralytics.com/license) |
| PyTorch | 2.15.0+cpu | CPU推論 | 本体はBSD-3-Clause系。[配布物の本文](licenses/PYTORCH-LICENSE.txt)・[配布元](https://github.com/pytorch/pytorch)。wheelにはApache-2.0、MIT等の追加条件を持つ同梱物を含む |
| torchvision | 0.29.2+cpu | 推論に用いる画像処理関連機能 | BSD-3-Clause。[配布物の本文](licenses/TORCHVISION-BSD-3-Clause.txt)・[配布元](https://github.com/pytorch/vision) |
| OpenCV / opencv-python-headless | 4.14.0.94 | カメラ取得、描画、JPEG・AVI | OpenCV本体はApache-2.0、Pythonパッケージ化部分はMIT。[Python側本文](licenses/OPENCV-PYTHON-MIT.txt)・[OpenCVと同梱物の本文](licenses/OPENCV-THIRD-PARTY.txt)・[配布元](https://github.com/opencv/opencv-python) |
| NumPy | 2.4.6 | 画像配列、JPEG入力の変換、画面の再現 | 本体BSD-3-Clauseと同梱物の条件。[配布物の本文](licenses/NUMPY-LICENSE.txt)・[配布元](https://github.com/numpy/numpy) |
| lap | 0.5.13 | 追跡の対応付け | BSD-2-Clause。[配布物の本文](licenses/LAP-BSD-2-Clause.txt)・[配布元](https://github.com/gatagat/lap) |
| M5Unified | 0.2.29 | M5Stackの画面・ボタン | MIT。[配布物の本文](licenses/M5Unified-MIT.txt)・[配布元](https://github.com/m5stack/M5Unified) |
| M5GFX | 0.2.36 | LCD描画、JPEG表示 | MIT。[配布物の本文](licenses/M5GFX-MIT.txt)・[配布元](https://github.com/m5stack/M5GFX)。個別の同梱素材等はその権利表示も参照 |
| Arduino ESP32 | 2.0.16 | ESP32の実行基盤 | コアの基本条件はLGPL-2.1。[当該版の本文](https://github.com/espressif/arduino-esp32/blob/2.0.16/LICENSE.md)。ESP-IDF等の同梱コンポーネントには個別条件も適用 |
| FFmpeg | 開発機5.1.9 | H.264・AAC圧縮、MJPEGのstreamcopy、ALSA音声の録音・格納 | libx264を含む外部コマンドとして使用。LGPL/GPL等はビルド構成による。開発機は `--enable-gpl`。[公式ライセンス案内](https://ffmpeg.org/legal.html)。実行バイナリはリポジトリに含めない |
| librsvg | 2.54.7 | 動画用SVGタイトルの描画 | OSの共有ライブラリを使用。主な条件はLGPL-2.0-or-later、個別の同梱物には別条件もある。OS配布物のcopyrightを参照。バイナリは含めない |
| Cairo | 1.16.0 | 動画用SVGタイトルの画像化 | OSの共有ライブラリを使用。LGPL-2.1またはMPL-1.1等、OS配布物のcopyrightを参照。バイナリは含めない |
| PlatformIO Core | 6.2.0 | ビルド・書き込みツール | Apache-2.0。[本文](https://github.com/platformio/platformio-core/blob/develop/LICENSE)・[配布元](https://github.com/platformio/platformio-core) |

`licenses/` にはインストール済み配布物のライセンス本文を変更せず保存しています。記載された原著作権者の表示は保持します。

## 公開物と再配布の扱い

このリポジトリの公開対象は、PAN-CAMERAのソース、設定例、文書・図、使用する学習済み重み、依存関係の定義です。`.venv/`、PlatformIOの `.pio/`、生成したファームウェア・録画・キャッシュ、実際のWi-Fi認証情報は含めません。

ビルド済みファームウェアやランタイムを別途再配布する場合は、この一覧だけで済ませず、その配布物に組み込まれたライブラリ・ツールチェーン・フォント等のライセンス、NOTICE、対応ソースの条件も保持してください。

課題PDFや講義資料、外部サイトの画像、他者の写真を本プロジェクトのAGPLにより再許諾することはありません。以後レポート・動画へ外部素材を追加する際も、その出典と利用条件を個別に扱います。
