// Mirrors the backend DTOs in api/web/Dtos.kt.
// TODO(M1): generate these from the OpenAPI spec with openapi-typescript in CI instead of writing them by hand.

export type DelayClass = "REALTIME" | "DELAYED_15M" | "END_OF_DAY";

export interface Bar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  tradeCount: number;
  delay: DelayClass;
  receivedAt: string;
}

export interface Listing {
  id: string;
  symbol: string;
  companyId: string;
  companyName: string;
  tier: string;
  mic: string;
  currency: string;
  source: string;
  lastBar: Bar | null;
}

export interface BarSeries {
  listingId: string;
  currency: string;
  from: string;
  to: string;
  bars: Bar[];
}
