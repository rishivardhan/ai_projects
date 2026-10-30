package dev.rishi.aimonitor.api.web

import dev.rishi.aimonitor.marketdata.api.Bar
import dev.rishi.aimonitor.marketdata.api.MarketDataQueries
import dev.rishi.aimonitor.reference.api.ListingId
import dev.rishi.aimonitor.reference.api.ReferenceData
import org.springframework.format.annotation.DateTimeFormat
import org.springframework.http.HttpStatus
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.PathVariable
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RequestParam
import org.springframework.web.bind.annotation.RestController
import org.springframework.web.server.ResponseStatusException
import java.time.LocalDate
import java.time.ZoneId

@RestController
@RequestMapping("/api/listings")
class ListingController(
    private val reference: ReferenceData,
    private val marketData: MarketDataQueries,
) {
    @GetMapping
    fun listings(): List<ListingDto> {
        val companies = reference.companies().associateBy { it.id }
        val latest = marketData.latestBars()
        return reference.listings().map { listing ->
            val company = companies.getValue(listing.company)
            ListingDto(
                id = listing.id.value,
                symbol = listing.symbol,
                companyId = company.id.value,
                companyName = company.name,
                tier = company.tier.name,
                mic = listing.mic,
                currency = listing.currency.currencyCode,
                source = listing.source.value,
                lastBar = latest[listing.id]?.toDto(),
            )
        }
    }

    /** All 1-minute bars of a listing for one calendar day in the given zone (default Frankfurt time). */
    @GetMapping("/{listingId}/bars")
    fun bars(
        @PathVariable listingId: String,
        @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) date: LocalDate,
        @RequestParam(defaultValue = "Europe/Berlin") zone: String,
    ): BarSeriesDto {
        val id = runCatching { ListingId(listingId) }.getOrElse { throw badRequest(it) }
        val zoneId = runCatching { ZoneId.of(zone) }.getOrElse { throw badRequest(it) }
        val listing = reference.listing(id) ?: throw ResponseStatusException(HttpStatus.NOT_FOUND, "Unknown listing $listingId")
        val from = date.atStartOfDay(zoneId).toInstant()
        val to = date.plusDays(1).atStartOfDay(zoneId).toInstant()
        return BarSeriesDto(
            listingId = id.value,
            currency = listing.currency.currencyCode,
            from = from,
            to = to,
            bars = marketData.bars(id, from, to).map { it.toDto() },
        )
    }

    private fun badRequest(cause: Throwable) = ResponseStatusException(HttpStatus.BAD_REQUEST, cause.message, cause)

    private fun Bar.toDto() = BarDto(barStart, open, high, low, close, volume, tradeCount, delay.name, receivedAt)
}
