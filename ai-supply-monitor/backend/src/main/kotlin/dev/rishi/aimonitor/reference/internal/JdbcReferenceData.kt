package dev.rishi.aimonitor.reference.internal

import dev.rishi.aimonitor.reference.api.Company
import dev.rishi.aimonitor.reference.api.CompanyId
import dev.rishi.aimonitor.reference.api.Listing
import dev.rishi.aimonitor.reference.api.ListingId
import dev.rishi.aimonitor.reference.api.ReferenceData
import dev.rishi.aimonitor.reference.api.SourceId
import dev.rishi.aimonitor.reference.api.Tier
import org.springframework.jdbc.core.simple.JdbcClient
import org.springframework.stereotype.Repository
import java.sql.ResultSet
import java.util.Currency

@Repository
internal class JdbcReferenceData(private val jdbc: JdbcClient) : ReferenceData {
    override fun companies(): List<Company> =
        jdbc.sql("SELECT * FROM reference.company ORDER BY tier, name").query { rs, _ -> rs.toCompany() }.list()

    override fun company(id: CompanyId): Company? =
        jdbc
            .sql("SELECT * FROM reference.company WHERE id = ?")
            .param(id.value)
            .query { rs, _ -> rs.toCompany() }
            .optional()
            .orElse(null)

    override fun listings(): List<Listing> =
        jdbc.sql("SELECT * FROM reference.listing ORDER BY mic, symbol").query { rs, _ -> rs.toListing() }.list()

    override fun listing(id: ListingId): Listing? =
        jdbc
            .sql("SELECT * FROM reference.listing WHERE id = ?")
            .param(id.value)
            .query { rs, _ -> rs.toListing() }
            .optional()
            .orElse(null)

    override fun listingsByIsin(mic: String): Map<String, Listing> =
        jdbc
            .sql("SELECT * FROM reference.listing WHERE mic = ?")
            .param(mic)
            .query { rs, _ -> rs.toListing() }
            .list()
            .associateBy { it.id.isin }

    private fun ResultSet.toCompany() =
        Company(
            id = CompanyId(getString("id")),
            name = getString("name"),
            tier = Tier.valueOf(getString("tier")),
            country = getString("country"),
            tradable = getBoolean("tradable"),
        )

    private fun ResultSet.toListing() =
        Listing(
            id = ListingId(getString("id")),
            company = CompanyId(getString("company_id")),
            symbol = getString("symbol"),
            mic = getString("mic"),
            currency = Currency.getInstance(getString("currency")),
            source = SourceId(getString("source")),
        )
}
