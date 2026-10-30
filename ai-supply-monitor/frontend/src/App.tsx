import { useEffect, useState } from "react";
import { fetchBars, fetchListings } from "./api";
import { BarChart } from "./BarChart";
import type { BarSeries, DelayClass, Listing } from "./types";

const berlinDate = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Berlin" });
const price = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const DELAY_LABEL: Record<DelayClass, string> = {
  REALTIME: "live",
  DELAYED_15M: "15 min delayed",
  END_OF_DAY: "end of day",
};

function DelayBadge({ delay }: { delay: DelayClass }) {
  return <span className={`badge badge-${delay.toLowerCase()}`}>{DELAY_LABEL[delay]}</span>;
}

export function App() {
  const [listings, setListings] = useState<Listing[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [date, setDate] = useState(() => berlinDate.format(new Date()));
  const [series, setSeries] = useState<BarSeries | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchListings()
      .then((ls) => {
        setListings(ls);
        const withData = ls.find((l) => l.lastBar) ?? ls[0];
        if (withData) {
          setSelected(withData.id);
          if (withData.lastBar) setDate(berlinDate.format(new Date(withData.lastBar.time)));
        }
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!selected) return;
    fetchBars(selected, date)
      .then(setSeries)
      .catch((e: Error) => setError(e.message));
  }, [selected, date]);

  const listing = listings.find((l) => l.id === selected);
  const bars = series?.listingId === selected ? series.bars : [];
  const last = bars.at(-1);

  return (
    <div className="layout">
      <aside>
        <h1>AI supply chain</h1>
        <p className="muted">M0 · Xetra via Deutsche Börse delayed data</p>
        <ul className="listings">
          {listings.map((l) => (
            <li key={l.id}>
              <button className={l.id === selected ? "active" : ""} onClick={() => setSelected(l.id)}>
                <span className="symbol">{l.symbol}</span>
                <span className="name">{l.companyName}</span>
                <span className="last">{l.lastBar ? price.format(l.lastBar.close) : "–"}</span>
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <main>
        {error && <p className="error">{error}</p>}
        {listing && (
          <header>
            <div>
              <h2>
                {listing.companyName} <span className="muted">{listing.symbol} · {listing.mic}</span>
              </h2>
              <p className="muted">
                {listing.tier.replaceAll("_", " ").toLowerCase()} · {listing.id}
              </p>
            </div>
            <div className="quote">
              {last ? (
                <>
                  <span className="price">
                    {price.format(last.close)} {listing.currency}
                  </span>
                  <DelayBadge delay={last.delay} />
                </>
              ) : (
                <span className="muted">no bars</span>
              )}
            </div>
            <label>
              Day <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </label>
          </header>
        )}
        <BarChart bars={bars} />
        <p className="muted footnote">
          {bars.length} one-minute bars · times in Frankfurt time · source {listing?.source ?? "–"}
        </p>
      </main>
    </div>
  );
}
