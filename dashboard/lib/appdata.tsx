"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api } from "./api";
import type { Agent, Balance } from "./types";

interface AppData {
  agents: Agent[];
  balances: Record<string, Balance>; // derived from the agent list's balance_sats
  loadingAgents: boolean;
  balancesReady: boolean;
  treasurySats: number;
  activeCount: number;
  refresh: () => void;
}

const Ctx = createContext<AppData | null>(null);

export function AppDataProvider({ children }: { children: ReactNode }) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loadingAgents, setLoadingAgents] = useState(true);
  const [tick, setTick] = useState(0);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  // ONE call fetches the whole fleet WITH balances (balance_sats is on the list).
  // No per-agent /balance fan-out — this is the fix for the 900-request load.
  useEffect(() => {
    let cancelled = false;
    const ctrl = new AbortController();
    async function load() {
      try {
        const list = await api.listAgents(ctrl.signal);
        if (!cancelled) {
          setAgents(list);
          setLoadingAgents(false);
        }
      } catch {
        if (!cancelled) setLoadingAgents(false);
      }
    }
    load();
    const t = setInterval(load, 30_000);
    return () => {
      cancelled = true;
      clearInterval(t);
      ctrl.abort();
    };
  }, [tick]);

  const balances = useMemo(() => {
    const m: Record<string, Balance> = {};
    for (const a of agents) {
      m[a.id] = {
        agent_id: a.id,
        available_sats: a.balance_sats,
        pending_sats: 0,
        total_sats: a.balance_sats,
      };
    }
    return m;
  }, [agents]);

  const treasurySats = useMemo(
    () => agents.reduce((s, a) => s + (a.balance_sats || 0), 0),
    [agents],
  );
  const activeCount = useMemo(() => agents.filter((a) => a.active).length, [agents]);

  return (
    <Ctx.Provider
      value={{
        agents,
        balances,
        loadingAgents,
        balancesReady: !loadingAgents,
        treasurySats,
        activeCount,
        refresh,
      }}
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
