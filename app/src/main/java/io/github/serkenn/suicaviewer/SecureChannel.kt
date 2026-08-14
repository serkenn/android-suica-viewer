package io.github.serkenn.suicaviewer

import javax.crypto.Cipher
import javax.crypto.spec.IvParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * FeliCa Standard secure messaging (DES scheme), ported from `felica-rs`
 * (`felica_standard::secure::des`) as used by the desktop viewer.
 *
 * The auth server takes part only in the mutual authentication: it hands back
 * the ephemeral session material and forgets the session, and every encrypted
 * command from there on is built, sent and verified here. Card data therefore
 * never crosses the network.
 */

private const val DES_BLOCK_SIZE = 8
private const val DES_MAC_SIZE = 8

/** Raised when secure messaging fails (bad MAC, replayed counter, framing). */
class SecureSessionError(message: String) : Exception(message)

/**
 * The ephemeral secure session established by the auth server.
 *
 * [transactionNumber] is a counter shared with the card: it advances once for
 * every command sent and once for every response received, and a response that
 * fails to advance it is a replay.
 */
class SecureSession(
    val key: ByteArray,
    val transactionId: ByteArray,
    transactionNumber: Int,
) {
    var transactionNumber: Int = transactionNumber
        private set

    init {
        require(key.size == 8) { "セッション鍵は 8 バイトである必要があります。" }
        require(transactionId.size == 6) { "トランザクション ID は 6 バイトである必要があります。" }
        require(transactionNumber in 0..0xFFFF) { "トランザクション番号が範囲外です。" }
    }

    /** Claims the next number for an outgoing command. */
    fun nextTransactionNumber(): Int {
        if (transactionNumber >= 0xFFFF) {
            throw SecureSessionError("セキュアセッションのトランザクション番号が上限に達しました。")
        }
        transactionNumber += 1
        return transactionNumber
    }

    /** Adopts the number the card reported, after it has been checked. */
    fun adoptTransactionNumber(value: Int) {
        transactionNumber = value
    }
}

/**
 * Runs encrypted commands against the card over an established [SecureSession].
 *
 * [transceive] sends one raw Type 3 frame (length byte included) and returns the
 * card's reply.
 */
class SecureCardChannel(
    private val session: SecureSession,
    private val transceive: (ByteArray) -> ByteArray,
) {
    /**
     * Sends one secure command and returns the decrypted response payload
     * (status flags first, exactly as the card wrote them).
     */
    fun exchange(commandCode: Int, commandPayload: ByteArray): ByteArray {
        val transactionNumber = session.nextTransactionNumber()

        val payload = ByteArray(2 + session.transactionId.size + commandPayload.size)
        payload[0] = (transactionNumber and 0xFF).toByte()
        payload[1] = ((transactionNumber shr 8) and 0xFF).toByte()
        session.transactionId.copyInto(payload, 2)
        commandPayload.copyInto(payload, 2 + session.transactionId.size)

        val padded = padToDesBlockSize(payload)
        val commandData = padded + calculateCommandMac(commandCode, padded)
        val encrypted = desCbcEncryptZeroIv(commandData, session.key)

        val responseCode = commandCode + 1
        val response = transceive(frameWithLengthPrefix(commandCode, encrypted))
        if (response.size < 2) throw SecureSessionError("暗号化応答が短すぎます。")
        if ((response[0].toInt() and 0xFF) != response.size) {
            throw SecureSessionError("暗号化応答の長さが一致しません。")
        }
        if ((response[1].toInt() and 0xFF) != responseCode) {
            throw SecureSessionError("暗号化応答のコマンドコードが一致しません。")
        }

        val body = response.copyOfRange(2, response.size)
        if (body.size % DES_BLOCK_SIZE != 0 || body.size < DES_BLOCK_SIZE * 2) {
            throw SecureSessionError("暗号化応答の長さが不正です。")
        }
        val plaintext = desCbcDecryptZeroIv(body, session.key)
        if (!checkPacketMac(plaintext, responseCode)) {
            throw SecureSessionError("暗号化応答の MAC 検証に失敗しました。")
        }

        val responseTransactionNumber =
            (plaintext[0].toInt() and 0xFF) or ((plaintext[1].toInt() and 0xFF) shl 8)
        val responseTransactionId = plaintext.copyOfRange(2, 8)
        if (!responseTransactionId.contentEquals(session.transactionId)) {
            throw SecureSessionError("暗号化応答のトランザクション ID が一致しません。")
        }
        if (responseTransactionNumber <= transactionNumber) {
            throw SecureSessionError("暗号化応答のトランザクション番号が進んでいません。")
        }
        session.adoptTransactionNumber(responseTransactionNumber)

        // Drop the 8-byte header and the trailing MAC; any PKCS#7 padding the
        // card appended stays and is ignored by the callers, which read a fixed
        // prefix (status flags, block count, blocks).
        return plaintext.copyOfRange(8, plaintext.size - DES_MAC_SIZE)
    }
}

// ---- DES secure-messaging primitives ---------------------------------------

private fun frameWithLengthPrefix(commandCode: Int, encrypted: ByteArray): ByteArray {
    val length = encrypted.size + 2
    if (length > 0xFF) throw SecureSessionError("コマンドフレームが長すぎます。")
    val frame = ByteArray(length)
    frame[0] = length.toByte()
    frame[1] = commandCode.toByte()
    encrypted.copyInto(frame, 2)
    return frame
}

/** PKCS#7 padding, applied only when the payload is not already aligned. */
internal fun padToDesBlockSize(data: ByteArray): ByteArray {
    val remainder = data.size % DES_BLOCK_SIZE
    if (remainder == 0) return data
    val padLength = DES_BLOCK_SIZE - remainder
    val padded = data.copyOf(data.size + padLength)
    for (i in data.size until padded.size) padded[i] = padLength.toByte()
    return padded
}

/**
 * The command MAC: a DES chain over the payload where each plaintext block is
 * used as the key and the running MAC as the data, seeded with the frame length
 * and command code.
 */
internal fun calculateCommandMac(commandCode: Int, payload: ByteArray): ByteArray {
    if (payload.size % DES_BLOCK_SIZE != 0) {
        throw SecureSessionError("セキュアコマンドのペイロードは 8 バイト単位である必要があります。")
    }
    val totalLength = 2 + payload.size + DES_MAC_SIZE
    if (totalLength > 0xFF) {
        throw SecureSessionError("セキュアコマンドのペイロードが長すぎます。")
    }

    var mac = ByteArray(DES_BLOCK_SIZE)
    mac[0] = totalLength.toByte()
    mac[1] = commandCode.toByte()
    var offset = 0
    while (offset < payload.size) {
        val block = payload.copyOfRange(offset, offset + DES_BLOCK_SIZE)
        mac = desEncryptBlock(mac, block)
        offset += DES_BLOCK_SIZE
    }
    return mac
}

/**
 * Verifies a packet MAC by unwinding the chain: a genuine MAC recovers the
 * whole pre-image `[length, code, 0, 0, 0, 0, 0, 0]`, so all eight bytes are
 * checked — the reserved six carry most of the forgery resistance.
 */
internal fun checkPacketMac(data: ByteArray, expectedResponseCode: Int): Boolean {
    if (data.size % DES_BLOCK_SIZE != 0 || data.size < DES_BLOCK_SIZE + DES_MAC_SIZE) return false

    var current = data.copyOfRange(data.size - DES_MAC_SIZE, data.size)
    var offset = data.size - DES_MAC_SIZE
    while (offset > 0) {
        val block = data.copyOfRange(offset - DES_BLOCK_SIZE, offset)
        current = desDecryptBlock(current, block)
        offset -= DES_BLOCK_SIZE
    }

    val expected = ByteArray(DES_MAC_SIZE)
    expected[0] = (data.size + 2).toByte()
    expected[1] = expectedResponseCode.toByte()
    return current.contentEquals(expected)
}

private fun desKey(key: ByteArray) = SecretKeySpec(key, "DES")

private fun desEncryptBlock(data: ByteArray, key: ByteArray): ByteArray =
    Cipher.getInstance("DES/ECB/NoPadding").run {
        init(Cipher.ENCRYPT_MODE, desKey(key))
        doFinal(data)
    }

private fun desDecryptBlock(data: ByteArray, key: ByteArray): ByteArray =
    Cipher.getInstance("DES/ECB/NoPadding").run {
        init(Cipher.DECRYPT_MODE, desKey(key))
        doFinal(data)
    }

internal fun desCbcEncryptZeroIv(data: ByteArray, key: ByteArray): ByteArray =
    Cipher.getInstance("DES/CBC/NoPadding").run {
        init(Cipher.ENCRYPT_MODE, desKey(key), IvParameterSpec(ByteArray(DES_BLOCK_SIZE)))
        doFinal(data)
    }

internal fun desCbcDecryptZeroIv(data: ByteArray, key: ByteArray): ByteArray =
    Cipher.getInstance("DES/CBC/NoPadding").run {
        init(Cipher.DECRYPT_MODE, desKey(key), IvParameterSpec(ByteArray(DES_BLOCK_SIZE)))
        doFinal(data)
    }
