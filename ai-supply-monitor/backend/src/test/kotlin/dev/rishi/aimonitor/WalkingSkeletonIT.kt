package dev.rishi.aimonitor

import dev.rishi.aimonitor.ingestion.internal.deutscheboerse.DeutscheBoerseIngestion
import dev.rishi.aimonitor.marketdata.api.MarketDataQueries
import dev.rishi.aimonitor.reference.api.ListingId
import org.assertj.core.api.Assertions.assertThat
import org.awaitility.Awaitility.await
import org.junit.jupiter.api.Test
import org.springframework.beans.factory.annotation.Autowired
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.boot.test.web.client.TestRestTemplate
import org.springframework.context.annotation.Import
import org.testcontainers.junit.jupiter.Testcontainers
import java.time.Duration
import java.time.Instant

/** M0 slice end to end: post-trade file -> raw archive -> bars in Timescale -> REST. */
@Testcontainers(disabledWithoutDocker = true)
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@Import(TestcontainersConfig::class)
class WalkingSkeletonIT {
    @Autowired lateinit var ingestion: DeutscheBoerseIngestion

    @Autowired lateinit var marketData: MarketDataQueries

    @Autowired lateinit var rest: TestRestTemplate

    private val sap = ListingId("DE0007164600@XETR")
    private val ifx = ListingId("DE0006231004@XETR")
    private val file = "DETR-posttrade-2026-10-29T08_01.json.gz"

    @Test
    fun `a post-trade file becomes queryable bars, and re-importing it changes nothing`() {
        val payload = javaClass.getResourceAsStream("/fixtures/deutsche-boerse/$file")!!.readAllBytes()

        assertThat(ingestion.ingest("DETR-posttrade", "XETR", file, payload)).isEqualTo(3)

        val from = Instant.parse("2026-10-29T00:00:00Z")
        val to = Instant.parse("2026-10-30T00:00:00Z")
        await().atMost(Duration.ofSeconds(10)).until { marketData.bars(sap, from, to).size == 2 }

        val sapBars = marketData.bars(sap, from, to)
        assertThat(sapBars[0].open).isEqualByComparingTo("231.10")
        assertThat(sapBars[0].close).isEqualByComparingTo("231.40")
        assertThat(sapBars[0].volume).isEqualByComparingTo("170")
        // The cancelled 99.99 trade must not appear.
        assertThat(marketData.bars(ifx, from, to).single().high).isEqualByComparingTo("35.20")

        assertThat(ingestion.ingest("DETR-posttrade", "XETR", file, payload)).isNull()

        val json = rest.getForObject("/api/listings/${sap.value}/bars?date=2026-10-29", String::class.java)
        assertThat(json).contains("\"delay\":\"DELAYED_15M\"").contains("231.55")
        assertThat(rest.getForObject("/api/listings", String::class.java)).contains("\"symbol\":\"ASME\"")
    }
}
