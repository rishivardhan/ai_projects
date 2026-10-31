package dev.rishi.aimonitor.marketdata.internal

import dev.rishi.aimonitor.ingestion.api.PriceBar
import dev.rishi.aimonitor.marketdata.api.Bar
import dev.rishi.aimonitor.marketdata.api.MarketDataQueries
import dev.rishi.aimonitor.reference.api.DelayClass
import dev.rishi.aimonitor.reference.api.ListingId
import dev.rishi.aimonitor.reference.api.SourceId
import org.springframework.jdbc.core.simple.JdbcClient
import org.springframework.stereotype.Repository
import java.sql.ResultSet
import java.sql.Timestamp
import java.time.Instant

@Repository
class BarRepository(private val jdbc: JdbcClient) : MarketDataQueries {
    /**
     * Records [batchId] as applied. Returns false if it was applied before, which makes redelivered events
     * (the publication registry replays unfinished ones on restart) harmless.
     */
    fun claimBatch(batchId: String): Boolean =
        jdbc
            .sql("INSERT INTO marketdata.applied_batch (batch_id) VALUES (?) ON CONFLICT DO NOTHING")
            .param(batchId)
            .update() == 1

    /**
     * Upserts on (listing, bar start). Two partial bars for the same minute merge: open from the earlier first
     * trade, close from the later last trade, extremes and volume combined.
     */
    fun upsert(bar: PriceBar) {
        jdbc
            .sql(
                """
                INSERT INTO marketdata.bar AS b (listing_id, bar_start, open, high, low, close, volume, trade_count,
                                                 first_trade_at, last_trade_at, source, delay_class, received_at)
                VALUES (:listing, :barStart, :open, :high, :low, :close, :volume, :tradeCount,
                        :firstTradeAt, :lastTradeAt, :source, :delay, :receivedAt)
                ON CONFLICT (listing_id, bar_start) DO UPDATE SET
                    open           = CASE WHEN EXCLUDED.first_trade_at < b.first_trade_at THEN EXCLUDED.open ELSE b.open END,
                    close          = CASE WHEN EXCLUDED.last_trade_at >= b.last_trade_at THEN EXCLUDED.close ELSE b.close END,
                    high           = GREATEST(b.high, EXCLUDED.high),
                    low            = LEAST(b.low, EXCLUDED.low),
                    volume         = b.volume + EXCLUDED.volume,
                    trade_count    = b.trade_count + EXCLUDED.trade_count,
                    first_trade_at = LEAST(b.first_trade_at, EXCLUDED.first_trade_at),
                    last_trade_at  = GREATEST(b.last_trade_at, EXCLUDED.last_trade_at),
                    received_at    = GREATEST(b.received_at, EXCLUDED.received_at)
                """.trimIndent(),
            ).param("listing", bar.listing.value)
            .param("barStart", Timestamp.from(bar.barStart))
            .param("open", bar.open)
            .param("high", bar.high)
            .param("low", bar.low)
            .param("close", bar.close)
            .param("volume", bar.volume)
            .param("tradeCount", bar.tradeCount)
            .param("firstTradeAt", Timestamp.from(bar.firstTradeAt))
            .param("lastTradeAt", Timestamp.from(bar.lastTradeAt))
            .param("source", bar.source.value)
            .param("delay", bar.delay.name)
            .param("receivedAt", Timestamp.from(bar.receivedAt))
            .update()
    }

    override fun bars(
        listing: ListingId,
        from: Instant,
        to: Instant,
    ): List<Bar> =
        jdbc
            .sql(
                """
                SELECT * FROM marketdata.bar
                WHERE listing_id = ? AND bar_start >= ? AND bar_start < ?
                ORDER BY bar_start
                """.trimIndent(),
            ).params(listing.value, Timestamp.from(from), Timestamp.from(to))
            .query { rs, _ -> rs.toBar() }
            .list()

    override fun latestBars(): Map<ListingId, Bar> =
        jdbc
            .sql("SELECT DISTINCT ON (listing_id) * FROM marketdata.bar ORDER BY listing_id, bar_start DESC")
            .query { rs, _ -> rs.toBar() }
            .list()
            .associateBy { it.listing }

    private fun ResultSet.toBar() =
        Bar(
            listing = ListingId(getString("listing_id")),
            barStart = getTimestamp("bar_start").toInstant(),
            open = getBigDecimal("open"),
            high = getBigDecimal("high"),
            low = getBigDecimal("low"),
            close = getBigDecimal("close"),
            volume = getBigDecimal("volume"),
            tradeCount = getInt("trade_count"),
            source = SourceId(getString("source")),
            delay = DelayClass.valueOf(getString("delay_class")),
            receivedAt = getTimestamp("received_at").toInstant(),
        )
}
