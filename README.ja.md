# Suica Viewer for Android

Suica Viewer は、FeliCa 系交通 IC カード（Suica・PASMO・ICOCA など）をスマートフォンの
NFC で読み取り、残高・発行情報・取引履歴・定期券情報・改札記録を表示するアプリです。
Kotlin + Jetpack Compose 実装で、専用リーダーは不要です。

English: [README.md](README.md)

## 仕組み

カードの暗号化領域を読むには鍵を持つ側でしか行えない相互認証が必要なため、その部分だけを
リモートの認証サーバーに任せています。サーバーが認証フレームを組み立て、アプリがそれを
カードに流し、カードの応答をサーバーに返す、という往復です。

サーバーの関与はそこまでです。認証が完了するとサーバーは一時セッション情報を返してセッションを
破棄し、以降の暗号化リードはアプリ自身が実行します。つまり **カードの中身がネットワークに出ることは
なく**、長期鍵がサーバーから出ることもありません。

## 主な機能

- カード識別情報（IDm / PMm / IDi / PMi）と発行者
- 発行情報（取り込み済み＝無効カードのフラグを含む）
- 残高と属性フラグ（音声案内サービス、定期有効期間外のSF利用、タッチでGo！新幹線）
- 取引履歴（最大 20 件、1 件ごとの残高差分つき、全文フィルタ対応）
- 定期券情報（区間・券番・発売額・購入時支払方法・R通番・通学証明書省略期限）
- オートチャージの契約状況・有効状態・しきい値・チャージ額
- 改札入出場情報、SF改札入場情報、料金発券・改札情報（カードが該当サービスを持つ場合）
- `station_codes.csv` による会社名・路線名・駅名の解決
- カード情報全体の JSON コピー／共有

## 動作条件

- Android 8.0（API 26）以降、かつ FeliCa 対応の NFC を搭載した端末（いわゆる「おサイフケータイ」
  対応機種）
- 認証サーバーと通信できるネットワーク

## インストール

[Releases](../../releases) から `suica-viewer-android-<タグ>.apk` をダウンロードして
インストールしてください。リリース APK はプロジェクトのリリース鍵で署名されています。

## 認証サーバーの設定

既定の認証サーバーは `https://felica-auth.nyaa.ws` です。アプリバーの **設定** から
自前のサーバーなど別の URL に変更できます。設定は端末に保存され、空欄で保存すると既定値に
戻ります。

サーバー側には `POST /mutual-authentication` が必要で、認証完了時にセキュアセッション情報
（`result.session` の `key` / `transaction_id` / `transaction_number`）を返す実装である
必要があります。認証中は IDm・PMm・カードの発行識別子がサーバーを経由するため、信頼できる
サーバーのみに接続してください。

## ローカルビルド

```bash
./gradlew assembleRelease
```

生成物: `app/build/outputs/apk/release/app-release-unsigned.apk`

リリース署名は環境変数 `ANDROID_KEYSTORE_PATH` / `ANDROID_KEYSTORE_PASSWORD` /
`ANDROID_KEY_ALIAS` で行います。未設定の場合、リリースビルドは未署名のままになります
（デバッグビルドには影響しません）。

`v*` タグを push すると [`.github/workflows/android-release.yml`](.github/workflows/android-release.yml)
が APK をビルドし、リポジトリのシークレットにあるキーストアで署名して GitHub Release に添付します。

## 駅コードデータ

`app/src/main/assets/station_codes.csv` に JR 東日本などの駅コードが入っており、線区コードと
駅順コードから会社名・路線名・駅名を解決します。差し替えれば独自データセットも利用できます。

## 備考

- 以前このリポジトリに含まれていたデスクトップ版（Python）は削除しました。PC 版が必要な場合は
  上流の [soltia48/suica-viewer](https://github.com/soltia48/suica-viewer) を参照してください。
  本リポジトリは Android アプリ専用です。

## 開発者

- KIRISHIKI Yudai

## ライセンス

[MIT](https://opensource.org/licenses/MIT)

Copyright (c) 2025 KIRISHIKI Yudai
