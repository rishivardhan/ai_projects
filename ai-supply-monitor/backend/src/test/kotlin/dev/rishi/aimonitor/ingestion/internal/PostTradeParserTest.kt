package dev.rishi.aimonitor.ingestion.internal

import dev.rishi.aimonitor.ingestion.internal.deutscheboerse.PostTradeParser
import org.assertj.core.api.Assertions.assertThat
import org.junit.jupiter.api.Test
import java.time.Instant

class PostTradeParserTest {
    private val parser = PostTradeParser()

    @Test
    fun `parses gzipped newline-delimited fixture and skips incomplete records`() {
        val payload = fixture("DETR-posttrade-2026-10-29T08_01.json.gz")

        val result = parser.parse(payload)

        assertThat(result.records).hasSize(8)
        assertThat(result.skipped).isEqualTo(1)
        val first = result.records.first()
        assertThat(first.isin).isEqualTo("DE0007164600")
        assertThat(first.price).isEqualByComparingTo("231.10")
        assertThat(first.quantity).isEqualByComparingTo("100")
        assertThat(first.tradedAt).isEqualTo(Instant.parse("2026-10-29T08:00:05.123456789Z"))
        assertThat(result.records.single { it.transactionId == "T4" }.price).isEqualByComparingTo("231.55")
        assertThat(result.records.filter { it.cancellation }.map { it.transactionId }).containsExactly("T6")
    }

    @Test
    fun `accepts a plain top-level JSON array`() {
        val json =
            """
            [ {"isin":"DE0006231004","lastTrade":35.2,"lastQty":10,"tradingDateTime":"2026-10-29T08:00:10"} ]
            """.trimIndent()

        val result = parser.parse(json.toByteArray())

        assertThat(result.records.single().tradedAt).isEqualTo(Instant.parse("2026-10-29T08:00:10Z"))
    }

    @Test
    fun `empty file yields nothing`() {
        assertThat(parser.parse(ByteArray(0)).records).isEmpty()
        assertThat(parser.parse("  \n".toByteArray()).records).isEmpty()
    }

    private fun fixture(name: String) = javaClass.getResourceAsStream("/fixtures/deutsche-boerse/$name")!!.readAllBytes()
}
