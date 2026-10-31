package dev.rishi.aimonitor.ingestion.internal.calendar

import dev.rishi.aimonitor.reference.api.Mic
import org.springframework.stereotype.Component
import java.time.DayOfWeek
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId
import java.time.ZonedDateTime

/** Continuous-trading hours of a venue, in the venue's own time zone. */
data class VenueSession(
    val mic: String,
    val zone: ZoneId,
    val open: LocalTime,
    val close: LocalTime,
)

/**
 * Market-session calendar per MIC. Windows are always derived from the venue's time zone, never hard-coded in
 * Frankfurt time, so the weeks where EU and US daylight saving disagree shift the US open to 14:30 CET by themselves.
 *
 * Exchange holidays are not modelled yet (M4); a closed day only costs a few empty polls.
 */
@Component
class SessionCalendar {
    private val sessions =
        listOf(
            VenueSession(Mic.XETRA, BERLIN, LocalTime.of(9, 0), LocalTime.of(17, 30)),
            VenueSession(Mic.BOERSE_FRANKFURT, BERLIN, LocalTime.of(8, 0), LocalTime.of(22, 0)),
            VenueSession(Mic.TRADEGATE, BERLIN, LocalTime.of(8, 0), LocalTime.of(22, 0)),
            VenueSession(Mic.NASDAQ, NEW_YORK, LocalTime.of(9, 30), LocalTime.of(16, 0)),
            VenueSession(Mic.NYSE, NEW_YORK, LocalTime.of(9, 30), LocalTime.of(16, 0)),
        ).associateBy { it.mic }

    fun session(mic: String): VenueSession = sessions[mic] ?: error("No session defined for MIC $mic")

    fun isOpen(
        mic: String,
        at: Instant,
    ): Boolean = isWithin(mic, at, Duration.ZERO)

    /**
     * True while a feed for [mic] can still deliver data: from the open until [trailing] after the close.
     * Delayed feeds publish the last trades of the day only after the close.
     */
    fun isWithin(
        mic: String,
        at: Instant,
        trailing: Duration,
    ): Boolean {
        val s = session(mic)
        val local = at.atZone(s.zone)
        if (local.dayOfWeek in WEEKEND) return false
        val open = local.with(s.open)
        val close = local.with(s.close).plus(trailing)
        return !local.isBefore(open) && local.isBefore(close)
    }

    /** Open and close of [mic] on [date] as instants, for e.g. "chart the whole session". */
    fun sessionBounds(
        mic: String,
        date: LocalDate,
    ): Pair<Instant, Instant> {
        val s = session(mic)
        return ZonedDateTime.of(date, s.open, s.zone).toInstant() to ZonedDateTime.of(date, s.close, s.zone).toInstant()
    }

    companion object {
        val BERLIN: ZoneId = ZoneId.of("Europe/Berlin")
        val NEW_YORK: ZoneId = ZoneId.of("America/New_York")
        private val WEEKEND = setOf(DayOfWeek.SATURDAY, DayOfWeek.SUNDAY)
    }
}
