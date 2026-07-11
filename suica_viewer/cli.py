import argparse
import json
import sys
import unicodedata

import nfc
import usb1
from nfc.clf import RemoteTarget
from nfc.tag import Tag
from nfc.tag.tt3_sony import FelicaStandard

from .auth_client import FelicaRemoteClient, FelicaRemoteClientError
from .card_data import (
    CardData,
    CardDataService,
    resolve_server_url,
)
from .reader_errors import describe_reader_error
from .station_code_lookup import StationCodeLookup
from .utils import SYSTEM_CODE, format_region, format_yen


# --------------------------------------------------------------------------- #
# Terminal helpers                                                            #
# --------------------------------------------------------------------------- #
def _char_width(char: str) -> int:
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def display_width(text: str) -> int:
    """Terminal column width of *text*, counting full-width glyphs as 2."""
    return sum(_char_width(char) for char in text)


def truncate(text: str, width: int) -> str:
    if display_width(text) <= width:
        return text
    out: list[str] = []
    used = 0
    for char in text:
        char_w = _char_width(char)
        if used + char_w > width - 1:
            break
        out.append(char)
        used += char_w
    return "".join(out) + "…"


def fit(text: str, width: int, *, align: str = "left") -> str:
    """Pad/truncate *text* to exactly *width* terminal columns."""
    text = truncate(text, width)
    padding = " " * max(0, width - display_width(text))
    return padding + text if align == "right" else text + padding


class Palette:
    """ANSI styling that collapses to a no-op when color is disabled."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def cyan(self, text: str) -> str:
        return self._wrap("36", text)

    def green(self, text: str) -> str:
        return self._wrap("32", text)


# --------------------------------------------------------------------------- #
# Value formatting                                                            #
# --------------------------------------------------------------------------- #
def _yen_compact(value: object) -> str:
    return f"¥{value:,}" if isinstance(value, int) else "—"


def _format_delta(value: object) -> str:
    if not isinstance(value, int):
        return "—"
    if value > 0:
        return f"+{value:,}"
    return f"{value:,}"


def _clean_station(name: object) -> str:
    if not isinstance(name, str) or not name or name.startswith("不明"):
        return ""
    return name


def _route_or_time(entry: dict) -> str:
    if "transaction_time" in entry:
        return entry["transaction_time"]
    entry_station = _clean_station(entry.get("entry_station"))
    exit_station = _clean_station(entry.get("exit_station"))
    if entry_station and exit_station:
        return f"{entry_station} → {exit_station}"
    return entry_station or exit_station or "—"


def _hhmm(hex_clock: object) -> str:
    if isinstance(hex_clock, str) and len(hex_clock) >= 4:
        return f"{hex_clock[0:2]}:{hex_clock[2:4]}"
    return "—"


# --------------------------------------------------------------------------- #
# Rendering                                                                   #
# --------------------------------------------------------------------------- #
class TextReport:
    """Renders :class:`CardData` as a colored, aligned console report."""

    def __init__(self, palette: Palette, *, verbose: bool) -> None:
        self.palette = palette
        self.verbose = verbose
        self.lines: list[str] = []

    def render(self, card: CardData) -> str:
        self.lines = []
        self._banner("Suica カード情報")
        self._quick_summary(card)
        self._identification(card)
        self._issue_information(card)
        self._attribute_information(card)
        self._last_topup(card)
        if self.verbose:
            self._misc_information(card)
        self._transaction_history(card)
        self._commuter_pass(card)
        self._gate_history(card)
        self._sf_gate(card)
        self._paid_ticket(card)
        return "\n".join(self.lines)

    # -- building blocks ---------------------------------------------------- #
    def _banner(self, title: str) -> None:
        inner = f"  {title}  "
        bar = "━" * display_width(inner)
        self.lines.append(self.palette.cyan(bar))
        self.lines.append(self.palette.bold(self.palette.cyan(inner)))
        self.lines.append(self.palette.cyan(bar))

    def _section(self, title: str) -> None:
        self.lines.append("")
        self.lines.append(self.palette.bold(title))
        self.lines.append(self.palette.dim("─" * display_width(title)))

    def _kv(self, pairs: list[tuple[str, str]], *, indent: str = "  ") -> None:
        width = max((display_width(label) for label, _ in pairs), default=0)
        for label, value in pairs:
            self.lines.append(f"{indent}{self.palette.dim(fit(label, width))}  {value}")

    def _quick_summary(self, card: CardData) -> None:
        balance = card.attribute.get("balance")
        pairs = [
            (
                "残高",
                (
                    self.palette.bold(self.palette.green(format_yen(balance)))
                    if isinstance(balance, int)
                    else "—"
                ),
            ),
            ("カード種別", card.attribute.get("card_type", "—")),
            ("発行者", card.issue_primary.get("issuer_id", "—")),
            ("有効期限", card.issue_primary.get("expires_at", "—")),
        ]
        self.lines.append("")
        self._kv(pairs, indent="  ")

    def _identification(self, card: CardData) -> None:
        self._section("カード識別")
        self._kv(
            [
                ("IDm", card.system.idm_hex),
                ("PMm", card.system.pmm_hex),
                ("IDi", card.system.idi_display),
                ("PMi", card.system.pmi),
            ]
        )

    def _issue_information(self, card: CardData) -> None:
        issue = card.issue_primary
        self._section("発行情報")
        pairs = [
            ("所有者名", issue.get("owner_name") or "—"),
            ("生年月日", issue.get("owner_birthdate", "—")),
            ("第二発行ID", issue.get("secondary_issue_id", "—")),
            ("発行者ID", issue.get("issuer_id", "—")),
            ("発行機器", issue.get("issued_by", "—")),
            ("発行駅", issue.get("issued_station", "—")),
            ("発行日", issue.get("issued_at", "—")),
            ("有効期限", issue.get("expires_at", "—")),
            ("デポジット額", format_yen(issue.get("deposit", 0))),
        ]
        if self.verbose:
            pairs.insert(2, ("電話番号(hex)", issue.get("owner_phone_hex") or "—"))
            pairs.insert(3, ("年齢コード", issue.get("owner_age_code", "—")))
        self._kv(pairs)

    def _attribute_information(self, card: CardData) -> None:
        attr = card.attribute
        self._section("属性情報")
        pairs = [
            ("カード種別", attr.get("card_type", "—")),
            ("残高", format_yen(attr.get("balance", 0))),
            ("取引通番", f"{attr.get('transaction_number', 0):,}"),
        ]
        if self.verbose:
            pairs.append(("地域コード", format_region(attr.get("region", 0))))
        self._kv(pairs)

    def _last_topup(self, card: CardData) -> None:
        topup = card.last_topup
        self._section("最終チャージ情報")
        self._kv(
            [
                ("チャージ機器", topup.get("equipment", "—")),
                ("チャージ駅", topup.get("station", "—")),
                ("チャージ金額", format_yen(topup.get("amount", 0))),
            ]
        )

    def _misc_information(self, card: CardData) -> None:
        misc = card.unknown
        self._section("その他情報（用途未確定）")
        self._kv(
            [
                ("不明な残高", format_yen(misc.get("balance", 0))),
                ("不明な日付", misc.get("date", "—")),
                ("不明な取引通番", f"{misc.get('transaction_number', 0):,}"),
            ]
        )

    def _transaction_history(self, card: CardData) -> None:
        entries = card.transaction_history
        self._section(f"取引履歴（新しい順・{len(entries)}件）")
        if not entries:
            self.lines.append(self.palette.dim("  （記録なし）"))
            return

        widths = (3, 10, 14, 9, 9)
        headers = ("No", "日付", "種別", "差額", "残高", "経路 / 時刻")
        self._table_header(headers, widths)
        for entry in entries:
            delta = entry.get("delta")
            cells = [
                fit(str(entry["index"] + 1), widths[0], align="right"),
                fit(entry["recorded_on"], widths[1]),
                fit(entry.get("transaction_type", "—"), widths[2]),
                fit(_format_delta(delta), widths[3], align="right"),
                fit(_yen_compact(entry.get("balance")), widths[4], align="right"),
                _route_or_time(entry),
            ]
            if isinstance(delta, int) and delta > 0:
                cells[3] = self.palette.green(cells[3])
            self.lines.append("  " + "  ".join(cells))

    def _commuter_pass(self, card: CardData) -> None:
        self._section("定期情報")
        if not card.has_commuter_pass:
            self.lines.append(self.palette.dim("  （定期券なし）"))
            return
        commuter = card.commuter
        pairs = [
            (
                "区間",
                f"{commuter.get('start_station', '—')} → "
                f"{commuter.get('end_station', '—')}",
            ),
            ("有効期間", f"{commuter.get('valid_from')} 〜 {commuter.get('valid_to')}"),
            ("発行日", commuter.get("issued_at", "—")),
        ]
        via1 = _clean_station(commuter.get("via1_station"))
        via2 = _clean_station(commuter.get("via2_station"))
        vias = " / ".join(v for v in (via1, via2) if v)
        if vias:
            pairs.insert(1, ("経由", vias))
        self._kv(pairs)

    def _gate_history(self, card: CardData) -> None:
        entries = card.gate
        self._section(f"改札入出場情報（{len(entries)}件）")
        if not entries:
            self.lines.append(self.palette.dim("  （記録なし）"))
            return

        widths = (3, 17, 14, 9)
        headers = ("No", "日時", "入出場種別", "金額", "駅")
        self._table_header(headers, widths)
        for entry in entries:
            timestamp = f"{entry.get('date', '—')} {entry.get('time', '')}".strip()
            cells = [
                fit(str(entry["index"] + 1), widths[0], align="right"),
                fit(timestamp, widths[1]),
                fit(entry.get("gate_in_out_type", "—"), widths[2]),
                fit(_yen_compact(entry.get("amount")), widths[3], align="right"),
                entry.get("station", "—"),
            ]
            self.lines.append("  " + "  ".join(cells))
            if self.verbose:
                self.lines.append(
                    self.palette.dim(
                        f"       装置番号 {entry.get('device_id_hex', '—')} / "
                        f"中間処理 {entry.get('intermediate_gate_instruction_type', '—')} / "
                        f"定期運賃 {_yen_compact(entry.get('commuter_pass_fee'))} / "
                        f"最寄定期駅 {entry.get('commuter_station', '—')}"
                    )
                )

    def _sf_gate(self, card: CardData) -> None:
        sf = card.sf_gate
        self._section("SF改札入場情報")
        if not sf.get("has_record"):
            self.lines.append(self.palette.dim("  （記録なし）"))
            return
        pairs = [
            ("入場駅", sf.get("entry_station", "—")),
            ("中間改札入場駅", sf.get("intermediate_entry_station", "—")),
            (
                "中間改札入場",
                f"{sf.get('intermediate_entry_date', '—')} "
                f"{_hhmm(sf.get('intermediate_entry_time'))}",
            ),
            ("中間改札出場駅", sf.get("intermediate_exit_station", "—")),
            ("中間改札出場時刻", _hhmm(sf.get("intermediate_exit_time"))),
        ]
        if self.verbose:
            pairs.append(("不明値1", sf.get("unknown_value1_hex", "—")))
            pairs.append(("不明値2", sf.get("unknown_value2_hex", "—")))
        self._kv(pairs)

    def _paid_ticket(self, card: CardData) -> None:
        entries = card.paid_ticket
        self._section(f"料金発券・改札情報（{len(entries)}件）")
        if not entries:
            reason = card.paid_ticket_reason or "（記録なし）"
            self.lines.append(self.palette.dim(f"  {reason}"))
            return

        widths = (3, 10, 9, 8)
        headers = ("No", "有効期限", "金額", "発券時刻", "区間（発→着）")
        self._table_header(headers, widths)
        for entry in entries:
            cells = [
                fit(str(entry["index"] + 1), widths[0], align="right"),
                fit(entry.get("expires_at", "—"), widths[1]),
                fit(_yen_compact(entry.get("amount")), widths[2], align="right"),
                fit(entry.get("issued_time", "—"), widths[3]),
                f"{entry.get('depart_station', '—')} → {entry.get('arrive_station', '—')}",
            ]
            self.lines.append("  " + "  ".join(cells))
            if self.verbose:
                self.lines.append(
                    self.palette.dim(
                        f"       発券種別 {entry.get('issue_type_hex', '—')} / "
                        f"装置番号 {entry.get('device_id_hex', '—')} / "
                        f"改札実施 {entry.get('checked_station', '—')} "
                        f"{entry.get('checked_time', '—')}"
                    )
                )

    def _table_header(self, headers: tuple[str, ...], widths: tuple[int, ...]) -> None:
        cells = []
        for index, header in enumerate(headers):
            if index < len(widths):
                align = "right" if header in ("No", "差額", "残高", "金額") else "left"
                cells.append(fit(header, widths[index], align=align))
            else:
                cells.append(header)
        self.lines.append("  " + self.palette.dim("  ".join(cells)))


# --------------------------------------------------------------------------- #
# NFC flow                                                                     #
# --------------------------------------------------------------------------- #
class CliRunner:
    """Holds the shared state the nfcpy connect callback needs."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.json_output: bool = args.json
        self.verbose: bool = args.verbose
        self.server_url: str = resolve_server_url(args.server)
        color_enabled = (
            not args.no_color and not self.json_output and sys.stdout.isatty()
        )
        self.palette = Palette(color_enabled)
        self.station_code_lookup = StationCodeLookup()
        self.service = CardDataService(self.station_code_lookup)

    def on_connect(self, tag: Tag) -> None:
        if not isinstance(tag, FelicaStandard):
            print("FeliCa 以外のタグを検出しました。", file=sys.stderr)
            return

        polling_result = tag.polling(SYSTEM_CODE)
        if len(polling_result) != 2:
            print("Polling 応答が不正です。", file=sys.stderr)
            return
        tag.idm, tag.pmm = polling_result

        print("カードを読み取っています…", file=sys.stderr, flush=True)
        client = FelicaRemoteClient(self.server_url, tag)
        try:
            card = self.service.collect(client)
        except FelicaRemoteClientError as exc:
            print(f"サーバ通信エラー: {exc}", file=sys.stderr)
            return
        except Exception as exc:
            print(f"カード情報の取得に失敗しました: {exc}", file=sys.stderr)
            return
        finally:
            client.close()

        if self.json_output:
            print(json.dumps(card.to_serializable_dict(), ensure_ascii=False, indent=2))
        else:
            report = TextReport(self.palette, verbose=self.verbose)
            print(report.render(card))


def on_startup(targets: list[RemoteTarget]) -> list[RemoteTarget]:
    return targets


def fix_ic_code_map() -> None:
    FelicaStandard.IC_CODE_MAP[0x31] = ("RC-S???", 1, 1)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="suica-viewer",
        description="FeliCa 交通系ICカードの詳細情報を読み取って表示します。",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="人間向けの表ではなく JSON を出力する。",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="装置番号・生コードなどの詳細フィールドも表示する。",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="ANSI カラー出力を無効化する（NO_COLOR / 非TTY でも自動的に無効）。",
    )
    parser.add_argument(
        "--server",
        metavar="URL",
        default=None,
        help="認証サーバの URL（未指定なら AUTH_SERVER_URL 環境変数か既定値）。",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    fix_ic_code_map()

    try:
        runner = CliRunner(args)
    except Exception as exc:
        raise SystemExit(f"初期化に失敗しました: {exc}")

    # usb1 raises USBError, which does not derive from OSError, so nfcpy's own
    # `except IOError` lets it through and the user sees a bare traceback.
    try:
        clf = nfc.ContactlessFrontend("usb")
    except (OSError, usb1.USBError) as exc:
        raise SystemExit(
            f"NFC リーダーを初期化できません: {describe_reader_error(exc)}"
        )

    with clf:
        if not args.json:
            print("カードをかざしてください。", file=sys.stderr, flush=True)
        clf.connect(
            rdwr={
                "targets": ["212F", "424F"],  # FeliCa only
                "on-startup": on_startup,
                "on-connect": runner.on_connect,
            }
        )


if __name__ == "__main__":
    main()
