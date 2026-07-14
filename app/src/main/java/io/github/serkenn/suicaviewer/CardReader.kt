package io.github.serkenn.suicaviewer

import org.json.JSONArray
import org.json.JSONObject
import java.nio.charset.Charset

/**
 * Card reading and parsing ported from `suica_viewer/card_data.py`.
 *
 * All byte offsets and service/area node ids are kept identical to the desktop
 * implementation so the Android viewer decodes exactly the same fields.
 */

const val DEFAULT_AUTH_SERVER_URL = "https://felica-auth.nyaa.ws"

private val AREA_NODE_IDS: List<Int> = listOf(0x0000, 0x0040, 0x0800, 0x0FC0, 0x1000)
private val SERVICE_NODE_IDS: List<Int> = listOf(
    0x0048, 0x0088, 0x0810, 0x08C8, 0x090C, 0x1008, 0x1048, 0x108C, 0x10C8,
)
private const val PAID_TICKET_SERVICE_NODE_ID = 0x1848

private const val READ_COMMAND_CODE = 0x14
private const val DATA_BLOCK_SIZE = 16
private const val MAX_BLOCKS_PER_REQUEST = 9

// Purchase (物販) transactions store a clock instead of entry/exit stations.
private const val PURCHASE_TRANSACTION_TYPE = 0x46

private val SHIFT_JIS: Charset = Charset.forName("Shift_JIS")

data class SystemInfo(
    val idmHex: String,
    val pmmHex: String,
    val idiHex: String,
    val idiDisplay: String,
    val pmi: String,
)

data class IssuePrimary(
    val ownerName: String,
    val secondaryIssueId: String,
    val ownerPhoneHex: String,
    val ownerAgeCode: String,
    val ownerBirthdate: String,
    val deposit: Int,
    val issuerId: String,
    val issuerIdHex: String,
    val issuedByCode: Int,
    val issuedBy: String,
    val issuedStation: String,
    val issuedAt: String,
    val expiresAt: String,
)

data class Attribute(
    val cardTypeCode: Int,
    val cardType: String,
    val region: Int,
    val balance: Int,
    val transactionNumber: Int,
)

data class UnknownInfo(
    val balance: Int,
    val date: String,
    val transactionNumber: Int,
)

data class LastTopup(
    val equipmentCode: Int,
    val equipment: String,
    val station: String,
    val amount: Int,
)

data class TransactionEntry(
    val index: Int,
    val recordedOn: String,
    val recordedByCode: Int,
    val recordedBy: String,
    val transactionTypeCode: Int,
    val transactionType: String,
    val payTypeCode: Int,
    val payType: String,
    val gateInstructionTypeCode: Int,
    val gateInstructionType: String,
    val entryStation: String?,
    val exitStation: String?,
    val transactionTime: String?,
    val balance: Int,
    val transactionNumber: Int,
    var delta: Int?,
)

data class Commuter(
    val validFrom: String,
    val validTo: String,
    val startStation: String,
    val endStation: String,
    val via1Station: String,
    val via2Station: String,
    val issuedAt: String,
) {
    val hasCommuterPass: Boolean
        get() = validFrom.isNotEmpty() && validFrom != "—"
}

data class GateEntry(
    val index: Int,
    val date: String,
    val time: String,
    val gateInOutTypeCode: Int,
    val gateInOutType: String,
    val intermediateTypeCode: Int,
    val intermediateType: String,
    val station: String,
    val deviceIdHex: String,
    val amount: Int,
    val commuterPassFee: Int,
    val commuterStation: String,
)

data class SfGate(
    val hasRecord: Boolean,
    val entryStation: String,
    val intermediateEntryDate: String,
    val intermediateEntryTime: String,
    val intermediateEntryStation: String,
    val unknownValue1Hex: String,
    val intermediateExitTime: String,
    val intermediateExitStation: String,
    val unknownValue2Hex: String,
)

data class PaidTicket(
    val index: Int,
    val departStation: String,
    val arriveStation: String,
    val expiresAt: String,
    val issuedTime: String,
    val issueTypeHex: String,
    val amount: Int,
    val deviceIdHex: String,
    val checkedStation: String,
    val checkedTime: String,
)

data class CardData(
    val system: SystemInfo,
    val issuePrimary: IssuePrimary,
    val attribute: Attribute,
    val lastTopup: LastTopup,
    val unknown: UnknownInfo,
    val transactionHistory: List<TransactionEntry>,
    val commuter: Commuter,
    val gate: List<GateEntry>,
    val sfGate: SfGate,
    val paidTicket: List<PaidTicket>,
    val paidTicketAvailable: Boolean,
    val paidTicketReason: String?,
) {
    fun toJson(): JSONObject = buildCardDataJson(this)
}

/** Issues encrypted read commands through the remote server. */
private class RemoteCardReader(private val client: RemoteAuthClient) {
    fun readBlocks(serviceIndex: Int, indexes: List<Int>): List<ByteArray> {
        val blocks = ArrayList<ByteArray>()
        var start = 0
        while (start < indexes.size) {
            val chunk = indexes.subList(start, minOf(start + MAX_BLOCKS_PER_REQUEST, indexes.size))
            if (chunk.isNotEmpty()) {
                blocks.addAll(readElements(serviceIndex, chunk))
            }
            start += MAX_BLOCKS_PER_REQUEST
        }
        return blocks
    }

    private fun readElements(serviceIndex: Int, chunk: List<Int>): List<ByteArray> {
        require(serviceIndex in 0 until 16) { "サービスインデックスは 0 から 15 の範囲である必要があります。" }
        val payload = ArrayList<Byte>()
        payload.add(chunk.size.toByte())
        for (block in chunk) {
            require(block in 0 until 256) { "ブロック番号は 0 から 255 の範囲である必要があります。" }
            payload.add((0x80 or serviceIndex).toByte())
            payload.add((block and 0xFF).toByte())
        }

        val response = client.encryptionExchange(READ_COMMAND_CODE, payload.toByteArray())
        if (response.size < 3) throw FelicaRemoteClientError("リモートサーバーからの応答が不正です。")

        val statusFlag1 = response.u(0)
        val statusFlag2 = response.u(1)
        if (statusFlag1 != 0x00) throw CardCommandError((statusFlag1 shl 8) or statusFlag2)

        val expectedBlocks = chunk.size
        if (response.u(2) != expectedBlocks) throw FelicaRemoteClientError("取得したブロック数が一致しません。")

        val blockPayload = response.copyOfRange(3, response.size)
        val expectedLength = expectedBlocks * DATA_BLOCK_SIZE
        if (blockPayload.size < expectedLength) throw FelicaRemoteClientError("ブロックデータの長さが不正です。")

        return (0 until expectedBlocks).map {
            blockPayload.copyOfRange(it * DATA_BLOCK_SIZE, (it + 1) * DATA_BLOCK_SIZE)
        }
    }
}

/** Extracts structured data from a Suica FeliCa tag via the remote reader. */
private class SuicaCardDataExtractor(
    private val reader: RemoteCardReader,
    private val stations: StationCodeLookup,
) {
    private fun station(line: Int, order: Int) = stations.formatStation(line, order)
    private fun readBlocks(serviceIndex: Int, count: Int) = reader.readBlocks(serviceIndex, (0 until count).toList())
    private fun readSingle(serviceIndex: Int, index: Int) = reader.readBlocks(serviceIndex, listOf(index))[0]

    fun readIssueInformationPrimary(): IssuePrimary {
        val (owner, personal, secondaryIdi, metadata) = readBlocks(0, 4).let {
            listOf(it[0], it[1], it[2], it[3])
        }
        val ownerName = try {
            String(owner, SHIFT_JIS).trimEnd()
        } catch (_: Exception) {
            String(owner, SHIFT_JIS).trimEnd()
        }
        return IssuePrimary(
            ownerName = ownerName,
            secondaryIssueId = idiBytesToStr(secondaryIdi),
            ownerPhoneHex = personal.hexUpper(0, 8).trimEnd('F'),
            ownerAgeCode = personal.hexUpper(8, 9),
            ownerBirthdate = formatBirthDate(personal.beInt(9, 11)),
            deposit = personal.leInt(12, 14),
            issuerId = issuerIdToStr(metadata.hexUpper(0, 2)),
            issuerIdHex = metadata.hexUpper(0, 2),
            issuedByCode = metadata.u(2),
            issuedBy = equipmentTypeToStr(metadata.u(2)),
            issuedStation = station(metadata.u(3), metadata.u(4)),
            issuedAt = formatDate(metadata.beInt(7, 9)),
            expiresAt = formatDate(metadata.beInt(14, 16)),
        )
    }

    fun readAttributeInformation(): Attribute {
        val block = readSingle(1, 0)
        val cardTypeCode = block.u(8) shr 4
        return Attribute(
            cardTypeCode = cardTypeCode,
            cardType = CARD_TYPE_LABELS[cardTypeCode] ?: "不明",
            region = block.u(8) and 0x0F,
            balance = block.leInt(11, 13),
            transactionNumber = block.beInt(14, 16),
        )
    }

    fun readUnknownInformation(): UnknownInfo {
        val block = readSingle(2, 0)
        return UnknownInfo(
            balance = block.leInt(0, 2),
            date = formatDate(block.beInt(8, 10)),
            transactionNumber = block.beInt(14, 16),
        )
    }

    fun readLastTopupInformation(): LastTopup {
        val detail = readBlocks(3, 3)[0]
        return LastTopup(
            equipmentCode = detail.u(0),
            equipment = equipmentTypeToStr(detail.u(0)),
            station = station(detail.u(1), detail.u(2)),
            amount = detail.leInt(5, 7),
        )
    }

    fun readTransactionHistory(): List<TransactionEntry> {
        val blocks = readBlocks(4, 20)
        val entries = ArrayList<TransactionEntry>()
        for ((index, block) in blocks.withIndex()) {
            val recordedBy = block.u(0)
            if (recordedBy == 0x00) break

            val transactionTypeCode = block.u(1) and 0x7F
            var entryStation: String? = null
            var exitStation: String? = null
            var transactionTime: String? = null
            if (transactionTypeCode == PURCHASE_TRANSACTION_TYPE) {
                transactionTime = formatTime(block.beInt(6, 8))
            } else {
                entryStation = station(block.u(6), block.u(7))
                exitStation = station(block.u(8), block.u(9))
            }
            entries.add(
                TransactionEntry(
                    index = index,
                    recordedOn = formatDate(block.beInt(4, 6)),
                    recordedByCode = recordedBy,
                    recordedBy = equipmentTypeToStr(recordedBy),
                    transactionTypeCode = transactionTypeCode,
                    transactionType = transactionTypeToStr(transactionTypeCode),
                    payTypeCode = block.u(2),
                    payType = payTypeToStr(block.u(2)),
                    gateInstructionTypeCode = block.u(3),
                    gateInstructionType = gateInstructionTypeToStr(block.u(3)),
                    entryStation = entryStation,
                    exitStation = exitStation,
                    transactionTime = transactionTime,
                    balance = block.leInt(10, 12),
                    transactionNumber = block.beInt(13, 15),
                    delta = null,
                ),
            )
        }
        annotateBalanceDeltas(entries)
        return entries
    }

    fun readCommuterPassInformation(): Commuter {
        val blocks = readBlocks(6, 3)
        val primary = blocks[0]
        val supplemental = blocks[2]
        return Commuter(
            validFrom = formatDate(primary.beInt(0, 2)),
            validTo = formatDate(primary.beInt(2, 4)),
            startStation = station(primary.u(8), primary.u(9)),
            endStation = station(primary.u(10), primary.u(11)),
            via1Station = station(primary.u(12), primary.u(13)),
            via2Station = station(primary.u(14), primary.u(15)),
            issuedAt = formatDate(supplemental.beInt(5, 7)),
        )
    }

    fun readGateInOutInformation(): List<GateEntry> {
        val blocks = readBlocks(7, 3)
        val entries = ArrayList<GateEntry>()
        for ((index, block) in blocks.withIndex()) {
            // Unused gate slots come back zero-filled; skip them.
            if (block.all { it.toInt() == 0 }) continue
            val timeHex = block.hexUpper(8, 10)
            entries.add(
                GateEntry(
                    index = index,
                    date = formatDate(block.beInt(6, 8)),
                    time = "${timeHex.substring(0, 2)}:${timeHex.substring(2, 4)}",
                    gateInOutTypeCode = block.u(0),
                    gateInOutType = gateInOutTypeToStr(block.u(0)),
                    intermediateTypeCode = block.u(1),
                    intermediateType = intermadiateGateInstructionTypeToStr(block.u(1)),
                    station = station(block.u(2), block.u(3)),
                    deviceIdHex = block.hexUpper(4, 6),
                    amount = block.leInt(10, 12),
                    commuterPassFee = block.leInt(12, 14),
                    commuterStation = station(block.u(14), block.u(15)),
                ),
            )
        }
        return entries
    }

    fun readSfGateInInformation(): SfGate {
        val blocks = readBlocks(8, 2)
        val first = blocks[0]
        val second = blocks[1]
        val hasRecord = first.any { it.toInt() != 0 } || second.any { it.toInt() != 0 }
        return SfGate(
            hasRecord = hasRecord,
            entryStation = station(first.u(0), first.u(1)),
            intermediateEntryDate = formatDate(second.beInt(0, 2)),
            intermediateEntryTime = second.hexUpper(2, 4),
            intermediateEntryStation = station(second.u(4), second.u(5)),
            unknownValue1Hex = "0x%x".format(second.u(6)),
            intermediateExitTime = second.hexUpper(7, 9),
            intermediateExitStation = station(second.u(9), second.u(10)),
            unknownValue2Hex = "0x%x".format(second.u(11)),
        )
    }

    fun readPaidTicketInformation(serviceIndex: Int): List<PaidTicket> {
        val blocks = readBlocks(serviceIndex, 2)
        val entries = ArrayList<PaidTicket>()
        for ((index, block) in blocks.withIndex()) {
            if (block.all { it.toInt() == 0 }) continue
            entries.add(
                PaidTicket(
                    index = index,
                    departStation = station(block.u(0), block.u(1)),
                    arriveStation = station(block.u(2), block.u(3)),
                    expiresAt = formatDate(block.beInt(4, 6)),
                    issuedTime = formatTime(block.beInt(6, 8)),
                    issueTypeHex = block.hexUpper(8, 9),
                    // The fee byte stores the amount divided by ten.
                    amount = block.u(9) * 10,
                    deviceIdHex = block.hexUpper(10, 12),
                    checkedStation = station(block.u(12), block.u(13)),
                    checkedTime = formatTime(block.beInt(14, 16)),
                ),
            )
        }
        return entries
    }
}

private fun annotateBalanceDeltas(entries: List<TransactionEntry>) {
    // Newest-first, so entry i moved balance[i] - balance[i+1]. Oldest has none.
    for (i in entries.indices) {
        val older = if (i + 1 < entries.size) entries[i + 1].balance else null
        entries[i].delta = if (older != null) entries[i].balance - older else null
    }
}

/**
 * Coordinates the paid-ticket probe, remote authentication, and the full set of
 * reads — the Android equivalent of `CardDataService.collect`.
 */
class SuicaCardReader(
    serverUrl: String,
    private val idm: ByteArray,
    private val pmm: ByteArray,
    private val stations: StationCodeLookup,
    private val transceive: (ByteArray) -> ByteArray,
) {
    private val client = RemoteAuthClient(serverUrl, idm, pmm, transceive = transceive)

    fun collect(progress: (Int) -> Unit = {}): CardData {
        // Probe (unencrypted) for the optional paid-ticket service and only fold
        // it into the authenticated node set when the card actually carries it.
        var (paidPresent, paidReason) = probePaidTicket()
        val services = SERVICE_NODE_IDS.toMutableList()
        var paidIndex: Int? = null
        if (paidPresent) {
            paidIndex = services.size
            services.add(PAID_TICKET_SERVICE_NODE_ID)
        }

        var authResult: JSONObject
        try {
            authResult = client.mutualAuthentication(SYSTEM_CODE, AREA_NODE_IDS, services)
        } catch (e: Exception) {
            if (paidIndex == null) throw e
            // Most likely the server has no key for the paid-ticket node. Recover
            // by authenticating the known-good base set (idm/pmm are retained, so
            // no re-poll is needed) and skip the paid-ticket service.
            paidIndex = null
            paidReason = "料金発券サービスの認証に失敗しました（サーバに鍵が無い可能性）。"
            client.reset()
            authResult = client.mutualAuthentication(SYSTEM_CODE, AREA_NODE_IDS, SERVICE_NODE_IDS)
        }
        progress(30)

        val systemInfo = buildSystemInfo(authResult)

        val reader = RemoteCardReader(client)
        val extractor = SuicaCardDataExtractor(reader, stations)

        val issuePrimary = extractor.readIssueInformationPrimary(); progress(45)
        val attribute = extractor.readAttributeInformation(); progress(55)
        val lastTopup = extractor.readLastTopupInformation(); progress(65)
        val unknown = extractor.readUnknownInformation(); progress(75)
        val history = extractor.readTransactionHistory(); progress(85)
        val commuter = extractor.readCommuterPassInformation(); progress(92)
        val gate = extractor.readGateInOutInformation(); progress(97)
        val sfGate = extractor.readSfGateInInformation()

        var paidTicket: List<PaidTicket> = emptyList()
        var paidAvailable = false
        if (paidIndex != null) {
            try {
                paidTicket = extractor.readPaidTicketInformation(paidIndex)
                paidAvailable = true
                paidReason = null
            } catch (e: Exception) {
                paidReason = "料金発券情報の読み取りに失敗しました: ${e.message}"
            }
        }
        progress(100)

        return CardData(
            system = systemInfo,
            issuePrimary = issuePrimary,
            attribute = attribute,
            lastTopup = lastTopup,
            unknown = unknown,
            transactionHistory = history,
            commuter = commuter,
            gate = gate,
            sfGate = sfGate,
            paidTicket = paidTicket,
            paidTicketAvailable = paidAvailable,
            paidTicketReason = paidReason,
        )
    }

    /** Check (unencrypted) whether the card carries the paid-ticket service. */
    private fun probePaidTicket(): Pair<Boolean, String?> {
        return try {
            val version = requestServiceVersion(PAID_TICKET_SERVICE_NODE_ID)
            if (version == 0xFFFF) false to "カードに料金発券サービスがありません。" else true to null
        } catch (e: Exception) {
            false to "料金発券サービスの存在確認に失敗しました: ${e.message}"
        }
    }

    /** FeliCa Request Service (0x02) for a single node; returns its key version. */
    private fun requestServiceVersion(nodeCode: Int): Int {
        val command = ArrayList<Byte>()
        command.add(0x02)                       // command code
        command.addAll(idm.toList())            // IDm (8)
        command.add(0x01)                       // number of nodes
        command.add((nodeCode and 0xFF).toByte())
        command.add(((nodeCode shr 8) and 0xFF).toByte())
        val framed = ByteArray(command.size + 1)
        framed[0] = framed.size.toByte()        // leading length byte
        for (i in command.indices) framed[i + 1] = command[i]

        val response = transceive(framed)
        // response: len | 0x03 | IDm(8) | numNodes | verLo | verHi
        if (response.size < 13) throw FelicaRemoteClientError("Request Service 応答が不正です。")
        return response.u(11) or (response.u(12) shl 8)
    }

    private fun buildSystemInfo(authResult: JSONObject): SystemInfo {
        val idiHex = (firstNonEmpty(authResult, "issue_id", "idi")).uppercase()
        val pmiHex = (firstNonEmpty(authResult, "issue_parameter", "pmi")).uppercase()
        if (idiHex.isEmpty()) throw FelicaRemoteClientError("サーバ応答に Issue ID が含まれていません。")
        if (pmiHex.isEmpty()) throw FelicaRemoteClientError("サーバ応答に Issue Parameter が含まれていません。")

        val idiBytes = try {
            idiHex.hexToBytes()
        } catch (e: Exception) {
            throw FelicaRemoteClientError("Issue ID の形式が不正です。")
        }
        return SystemInfo(
            idmHex = idm.toHexUpper(),
            pmmHex = pmm.toHexUpper(),
            idiHex = idiHex,
            idiDisplay = idiBytesToStr(idiBytes),
            pmi = pmiHex,
        )
    }

    private fun firstNonEmpty(obj: JSONObject, vararg keys: String): String {
        for (key in keys) {
            val value = obj.optString(key, "")
            if (value.isNotEmpty()) return value
        }
        return ""
    }
}

// ---- byte helpers ---------------------------------------------------------

private fun ByteArray.u(i: Int): Int = this[i].toInt() and 0xFF

private fun ByteArray.beInt(from: Int, toExclusive: Int): Int {
    var value = 0
    for (i in from until toExclusive) value = (value shl 8) or u(i)
    return value
}

private fun ByteArray.leInt(from: Int, toExclusive: Int): Int {
    var value = 0
    var shift = 0
    for (i in from until toExclusive) {
        value = value or (u(i) shl shift)
        shift += 8
    }
    return value
}

private fun ByteArray.hexUpper(from: Int, toExclusive: Int): String {
    val sb = StringBuilder()
    for (i in from until toExclusive) sb.append("%02X".format(u(i)))
    return sb.toString()
}

// ---- JSON export (mirrors CardData.to_serializable_dict) ------------------

private fun buildCardDataJson(data: CardData): JSONObject = JSONObject().apply {
    put("system", JSONObject().apply {
        put("idm_hex", data.system.idmHex)
        put("pmm_hex", data.system.pmmHex)
        put("idi_hex", data.system.idiHex)
        put("idi_display", data.system.idiDisplay)
        put("pmi", data.system.pmi)
    })
    put("issue_primary", JSONObject().apply {
        put("owner_name", data.issuePrimary.ownerName)
        put("secondary_issue_id", data.issuePrimary.secondaryIssueId)
        put("owner_phone_hex", data.issuePrimary.ownerPhoneHex)
        put("owner_age_code", data.issuePrimary.ownerAgeCode)
        put("owner_birthdate", data.issuePrimary.ownerBirthdate)
        put("deposit", data.issuePrimary.deposit)
        put("issuer_id", data.issuePrimary.issuerId)
        put("issuer_id_hex", data.issuePrimary.issuerIdHex)
        put("issued_by_code", data.issuePrimary.issuedByCode)
        put("issued_by", data.issuePrimary.issuedBy)
        put("issued_station", data.issuePrimary.issuedStation)
        put("issued_at", data.issuePrimary.issuedAt)
        put("expires_at", data.issuePrimary.expiresAt)
    })
    put("attribute", JSONObject().apply {
        put("card_type_code", data.attribute.cardTypeCode)
        put("card_type", data.attribute.cardType)
        put("region", data.attribute.region)
        put("balance", data.attribute.balance)
        put("transaction_number", data.attribute.transactionNumber)
    })
    put("last_topup", JSONObject().apply {
        put("equipment_code", data.lastTopup.equipmentCode)
        put("equipment", data.lastTopup.equipment)
        put("station", data.lastTopup.station)
        put("amount", data.lastTopup.amount)
    })
    put("unknown", JSONObject().apply {
        put("balance", data.unknown.balance)
        put("date", data.unknown.date)
        put("transaction_number", data.unknown.transactionNumber)
    })
    put("transaction_history", JSONArray().apply {
        for (e in data.transactionHistory) {
            put(JSONObject().apply {
                put("index", e.index)
                put("recorded_on", e.recordedOn)
                put("recorded_by_code", e.recordedByCode)
                put("recorded_by", e.recordedBy)
                put("transaction_type_code", e.transactionTypeCode)
                put("transaction_type", e.transactionType)
                put("pay_type_code", e.payTypeCode)
                put("pay_type", e.payType)
                put("gate_instruction_type_code", e.gateInstructionTypeCode)
                put("gate_instruction_type", e.gateInstructionType)
                e.transactionTime?.let { put("transaction_time", it) }
                e.entryStation?.let { put("entry_station", it) }
                e.exitStation?.let { put("exit_station", it) }
                put("balance", e.balance)
                put("transaction_number", e.transactionNumber)
                put("delta", e.delta ?: JSONObject.NULL)
            })
        }
    })
    put("commuter", JSONObject().apply {
        put("valid_from", data.commuter.validFrom)
        put("valid_to", data.commuter.validTo)
        put("start_station", data.commuter.startStation)
        put("end_station", data.commuter.endStation)
        put("via1_station", data.commuter.via1Station)
        put("via2_station", data.commuter.via2Station)
        put("issued_at", data.commuter.issuedAt)
    })
    put("gate", JSONArray().apply {
        for (g in data.gate) {
            put(JSONObject().apply {
                put("index", g.index)
                put("date", g.date)
                put("time", g.time)
                put("gate_in_out_type_code", g.gateInOutTypeCode)
                put("gate_in_out_type", g.gateInOutType)
                put("intermediate_gate_instruction_type_code", g.intermediateTypeCode)
                put("intermediate_gate_instruction_type", g.intermediateType)
                put("station", g.station)
                put("device_id_hex", g.deviceIdHex)
                put("amount", g.amount)
                put("commuter_pass_fee", g.commuterPassFee)
                put("commuter_station", g.commuterStation)
            })
        }
    })
    put("sf_gate", JSONObject().apply {
        put("has_record", data.sfGate.hasRecord)
        put("entry_station", data.sfGate.entryStation)
        put("intermediate_entry_date", data.sfGate.intermediateEntryDate)
        put("intermediate_entry_time", data.sfGate.intermediateEntryTime)
        put("intermediate_entry_station", data.sfGate.intermediateEntryStation)
        put("unknown_value1_hex", data.sfGate.unknownValue1Hex)
        put("intermediate_exit_time", data.sfGate.intermediateExitTime)
        put("intermediate_exit_station", data.sfGate.intermediateExitStation)
        put("unknown_value2_hex", data.sfGate.unknownValue2Hex)
    })
    put("paid_ticket", JSONArray().apply {
        for (p in data.paidTicket) {
            put(JSONObject().apply {
                put("index", p.index)
                put("depart_station", p.departStation)
                put("arrive_station", p.arriveStation)
                put("expires_at", p.expiresAt)
                put("issued_time", p.issuedTime)
                put("issue_type_hex", p.issueTypeHex)
                put("amount", p.amount)
                put("device_id_hex", p.deviceIdHex)
                put("checked_station", p.checkedStation)
                put("checked_time", p.checkedTime)
            })
        }
    })
    put("paid_ticket_available", data.paidTicketAvailable)
    put("paid_ticket_reason", data.paidTicketReason ?: JSONObject.NULL)
}
