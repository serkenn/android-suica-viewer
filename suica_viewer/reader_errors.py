import errno
import sys

import usb1

ZADIG_URL = "https://zadig.akeo.ie/"

_WINUSB_HINT = (
    "リーダーに WinUSB 互換ドライバがバインドされていません。"
    f"Zadig ({ZADIG_URL}) でリーダーのドライバを WinUSB に置き換えてください。"
)

_LINUX_ACCESS_HINT = (
    "リーダーへのアクセス権がありません。"
    "udev ルールを追加するか、root 権限で実行してください。"
)

_NO_READER_HINT = "USB に接続されたリーダーが見つかりません。接続を確認してください。"


def describe_reader_error(exc: BaseException) -> str:
    """リーダー初期化エラーに、分かる範囲で対処方法を添えて返す。

    usb1 の USBError は OSError を継承しないため nfcpy の ``except IOError`` を
    すり抜ける。そのままでは LIBUSB_ERROR_NOT_SUPPORTED のような素の値しか
    呼び出し側に届かない。
    """
    hint = _hint_for(exc)
    return f"{exc}\n\n{hint}" if hint else str(exc)


def _hint_for(exc: BaseException) -> str | None:
    if isinstance(exc, usb1.USBErrorNotSupported) and sys.platform == "win32":
        return _WINUSB_HINT
    if isinstance(exc, usb1.USBErrorAccess) and sys.platform.startswith("linux"):
        return _LINUX_ACCESS_HINT
    if isinstance(exc, OSError) and exc.errno == errno.ENODEV:
        return _NO_READER_HINT
    return None
