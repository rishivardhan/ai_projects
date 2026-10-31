package dev.rishi.aimonitor.ingestion.internal.archive

import dev.rishi.aimonitor.reference.api.SourceId
import org.springframework.jdbc.core.simple.JdbcClient
import org.springframework.stereotype.Repository
import java.security.MessageDigest
import java.time.Instant
import java.util.HexFormat

data class RawObject(
    val id: Long,
    val source: SourceId,
    val objectName: String,
    val fetchedAt: Instant,
    val payload: ByteArray,
)

/**
 * Raw payloads are stored before parsing, exactly as received (usually already gzipped).
 * A parser bug is fixed by replaying from here, never by re-fetching from a source that may have expired the data.
 */
@Repository
class RawArchive(private val jdbc: JdbcClient) {
    fun contains(
        source: SourceId,
        objectName: String,
    ): Boolean =
        jdbc
            .sql("SELECT count(*) FROM ingestion.raw_ingest WHERE source = ? AND object_name = ?")
            .params(source.value, objectName)
            .query(Long::class.java)
            .single() > 0

    /** Stores the payload and returns it with its id, or null if this object was archived before. */
    fun storeIfNew(
        source: SourceId,
        objectName: String,
        payload: ByteArray,
        fetchedAt: Instant = Instant.now(),
    ): RawObject? {
        val id =
            jdbc
                .sql(
                    """
                    INSERT INTO ingestion.raw_ingest (source, object_name, fetched_at, sha256, size_bytes, payload)
                    VALUES (:source, :name, :fetchedAt, :sha, :size, :payload)
                    ON CONFLICT (source, object_name) DO NOTHING
                    RETURNING id
                    """.trimIndent(),
                ).param("source", source.value)
                .param("name", objectName)
                .param("fetchedAt", java.sql.Timestamp.from(fetchedAt))
                .param("sha", sha256(payload))
                .param("size", payload.size)
                .param("payload", payload)
                .query(Long::class.java)
                .optional()
                .orElse(null) ?: return null
        return RawObject(id, source, objectName, fetchedAt, payload)
    }

    fun markParsed(
        id: Long,
        barCount: Int,
    ) {
        jdbc
            .sql("UPDATE ingestion.raw_ingest SET status = 'PARSED', parsed_at = now(), bar_count = ?, error = NULL WHERE id = ?")
            .params(barCount, id)
            .update()
    }

    fun markFailed(
        id: Long,
        error: String,
    ) {
        jdbc
            .sql("UPDATE ingestion.raw_ingest SET status = 'FAILED', parsed_at = now(), error = ? WHERE id = ?")
            .params(error.take(MAX_ERROR_LENGTH), id)
            .update()
    }

    private fun sha256(bytes: ByteArray) = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes))

    private companion object {
        const val MAX_ERROR_LENGTH = 2000
    }
}
