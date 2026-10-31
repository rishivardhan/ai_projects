package dev.rishi.aimonitor.ingestion.internal.deutscheboerse

import com.fasterxml.jackson.databind.DeserializationFeature
import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import java.io.ByteArrayInputStream
import java.io.InputStream
import java.math.BigDecimal
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneOffset
import java.util.zip.GZIPInputStream

/** One record of a Deutsche Börse MiFIR post-trade file, reduced to the fields v1 uses. */
data class PostTradeRecord(
    val isin: String,
    val currency: String?,
    val price: BigDecimal,
    val quantity: BigDecimal,
    val tradedAt: Instant,
    val transactionId: String?,
    val cancellation: Boolean,
)

/**
 * Parses the delayed post-trade files Deutsche Börse publishes under MiFIR (`DETR-posttrade-*.json.gz` etc.).
 *
 * The file is gzipped JSON; both newline-delimited records and a top-level array are accepted. Unknown fields
 * are ignored and records missing a price, quantity or trade time are skipped and counted, so a format drift shows
 * up as a rising skip count instead of a crash.
 *
 * Field names follow the published post-trade layout (`isin`, `lastTrade`, `lastQty`, `tradingDateTime`,
 * `tickActionIndicator`, `transIdCode`). They still need checking against a recorded real file (see README).
 */
class PostTradeParser(
    private val mapper: ObjectMapper = defaultMapper(),
) {
    data class Result(
        val records: List<PostTradeRecord>,
        val skipped: Int,
    )

    fun parse(payload: ByteArray): Result {
        val records = mutableListOf<PostTradeRecord>()
        var skipped = 0
        nodes(decompress(payload)).forEach { node ->
            val record = toRecord(node)
            if (record == null) skipped++ else records += record
        }
        return Result(records, skipped)
    }

    private fun nodes(input: InputStream): Sequence<JsonNode> {
        val buffered = input.buffered()
        buffered.mark(1)
        var first = buffered.read()
        while (first != -1 && Character.isWhitespace(first)) {
            buffered.mark(1)
            first = buffered.read()
        }
        if (first == -1) return emptySequence()
        buffered.reset()
        return if (first == '['.code) {
            mapper.readTree(buffered).asSequence()
        } else {
            mapper.readerFor(JsonNode::class.java).readValues<JsonNode>(buffered).asSequence()
        }
    }

    private fun toRecord(node: JsonNode): PostTradeRecord? {
        val isin = node.text("isin") ?: return null
        val price = node.decimal("lastTrade") ?: return null
        val quantity = node.decimal("lastQty") ?: return null
        val tradedAt = node.text("tradingDateTime")?.let(::parseTimestamp) ?: return null
        return PostTradeRecord(
            isin = isin,
            currency = node.text("currency"),
            price = price,
            quantity = quantity,
            tradedAt = tradedAt,
            transactionId = node.text("transIdCode"),
            cancellation = node.text("tickActionIndicator") == CANCEL,
        )
    }

    private fun JsonNode.text(field: String): String? =
        get(field)
            ?.takeUnless { it.isNull }
            ?.asText()
            ?.trim()
            ?.ifEmpty { null }

    private fun JsonNode.decimal(field: String): BigDecimal? {
        val value = get(field) ?: return null
        return when {
            value.isNumber -> value.decimalValue()
            value.isTextual -> value.asText().trim().toBigDecimalOrNull()
            else -> null
        }
    }

    private companion object {
        const val CANCEL = "C"
        val GZIP_MAGIC = byteArrayOf(0x1f, 0x8b.toByte())

        fun defaultMapper(): ObjectMapper = ObjectMapper().enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)

        fun decompress(payload: ByteArray): InputStream {
            val gzipped = payload.size >= 2 && payload[0] == GZIP_MAGIC[0] && payload[1] == GZIP_MAGIC[1]
            return if (gzipped) GZIPInputStream(ByteArrayInputStream(payload)) else ByteArrayInputStream(payload)
        }

        /** Timestamps carry nanoseconds and normally a `Z`; a missing offset is read as UTC. */
        fun parseTimestamp(text: String): Instant? =
            runCatching { Instant.parse(text) }.getOrNull()
                ?: runCatching { LocalDateTime.parse(text).toInstant(ZoneOffset.UTC) }.getOrNull()
    }
}
