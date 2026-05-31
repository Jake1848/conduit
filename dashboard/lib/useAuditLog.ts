"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { Agent, Transaction } from "./types";

export interface AuditRow extends Transaction {
  agentName: string;
}

const SAMPLE = 40; // agents to aggregate
const LIMIT = 25; // tx per agent

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

/** Aggregate recent transactions across a sample of agents into one signed record. */
export function useAuditLog(agents: Agent[]): { rows: AuditRow[]; loading: boolean } {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [loading, setLoading] = useState(true);
  // Key on agent identity (id+name), not just count, so a same-size membership
  // swap or rename (the 30s fleet refresh) still re-aggregates.
  const key = useMemo(() => agents.map((a) => `${a.id}:${a.name}`).join(","), [agents]);

  useEffect(() => {
    if (agents.length === 0) {
      setRows([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    const ctrl = new AbortController();
    setLoading(true);
    const sample = agents.slice(0, SAMPLE);
    const nameById = new Map(agents.map((a) => [a.id, a.name]));

    (async () => {
      const lists = await mapPool(sample, 12, (a) => api.getTransactions(a.id, LIMIT, ctrl.signal));
      if (cancelled) return;
      const merged: AuditRow[] = [];
      for (const r of lists) {
        if (!r?.data) continue;
        for (const t of r.data) merged.push({ ...t, agentName: nameById.get(t.agent_id) || t.agent_id });
      }
      merged.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
      setRows(merged);
      setLoading(false);
    })();

    return () => {
      cancelled = true;
      ctrl.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { rows, loading };
}
