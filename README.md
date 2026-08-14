# Suica Viewer for Android

Suica Viewer reads FeliCa-based transit IC cards (Suica, PASMO, ICOCA and the
rest of the family) with your phone's NFC and shows what is on them: balance,
issuance data, transaction history, commuter pass details and gate records.
Kotlin + Jetpack Compose, no reader hardware required.

Japanese: [README.ja.md](README.ja.md)

## How it works

The card's encrypted areas need a mutual authentication that only the card's key
holder can perform, so the app does that part through a remote authentication
server: the server builds each authentication frame, the app puts it on the card
and sends the card's reply back.

That is the server's whole involvement. On success it returns the ephemeral
session material and forgets the session, and the app runs the encrypted reads
itself — so **the card's contents never cross the network**, and the long-term
keys never leave the server.

## Features

- Card identity (IDm / PMm / IDi / PMi) and issuer
- Issuance info, including the collected (invalidated) card flag
- Balance and attribute flags (voice guidance, SF use outside the commuter
  period, Touch de Go! Shinkansen)
- Transaction history (up to 20 entries) with the balance change per entry, and
  full-text filtering
- Commuter pass details: route, pass number, sale price, purchase payment
  method, R number, student certificate expiry
- Auto-charge contract, enabled state, threshold and amount
- Gate entry/exit records, SF gate records, and paid-ticket / express-gate
  records when the card carries that service
- Resolves company, line and station names from `station_codes.csv`
- Copy or share the whole card as JSON

## Requirements

- Android 8.0 (API 26) or later, with FeliCa-capable NFC hardware (this means a
  phone sold in Japan, or one whose NFC chip carries the FeliCa firmware)
- Internet connectivity for the authentication server

## Install

Grab `suica-viewer-android-<tag>.apk` from the [Releases](../../releases) page
and install it. Releases are signed with the project's release key.

## Auth server setting

The app ships with `https://felica-auth.nyaa.ws` as its default authentication
server. Tap **設定** in the app bar to point it at another one — for example your
own instance. The value is stored on the device; saving an empty field restores
the default.

A server has to expose `POST /mutual-authentication` and return the secure
session material (`result.session`: `key`, `transaction_id`,
`transaction_number`) when the authentication completes. Only connect to servers
you trust: the IDm, PMm and the card's issue identifiers pass through them
during authentication.

## Build locally

```bash
./gradlew assembleRelease
```

Output: `app/build/outputs/apk/release/app-release-unsigned.apk`

Release signing is driven by the `ANDROID_KEYSTORE_PATH`,
`ANDROID_KEYSTORE_PASSWORD` and `ANDROID_KEY_ALIAS` environment variables; when
they are absent the release build stays unsigned. Debug builds are unaffected.

Pushing a `v*` tag runs
[`.github/workflows/android-release.yml`](.github/workflows/android-release.yml),
which builds the APK, signs it with the keystore from the repository secrets and
attaches it to the GitHub release.

## Station code data

`app/src/main/assets/station_codes.csv` carries the JR East and other station
codes the app resolves line/station names from. Replace it to use a custom
dataset.

## Notes

- The desktop (Python) viewer that used to live here has been removed; upstream
  [soltia48/suica-viewer](https://github.com/soltia48/suica-viewer) is the place
  to look for a PC client. This repository is the Android app only.

## Author

- KIRISHIKI Yudai

## License

[MIT](https://opensource.org/licenses/MIT)

Copyright (c) 2025 KIRISHIKI Yudai
