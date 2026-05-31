"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Agent, Transaction } from "./types";

/** A transaction enriched with the agent it belongs to (for feed display). */
export interface FeedTx extends Transaction {
  agentName: string;
  isNew?: boolean;
}

export interface OverviewData {
  feed: FeedTx[];
  txPerMin: number;
  avgSettlementMs: number | null;
  p99SettlementMs: number | null;
  // chart series
  area: number[]; // routed volume (sats) bucketed over recent hours
  areaLabels: string[];
  bars: number[]; // hourly throughput (tx count) for the last 24h
  barLabels: string[];
  ready: boolean;
}

const POLL_MS = 4000;
const SAMPLE = 24; // active agents to poll for the live pool
const LIMIT = 40; // tx per agent per poll

const EMPTY: OverviewData = {
  feed: [],
  txPerMin: 0,
  avgSettlementMs: null,
  p99SettlementMs: null,
  area: [],
  areaLabels: [],
  bars: [],
  barLabels: [],
  ready: false,
};

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

function hourBuckets(txs: Transaction[]): { bars: number[]; area: number[]; labels: string[] } {
  const now = new Date();
  const counts = new Array(24).fill(0);
  const volume = new Array(24).fill(0);
  const labels: string[] = [];
  const baseHour = new Date(now);
  baseHour.setMinutes(0, 0, 0);
  for (let i = 0; i < 24; i++) {
    const h = new Date(baseHour.getTime() - (23 - i) * 3600_000);
    labels.push(i % 4 === 0 ? String(h.getHours()).padStart(2, "0") : "");
  }
  for (const t of txs) {
    const ts = new Date(t.created_at).getTime();
    const diffH = Math.floor((baseHour.getTime() + 3600_000 - ts) / 3600_000);
    const idx = 23 - diffH;
    if (idx >= 0 && idx < 24) {
      counts[idx]++;
      volume[idx] += t.amount_sats;
    }
  }
  return { bars: counts, area: volume, labels };
}

export function useOverview(agents: Agent[]): OverviewData {
  const [data, setData] = useState<OverviewData>(EMPTY);
  const seenIds = useRef<Set<string>>(new Set());
  const firstLoad = useRef(true);

  useEffect(() => {
    // Empty fleet: resolve to a ready+empty state instead of polling forever.
    if (agents.length === 0) {
      setData({ ...EMPTY, ready: true });
      return;
    }

    const sample = agents.filter((a) => a.active).slice(0, SAMPLE);
    const nameById = new Map(agents.map((a) => [a.id, a.name]));
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const ctrl = new AbortController();

    async function poll() {
      const lists = await mapPool(sample, 12, (a) => api.getTransactions(a.id, LIMIT, ctrl.signal));
      if (cancelled) return;
      const all: Transaction[] = [];
      for (const r of lists) if (r?.data) all.push(...r.data);
      all.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

      const feed: FeedTx[] = all.slice(0, 7).map((t) => ({
        ...t,
        agentName: nameById.get(t.agent_id) || t.agent_id,
        isNew: !firstLoad.current && !seenIds.current.has(t.id),
      }));
      all.slice(0, 60).forEach((t) => seenIds.current.add(t.id));
      if (seenIds.current.size > 4000) seenIds.current = new Set(all.slice(0, 200).map((t) => t.id));

      const cutoff = Date.now() - 60_000;
      const txPerMin = all.filter((t) => new Date(t.created_at).getTime() >= cutoff).length;

      const lats = all
        .filter((t) => t.status === "settled" && typeof t.latency_ms === "number")
        .map((t) => t.latency_ms as number)
        .sort((a, b) => a - b);
      const avg = lats.length ? Math.round(lats.reduce((s, x) => s + x, 0) / lats.length) : null;
      const p99 = lats.length ? lats[Math.min(lats.length - 1, Math.floor(lats.length * 0.99))] : null;

      const { bars, area, labels } = hourBuckets(all);

      setData({
        feed,
        txPerMin,
        avgSettlementMs: avg,
        p99SettlementMs: p99,
        area,
        areaLabels: labels,
        bars,
        barLabels: labels,
        ready: true,
      });
      firstLoad.current = false;
    }

    // Self-scheduling loop: the next poll starts POLL_MS AFTER the previous one
    // finishes, so cycles never overlap (no stacking fetch storm, no ref races).
    (async function loop() {
      try {
        await poll();
      } catch {
        /* swallow (incl. AbortError) */
      }
      if (!cancelled) timer = setTimeout(loop, POLL_MS);
    })();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      ctrl.abort();
    };
  }, [agents]);

  return data;
}
