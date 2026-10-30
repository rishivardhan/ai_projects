package dev.rishi.aimonitor.reference.api

/** LEI where available, else an internal slug such as `asml`. */
@JvmInline
value class CompanyId(val value: String) {
    override fun toString() = value
}

/** ISIN + MIC, e.g. `NL0010273215@XETR`. */
@JvmInline
value class ListingId(val value: String) {
    init {
        require(PATTERN.matches(value)) { "ListingId must look like ISIN@MIC, was '$value'" }
    }

    val isin: String get() = value.substringBefore('@')
    val mic: String get() = value.substringAfter('@')

    override fun toString() = value

    companion object {
        private val PATTERN = Regex("^[A-Z]{2}[A-Z0-9]{9}[0-9]@[A-Z0-9]{4}$")

        fun of(isin: String, mic: String) = ListingId("$isin@$mic")
    }
}

/** Identifies a data source adapter, e.g. `deutsche-boerse-detr`. */
@JvmInline
value class SourceId(val value: String) {
    override fun toString() = value
}

/** Market identifier codes (ISO 10383) used in v1. */
object Mic {
    const val XETRA = "XETR"
    const val BOERSE_FRANKFURT = "XFRA"
    const val TRADEGATE = "TGAT"
    const val NASDAQ = "XNAS"
    const val NYSE = "XNYS"
}
