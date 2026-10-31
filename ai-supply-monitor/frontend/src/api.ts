import type { BarSeries, Listing } from "./types";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} for ${path}`);
  return (await res.json()) as T;
}

export const fetchListings = () => get<Listing[]>("/api/listings");

export const fetchBars = (listingId: string, date: string) =>
  get<BarSeries>(`/api/listings/${encodeURIComponent(listingId)}/bars?date=${date}`);
