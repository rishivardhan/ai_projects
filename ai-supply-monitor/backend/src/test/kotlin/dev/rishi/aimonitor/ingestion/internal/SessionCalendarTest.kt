package dev.rishi.aimonitor.ingestion.internal

import dev.rishi.aimonitor.ingestion.internal.calendar.SessionCalendar
import dev.rishi.aimonitor.reference.api.Mic
import org.assertj.core.api.Assertions.assertThat
import org.junit.jupiter.api.Test
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZonedDateTime

class SessionCalendarTest {
    private val calendar = SessionCalendar()
    private val berlin = ZoneId.of("Europe/Berlin")

    private fun berlin(text: String): Instant = ZonedDateTime.of(java.time.LocalDateTime.parse(text), berlin).toInstant()

    @Test
    fun `xetra is open 09_00 to 17_30 Frankfurt time on weekdays`() {
        assertThat(calendar.isOpen(Mic.XETRA, berlin("2026-10-29T08:59:59"))).isFalse()
        assertThat(calendar.isOpen(Mic.XETRA, berlin("2026-10-29T09:00:00"))).isTrue()
        assertThat(calendar.isOpen(Mic.XETRA, berlin("2026-10-29T17:29:59"))).isTrue()
        assertThat(calendar.isOpen(Mic.XETRA, berlin("2026-10-29T17:30:00"))).isFalse()
        assertThat(calendar.isOpen(Mic.XETRA, berlin("2026-10-31T12:00:00"))).isFalse()
    }

    @Test
    fun `delayed feed stays active for the trailing window after the close`() {
        assertThat(calendar.isWithin(Mic.XETRA, berlin("2026-10-29T17:50:00"), Duration.ofMinutes(30))).isTrue()
        assertThat(calendar.isWithin(Mic.XETRA, berlin("2026-10-29T18:00:00"), Duration.ofMinutes(30))).isFalse()
    }

    @Test
    fun `US open moves to 14_30 Frankfurt time while EU and US daylight saving disagree`() {
        // EU left summer time on 25 Oct 2026, the US only on 1 Nov 2026.
        assertThat(calendar.isOpen(Mic.NASDAQ, berlin("2026-10-27T14:30:00"))).isTrue()
        assertThat(calendar.isOpen(Mic.NASDAQ, berlin("2026-10-27T14:29:00"))).isFalse()
        // Normal weeks: 15:30.
        assertThat(calendar.isOpen(Mic.NASDAQ, berlin("2026-11-03T14:30:00"))).isFalse()
        assertThat(calendar.isOpen(Mic.NASDAQ, berlin("2026-11-03T15:30:00"))).isTrue()
    }

    @Test
    fun `session bounds are instants in the venue zone`() {
        val (open, close) = calendar.sessionBounds(Mic.XETRA, LocalDate.of(2026, 10, 29))
        assertThat(open).isEqualTo(Instant.parse("2026-10-29T08:00:00Z"))
        assertThat(close).isEqualTo(Instant.parse("2026-10-29T16:30:00Z"))
    }
}
