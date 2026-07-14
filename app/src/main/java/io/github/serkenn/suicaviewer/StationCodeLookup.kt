package io.github.serkenn.suicaviewer

import android.content.Context
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * Station lookup ported from `suica_viewer/station_code_lookup.py`.
 *
 * Indexes `station_codes.csv` by (line code, station order code) as normalized
 * uppercase hex — matching the desktop app's `_normalize_hex_code` (int →
 * `Integer.toHexString().uppercase()`, i.e. no zero padding).
 */
class StationCodeLookup private constructor(
    private val byLineStation: Map<String, Map<String, StationInfo>>,
) {
    data class StationInfo(
        val companyName: String,
        val lineName: String,
        val stationName: String,
    )

    private fun normalize(code: Int): String = Integer.toHexString(code).uppercase()

    fun getStationInfo(lineCode: Int, stationOrder: Int): StationInfo? =
        byLineStation[normalize(lineCode)]?.get(normalize(stationOrder))

    /**
     * Render a station as "会社名 線区名 駅名", or the raw codes when unknown —
     * mirrors `utils.format_station`.
     */
    fun formatStation(lineCode: Int, stationOrder: Int): String {
        val station = getStationInfo(lineCode, stationOrder)
            ?: return "不明 (線区コード: 0x%02X, 駅順コード: 0x%02X)".format(lineCode, stationOrder)
        return "${station.companyName} ${station.lineName} ${station.stationName}"
    }

    companion object {
        // Column indexes in station_codes.csv.
        private const val COL_LINE = 1
        private const val COL_STATION = 2
        private const val COL_COMPANY = 3
        private const val COL_LINE_NAME = 4
        private const val COL_STATION_NAME = 5

        fun fromAssets(context: Context, fileName: String = "station_codes.csv"): StationCodeLookup {
            context.assets.open(fileName).use { stream ->
                BufferedReader(InputStreamReader(stream, Charsets.UTF_8)).use { reader ->
                    return parse(reader)
                }
            }
        }

        private fun parse(reader: BufferedReader): StationCodeLookup {
            val index = HashMap<String, HashMap<String, StationInfo>>()
            var isHeader = true
            reader.forEachLine { rawLine ->
                if (rawLine.isEmpty()) return@forEachLine
                if (isHeader) {
                    isHeader = false
                    return@forEachLine
                }
                val fields = parseCsvLine(rawLine)
                if (fields.size <= COL_STATION_NAME) return@forEachLine
                val lineCode = fields[COL_LINE].trim().uppercase()
                val stationCode = fields[COL_STATION].trim().uppercase()
                val info = StationInfo(
                    companyName = fields[COL_COMPANY].trim(),
                    lineName = fields[COL_LINE_NAME].trim(),
                    stationName = fields[COL_STATION_NAME].trim(),
                )
                index.getOrPut(lineCode) { HashMap() }[stationCode] = info
            }
            return StationCodeLookup(index)
        }

        /** Minimal RFC-4180 style splitter: honors double-quoted fields. */
        private fun parseCsvLine(line: String): List<String> {
            val fields = ArrayList<String>()
            val current = StringBuilder()
            var inQuotes = false
            var i = 0
            while (i < line.length) {
                val c = line[i]
                when {
                    inQuotes -> {
                        if (c == '"') {
                            if (i + 1 < line.length && line[i + 1] == '"') {
                                current.append('"')
                                i++
                            } else {
                                inQuotes = false
                            }
                        } else {
                            current.append(c)
                        }
                    }
                    c == '"' -> inQuotes = true
                    c == ',' -> {
                        fields.add(current.toString())
                        current.setLength(0)
                    }
                    else -> current.append(c)
                }
                i++
            }
            fields.add(current.toString())
            return fields
        }
    }
}
