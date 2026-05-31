"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api } from "./api";
import type { Agent, Balance } from "./types";

/** Run async tasks with a concurrency cap (keeps 204+ balance calls civil). */
async function mapPool<T, R>(items: T[], limit: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(items.length);
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

interface AppData {
  agents: Agent[];
  balances: Record<string, Balance>;
  loadingAgents: boolean;
  balancesReady: boolean;
  treasurySats: number;
  activeCount: number;
  refresh: () => void;
}

const Ctx = createContext<AppData | null>(null);

export function AppDataProvider({ children }: { children: ReactNode }) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [balances, setBalances] = useState<Record<string, Balance>>({});
  const [loadingAgents, setLoadingAgents] = useState(true);
  const [balancesReady, setBalancesReady] = useState(false);
  const [tick, setTick] = useState(0);
  const aliveRef = useRef(true);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    aliveRef.current = true;
    let cancelled = false;
    const ctrl = new AbortController();

    (async () => {
      try {
        const list = await api.listAgents(ctrl.signal);
        if (cancelled) return;
        setAgents(list);
        setLoadingAgents(false);

        // Balances, concurrency-capped. Update the map progressively.
        setBalancesReady(false);
        const acc: Record<string, Balance> = {};
        let done = 0;
        await mapPool(list, 16, async (a) => {
          const b = await api.getBalance(a.id, ctrl.signal);
          if (cancelled) return b;
          acc[a.id] = b;
          done++;
          // Flush in batches to avoid excessive renders.
          if (done % 24 === 0) setBalances({ ...acc });
          return b;
        });
        if (cancelled) return;
        setBalances({ ...acc });
        setBalancesReady(true);
      } catch {
        if (!cancelled) setLoadingAgents(false);
      }
    })();

    // Light refresh of the agent list every 30s (cheap single call).
    const t = setInterval(async () => {
      try {
        const list = await api.listAgents(ctrl.signal);
        if (!cancelled) setAgents(list);
      } catch {
        /* ignore */
      }
    }, 30_000);

    return () => {
      cancelled = true;
      aliveRef.current = false;
      clearInterval(t);
      ctrl.abort();
    };
  }, [tick]);

  const treasurySats = Object.values(balances).reduce((s, b) => s + (b?.available_sats || 0), 0);
  const activeCount = agents.filter((a) => a.active).length;

  return (
    <Ctx.Provider
      value={{ agents, balances, loadingAgents, balancesReady, treasurySats, activeCount, refresh }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useAppData(): AppData {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAppData must be used within <AppDataProvider>");
  return ctx;
}
