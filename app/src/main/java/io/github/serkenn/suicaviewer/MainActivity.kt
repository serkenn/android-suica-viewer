package io.github.serkenn.suicaviewer

import android.nfc.NfcAdapter
import android.nfc.Tag
import android.nfc.tech.NfcF
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import java.time.LocalDate
import java.time.format.DateTimeFormatter

class MainActivity : ComponentActivity(), NfcAdapter.ReaderCallback {
    private var snapshot by mutableStateOf(SuicaSnapshot.initial())
    private var nfcAdapter: NfcAdapter? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        nfcAdapter = NfcAdapter.getDefaultAdapter(this)
        setContent {
            MaterialTheme {
                SuicaViewerScreen(snapshot)
            }
        }
    }

    override fun onResume() {
        super.onResume()
        val adapter = nfcAdapter
        if (adapter == null) {
            snapshot = SuicaSnapshot.error("この端末は NFC に対応していません。")
            return
        }
        adapter.enableReaderMode(
            this,
            this,
            NfcAdapter.FLAG_READER_NFC_F or NfcAdapter.FLAG_READER_SKIP_NDEF_CHECK,
            null
        )
    }

    override fun onPause() {
        nfcAdapter?.disableReaderMode(this)
        super.onPause()
    }

    override fun onTagDiscovered(tag: Tag) {
        runCatching { readSuicaSnapshot(tag) }
            .onSuccess { result -> runOnUiThread { snapshot = result } }
            .onFailure { error ->
                runOnUiThread {
                    snapshot = SuicaSnapshot.error(error.message ?: "カード読み取りに失敗しました。")
                }
            }
    }

    private fun readSuicaSnapshot(tag: Tag): SuicaSnapshot {
        val nfcF = NfcF.get(tag) ?: return SuicaSnapshot.error("NFC-F カードではありません。")
        nfcF.connect()
        return try {
            val idm = nfcF.tag.id
            val pmm = nfcF.manufacturer
            val balance = readBalance(nfcF, idm)
            val history = readHistory(nfcF, idm)
            SuicaSnapshot(
                status = "読み取り成功",
                idmHex = idm.toHex(),
                pmmHex = pmm.toHex(),
                systemCodeHex = nfcF.systemCode.toHex(),
                balance = balance,
                transactions = history,
            )
        } finally {
            nfcF.close()
        }
    }

    private fun readBalance(nfcF: NfcF, idm: ByteArray): Int? {
        val block = readWithoutEncryption(nfcF, idm, SERVICE_BALANCE, 0) ?: return null
        // 属性情報ブロックの SF 残高は offset 11-12（リトルエンディアン）。
        // 履歴ブロックの残高 offset 10-11 と取り違えないこと。
        return littleEndianUInt16(block[11], block[12])
    }

    private fun readHistory(nfcF: NfcF, idm: ByteArray): List<TransactionRecord> {
        val records = mutableListOf<TransactionRecord>()
        for (blockNumber in 0 until 20) {
            val block = readWithoutEncryption(nfcF, idm, SERVICE_HISTORY, blockNumber) ?: break
            val terminal = block[0].toInt() and 0xFF
            if (terminal == 0x00) break
            val transactionType = block[1].toInt() and 0x7F
            val date = decodeDate(block[4], block[5])
            val inLine = block[6].toInt() and 0xFF
            val inStation = block[7].toInt() and 0xFF
            val outLine = block[8].toInt() and 0xFF
            val outStation = block[9].toInt() and 0xFF
            val balance = littleEndianUInt16(block[10], block[11])
            records += TransactionRecord(
                date = date,
                terminal = terminalLabel(terminal),
                transactionType = transactionTypeLabel(transactionType),
                route = "${inLine.toHex2()}-${inStation.toHex2()} → ${outLine.toHex2()}-${outStation.toHex2()}",
                balance = balance,
            )
        }
        return records
    }

    private fun readWithoutEncryption(
        nfcF: NfcF,
        idm: ByteArray,
        serviceCode: Int,
        blockNumber: Int,
    ): ByteArray? {
        val command = ByteArray(14)
        command[0] = command.size.toByte()
        command[1] = 0x06
        System.arraycopy(idm, 0, command, 2, 8)
        command[10] = 0x01
        command[11] = (serviceCode and 0xFF).toByte()
        command[12] = ((serviceCode shr 8) and 0xFF).toByte()
        command[13] = 0x01

        val blockList = byteArrayOf(0x80.toByte(), (blockNumber and 0xFF).toByte())
        val fullCommand = command + blockList
        fullCommand[0] = fullCommand.size.toByte()

        val response = nfcF.transceive(fullCommand)
        if (response.size < 13 || response[1].toInt() != 0x07) return null
        if ((response[10].toInt() and 0xFF) != 0x00 || (response[11].toInt() and 0xFF) != 0x00) return null
        if ((response[12].toInt() and 0xFF) < 1 || response.size < 29) return null
        return response.copyOfRange(13, 29)
    }

    private fun decodeDate(high: Byte, low: Byte): String {
        val raw = ((high.toInt() and 0xFF) shl 8) or (low.toInt() and 0xFF)
        if (raw == 0) return "-"
        val year = 2000 + ((raw shr 9) and 0x7F)
        val month = (raw shr 5) and 0x0F
        val day = raw and 0x1F
        return runCatching {
            LocalDate.of(year, month, day).format(DateTimeFormatter.ISO_LOCAL_DATE)
        }.getOrElse { "${year}-${month.toString().padStart(2, '0')}-${day.toString().padStart(2, '0')}" }
    }

    private fun littleEndianUInt16(low: Byte, high: Byte): Int =
        (low.toInt() and 0xFF) or ((high.toInt() and 0xFF) shl 8)

    private fun Int.toHex2(): String = toString(16).padStart(2, '0').uppercase()

    private fun ByteArray.toHex(): String = joinToString("") { "%02X".format(it) }
}

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@androidx.compose.runtime.Composable
private fun SuicaViewerScreen(snapshot: SuicaSnapshot) {
    Scaffold(topBar = { TopAppBar(title = { Text("Suica Viewer (Android)") }) }) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(text = snapshot.status, style = MaterialTheme.typography.titleMedium)
                        Text("残高: ${snapshot.balance?.let { "$it 円" } ?: "-"}")
                        Text("IDm: ${snapshot.idmHex}", fontFamily = FontFamily.Monospace)
                        Text("PMm: ${snapshot.pmmHex}", fontFamily = FontFamily.Monospace)
                        Text("System Code: ${snapshot.systemCodeHex}", fontFamily = FontFamily.Monospace)
                    }
                }
            }

            items(snapshot.transactions) { tx ->
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        Text("${tx.date} ${tx.transactionType}", style = MaterialTheme.typography.titleSmall)
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text(tx.terminal)
                            Text("残高 ${tx.balance} 円")
                        }
                        Text(tx.route, fontFamily = FontFamily.Monospace)
                    }
                }
            }
        }
    }
}

data class TransactionRecord(
    val date: String,
    val terminal: String,
    val transactionType: String,
    val route: String,
    val balance: Int,
)

data class SuicaSnapshot(
    val status: String,
    val idmHex: String,
    val pmmHex: String,
    val systemCodeHex: String,
    val balance: Int?,
    val transactions: List<TransactionRecord>,
) {
    companion object {
        fun initial() = SuicaSnapshot(
            status = "カードをかざしてください",
            idmHex = "-",
            pmmHex = "-",
            systemCodeHex = "-",
            balance = null,
            transactions = emptyList(),
        )

        fun error(message: String) = SuicaSnapshot(
            status = "エラー: $message",
            idmHex = "-",
            pmmHex = "-",
            systemCodeHex = "-",
            balance = null,
            transactions = emptyList(),
        )
    }
}

private const val SERVICE_BALANCE = 0x008B
private const val SERVICE_HISTORY = 0x090F

private fun terminalLabel(code: Int): String = when (code) {
    0x16 -> "自動改札機"
    0x17 -> "簡易改札機"
    0x1B -> "モバイルFeliCa"
    0xC7, 0xC8 -> "物販端末"
    else -> "機器種別 0x${code.toString(16).padStart(2, '0').uppercase()}"
}

private fun transactionTypeLabel(code: Int): String = when (code) {
    0x01 -> "自動改札機出場"
    0x02 -> "SFチャージ"
    0x03 -> "きっぷ購入"
    0x05 -> "乗越精算"
    0x0D -> "バス等均一運賃"
    0x0F -> "バス等"
    0x13 -> "料金出場"
    0x14 -> "オートチャージ"
    0x46 -> "物販"
    0x48 -> "ポイントチャージ"
    else -> "取引種別 0x${code.toString(16).padStart(2, '0').uppercase()}"
}
