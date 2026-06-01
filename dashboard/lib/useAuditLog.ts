"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { Agent, Transaction } from "./types";

export interface AuditRow extends Transaction {
  agentName: string;
}

const LIMIT = 500; // most-recent transactions across the whole fleet, in ONE call

/** Aggregate recent transactions across the fleet via /v1/transactions/recent
 *  (server-side ORDER BY) — no per-agent fan-out. Names resolved from appdata. */
export function useAuditLog(agents: Agent[]): { rows: AuditRow[]; loading: boolean } {
  const [recent, setRecent] = useState<Transaction[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const ctrl = new AbortController();
    setLoading(true);
    async function load() {
      try {
        const r = await api.getRecentTransactions(LIMIT, ctrl.signal);
        if (!cancelled) {
          setRecent(r.data);
          setLoading(false);
        }
      } catch {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    const t = setInterval(load, 15_000);
    return () => {
      cancelled = true;
      clearInterval(t);
      ctrl.abort();
    };
  }, []);

  const rows = useMemo(() => {
    const nameById = new Map(agents.map((a) => [a.id, a.name]));
    return recent.map((t) => ({ ...t, agentName: nameById.get(t.agent_id) || t.agent_id }));
  }, [recent, agents]);

  return { rows, loading };
}
