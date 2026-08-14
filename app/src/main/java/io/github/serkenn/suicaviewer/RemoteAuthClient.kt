package io.github.serkenn.suicaviewer

import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL

/** Raised for client-side transport or validation issues. */
class FelicaRemoteClientError(message: String) : Exception(message)

/** Raised when the card (via the server) reports a FeliCa status error. */
class CardCommandError(val statusCode: Int) :
    Exception("カードがエラーを返しました: 0x%04X".format(statusCode))

/** What the server returns once mutual authentication completes. */
data class AuthenticationResult(
    /** Issue ID (IDi) as uppercase hex. */
    val issueIdHex: String,
    /** Issue parameter (PMi) as uppercase hex. */
    val issueParameterHex: String,
    /** The ephemeral secure session, which the client drives from here on. */
    val session: SecureSession,
)

/** The only secure-session scheme the server issues. */
private const val DES_SCHEME = "des"

/**
 * Coordinates the mutual authentication with the remote crypto server, ported
 * from the desktop viewer's `auth_client`.
 *
 * The server's involvement ends there: it builds each authentication frame, this
 * client puts it on the card (via [transceive]) and sends the card's reply back,
 * and on success the server hands over the ephemeral session material and
 * forgets the session. Every encrypted read afterwards runs locally through
 * [SecureCardChannel], so no card data reaches the network.
 */
class RemoteAuthClient(
    serverUrl: String,
    private val idm: ByteArray,
    private val pmm: ByteArray,
    private val httpTimeoutMs: Int = 10_000,
    /** Sends a raw FeliCa frame to the card and returns its response. */
    private val transceive: (ByteArray) -> ByteArray,
) {
    private val baseUrl: String = validateServerUrl(serverUrl)
    private var sessionId: String? = null

    /** Perform a remote mutual authentication sequence. */
    fun mutualAuthentication(
        systemCode: Int,
        areas: List<Int>,
        services: List<Int>,
    ): AuthenticationResult {
        val request = JSONObject().apply {
            put("session_id", sessionId ?: JSONObject.NULL)
            put("idm", idm.toHexLower())
            put("pmm", pmm.toHexLower())
            put("system_code", systemCode)
            put("areas", JSONArray(areas))
            put("services", JSONArray(services))
        }

        var response = post("/mutual-authentication", request)
        updateSessionId(response)

        while (true) {
            when (response.optString("step")) {
                "auth1", "auth2" -> {
                    val frame = extractCommandFrame(response)
                    val cardResponse = transceive(frame)
                    response = post(
                        "/mutual-authentication",
                        JSONObject().apply {
                            put("session_id", sessionId ?: JSONObject.NULL)
                            put("card_response", cardResponse.toHexLower())
                        },
                    )
                    updateSessionId(response)
                }
                "complete" -> {
                    // The server discards the session the moment it hands the
                    // material over, so the id is already dead here.
                    sessionId = null
                    return authenticationResult(response)
                }
                else -> throw FelicaRemoteClientError("unexpected server response: $response")
            }
        }
    }

    /** Reset session state so the transport can be reused for a fresh authentication. */
    fun reset() {
        sessionId = null
    }

    private fun extractCommandFrame(response: JSONObject): ByteArray {
        val command = response.optJSONObject("command")
            ?: throw FelicaRemoteClientError("missing command data in response: $response")
        val frameHex = command.optString("frame", "")
        if (frameHex.isEmpty()) {
            throw FelicaRemoteClientError("missing command data in response: $response")
        }
        return frameHex.hexToBytes()
    }

    private fun updateSessionId(response: JSONObject) {
        val id = response.optString("session_id", "")
        if (id.isNotEmpty()) sessionId = id
    }

    private fun post(path: String, payload: JSONObject): JSONObject {
        val decoded = postWithRetry(path, payload)
        val error = decoded.optJSONObject("error")
        if (error != null) {
            if (error.has("code") && !error.isNull("code")) {
                throw CardCommandError(error.getInt("code"))
            }
            throw FelicaRemoteClientError(error.optString("message", "server reported an error"))
        }
        return decoded
    }

    /**
     * A transport hiccup is retried once: a pooled connection can be closed by
     * the far end between requests, through no fault of this request.
     */
    private fun postWithRetry(path: String, payload: JSONObject): JSONObject {
        var lastError: java.io.IOException? = null
        repeat(2) {
            try {
                return postRaw(path, payload)
            } catch (e: java.io.IOException) {
                lastError = e
            }
        }
        throw FelicaRemoteClientError("サーバ通信エラー: ${lastError?.message ?: "原因不明のエラー"}")
    }

    private fun postRaw(path: String, payload: JSONObject): JSONObject {
        val url = URL("$baseUrl$path")
        val connection = url.openConnection() as HttpURLConnection
        try {
            connection.requestMethod = "POST"
            connection.connectTimeout = httpTimeoutMs
            connection.readTimeout = httpTimeoutMs
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json")
            connection.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }

            val status = connection.responseCode
            val stream = if (status >= 400) connection.errorStream else connection.inputStream
            val body = stream?.let {
                BufferedReader(InputStreamReader(it, Charsets.UTF_8)).use(BufferedReader::readText)
            } ?: ""

            if (status >= 400) {
                val (message, errno) = extractError(body, "$status ${connection.responseMessage}")
                if (errno != null) throw CardCommandError(errno)
                throw FelicaRemoteClientError("$status ${connection.responseMessage}: $message")
            }

            return if (body.isEmpty()) JSONObject() else JSONObject(body)
        } finally {
            connection.disconnect()
        }
    }

    private fun extractError(body: String, default: String): Pair<String, Int?> {
        return try {
            val error = JSONObject(body).optJSONObject("error") ?: return default to null
            val message = error.optString("message", default)
            val errno = if (error.has("code") && !error.isNull("code")) error.getInt("code") else null
            message to errno
        } catch (_: Exception) {
            default to null
        }
    }
}

/**
 * Normalizes and checks a server URL up front, so a typo surfaces before a card
 * is ever touched rather than as a confusing mid-authentication failure.
 */
fun validateServerUrl(serverUrl: String): String {
    val trimmed = serverUrl.trim().trimEnd('/')
    val scheme = trimmed.substringBefore("://", "").lowercase()
    if (scheme != "http" && scheme != "https") {
        throw FelicaRemoteClientError("認証サーバの URL は http または https である必要があります。")
    }
    if (trimmed.substringAfter("://", "").isEmpty()) {
        throw FelicaRemoteClientError("認証サーバの URL にホスト名がありません。")
    }
    return trimmed
}

/** Reads the completed authentication out of the server's final reply. */
private fun authenticationResult(response: JSONObject): AuthenticationResult {
    val result = response.optJSONObject("result") ?: JSONObject()

    fun field(vararg names: String): String {
        for (name in names) {
            val value = result.optString(name, "")
            if (value.isNotEmpty()) return value.uppercase()
        }
        return ""
    }

    val issueIdHex = field("issue_id", "idi")
    if (issueIdHex.isEmpty()) {
        throw FelicaRemoteClientError("サーバ応答に Issue ID が含まれていません。")
    }
    val issueParameterHex = field("issue_parameter", "pmi")
    if (issueParameterHex.isEmpty()) {
        throw FelicaRemoteClientError("サーバ応答に Issue Parameter が含まれていません。")
    }
    runCatching { issueIdHex.hexToBytes() }
        .getOrElse { throw FelicaRemoteClientError("Issue ID の形式が不正です。") }

    val session = result.optJSONObject("session")
        ?: throw FelicaRemoteClientError(
            "サーバ応答にセッション情報が含まれていません。認証サーバが対応バージョンか確認してください。",
        )
    return AuthenticationResult(issueIdHex, issueParameterHex, secureSession(session))
}

/** Reads the ephemeral session material the server established with the card. */
private fun secureSession(session: JSONObject): SecureSession {
    val scheme = session.optString("scheme", DES_SCHEME)
    if (!scheme.equals(DES_SCHEME, ignoreCase = true)) {
        throw FelicaRemoteClientError("未対応のセッション方式です: $scheme")
    }

    fun bytes(name: String, size: Int): ByteArray {
        val value = session.optString(name, "")
        if (value.isEmpty()) throw FelicaRemoteClientError("セッション情報に $name がありません。")
        val decoded = runCatching { value.hexToBytes() }.getOrNull()
        if (decoded == null || decoded.size != size) {
            throw FelicaRemoteClientError("セッション情報の $name が不正です（$size バイトの hex が必要）。")
        }
        return decoded
    }

    val transactionNumber = session.optInt("transaction_number", -1)
    if (transactionNumber !in 0..0xFFFF) {
        throw FelicaRemoteClientError("セッション情報の transaction_number が不正です。")
    }
    return SecureSession(bytes("key", 8), bytes("transaction_id", 6), transactionNumber)
}

fun ByteArray.toHexLower(): String = joinToString("") { "%02x".format(it) }

fun String.hexToBytes(): ByteArray {
    val clean = trim()
    require(clean.length % 2 == 0) { "invalid hex length" }
    return ByteArray(clean.length / 2) {
        clean.substring(it * 2, it * 2 + 2).toInt(16).toByte()
    }
}
