# AzooKey Live Bridge

Windows アプリ上で [azooKey for Windows](https://github.com/fkunn1326/azooKey-Windows)（`azookey-server.dll`）によるインライン・ライブ変換を利用するブリッジ。IME 登録や管理者権限は不要です。

---

## 要件・セットアップ

- **OS**: Windows 10 / 11（64-bit）
- **Python**: **64-bit 版 Python 3.10 以上**（標準ライブラリ・`tkinter` のみ使用、追加パッケージ不要）
  - `azookey-server.dll` は x64 専用のため、32-bit 版 Python では動作しません。
- **AzooKey ランタイムの配置**（GitHub リポジトリにはバイナリを含めていません）:
  1. [azooKey for Windows](https://github.com/fkunn1326/azooKey-Windows) のリリース等から `azookey-server.dll`、`Dictionary/`、`llama_cpu/`（任意で `llama_vulkan/`・`llama_cuda/`・`zenz.gguf`）を用意します。
  2. リポジトリ直下の `azookey-runtime/app/` に配置するか、アプリ起動後に設定画面から既存の AzooKey インストール先フォルダーを選択してください。

### 起動方法

```bat
run.bat
```

`.venv` が存在する場合は優先して使用し、未作成の場合はシステム PATH の `pythonw` / `python` で `app.py` を起動します（直接 `python app.py` でも起動可能）。

---

## 主な仕様・設定機能

- **文節部分確定**: 文節候補を選択確定するとその文節のみ確定し、後続の変換を継続。
- **Zenzai・文脈**: `zenz.gguf`（Zenzai v3）と左側文脈（最大 60 文字）を使用。設定画面から Zenzai の ON/OFF、プロファイル、推論バックエンド（`CPU` / `Vulkan` / `CUDA`）を切替可能。非変換時の矢印・`Home`・`End`・`PageUp`・`PageDown`・`Delete`・`Tab`・`Escape`・クリック・`Ctrl+C` 以外のショートカット操作で文脈をリセット。
- **変換学習**: 第2候補以降を明示選択して確定した場合のみ学習保存（最大 2,000 件・読み 24 文字以内・未確定子音なし）。設定画面の学習履歴ウィンドウから検索・コピー・個別削除・全リセットが可能。
- **英数・大文字制御**: 日本語モード中は `CapsLock` を無視。英語モードは Unicode 文字の直接送出、または設定画面の「英語モードをそのまま透過」で通常入力のパススルー切替が可能。
- **入力・表示設定**: 全角/半角スペース切替、`Shift + 英字` の一時半角英字入力 ON/OFF、表示サイズ（標準 / 大きめ / 特大、OS テーマ・DPI・テキスト拡大率連動）、トレイ最小化・最小化起動。

---

## キーバインド・操作

### モード切替

| 操作 | 動作 |
| :--- | :--- |
| `Scroll Lock` / `半角/全角` / `Alt + ~` / `Ctrl + Space` / `無変換` | 日本語（ON）/ 英語（OFF）をトグル（未確定文字は確定） |
| `変換` / `カタカナ・ひらがな` / `IME ON` | 日本語（ON）へ切替（変換中の `変換` は次候補） |
| `英数` / `IME OFF` | 英語（OFF）へ切替 |
| 画面の「ライブ変換」ボタン（ドラッグ / 右ダブルクリック） | 位置移動（自動保存） / 初期位置リセット |

### 日本語変換中

| 操作 | 動作 |
| :--- | :--- |
| 記号 / テンキー | 全角記号変換（`/`→`・`・`-`→`ー`・`[ ]`→`「」` 等）、`、。！？` で自動確定、テンキー（`0`〜`9`・`.` `/` `-` `+` `*`）は半角 |
| `Shift + 英字`（有効時） | 一時半角英字入力（`.` `,` `!` `?` 等も継続。確定または候補選択後の追加入力でかな復帰） |
| `Space` / `Shift + Space` / `変換` | 候補選択（`Shift+Space` で逆順、選択中の追加入力で確定。選択中の確定はテンキー `1`〜`6` も有効） |
| `PageDown` / `PageUp` | 候補ページ移動（6 件単位） |
| `Shift + ←` / `Shift + →` | 文節区切り縮小・拡大 |
| `F6` / `F7` / `F8` / `F9` / `F10` | ひらがな / 全角カナ / 半角カナ / 全角英数 / 半角英数（大文字・`-` 等を保持） |
| `←` / `→` / `Home` / `End` | 読み表示に戻しカーソル移動・途中編集（末尾復帰でライブ変換再開） |
| `Backspace` | 子音入力中はローマ字 1 文字、それ以外はかな 1 文字を削除 |
| `Escape` | 候補選択解除 / 未選択時は未確定文字を消去 |
| `Tab` / `Ctrl`・`Alt`・`Win` ショートカット | 確定してキー透過 |
| 本文クリック / フォーカス移動 | その場で確定デタッチ |

### 学習履歴ウィンドウ

- `Ctrl+C`・`Enter`・セルダブルクリックで `読み<Tab>変換候補` 形式でコピー
- `Ctrl+F` 検索 / `Ctrl+A` 全選択 / `Delete` 削除 / `F5` 再読込 / `Escape` 検索クリアまたは閉じる

---

## ファイル構成・保存先

```text
.
├── .github/workflows/ci.yml # Windows 自動テスト CI
├── .gitignore
├── app.py                   # GUI・変換制御
├── azookey_client.py        # azookey-server.dll 連携・GPU バックエンド診断
├── LICENSE                  # MIT License
├── README.md
├── requirements.txt         # 標準ライブラリのみ使用
├── run.bat                  # 起動スクリプト（.venv 優先）
├── tests/                   # ユニットテスト（unittest）
└── windows_input.py         # Windows フック（WH_KEYBOARD_LL / WH_MOUSE_LL）・入力送出・通知領域アイコン
```

ローカル実行時に配置するランタイム構成（`.gitignore` 対象）:

```text
azookey-runtime/app/
├── Dictionary/              # 変換辞書（必須）
├── EmojiDictionary/         # 絵文字辞書（任意）
├── llama_cpu/               # Zenzai CPU バックエンド（必須）
├── llama_vulkan/            # Zenzai Vulkan バックエンド（任意）
├── llama_cuda/              # Zenzai CUDA バックエンド（任意）
├── azookey-server.dll       # 変換エンジン DLL（必須）
└── zenz.gguf                # Zenzai v3 モデル（任意）
```

- **設定・データ保存先**（`%APPDATA%` 書き込み不可時はフォールバック保存先 `.appdata\` を使用。JSON は一時ファイル経由で原子的に保存し、破損時は `.corrupt.<timestamp>` に退避します）:
  - `%APPDATA%\AzooKeyLiveBridge\settings.json`: アプリ設定
  - `%APPDATA%\AzooKeyLiveBridge\learning.json`: 変換学習履歴
  - `%APPDATA%\Azookey\settings.json`: AzooKey エンジン設定

---

## テスト

標準ライブラリの `unittest` で実行できます:

```powershell
python -m unittest discover -s tests -v
```

---

## 注意事項・制限事項

- **パスワード欄**: 日本語モード中は入力をフックするため、英語モードへ切替または終了してください。
- **管理者権限アプリ（UIPI）**: 前面時はユーザー権限フック・入力送出が無効になります。
- **再変換非対応**: 確定済み・既存テキストの再変換・文節変更は不可。
- **Zenzai GPU バックエンド（Vulkan / CUDA）**（利用不可時は `CPU` へフォールバック）:
  - `Vulkan (GPU)`: 追加 SDK 不要（`ggml-vulkan.dll`・`vulkan-1.dll` 使用）。
  - `CUDA (NVIDIA)`: CUDA 12 ランタイム DLL（`cudart64_12.dll`・`cublas64_12.dll`・`cublasLt64_12.dll`）が必要（`CUDA_PATH`、`C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.*\bin`、`.venv` 内 `nvidia-cuda-runtime-cu12` / `nvidia-cublas-cu12`、`llama_cuda` フォルダー等から自動検出）。
