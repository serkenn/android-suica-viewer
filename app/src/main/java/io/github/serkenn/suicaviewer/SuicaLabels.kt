package io.github.serkenn.suicaviewer

import java.time.LocalDate

/**
 * Label maps and formatting helpers ported from the desktop app's
 * `suica_viewer/utils.py`. Kept byte-for-byte compatible so the Android
 * viewer renders exactly the same values as the reference implementation.
 */

const val SYSTEM_CODE = 0x0003

val EQUIPMENT_TYPES: Map<Int, String> = mapOf(
    0x00 to "未定義",
    0x03 to "のりこし精算機",
    0x04 to "携帯端末",
    0x05 to "バス等車載機",
    0x07 to "カード発売機",
    0x08 to "自動券売機",
    0x09 to "SMART ICOCA クイックチャージ機?",
    0x12 to "自動券売機(東京モノレール)",
    0x14 to "駅務機器(PASMO発行機?)",
    0x15 to "定期券発売機",
    0x16 to "自動改札機",
    0x17 to "簡易改札機",
    0x18 to "駅務機器(発行機?)",
    0x19 to "窓口処理機(みどりの窓口)",
    0x1A to "窓口処理機(有人改札)",
    0x1B to "モバイルFeliCa",
    0x1C to "入場券券売機",
    0x1D to "他社乗換自動改札機",
    0x1F to "入金機",
    0x20 to "発行機?(モノレール)",
    0x22 to "簡易改札機(ことでん)",
    0x34 to "カード発売機(せたまる?)",
    0x35 to "バス等車載機(せたまる車内入金機?)",
    0x36 to "バス等車載機(車内簡易改札機)",
    0x46 to "ビューアルッテ端末",
    0xC7 to "物販端末",
    0xC8 to "物販端末",
)

val TRANSACTION_TYPES: Map<Int, String> = mapOf(
    0x00 to "未定義",
    0x01 to "自動改札機出場",
    0x02 to "SFチャージ",
    0x03 to "きっぷ購入",
    0x04 to "磁気券精算",
    0x05 to "乗越精算",
    0x06 to "窓口出場",
    0x07 to "新規",
    0x08 to "控除",
    0x0D to "バス等均一運賃",
    0x0F to "バス等",
    0x11 to "再発行?",
    0x13 to "料金出場",
    0x14 to "オートチャージ",
    0x1F to "バス等チャージ",
    0x46 to "物販",
    0x48 to "ポイントチャージ",
    0x4B to "入場・物販",
)

val PAY_TYPES: Map<Int, String> = mapOf(
    0x00 to "現金/なし",
    0x02 to "VIEW",
    0x0B to "PiTaPa",
    0x0D to "オートチャージ対応PASMO",
    0x3F to "モバイルSuica(VIEW決済以外)",
)

val GATE_INSTRUCTION_TYPES: Map<Int, String> = mapOf(
    0x00 to "未定義",
    0x01 to "入場",
    0x02 to "入場/出場",
    0x03 to "定期入場/出場",
    0x04 to "入場/定期出場",
    0x0E to "窓口出場",
    0x0F to "入場/出場(バス等)",
    0x12 to "料金定期入場/料金出場",
    0x17 to "入場/出場(乗継割引)",
    0x21 to "入場/出場(バス等乗継割引)",
)

val CARD_TYPE_LABELS: Map<Int, String> = mapOf(
    0 to "せたまる/IruCa",
    2 to "Suica/PiTaPa/TOICA/PASMO",
    3 to "ICOCA",
)

val ISSUER_ID_MAP: Map<String, Pair<String, String>> = mapOf(
    "0102" to ("北海道旅客鉄道株式会社" to "JH"),
    "0103" to ("東日本旅客鉄道株式会社" to "JE"),
    "0104" to ("東海旅客鉄道株式会社" to "JC"),
    "0105" to ("西日本旅客鉄道株式会社" to "JW"),
    "0107" to ("九州旅客鉄道株式会社" to "JK"),
    "0252" to ("株式会社パスモ" to "PB"),
    "0387" to ("株式会社名古屋交通開発機構・株式会社エムアイシー" to "TP"),
    "04AD" to ("株式会社スルッとKANSAI" to "SU"),
    "05D5" to ("株式会社ニモカ" to "NR"),
    "05D7" to ("福岡市交通局" to "FC"),
)

val GATE_IN_OUT_TYPES: Map<Int, String> = mapOf(
    0x00 to "精算出場",
    0x01 to "精算出場(プリペイドカード併用?)",
    0x20 to "出場",
    0x21 to "駅務機器出場",
    0x22 to "割引出場",
    0x24 to "割引出場?",
    0x40 to "定期出場",
    0x80 to "均一区間入場?",
    0xA0 to "入場",
    0xA2 to "割引入場?",
    0xC0 to "定期入場",
)

val INTERMADIATE_GATE_INSTRUCTION_TYPES: Map<Int, String> = mapOf(
    0x00 to "未定義",
    0x04 to "乗継割引?",
    0x08 to "電車バス乗継割引?",
    0x40 to "新幹線中間改札?",
)

private fun lookupByMapping(mapping: Map<Int, String>, value: Int, unknownLabel: String): String =
    mapping[value] ?: "不明な$unknownLabel (0x%02X)".format(value)

fun equipmentTypeToStr(equipmentType: Int): String =
    lookupByMapping(EQUIPMENT_TYPES, equipmentType, "機器種別")

fun transactionTypeToStr(transactionType: Int): String =
    lookupByMapping(TRANSACTION_TYPES, transactionType, "取引種別")

fun payTypeToStr(payType: Int): String =
    lookupByMapping(PAY_TYPES, payType, "支払種別")

fun gateInstructionTypeToStr(code: Int): String =
    lookupByMapping(GATE_INSTRUCTION_TYPES, code, "改札処理種別")

fun gateInOutTypeToStr(code: Int): String =
    lookupByMapping(GATE_IN_OUT_TYPES, code, "改札入出場種別")

fun intermadiateGateInstructionTypeToStr(code: Int): String =
    lookupByMapping(INTERMADIATE_GATE_INSTRUCTION_TYPES, code, "中間改札処理種別")

fun intToDate(value: Int): Triple<Int, Int, Int> {
    val year = value shr 9
    val month = (value shr 5) and 0x0F
    val day = value and 0x1F
    return Triple(year, month, day)
}

fun intToTime(value: Int): Triple<Int, Int, Int> {
    val hour = value shr 11
    val minute = (value shr 5) and 0x3F
    val second = (value and 0x1F) * 2
    return Triple(hour, minute, second)
}

fun formatDate(value: Int): String {
    // Empty date slots come back all-zero; render a dash rather than 2000-00-00.
    if (value == 0) return "—"
    val (year, month, day) = intToDate(value)
    return "%04d-%02d-%02d".format(2000 + year, month, day)
}

/**
 * Format a birth date, inferring the century of its two-digit year. A birth
 * date can predate 2000, so pick the most recent century that is not in the
 * future (a birth date cannot be later than today).
 */
fun formatBirthDate(value: Int, referenceYear: Int? = null): String {
    if (value == 0) return "—"
    val (year, month, day) = intToDate(value)
    var fullYear = 2000 + year
    val ref = referenceYear ?: LocalDate.now().year
    if (fullYear > ref) fullYear -= 100
    return "%04d-%02d-%02d".format(fullYear, month, day)
}

fun formatTime(value: Int): String {
    val (hour, minute, second) = intToTime(value)
    return "%02d:%02d:%02d".format(hour, minute, second)
}

fun formatYen(value: Int): String = "%,d 円".format(value)

fun formatRegion(regionCode: Int): String = "$regionCode (0x%02X)".format(regionCode)

fun issuerIdToStr(issuerIdHex: String): String {
    val key = issuerIdHex.uppercase()
    val info = ISSUER_ID_MAP[key] ?: return key
    val (company, identifier) = info
    return "$key ($company / $identifier)"
}

fun issuerIdentifierFromId(issuerIdHex: String): String? =
    ISSUER_ID_MAP[issuerIdHex.uppercase()]?.second

/** Convert an 8-byte IDi to its string form. */
fun idiBytesToStr(idiBytes: ByteArray): String {
    require(idiBytes.size >= 8) { "idiBytes must be 8 bytes." }

    val issuerHex = idiBytes.copyOfRange(0, 2).toHexUpper()
    val remainder = idiBytes.copyOfRange(2, 4).toHexUpper()
    val issuerIdentifier = issuerIdentifierFromId(issuerHex)
    val head = if (issuerIdentifier != null) "$issuerIdentifier$remainder" else "$issuerHex$remainder"

    val v = ((idiBytes[4].toInt() and 0xFF) shl 8) or (idiBytes[5].toInt() and 0xFF)
    val year = (v shr 9) and 0x3F
    val month = (v shr 5) and 0x0F
    val day = v and 0x1F
    val yy = year % 100
    val datePart = "%02d%02d%02d".format(yy, month, day)

    val tailVal = ((idiBytes[6].toInt() and 0xFF) shl 8) or (idiBytes[7].toInt() and 0xFF)
    val tail = "%05d".format(tailVal)

    return "$head$datePart$tail"
}

/** Uppercase hex of a byte array, no separators. */
fun ByteArray.toHexUpper(): String = joinToString("") { "%02X".format(it) }
