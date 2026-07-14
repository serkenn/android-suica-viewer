package io.github.serkenn.suicaviewer

import android.content.Intent
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.ScrollableTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SuicaViewerApp(state: SuicaUiState) {
    MaterialTheme {
        Scaffold(topBar = { TopAppBar(title = { Text("Suica ビューア") }) }) { padding ->
            Column(modifier = Modifier.fillMaxSize().padding(padding)) {
                StatusHeader(state)
                if (state is SuicaUiState.Success) {
                    CardTabs(state.card)
                }
            }
        }
    }
}

@Composable
private fun StatusHeader(state: SuicaUiState) {
    val message = when (state) {
        is SuicaUiState.Idle -> "カードをかざしてください"
        is SuicaUiState.Reading -> "読み取り中… ${state.progress}%"
        is SuicaUiState.Success -> "読み取り成功"
        is SuicaUiState.Error -> "エラー: ${state.message}"
    }
    Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
        Text(message, style = MaterialTheme.typography.titleMedium)
        if (state is SuicaUiState.Reading) {
            Spacer(Modifier.height(8.dp))
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }
    }
}

private val TAB_TITLES = listOf("概要", "カード情報", "取引履歴", "改札", "データ")

@Composable
private fun CardTabs(card: CardData) {
    var selected by remember { mutableIntStateOf(0) }
    ScrollableTabRow(selectedTabIndex = selected, edgePadding = 0.dp) {
        TAB_TITLES.forEachIndexed { index, title ->
            Tab(
                selected = selected == index,
                onClick = { selected = index },
                text = { Text(title) },
            )
        }
    }
    when (selected) {
        0 -> OverviewTab(card)
        1 -> CardInfoTab(card)
        2 -> HistoryTab(card)
        3 -> GateTab(card)
        else -> DataTab(card)
    }
}

// ---- Tabs -----------------------------------------------------------------

@Composable
private fun OverviewTab(card: CardData) = ScrollColumn {
    Section("カード識別") {
        LabeledRow("IDm", card.system.idmHex, mono = true)
        LabeledRow("PMm", card.system.pmmHex, mono = true)
        LabeledRow("IDi", card.system.idiDisplay, mono = true)
        LabeledRow("PMi", card.system.pmi, mono = true)
        LabeledRow("カード種別", card.attribute.cardType)
    }
    Section("利用サマリ") {
        LabeledRow("残高", formatYen(card.attribute.balance))
        LabeledRow("最終チャージ金額", formatYen(card.lastTopup.amount))
        LabeledRow("取引通番", card.attribute.transactionNumber.toString())
    }
    Section("発行・有効情報") {
        LabeledRow("発行日", card.issuePrimary.issuedAt)
        LabeledRow("有効期限", card.issuePrimary.expiresAt)
        LabeledRow("発行駅", card.issuePrimary.issuedStation)
    }
    Section("定期券ハイライト") {
        if (card.commuter.hasCommuterPass) {
            LabeledRow("区間", "${card.commuter.startStation} → ${card.commuter.endStation}")
            LabeledRow("有効期間", "${card.commuter.validFrom} 〜 ${card.commuter.validTo}")
        } else {
            LabeledRow("区間", "—")
            LabeledRow("有効期間", "—")
        }
    }
}

@Composable
private fun CardInfoTab(card: CardData) = ScrollColumn {
    val issue = card.issuePrimary
    Section("発行情報") {
        LabeledRow("所有者名", issue.ownerName.ifBlank { "—" })
        LabeledRow("所有者電話番号", issue.ownerPhoneHex.ifBlank { "—" }, mono = true)
        LabeledRow("所有者年齢", issue.ownerAgeCode, mono = true)
        LabeledRow("所有者生年月日", issue.ownerBirthdate)
        LabeledRow("第二発行ID", issue.secondaryIssueId, mono = true)
        LabeledRow("発行者ID", issue.issuerId)
        LabeledRow("デポジット額", formatYen(issue.deposit))
        LabeledRow("発行機器", issue.issuedBy)
        LabeledRow("発行駅", issue.issuedStation)
        LabeledRow("発行日", issue.issuedAt)
        LabeledRow("有効期限", issue.expiresAt)
    }
    Section("最終チャージ情報") {
        LabeledRow("チャージ機器", card.lastTopup.equipment)
        LabeledRow("チャージ駅", card.lastTopup.station)
        LabeledRow("チャージ金額", formatYen(card.lastTopup.amount))
    }
    Section("カード属性") {
        LabeledRow("カード種別", card.attribute.cardType)
        LabeledRow("地域", formatRegion(card.attribute.region))
        LabeledRow("残高", formatYen(card.attribute.balance))
        LabeledRow("取引通番", card.attribute.transactionNumber.toString())
    }
    Section("定期券情報") {
        val c = card.commuter
        LabeledRow("開始日", c.validFrom)
        LabeledRow("終了日", c.validTo)
        LabeledRow("始点駅", c.startStation)
        LabeledRow("終点駅", c.endStation)
        LabeledRow("経由駅1", c.via1Station)
        LabeledRow("経由駅2", c.via2Station)
        LabeledRow("発行日", c.issuedAt)
    }
}

@Composable
private fun HistoryTab(card: CardData) {
    var query by remember { mutableStateOf("") }
    val filtered = remember(query, card) {
        if (query.isBlank()) card.transactionHistory
        else card.transactionHistory.filter { it.searchText().contains(query, ignoreCase = true) }
    }
    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            label = { Text("フィルター") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(12.dp))
        if (filtered.isEmpty()) {
            Text("取引履歴はありません。", color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                items(filtered) { entry -> TransactionCard(entry) }
            }
        }
    }
}

@Composable
private fun TransactionCard(entry: TransactionEntry) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(entry.recordedOn, fontWeight = FontWeight.SemiBold)
                Text(entry.transactionType, fontWeight = FontWeight.SemiBold)
            }
            LabeledRow("支払種別", entry.payType)
            LabeledRow("改札処理", entry.gateInstructionType)
            entry.transactionTime?.let { LabeledRow("時刻", it) }
            entry.entryStation?.let { LabeledRow("入場駅", it) }
            entry.exitStation?.let { LabeledRow("出場駅", it) }
            LabeledRow("残高", formatYen(entry.balance))
            LabeledRow("差分", entry.delta?.let { "%+,d 円".format(it) } ?: "—")
            LabeledRow("機器", entry.recordedBy)
            LabeledRow("取引通番", entry.transactionNumber.toString())
        }
    }
}

@Composable
private fun GateTab(card: CardData) = ScrollColumn {
    Section("改札入出場履歴") {
        if (card.gate.isEmpty()) {
            Text("記録はありません。", color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
            card.gate.forEachIndexed { i, g ->
                if (i > 0) Spacer(Modifier.height(8.dp))
                LabeledRow("日時", "${g.date} ${g.time}")
                LabeledRow("入出場種別", g.gateInOutType)
                LabeledRow("中間処理", g.intermediateType)
                LabeledRow("駅", g.station)
                LabeledRow("装置番号", g.deviceIdHex, mono = true)
                LabeledRow("金額", formatYen(g.amount))
                LabeledRow("定期運賃", formatYen(g.commuterPassFee))
                LabeledRow("定期区間駅", g.commuterStation)
            }
        }
    }
    Section("SF改札入場情報") {
        val s = card.sfGate
        LabeledRow("入場駅", s.entryStation)
        LabeledRow("中間改札入場駅", s.intermediateEntryStation)
        LabeledRow("中間改札入場日付", s.intermediateEntryDate)
        LabeledRow("中間改札入場時刻", s.intermediateEntryTime, mono = true)
        LabeledRow("中間改札出場駅", s.intermediateExitStation)
        LabeledRow("中間改札出場時刻", s.intermediateExitTime, mono = true)
        LabeledRow("不明値1", s.unknownValue1Hex, mono = true)
        LabeledRow("不明値2", s.unknownValue2Hex, mono = true)
    }
    if (card.paidTicketAvailable || card.paidTicketReason != null) {
        Section("料金発券情報") {
            if (card.paidTicket.isEmpty()) {
                Text(card.paidTicketReason ?: "記録はありません。", color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else {
                card.paidTicket.forEachIndexed { i, p ->
                    if (i > 0) Spacer(Modifier.height(8.dp))
                    LabeledRow("発駅", p.departStation)
                    LabeledRow("着駅", p.arriveStation)
                    LabeledRow("有効期限", p.expiresAt)
                    LabeledRow("発券時刻", p.issuedTime, mono = true)
                    LabeledRow("金額", formatYen(p.amount))
                    LabeledRow("改札駅", p.checkedStation)
                    LabeledRow("改札時刻", p.checkedTime, mono = true)
                }
            }
        }
    }
}

@Composable
private fun DataTab(card: CardData) {
    val json = remember(card) { card.toJson().toString(2) }
    val clipboard = LocalClipboardManager.current
    val context = LocalContext.current
    ScrollColumn {
        Section("不明な情報") {
            LabeledRow("不明な残高", formatYen(card.unknown.balance))
            LabeledRow("不明な日付", card.unknown.date)
            LabeledRow("不明な取引通番", card.unknown.transactionNumber.toString())
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            OutlinedButton(onClick = { clipboard.setText(AnnotatedString(json)) }) {
                Text("JSONをコピー")
            }
            OutlinedButton(onClick = {
                val share = Intent(Intent.ACTION_SEND).apply {
                    type = "application/json"
                    putExtra(Intent.EXTRA_TEXT, json)
                }
                context.startActivity(Intent.createChooser(share, "カード情報 JSON を共有"))
            }) {
                Text("JSONを共有")
            }
        }
        Spacer(Modifier.height(8.dp))
        Card(modifier = Modifier.fillMaxWidth()) {
            Text(
                text = json,
                modifier = Modifier.padding(12.dp).horizontalScroll(rememberScrollState()),
                fontFamily = FontFamily.Monospace,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

// ---- Reusable pieces ------------------------------------------------------

@Composable
private fun ScrollColumn(content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
        content = content,
    )
}

@Composable
private fun Section(title: String, content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.padding(12.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
                content = content,
            )
        }
    }
}

@Composable
private fun LabeledRow(label: String, value: String, mono: Boolean = false) {
    Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
        Text(
            text = label,
            modifier = Modifier.width(120.dp),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
        )
        Text(
            text = value.ifEmpty { "—" },
            modifier = Modifier.weight(1f),
            fontFamily = if (mono) FontFamily.Monospace else FontFamily.Default,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

private fun TransactionEntry.searchText(): String = listOfNotNull(
    recordedOn, transactionType, payType, gateInstructionType,
    entryStation, exitStation, transactionTime, recordedBy,
    balance.toString(), transactionNumber.toString(),
).joinToString(" ")
