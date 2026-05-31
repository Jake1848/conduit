"use client";

import { useEffect, useState } from "react";
import { api } from "./api";

export interface TxCount {
  count: number; // transactions today (cap = fetch limit)
  hasMore: boolean;
}

async function mapPool<T, R>(items: T[], limit: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  const out: R[] = [];
  let i = 0;
  async function worker() {
    while (i < items.length) {
      const idx = i++;
      try {
        out[idx] = await fn(items[idx]);
      } catch {
        out[idx] = undefined as unknown as R;
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return out;
}

/** Fetch today's transaction counts for a (small) set of agent ids. */
export function useTxCounts(ids: string[], limit = 100): Record<string, TxCount> {
  const [counts, setCounts] = useState<Record<string, TxCount>>({});
  const key = ids.join(",");

  useEffect(() => {
    if (ids.length === 0) return;
    let cancelled = false;
    const ctrl = new AbortController();
    (async () => {
      const startOfDay = new Date();
      startOfDay.setHours(0, 0, 0, 0);
      const acc: Record<string, TxCount> = {};
      await mapPool(ids, 10, async (id) => {
        const r = await api.getTransactions(id, limit, ctrl.signal);
        if (cancelled) return;
        const today = r.data.filter((t) => new Date(t.created_at) >= startOfDay).length;
        acc[id] = { count: today, hasMore: r.has_more };
      });
      if (!cancelled) setCounts(acc);
    })();
    return () => {
      cancelled = true;
      ctrl.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, limit]);

  return counts;
}

/** Derive a human "scope"-ish role label from an agent name (no scope field in the API). */
export function roleFromName(name: string): string {
  const m = name.match(/^([a-z]+(?:-[a-z]+)*)/i);
  return m ? m[1] : name;
}
