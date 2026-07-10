# Suica Viewer

Suica Viewer は、FeliCa ベースの交通系 IC カードから詳細な情報を取得し、表示・保存するためのツールです。暗号領域の読み出しにはリモート認証サーバーを利用し、コンソール向け CLI と Tkinter 製 GUI の 2 つのエントリーポイントを提供します。

## 主な機能
- リモートサーバー経由での相互認証と暗号領域読み出し
- CLI 版: 発行情報・残高・履歴・定期券情報などをテキストで整形出力
- GUI 版: 概要／発行情報／取引履歴／改札履歴／その他タブを備えたビジュアルビューア、履歴フィルタ、JSON のコピー・保存機能
- `station_codes.csv` に基づく会社名・路線名・駅名の解決
- `AUTH_SERVER_URL` 環境変数での認証サーバーの切り替え（既定: `https://felica-auth.nyaa.ws`）

## 必要環境
- Python 3.10 以降
- [uv](https://docs.astral.sh/uv/)
- nfcpy が対応している FeliCa リーダー／ライター（例: Sony RC-S380）
- リーダーに libusb 互換ドライバーが割り当てられていること（[リーダーのドライバー設定](#リーダーのドライバー設定)を参照）
- インターネット接続（リモート認証サーバーとの通信に使用）

## インストール

### ビルド済み実行ファイル
リリースごとに `suica-viewer` と `suica-viewer-gui` の単体実行ファイルを配布しています。Python のインストールは不要です。[Releases](../../releases) から環境に合うファイルを、検証用の `SHA256SUMS.txt` とあわせてダウンロードしてください。

| 環境 | ファイル名の末尾 |
| --- | --- |
| Linux (x86_64) | `-linux-x86_64` |
| Windows (x86_64) | `-windows-x86_64.exe` |
| macOS (Apple Silicon) | `-macos-arm64` |
| macOS (Intel) | `-macos-x86_64` |

macOS 版は署名していないため、初回起動時に Gatekeeper がブロックします。「システム設定 → プライバシーとセキュリティ」から実行を許可してください。

実行ファイルを使う場合もリーダーのドライバー設定は必要で、Linux と macOS では libusb も別途必要です。[リーダーのドライバー設定](#リーダーのドライバー設定)を参照してください。

### ソースから

```bash
uv sync
```

## リーダーのドライバー設定
nfcpy は libusb 経由でリーダーと通信します。libusb が USB デバイスを掴めるドライバーが割り当てられている必要があります。

**Windows.** libusb 自体は同梱されていますが、既定では Windows がリーダーに独自のドライバーを割り当てており、libusb から開けません。[Zadig](https://zadig.akeo.ie/) でリーダーのドライバーを **WinUSB** に置き換えてください。置き換えると、デバイスマネージャーで元のドライバーに戻すまで、メーカー純正ソフト（Sony の NFC ポートソフトウェアなど）からはリーダーを利用できなくなります。

**Linux.** libusb をインストールし、ユーザーがデバイスへアクセスできるようにします。

```bash
sudo apt install libusb-1.0-0

# Sony RC-S380 (0x054c:0x06c1, 0x054c:0x06c3) 向けの udev ルール例
echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="054c", ATTRS{idProduct}=="06c3", GROUP="plugdev", MODE="0664"' \
  | sudo tee /etc/udev/rules.d/60-suica-viewer.rules
sudo udevadm control --reload-rules
```

ルールを追加しない場合は root 権限での実行が必要です。

**macOS.** libusb をインストールします。

```bash
brew install libusb
```

## 使い方 (CLI)
1. 対応する FeliCa リーダーを PC に接続
2. 必要であれば `AUTH_SERVER_URL` を設定し、リモートサーバーを指定
3. 下記コマンドでカードをかざすと、詳細情報がコンソールに出力

```bash
uv run suica-viewer
# 例:
# AUTH_SERVER_URL=https://example.com uv run suica-viewer
```

主な出力項目
- システム発行情報 (IDi, PMi)
- 発行情報 1・2（発行者／発行駅／有効期限など）
- 属性情報（カード種別・残高・取引通番）
- 取引履歴（入出場改札／物販／チャージなどを解析）
- 定期券情報、改札入出場情報、SF 改札入場情報

## 使い方 (GUI)
```bash
uv run suica-viewer-gui
```

GUI では以下の機能が利用できます。
- 起動後に自動で NFC リーダーをポーリングし、カードを検知すると進捗バーを表示しつつ読み出し
- 概要タブで主要項目を一覧表示
- 発行情報タブで発行者・駅・ID など詳細を表示
- 履歴タブでは取引履歴をテーブル表示し、入力ボックスで全文検索フィルタが可能 (`Ctrl+F` / `Cmd+F` でフォーカス)
- 改札タブで改札履歴・装置番号・金額・定期区間を表示、SF 改札入場情報も併記
- その他タブで未知フィールドの値を確認
- 詳細タブでカード情報 JSON を閲覧し、クリップボードへコピーまたはファイル出力

## 認証サーバーの設定
- 既定値: `https://felica-auth.nyaa.ws`
- 環境変数 `AUTH_SERVER_URL` にベース URL を指定すると切り替え可能です（末尾スラッシュは不要）。
- サーバーは以下のエンドポイントを提供する必要があります。
  - `POST /mutual-authentication`
  - `POST /encryption-exchange`
- 相互認証の途中ステップではカードとのコマンド／レスポンスを往復させる想定です。状況によっては個人情報やカード識別子が送信されるため、信頼できる環境のみに接続してください。

## 駅コードデータ
- `suica_viewer/station_codes.csv` に JR 東日本などの駅コードが格納されており、線区コードと駅順コードから会社名・路線名・駅名を解決します。
- CSV を差し替えることで独自のデータセットに変更することも可能です。

## トラブルシューティング
- `LIBUSB_ERROR_NOT_SUPPORTED [-12]`: libusb はリーダーを認識していますが、libusb 互換ドライバーが割り当てられていないため開けません。Windows では[リーダーのドライバー設定](#リーダーのドライバー設定)のとおり Zadig で WinUSB ドライバーを導入してください。管理者権限で実行しても解決しません（権限の問題なら `LIBUSB_ERROR_ACCESS` になります）。
- Linux で `LIBUSB_ERROR_ACCESS [-3]`: USB デバイスへのアクセス権限がありません。上記の udev ルールを追加するか、root 権限で実行してください。
- `NFC リーダーを初期化できません` / `No such device` と表示される場合: リーダーが接続されていないか、その USB ベンダー ID／プロダクト ID を nfcpy が認識していません。
- `サーバ通信エラー` が続く場合: 認証サーバー URL の設定やネットワーク接続を確認してください。必要に応じて `AUTH_SERVER_URL` を変更します。
- `FeliCa 以外のタグを検出しました` と表示される場合: 対応カードをかざしているかを確認してください。

## 開発向けメモ
- コード整形: `uv run black suica_viewer`
- GUI のホットリロードはありません。UI 変更時はアプリを再起動してください。
- 既存の `__pycache__` などビルド成果物はリポジトリに含まれていないため、必要に応じてクリーンアップしてください。

### 実行ファイルをローカルでビルドする
```bash
uv sync --group build
uv run pyinstaller packaging/suica-viewer.spec
```

成果物は `dist/` に出力されます。ビルドにはリンカーが Tcl/Tk ライブラリを解決できる Python を使ってください。uv が管理する CPython は Tcl/Tk 9 を同梱しており、その共有ライブラリを PyInstaller が収集できないため、`import tkinter` で即座にクラッシュする GUI バイナリができてしまいます。spec はこれを検出してビルドを失敗させます。リリースが CI で `actions/setup-python` を使っているのはこのためです。

`v*` タグを push すると [`.github/workflows/release.yml`](.github/workflows/release.yml) が全プラットフォームのビルドを行い、実行ファイルを GitHub Release に添付します。

## 開発者

- KIRISHIKI Yudai

## ライセンス

[MIT](https://opensource.org/licenses/MIT)

Copyright (c) 2025 KIRISHIKI Yudai
