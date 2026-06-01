"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Agent, Metrics, Transaction } from "./types";

/** A transaction enriched with its agent name (for the live feed). */
export interface FeedTx extends Transaction {
  agentName: string;
  isNew?: boolean;
}

export interface OverviewData {
  metrics: Metrics | null;
  feed: FeedTx[];
  ready: boolean;
}

const FEED_MS = 4000; // live feed cadence
const METRICS_MS = 10_000; // charts/stats cadence
const FEED_LIMIT = 20;

/** Drives the Overview from server-aggregated endpoints — /v1/metrics for the
 *  cards + charts + top agents, /v1/transactions/recent for the live feed.
 *  No per-agent fan-out: two cheap calls regardless of fleet size. */
export function useOverview(agents: Agent[]): OverviewData {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [feed, setFeed] = useState<FeedTx[]>([]);
  const [ready, setReady] = useState(false);
  const seen = useRef<Set<string>>(new Set());
  const first = useRef(true);
  const nameById = useRef<Map<string, string>>(new Map());

  // keep an id→name map current for the feed
  useEffect(() => {
    nameById.current = new Map(agents.map((a) => [a.id, a.name]));
  }, [agents]);

  useEffect(() => {
    let cancelled = false;
    const ctrl = new AbortController();

    async function pollFeed() {
      try {
        const r = await api.getRecentTransactions(FEED_LIMIT, ctrl.signal);
        if (cancelled) return;
        const names = nameById.current;
        const items: FeedTx[] = r.data.map((t) => ({
          ...t,
          agentName: names.get(t.agent_id) || t.agent_id,
          isNew: !first.current && !seen.current.has(t.id),
        }));
        r.data.forEach((t) => seen.current.add(t.id));
        if (seen.current.size > 3000) seen.current = new Set(r.data.map((t) => t.id));
        setFeed(items.slice(0, 7));
        first.current = false;
        setReady(true);
      } catch {
        /* swallow (incl. AbortError) */
      }
    }
    async function pollMetrics() {
      try {
        const m = await api.getMetrics(ctrl.signal);
        if (!cancelled) setMetrics(m);
      } catch {
        /* ignore */
      }
    }

    pollFeed();
    pollMetrics();
    const ft = setInterval(pollFeed, FEED_MS);
    const mt = setInterval(pollMetrics, METRICS_MS);
    return () => {
      cancelled = true;
      clearInterval(ft);
      clearInterval(mt);
      ctrl.abort();
    };
  }, []);

  return { metrics, feed, ready };
}
