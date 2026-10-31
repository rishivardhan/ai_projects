package dev.rishi.aimonitor.ingestion.internal

import dev.rishi.aimonitor.ingestion.internal.deutscheboerse.DeutscheBoerseClient
import dev.rishi.aimonitor.ingestion.internal.deutscheboerse.DeutscheBoerseProperties
import org.assertj.core.api.Assertions.assertThat
import org.junit.jupiter.api.Test
import org.springframework.http.HttpHeaders
import org.springframework.http.MediaType
import org.springframework.test.web.client.MockRestServiceServer
import org.springframework.test.web.client.match.MockRestRequestMatchers.header
import org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo
import org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess
import org.springframework.web.client.RestClient

class DeutscheBoerseClientTest {
    private val builder = RestClient.builder()
    private val server = MockRestServiceServer.bindTo(builder).build()
    private val client = DeutscheBoerseClient(DeutscheBoerseProperties(), builder)

    @Test
    fun `lists file names for a prefix, sorted and de-duplicated`() {
        server
            .expect(requestTo("https://mfs.deutsche-boerse.com/api/DETR-posttrade"))
            .andExpect(header(HttpHeaders.USER_AGENT, DeutscheBoerseProperties().userAgent))
            .andRespond(
                withSuccess(
                    """
                    {"SourcePrefix":"DETR-posttrade","CurrentFiles":[
                      "DETR-posttrade-2026-10-29T08_02.json.gz",
                      "DETR-posttrade-2026-10-29T08_01.json.gz",
                      "DETR-posttrade-2026-10-29T08_01.json.gz"]}
                    """.trimIndent(),
                    MediaType.APPLICATION_JSON,
                ),
            )

        assertThat(client.listFiles("DETR-posttrade"))
            .containsExactly("DETR-posttrade-2026-10-29T08_01.json.gz", "DETR-posttrade-2026-10-29T08_02.json.gz")
        server.verify()
    }

    @Test
    fun `downloads a file as raw bytes`() {
        val bytes = byteArrayOf(0x1f, 0x8b.toByte(), 1, 2, 3)
        server
            .expect(requestTo("https://mfs.deutsche-boerse.com/api/download/DETR-posttrade-2026-10-29T08_01.json.gz"))
            .andRespond(withSuccess(bytes, MediaType.APPLICATION_OCTET_STREAM))

        assertThat(client.download("DETR-posttrade-2026-10-29T08_01.json.gz")).isEqualTo(bytes)
    }
}
