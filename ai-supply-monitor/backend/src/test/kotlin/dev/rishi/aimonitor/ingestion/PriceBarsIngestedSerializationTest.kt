package dev.rishi.aimonitor.ingestion

import com.fasterxml.jackson.databind.ObjectMapper
import dev.rishi.aimonitor.ingestion.api.PriceBar
import dev.rishi.aimonitor.ingestion.api.PriceBarsIngested
import dev.rishi.aimonitor.reference.api.DelayClass
import dev.rishi.aimonitor.reference.api.ListingId
import dev.rishi.aimonitor.reference.api.SourceId
import org.assertj.core.api.Assertions.assertThat
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.autoconfigure.json.JsonTest
import java.time.Instant

/** Events are serialised into the publication registry; they must survive a round trip with value classes intact. */
@JsonTest
class PriceBarsIngestedSerializationTest {
    @Autowired
    lateinit var mapper: ObjectMapper

    @Test
    fun `round trips through the application ObjectMapper`() {
        val t = Instant.parse("2026-10-29T08:00:00Z")
        val event =
            PriceBarsIngested(
                batchId = "deutsche-boerse-detr/file.json.gz",
                source = SourceId("deutsche-boerse-detr"),
                bars =
                    listOf(
                        PriceBar(
                            ListingId("DE0007164600@XETR"),
                            t,
                            "1.5".toBigDecimal(),
                            "2".toBigDecimal(),
                            "1".toBigDecimal(),
                            "1.75".toBigDecimal(),
                            "100".toBigDecimal(),
                            3,
                            t,
                            t.plusSeconds(30),
                            t,
                            SourceId("x"),
                            DelayClass.DELAYED_15M,
                        ),
                    ),
            )

        val json = mapper.writeValueAsString(event)

        assertThat(json).contains("\"listing\":\"DE0007164600@XETR\"")
        assertThat(mapper.readValue(json, PriceBarsIngested::class.java)).isEqualTo(event)
    }
}
