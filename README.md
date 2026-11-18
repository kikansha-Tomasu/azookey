# AzooKey Live Bridge

Windows アプリ上で [azooKey for Windows](https://github.com/fkunn1326/azooKey-Windows)（`azookey-server.dll`）によるインライン・ライブ変換を利用するブリッジ。IME 登録や管理者権限は不要。

---

## 起動

- **要件**: Python 3（標準ライブラリ・`tkinter` のみ）
- **実行**: `run.bat`（`.venv` 優先）または `python app.py`

---

## 主な仕様

- **文節部分確定**: 文節候補を選択確定するとその文節のみ確定し、後続の変換を継続。
- **Zenzai・文脈**: 同梱 `zenz.gguf`（Zenzai v3）と左側文脈（最大 60 文字）を使用。非変換時の矢印・`Home`・`End`・`PageUp`・`PageDown`・`Delete`・`Tab`・`Escape`・クリック・`Ctrl+C` 以外のショートカット操作で文脈をリセット。
- **変換学習**: 第2候補以降を明示選択して確定した場合のみ学習保存（最大 2,000 件・読み 24 文字以内・未確定子音なし）。
- **英数・大文字制御**: 日本語モード中は `CapsLock` を無視。英語モードは Unicode 文字の直接送出。

---

## キーバインド・操作

### モード切替

| 操作 | 動作 |
| :--- | :--- |
| `Scroll Lock` / `半角/全角` / `Alt + ~` / `Ctrl + Space` / `無変換` | 日本語（ON）/ 英語（OFF）をトグル（未確定文字は確定） |
| `変換` / `カタカナ・ひらがな` / `IME ON` | 日本語（ON）へ切替（変換中の `変換` は次候補） |
| `英数` / `IME OFF` | 英語（OFF）へ切替 |
| 画面の「ライブ変換」ボタン（ドラッグ / 右ダブルクリック） | 位置移動 / 初期位置リセット |

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

- `Ctrl+C`・`Enter`・セルダブルクリックで `読み<Tab>変換候補` 形式でコピー（`Ctrl+F` 検索 / `Ctrl+A` 全選択 / `Delete` 削除 / `F5` 再読込 / `Escape` 閉じる）

---

## ファイル構成・保存先

```text
.
├── .gitignore
├── app.py                   # GUI・変換制御
├── azookey_client.py        # azookey-server.dll 連携・GPU バックエンド診断
├── LICENSE                  # MIT License
├── README.md
├── requirements.txt         # 標準ライブラリのみ使用
├── run.bat                  # 起動スクリプト（.venv 優先）
├── windows_input.py         # Windows フック（WH_KEYBOARD_LL / WH_MOUSE_LL）・入力送出・通知領域アイコン
├── .venv/                   # Python 仮想環境（環境固有・配下省略）
├── __pycache__/             # Python バイトコードキャッシュ（自動生成）
└── azookey-runtime/         # AzooKey ランタイム（主要ディレクトリ・ファイルのみ抜粋）
    ├── app/
    │   ├── .appdata/        # %APPDATA% 書込不可時のフォールバック保存先
    │   │   ├── Azookey/
    │   │   └── AzooKeyLiveBridge/
    │   ├── Dictionary/      # 変換辞書（mm.binary 等・配下ファイル省略）
    │   │   ├── cb/
    │   │   ├── louds/
    │   │   └── p/
    │   ├── EmojiDictionary/
    │   ├── llama_cpu/       # Zenzai CPU バックエンド
    │   ├── llama_cuda/      # Zenzai CUDA バックエンド
    │   ├── llama_vulkan/    # Zenzai Vulkan バックエンド
    │   ├── x86/
    │   ├── azookey-server.dll
    │   └── zenz.gguf        # Zenzai v3 モデル
    └── tmp/
```

- **設定・データ保存先**（`%APPDATA%` 書き込み不可時は `<engine_dir>\.appdata\` へフォールバック）:
  - `%APPDATA%\AzooKeyLiveBridge\settings.json`: アプリ設定
  - `%APPDATA%\AzooKeyLiveBridge\learning.json`: 変換学習履歴
  - `%APPDATA%\Azookey\settings.json`: AzooKey エンジン設定

---

## 注意事項・制限事項

- **パスワード欄**: 日本語モード中は入力をフックするため、英語モードへ切替または終了する。
- **管理者権限アプリ（UIPI）**: 前面時はユーザー権限フックが無効。
- **再変換非対応**: 確定済み・既存テキストの再変換・文節変更は不可。
- **Zenzai GPU バックエンド（Vulkan / CUDA）**（利用不可時は `CPU` へフォールバック）:
  - `Vulkan (GPU)`: 追加 SDK 不要（`ggml-vulkan.dll`・`vulkan-1.dll` 使用）。
  - `CUDA (NVIDIA)`: CUDA 12 ランタイム DLL（`cudart64_12.dll`・`cublas64_12.dll`・`cublasLt64_12.dll`）が必要（`CUDA_PATH`、`C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.*\bin`、`.venv` 内 `nvidia-cuda-runtime-cu12` / `nvidia-cublas-cu12`、`llama_cuda` フォルダー等から自動検出）。
