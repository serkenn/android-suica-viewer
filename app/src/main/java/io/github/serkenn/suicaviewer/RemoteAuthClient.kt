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

/**
 * Coordinates card I/O with the remote crypto server, ported from
 * `suica_viewer/auth_client.py`. The server performs all cryptography; this
 * client is a relay that forwards the server-built FeliCa frames to the card
 * (via [transceive]) and returns the card's response back to the server.
 */
class RemoteAuthClient(
    serverUrl: String,
    private val idm: ByteArray,
    private val pmm: ByteArray,
    private val httpTimeoutMs: Int = 10_000,
    /** Sends a raw FeliCa frame to the card and returns its response. */
    private val transceive: (ByteArray) -> ByteArray,
) {
    private val baseUrl: String = serverUrl.trimEnd('/').ifEmpty { serverUrl }
    private var sessionId: String? = null
    private var authenticated = false

    /** Perform a remote mutual authentication sequence; returns the server result object. */
    fun mutualAuthentication(systemCode: Int, areas: List<Int>, services: List<Int>): JSONObject {
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
                    authenticated = true
                    return response.optJSONObject("result") ?: JSONObject()
                }
                else -> throw FelicaRemoteClientError("unexpected server response: $response")
            }
        }
    }

    /** Send an encrypted command through the server and return the plaintext response. */
    fun encryptionExchange(cmdCode: Int, payload: ByteArray): ByteArray {
        if (!authenticated) {
            throw FelicaRemoteClientError("mutual authentication must be completed first")
        }
        val request = JSONObject().apply {
            put("session_id", sessionId ?: JSONObject.NULL)
            put("cmd_code", cmdCode)
            put("payload", payload.toHexLower())
        }

        var response = post("/encryption-exchange", request)
        updateSessionId(response)

        val frame = extractCommandFrame(response)
        val cardResponse = transceive(frame)
        val finalResponse = post(
            "/encryption-exchange",
            JSONObject().apply {
                put("session_id", sessionId ?: JSONObject.NULL)
                put("card_response", cardResponse.toHexLower())
            },
        )
        updateSessionId(finalResponse)

        val responseHex = finalResponse.optString("response", "")
        if (responseHex.isEmpty()) {
            throw FelicaRemoteClientError("unexpected server response: $finalResponse")
        }
        return responseHex.hexToBytes()
    }

    /** Reset session state so the transport can be reused for a fresh authentication. */
    fun reset() {
        sessionId = null
        authenticated = false
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
        val decoded = postRaw(path, payload)
        val error = decoded.optJSONObject("error")
        if (error != null) {
            if (error.has("code") && !error.isNull("code")) {
                throw CardCommandError(error.getInt("code"))
            }
            throw FelicaRemoteClientError(error.optString("message", "server reported an error"))
        }
        return decoded
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

fun ByteArray.toHexLower(): String = joinToString("") { "%02x".format(it) }

fun String.hexToBytes(): ByteArray {
    val clean = trim()
    require(clean.length % 2 == 0) { "invalid hex length" }
    return ByteArray(clean.length / 2) {
        clean.substring(it * 2, it * 2 + 2).toInt(16).toByte()
    }
}
