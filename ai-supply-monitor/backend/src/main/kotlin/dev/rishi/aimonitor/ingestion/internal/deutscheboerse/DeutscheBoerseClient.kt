package dev.rishi.aimonitor.ingestion.internal.deutscheboerse

import org.springframework.http.HttpHeaders
import org.springframework.stereotype.Component
import org.springframework.web.client.RestClient

/**
 * Talks to the Deutsche Börse file service that hosts the MiFIR delayed data.
 * `GET {base}/{prefix}` lists the files currently kept (until midnight of the next business day),
 * `GET {base}/download/{file}` returns one gzipped file.
 */
@Component
class DeutscheBoerseClient(
    properties: DeutscheBoerseProperties,
    builder: RestClient.Builder,
) {
    private val client =
        builder
            .baseUrl(properties.baseUrl.toString())
            .defaultHeader(HttpHeaders.USER_AGENT, properties.userAgent)
            .build()

    /**
     * File names currently offered for [prefix], oldest first. The listing is scanned for names rather than bound
     * to one JSON shape, so a cosmetic change to the listing payload does not stop ingestion.
     */
    fun listFiles(prefix: String): List<String> {
        val body =
            client
                .get()
                .uri("{prefix}", prefix)
                .retrieve()
                .body(String::class.java)
                .orEmpty()
        val pattern = Regex(Regex.escape(prefix) + """-[0-9T_:\-]+\.json(\.gz)?""")
        return pattern
            .findAll(body)
            .map { it.value }
            .distinct()
            .sorted()
            .toList()
    }

    fun download(fileName: String): ByteArray =
        client
            .get()
            .uri("download/{file}", fileName)
            .retrieve()
            .body(ByteArray::class.java)
            ?: error("Empty body for $fileName")
}
