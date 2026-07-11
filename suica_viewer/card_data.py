"""Shared card-reading data layer used by both the CLI and the GUI.

This module deliberately avoids importing ``tkinter`` or ``nfc`` so the CLI can
use it in headless environments. It owns the encrypted-block reader, the raw
byte parsing, and the assembled :class:`CardData` structure that both front
ends render.
"""

import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Callable

from .auth_client import FelicaRemoteClient
from .station_code_lookup import StationCodeLookup
from .utils import (
    CARD_TYPE_LABELS,
    SYSTEM_CODE,
    equipment_type_to_str,
    format_birth_date,
    format_date,
    format_station,
    format_time,
    gate_in_out_type_to_str,
    gate_instruction_type_to_str,
    idi_bytes_to_str,
    intermadiate_gate_instruction_type_to_str,
    issuer_id_to_str,
    pay_type_to_str,
    transaction_type_to_str,
)

AREA_NODE_IDS: tuple[int, ...] = (0x0000, 0x0040, 0x0800, 0x0FC0, 0x1000)
SERVICE_NODE_IDS: tuple[int, ...] = (
    0x0048,
    0x0088,
    0x0810,
    0x08C8,
    0x090C,
    0x1008,
    0x1048,
    0x108C,
    0x10C8,
)

# Paid-ticket / express-gate service (料金発券・改札情報). Not present on every
# card, and reading it needs its own key, so it is probed and authenticated
# only when the card actually carries it (see CardDataService.collect).
PAID_TICKET_SERVICE_NODE_ID = 0x1848

READ_COMMAND_CODE = 0x14
DATA_BLOCK_SIZE = 16
MAX_BLOCKS_PER_REQUEST = 9
DEFAULT_AUTH_SERVER_URL = "https://felica-auth.nyaa.ws"

# Purchase (物販) transactions store a clock instead of entry/exit stations.
PURCHASE_TRANSACTION_TYPE = 0x46

ProgressCallback = Callable[[float], None]


def resolve_server_url(override: str | None = None) -> str:
    """Resolve the auth server URL from an explicit override, env, or default."""
    if override:
        return override.strip()
    value = os.environ.get("AUTH_SERVER_URL", "").strip()
    return value or DEFAULT_AUTH_SERVER_URL


class RemoteCardReader:
    """Proxy that issues encrypted read commands through the remote server."""

    def __init__(self, client: FelicaRemoteClient) -> None:
        self.client = client

    def read_blocks(self, service_index: int, indexes: Iterable[int]) -> list[bytes]:
        index_list = list(indexes)
        blocks: list[bytes] = []
        for chunk_start in range(0, len(index_list), MAX_BLOCKS_PER_REQUEST):
            chunk = index_list[chunk_start : chunk_start + MAX_BLOCKS_PER_REQUEST]
            if not chunk:
                continue
            elements = [(service_index, block_index) for block_index in chunk]
            blocks.extend(self._read_elements(elements))
        return blocks

    def _read_elements(self, elements: list[tuple[int, int]]) -> list[bytes]:
        payload = bytes([len(elements)]) + self._elements_to_bytes(elements)
        response = self.client.encryption_exchange(READ_COMMAND_CODE, payload)
        if len(response) < 3:
            raise RuntimeError("リモートサーバーからの応答が不正です。")

        status_flag1, status_flag2 = response[0], response[1]
        if status_flag1 != 0x00:
            status_code = (status_flag1 << 8) | status_flag2
            raise RuntimeError(f"カードがエラーを返しました: 0x{status_code:04X}")

        expected_blocks = len(elements)
        block_count = response[2]
        if block_count != expected_blocks:
            raise RuntimeError("取得したブロック数が一致しません。")

        block_payload = response[3:]
        expected_length = expected_blocks * DATA_BLOCK_SIZE
        if len(block_payload) < expected_length:
            raise RuntimeError("ブロックデータの長さが不正です。")
        block_payload = block_payload[:expected_length]

        return [
            block_payload[i * DATA_BLOCK_SIZE : (i + 1) * DATA_BLOCK_SIZE]
            for i in range(expected_blocks)
        ]

    @staticmethod
    def _elements_to_bytes(elements: list[tuple[int, int]]) -> bytes:
        encoded = bytearray()
        for service_index, block_number in elements:
            if not 0 <= service_index < 16:
                raise ValueError(
                    "サービスインデックスは 0 から 15 の範囲である必要があります。"
                )
            if not 0 <= block_number < 256:
                raise ValueError(
                    "ブロック番号は 0 から 255 の範囲である必要があります。"
                )
            encoded.append(0x80 | service_index)
            encoded.append(block_number & 0xFF)
        return bytes(encoded)


@dataclass
class SystemInfo:
    idm_hex: str
    pmm_hex: str
    idi_hex: str
    idi_display: str
    pmi: str


@dataclass
class CardData:
    system: SystemInfo
    issue_primary: dict[str, Any]
    attribute: dict[str, Any]
    last_topup: dict[str, Any]
    unknown: dict[str, Any]
    transaction_history: list[dict[str, Any]]
    commuter: dict[str, Any]
    gate: list[dict[str, Any]]
    sf_gate: dict[str, Any]
    paid_ticket: list[dict[str, Any]] = field(default_factory=list)
    paid_ticket_available: bool = False
    paid_ticket_reason: str | None = None

    def to_serializable_dict(self) -> dict[str, Any]:
        return {
            "system": {
                "idm_hex": self.system.idm_hex,
                "pmm_hex": self.system.pmm_hex,
                "idi_hex": self.system.idi_hex,
                "idi_display": self.system.idi_display,
                "pmi": self.system.pmi,
            },
            "issue_primary": dict(self.issue_primary),
            "attribute": dict(self.attribute),
            "last_topup": dict(self.last_topup),
            "unknown": dict(self.unknown),
            "transaction_history": [dict(entry) for entry in self.transaction_history],
            "commuter": dict(self.commuter),
            "gate": [dict(entry) for entry in self.gate],
            "sf_gate": dict(self.sf_gate),
            "paid_ticket": [dict(entry) for entry in self.paid_ticket],
            "paid_ticket_available": self.paid_ticket_available,
            "paid_ticket_reason": self.paid_ticket_reason,
        }

    @property
    def has_commuter_pass(self) -> bool:
        """True when the card carries a usable commuter pass record."""
        return self.commuter.get("valid_from") not in (None, "", "—")


class SuicaCardDataExtractor:
    """Extracts structured data from a Suica FeliCa tag."""

    def __init__(
        self,
        reader: RemoteCardReader,
        station_code_lookup: StationCodeLookup,
    ) -> None:
        self.reader = reader
        self.station_code_lookup = station_code_lookup

    def _format_station(self, line_code: int, station_order: int) -> str:
        return format_station(self.station_code_lookup, line_code, station_order)

    def _read_blocks(self, service_index: int, indexes: Iterable[int]) -> list[bytes]:
        return self.reader.read_blocks(service_index, indexes)

    def _read_single_block(self, service_code: int, index: int) -> bytes:
        return self._read_blocks(service_code, [index])[0]

    def read_issue_information_primary(self) -> dict[str, Any]:
        owner_block, personal_block, secondary_idi_block, metadata_block = (
            self._read_blocks(0, range(4))
        )

        try:
            owner_name = owner_block.decode("shift_jis").rstrip()
        except UnicodeDecodeError:
            owner_name = owner_block.decode("shift_jis", errors="ignore").rstrip()

        phone_number = personal_block[0:8].hex().upper().rstrip("F")
        age_code = personal_block[8:9].hex().upper()
        dob = int.from_bytes(personal_block[9:11], byteorder="big")
        deposit = int.from_bytes(personal_block[12:14], byteorder="little")
        issuer_id_hex = metadata_block[0:2].hex().upper()
        issuer_id = issuer_id_to_str(issuer_id_hex)
        issued_by_code = metadata_block[2]
        issued_by = equipment_type_to_str(issued_by_code)
        issued_station_line = metadata_block[3]
        issued_station_order = metadata_block[4]
        issued_station = self._format_station(issued_station_line, issued_station_order)
        issued_at = int.from_bytes(metadata_block[7:9], byteorder="big")
        expires_at = int.from_bytes(metadata_block[14:16], byteorder="big")

        return {
            "owner_name": owner_name,
            "secondary_issue_id": idi_bytes_to_str(secondary_idi_block),
            "owner_phone_hex": phone_number,
            "owner_age_code": age_code,
            "owner_birthdate": format_birth_date(dob),
            "deposit": deposit,
            "issuer_id": issuer_id,
            "issuer_id_hex": issuer_id_hex,
            "issued_by_code": issued_by_code,
            "issued_by": issued_by,
            "issued_station": issued_station,
            "issued_at": format_date(issued_at),
            "expires_at": format_date(expires_at),
        }

    def read_attribute_information(self) -> dict[str, Any]:
        block = self._read_single_block(1, 0)

        card_type_code = block[8] >> 4
        card_type_label = CARD_TYPE_LABELS.get(card_type_code, "不明")
        region_code = block[8] & 0x0F
        amount = int.from_bytes(block[11:13], byteorder="little")
        transaction_number = int.from_bytes(block[14:16], byteorder="big")

        return {
            "card_type_code": card_type_code,
            "card_type": card_type_label,
            "region": region_code,
            "balance": amount,
            "transaction_number": transaction_number,
        }

    def read_unknown_information(self) -> dict[str, Any]:
        block = self._read_single_block(2, 0)

        amount = int.from_bytes(block[0:2], byteorder="little")
        issued_at = int.from_bytes(block[8:10], byteorder="big")
        transaction_number = int.from_bytes(block[14:16], byteorder="big")

        return {
            "balance": amount,
            "date": format_date(issued_at),
            "transaction_number": transaction_number,
        }

    def read_last_topup_information(self) -> dict[str, Any]:
        detail_block, *_ = self._read_blocks(3, range(3))

        equipment_code = detail_block[0]
        station_line = detail_block[1]
        station_order = detail_block[2]
        station = self._format_station(station_line, station_order)
        amount = int.from_bytes(detail_block[5:7], byteorder="little")

        return {
            "equipment_code": equipment_code,
            "equipment": equipment_type_to_str(equipment_code),
            "station": station,
            "amount": amount,
        }

    def read_transaction_history(self) -> list[dict[str, Any]]:
        blocks = self._read_blocks(4, range(20))
        entries: list[dict[str, Any]] = []

        for index, block in enumerate(blocks):
            recorded_by = block[0]
            if recorded_by == 0x00:
                break

            transaction_type_code = block[1] & 0x7F
            pay_type_code = block[2]
            gate_instruction_type_code = block[3]
            recorded_at = int.from_bytes(block[4:6], byteorder="big")

            entry: dict[str, Any] = {
                "index": index,
                "recorded_on": format_date(recorded_at),
                "recorded_by_code": recorded_by,
                "recorded_by": equipment_type_to_str(recorded_by),
                "transaction_type_code": transaction_type_code,
                "transaction_type": transaction_type_to_str(transaction_type_code),
                "pay_type_code": pay_type_code,
                "pay_type": pay_type_to_str(pay_type_code),
                "gate_instruction_type_code": gate_instruction_type_code,
                "gate_instruction_type": gate_instruction_type_to_str(
                    gate_instruction_type_code
                ),
            }

            if transaction_type_code == PURCHASE_TRANSACTION_TYPE:
                time_value = int.from_bytes(block[6:8], byteorder="big")
                entry["transaction_time"] = format_time(time_value)
            else:
                entry_station_line = block[6]
                entry_station_order = block[7]
                exit_station_line = block[8]
                exit_station_order = block[9]
                entry["entry_station"] = self._format_station(
                    entry_station_line, entry_station_order
                )
                entry["exit_station"] = self._format_station(
                    exit_station_line, exit_station_order
                )

            amount = int.from_bytes(block[10:12], byteorder="little")
            transaction_number = int.from_bytes(block[13:15], byteorder="big")
            entry["balance"] = amount
            entry["transaction_number"] = transaction_number

            entries.append(entry)

        _annotate_balance_deltas(entries)
        return entries

    def read_commuter_pass_information(self) -> dict[str, Any]:
        primary_block, _, supplemental_block = self._read_blocks(6, range(3))

        start_at = int.from_bytes(primary_block[0:2], byteorder="big")
        end_at = int.from_bytes(primary_block[2:4], byteorder="big")
        via1_station = self._format_station(primary_block[12], primary_block[13])
        via2_station = self._format_station(primary_block[14], primary_block[15])

        return {
            "valid_from": format_date(start_at),
            "valid_to": format_date(end_at),
            "start_station": self._format_station(primary_block[8], primary_block[9]),
            "end_station": self._format_station(primary_block[10], primary_block[11]),
            "via1_station": via1_station,
            "via2_station": via2_station,
            "issued_at": format_date(
                int.from_bytes(supplemental_block[5:7], byteorder="big")
            ),
        }

    def read_gate_in_out_information(self) -> list[dict[str, Any]]:
        blocks = self._read_blocks(7, range(3))
        entries: list[dict[str, Any]] = []

        for index, block in enumerate(blocks):
            # Unused gate slots come back zero-filled; skip them so neither the
            # CLI table nor the GUI grid shows phantom "—" rows.
            if not any(block):
                continue

            date = int.from_bytes(block[6:8], byteorder="big")
            time_hex = block[8:10].hex().upper()
            entries.append(
                {
                    "index": index,
                    "date": format_date(date),
                    "time": f"{time_hex[0:2]}:{time_hex[2:4]}",
                    "gate_in_out_type_code": block[0],
                    "gate_in_out_type": gate_in_out_type_to_str(block[0]),
                    "intermediate_gate_instruction_type_code": block[1],
                    "intermediate_gate_instruction_type": (
                        intermadiate_gate_instruction_type_to_str(block[1])
                    ),
                    "station": self._format_station(block[2], block[3]),
                    "device_id_hex": block[4:6].hex().upper(),
                    "amount": int.from_bytes(block[10:12], byteorder="little"),
                    "commuter_pass_fee": int.from_bytes(
                        block[12:14], byteorder="little"
                    ),
                    "commuter_station": self._format_station(block[14], block[15]),
                }
            )

        return entries

    def read_sf_gate_in_information(self) -> dict[str, Any]:
        first_block, second_block = self._read_blocks(8, range(2))

        entry_station_line = first_block[0]
        entry_station_order = first_block[1]
        intermadiate_entry_station_line = second_block[4]
        intermadiate_entry_station_order = second_block[5]
        intermadiate_exit_station_line = second_block[9]
        intermadiate_exit_station_order = second_block[10]

        return {
            "has_record": any(first_block) or any(second_block),
            "entry_station": self._format_station(
                entry_station_line, entry_station_order
            ),
            "intermediate_entry_date": format_date(
                int.from_bytes(second_block[0:2], byteorder="big")
            ),
            "intermediate_entry_time": second_block[2:4].hex().upper(),
            "intermediate_entry_station": self._format_station(
                intermadiate_entry_station_line, intermadiate_entry_station_order
            ),
            "unknown_value1_hex": hex(second_block[6]),
            "intermediate_exit_time": second_block[7:9].hex().upper(),
            "intermediate_exit_station": self._format_station(
                intermadiate_exit_station_line, intermadiate_exit_station_order
            ),
            "unknown_value2_hex": hex(second_block[11]),
        }

    def read_paid_ticket_information(self, service_index: int) -> list[dict[str, Any]]:
        """Parse the 料金発券・改札情報 service (express/paid gate records)."""
        blocks = self._read_blocks(service_index, range(2))
        entries: list[dict[str, Any]] = []
        for index, block in enumerate(blocks):
            if not any(block):
                continue
            entries.append(
                {
                    "index": index,
                    "depart_station": self._format_station(block[0], block[1]),
                    "arrive_station": self._format_station(block[2], block[3]),
                    "expires_at": format_date(
                        int.from_bytes(block[4:6], byteorder="big")
                    ),
                    "issued_time": format_time(
                        int.from_bytes(block[6:8], byteorder="big")
                    ),
                    "issue_type_hex": block[8:9].hex().upper(),
                    # The fee byte stores the amount divided by ten.
                    "amount": block[9] * 10,
                    "device_id_hex": block[10:12].hex().upper(),
                    "checked_station": self._format_station(block[12], block[13]),
                    "checked_time": format_time(
                        int.from_bytes(block[14:16], byteorder="big")
                    ),
                }
            )
        return entries


def _annotate_balance_deltas(entries: list[dict[str, Any]]) -> None:
    """Attach the per-transaction balance change to each history entry.

    Entries are newest-first, so the amount moved by transaction ``i`` is
    ``balance[i] - balance[i + 1]``. Positive means the balance grew (a charge
    or refund); negative means it was spent (a fare or purchase). The oldest
    available entry has no predecessor on the card, so its delta is ``None``.
    """
    for i, entry in enumerate(entries):
        current = entry.get("balance")
        older = entries[i + 1].get("balance") if i + 1 < len(entries) else None
        if isinstance(current, int) and isinstance(older, int):
            entry["delta"] = current - older
        else:
            entry["delta"] = None


class CardDataService:
    """Coordinates remote reads and assembles :class:`CardData`."""

    def __init__(self, station_code_lookup: StationCodeLookup) -> None:
        self.station_code_lookup = station_code_lookup

    def collect(
        self,
        client: FelicaRemoteClient,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> CardData:
        # The paid-ticket service (0x1848) is not on every card and needs its own
        # key. Probe for it (unencrypted, no server involved) and only fold it
        # into the authenticated node set when the card actually carries it.
        paid_present, paid_reason = self._probe_paid_ticket(client)
        services = list(SERVICE_NODE_IDS)
        paid_index: int | None = None
        if paid_present:
            paid_index = len(services)
            services.append(PAID_TICKET_SERVICE_NODE_ID)

        try:
            auth_result = client.mutual_authentication(
                SYSTEM_CODE, list(AREA_NODE_IDS), services
            )
        except Exception:
            if paid_index is None:
                raise
            # The extended authentication failed — most likely the server has no
            # key for the paid-ticket node. Recover by re-polling and
            # authenticating the known-good base set so everything else still
            # reads; the paid-ticket service is skipped with a reason.
            paid_index = None
            paid_reason = (
                "料金発券サービスの認証に失敗しました（サーバに鍵が無い可能性）。"
            )
            self._reauthenticate_base(client)
            auth_result = client.mutual_authentication(
                SYSTEM_CODE, list(AREA_NODE_IDS), list(SERVICE_NODE_IDS)
            )
        self._update_progress(progress_callback, 30.0)

        system_info = self._build_system_info(client, auth_result)

        reader = RemoteCardReader(client)
        extractor = SuicaCardDataExtractor(reader, self.station_code_lookup)

        issue_primary = extractor.read_issue_information_primary()
        self._update_progress(progress_callback, 45.0)

        attribute_info = extractor.read_attribute_information()
        self._update_progress(progress_callback, 55.0)

        last_topup = extractor.read_last_topup_information()
        self._update_progress(progress_callback, 65.0)

        unknown_info = extractor.read_unknown_information()
        self._update_progress(progress_callback, 75.0)

        transaction_history = extractor.read_transaction_history()
        self._update_progress(progress_callback, 85.0)

        commuter_info = extractor.read_commuter_pass_information()
        self._update_progress(progress_callback, 92.0)

        gate_info = extractor.read_gate_in_out_information()
        self._update_progress(progress_callback, 97.0)

        sf_gate_info = extractor.read_sf_gate_in_information()
        self._update_progress(progress_callback, 97.0)

        paid_ticket: list[dict[str, Any]] = []
        paid_available = False
        if paid_index is not None:
            try:
                paid_ticket = extractor.read_paid_ticket_information(paid_index)
                paid_available = True
                paid_reason = None
            except Exception as exc:
                paid_reason = f"料金発券情報の読み取りに失敗しました: {exc}"
        self._update_progress(progress_callback, 100.0)

        return CardData(
            system=system_info,
            issue_primary=issue_primary,
            attribute=attribute_info,
            last_topup=last_topup,
            unknown=unknown_info,
            transaction_history=transaction_history,
            commuter=commuter_info,
            gate=gate_info,
            sf_gate=sf_gate_info,
            paid_ticket=paid_ticket,
            paid_ticket_available=paid_available,
            paid_ticket_reason=paid_reason,
        )

    def _probe_paid_ticket(self, client: FelicaRemoteClient) -> tuple[bool, str | None]:
        """Check (unencrypted) whether the card carries the paid-ticket service."""
        from nfc.tag.tt3 import ServiceCode

        node = PAID_TICKET_SERVICE_NODE_ID
        try:
            versions = client.tag.request_service([ServiceCode(node >> 6, node & 0x3F)])
        except Exception as exc:
            return False, f"料金発券サービスの存在確認に失敗しました: {exc}"
        if not versions or versions[0] == 0xFFFF:
            return False, "カードに料金発券サービスがありません。"
        return True, None

    @staticmethod
    def _reauthenticate_base(client: FelicaRemoteClient) -> None:
        """Re-poll the card and clear session state before a fresh authentication."""
        polling_result = client.tag.polling(SYSTEM_CODE)
        if len(polling_result) == 2:
            client.tag.idm, client.tag.pmm = polling_result
        client.reset(client.tag)

    def _build_system_info(
        self, client: FelicaRemoteClient, auth_result: dict[str, Any]
    ) -> SystemInfo:
        idm_hex = client.idm.hex().upper()
        pmm_hex = client.pmm.hex().upper()
        idi_hex = (auth_result.get("issue_id") or auth_result.get("idi") or "").upper()
        pmi_hex = (
            auth_result.get("issue_parameter") or auth_result.get("pmi") or ""
        ).upper()

        if not idi_hex:
            raise RuntimeError("サーバ応答に Issue ID が含まれていません。")
        if not pmi_hex:
            raise RuntimeError("サーバ応答に Issue Parameter が含まれていません。")

        try:
            idi_bytes = bytes.fromhex(idi_hex)
        except ValueError as exc:
            raise RuntimeError("Issue ID の形式が不正です。") from exc

        return SystemInfo(
            idm_hex=idm_hex,
            pmm_hex=pmm_hex,
            idi_hex=idi_hex,
            idi_display=idi_bytes_to_str(idi_bytes),
            pmi=pmi_hex,
        )

    @staticmethod
    def _update_progress(
        callback: ProgressCallback | None,
        value: float,
    ) -> None:
        if callback is not None:
            callback(value)
