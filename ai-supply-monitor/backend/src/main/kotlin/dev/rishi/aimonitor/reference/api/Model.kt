package dev.rishi.aimonitor.reference.api

import java.util.Currency

enum class Tier {
    FRONTIER_LAB,
    HYPERSCALER,
    CHIP_DESIGNER,
    FOUNDRY_MEMORY,
    EQUIPMENT_MATERIALS,
    POWER_INFRA,
}

/** How stale a price from a source is by design; shown as a badge next to every price. */
enum class DelayClass {
    REALTIME,
    DELAYED_15M,
    END_OF_DAY,
}

data class Company(
    val id: CompanyId,
    val name: String,
    val tier: Tier,
    val country: String,
    val tradable: Boolean,
)

data class Listing(
    val id: ListingId,
    val company: CompanyId,
    val symbol: String,
    val mic: String,
    val currency: Currency,
    val source: SourceId,
)

/** Read-only queries other modules may run against reference data. */
interface ReferenceData {
    fun companies(): List<Company>

    fun company(id: CompanyId): Company?

    fun listings(): List<Listing>

    fun listing(id: ListingId): Listing?

    /** Listings on the given venue, keyed by ISIN, for adapters that receive ISIN-keyed records. */
    fun listingsByIsin(mic: String): Map<String, Listing>
}
