package io.github.serkenn.suicaviewer

import android.nfc.NfcAdapter
import android.nfc.Tag
import android.nfc.tech.NfcF
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Suica viewer host. Uses NFC reader mode to poll a FeliCa card, relays the
 * mutual-authentication and read exchanges through the remote crypto server
 * (see [SuicaCardReader]), and renders the same fields as the desktop app.
 */
class MainActivity : ComponentActivity(), NfcAdapter.ReaderCallback {
    private var uiState by mutableStateOf<SuicaUiState>(SuicaUiState.Idle)
    private var nfcAdapter: NfcAdapter? = null
    private var stationLookup: StationCodeLookup? = null

    // Reader mode re-dispatches onTagDiscovered continuously while a card stays
    // in the field. Guard against overlapping reads, and skip a card we already
    // handled so the UI stops looping and stays interactive.
    private val reading = AtomicBoolean(false)
    @Volatile private var lastIdmHex: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        nfcAdapter = NfcAdapter.getDefaultAdapter(this)
        try {
            stationLookup = StationCodeLookup.fromAssets(this)
        } catch (e: Exception) {
            uiState = SuicaUiState.Error("駅データの読み込みに失敗しました: ${e.message}")
        }
        setContent { SuicaViewerApp(uiState, onReset = ::resetForRescan) }
    }

    /** Clear the last-read card so the next tap (or the card still held) re-reads. */
    private fun resetForRescan() {
        lastIdmHex = null
        uiState = SuicaUiState.Idle
    }

    override fun onResume() {
        super.onResume()
        val adapter = nfcAdapter
        if (adapter == null) {
            uiState = SuicaUiState.Error("この端末は NFC に対応していません。")
            return
        }
        adapter.enableReaderMode(
            this,
            this,
            NfcAdapter.FLAG_READER_NFC_F or NfcAdapter.FLAG_READER_SKIP_NDEF_CHECK,
            null,
        )
    }

    override fun onPause() {
        nfcAdapter?.disableReaderMode(this)
        super.onPause()
    }

    override fun onTagDiscovered(tag: Tag) {
        val idmHex = tag.id.toHexUpper()
        // Already handled this card (or it is still on the reader): do nothing so
        // the result stays on screen and remains touchable.
        if (idmHex == lastIdmHex) return
        // A read is already running: ignore re-dispatches until it finishes.
        if (!reading.compareAndSet(false, true)) return

        try {
            val lookup = stationLookup
            if (lookup == null) {
                setState(SuicaUiState.Error("駅データが利用できません。"))
                return
            }
            val nfcF = NfcF.get(tag)
            if (nfcF == null) {
                setState(SuicaUiState.Error("NFC-F カードではありません。"))
                return
            }

            setState(SuicaUiState.Reading(0))
            try {
                nfcF.connect()
                nfcF.timeout = 1000
                val idm = nfcF.tag.id
                val pmm = nfcF.manufacturer
                val reader = SuicaCardReader(DEFAULT_AUTH_SERVER_URL, idm, pmm, lookup) { frame ->
                    nfcF.transceive(frame)
                }
                val card = reader.collect { progress -> setState(SuicaUiState.Reading(progress)) }
                setState(SuicaUiState.Success(card))
            } catch (e: Exception) {
                setState(SuicaUiState.Error(e.message ?: "カード読み取りに失敗しました。"))
            } finally {
                runCatching { nfcF.close() }
            }
        } finally {
            // Mark this card as handled (success or failure) so it does not loop.
            // "再読み込み" clears this to allow a deliberate re-read.
            lastIdmHex = idmHex
            reading.set(false)
        }
    }

    private fun setState(state: SuicaUiState) {
        runOnUiThread { uiState = state }
    }
}

sealed interface SuicaUiState {
    data object Idle : SuicaUiState
    data class Reading(val progress: Int) : SuicaUiState
    data class Success(val card: CardData) : SuicaUiState
    data class Error(val message: String) : SuicaUiState
}
