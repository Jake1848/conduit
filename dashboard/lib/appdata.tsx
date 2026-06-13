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
import { api, ApiError } from "./api";
import { useAuth } from "./auth";
import { useToast } from "./toast";
import type { Agent, Balance } from "./types";

interface AppData {
  agents: Agent[];
  balances: Record<string, Balance>; // derived from the agent list's balance_sats
  loadingAgents: boolean;
  balancesReady: boolean;
  treasurySats: number;
  activeCount: number;
  error: string | null; // set when a refresh fails (so the UI isn't silently stale)
  refresh: () => void;
}

const Ctx = createContext<AppData | null>(null);

export function AppDataProvider({ children }: { children: ReactNode }) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loadingAgents, setLoadingAgents] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const { disconnect } = useAuth();
  const toast = useToast();

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  // ONE call fetches the whole fleet WITH balances (balance_sats is on the list).
  // No per-agent /balance fan-out — this is the fix for the 900-request load.
  useEffect(() => {
    let cancelled = false;
    const ctrl = new AbortController();
    async function load() {
      try {
        const list = await api.listAgents(ctrl.signal);
        if (cancelled) return;
        setAgents(list);
        setLoadingAgents(false);
        setError(null); // recovered
      } catch (e) {
        if (cancelled || (e as Error)?.name === "AbortError") return;
        setLoadingAgents(false);
        // M9: never silently show stale/empty data. A revoked key (401/403)
        // drops to the login screen; any other failure surfaces a banner +
        // one toast (don't spam on the 30s poll).
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
          toast.err("Your API key was rejected — please reconnect.");
          disconnect();
        } else {
          if (error === null) {
            toast.err("Couldn't reach the Conduit API — showing last known data.");
          }
          setError(e instanceof Error ? e.message : "Connection error");
        }
      }
    }
    load();
    const t = setInterval(load, 30_000);
    return () => {
      cancelled = true;
      clearInterval(t);
      ctrl.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
        error,
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
