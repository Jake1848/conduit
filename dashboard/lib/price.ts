"use client";

import { useEffect, useState } from "react";

/* BTC spot price (USD). Cached in-module + localStorage, refreshed every 60s.
   CoinGecko's simple-price endpoint is CORS-enabled for browser use. */

const CACHE_KEY = "conduit_btc_price";
const REFRESH_MS = 60_000;
const FALLBACK = 95_000; // used only until the first successful fetch

interface Cached {
  price: number;
  ts: number;
}

let memo: Cached | null = null;

function readCache(): Cached | null {
  if (memo) return memo;
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(CACHE_KEY);
    if (raw) memo = JSON.parse(raw);
  } catch {
    /* ignore */
  }
  return memo;
}

async function fetchPrice(): Promise<number | null> {
  try {
    const res = await fetch(
      "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
      { headers: { Accept: "application/json" } },
    );
    if (!res.ok) return null;
    const json = (await res.json()) as { bitcoin?: { usd?: number } };
    const p = json?.bitcoin?.usd;
    if (typeof p === "number" && p > 0) {
      memo = { price: p, ts: Date.now() };
      try {
        window.localStorage.setItem(CACHE_KEY, JSON.stringify(memo));
      } catch {
        /* ignore */
      }
      return p;
    }
  } catch {
    /* ignore */
  }
  return null;
}

/** Returns the current BTC/USD price, refreshing in the background every 60s. */
export function useBtcPrice(): number {
  const [price, setPrice] = useState<number>(() => readCache()?.price ?? FALLBACK);

  useEffect(() => {
    let alive = true;
    const cached = readCache();
    const stale = !cached || Date.now() - cached.ts > REFRESH_MS;

    async function refresh() {
      const p = await fetchPrice();
      if (alive && p) setPrice(p);
    }
    if (stale) refresh();
    else if (cached) setPrice(cached.price);

    const t = setInterval(refresh, REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  return price;
}
