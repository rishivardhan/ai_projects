package dev.rishi.aimonitor.ingestion.internal.deutscheboerse

import org.springframework.boot.context.properties.ConfigurationProperties
import java.net.URI
import java.time.Duration

/**
 * @property feeds file-name prefix on the Deutsche Börse file service mapped to the MIC whose listings it carries,
 *   e.g. `DETR-posttrade` -> `XETR`.
 */
@Suppress("MagicNumber")
@ConfigurationProperties("aimonitor.ingestion.deutsche-boerse")
data class DeutscheBoerseProperties(
    val enabled: Boolean = false,
    val baseUrl: URI = URI.create("https://mfs.deutsche-boerse.com/api/"),
    val feeds: Map<String, String> = mapOf("DETR-posttrade" to "XETR"),
    val pollInterval: Duration = Duration.ofMinutes(1),
    val trailingAfterClose: Duration = Duration.ofMinutes(30),
    val userAgent: String = "ai-supply-monitor/0.1 (personal research, single user)",
)
