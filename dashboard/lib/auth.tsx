"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, clearStoredKey, getStoredKey, setStoredKey } from "./api";
import type { AccessTier } from "./types";

type Status = "loading" | "unauthed" | "authed";

interface AuthState {
  status: Status;
  apiKey: string | null;
  tier: AccessTier;
  network: string; // regtest | testnet | mainnet
  version: string;
  error: string | null;
  connect: (key: string) => Promise<void>;
  disconnect: () => void;
}

const AuthCtx = createContext<AuthState | null>(null);

/** Probe a candidate key: validate it can read agents, then detect admin tier. */
async function probe(key: string): Promise<{ tier: AccessTier; network: string; version: string }> {
  const health = await api.health(); // public — confirms the API is reachable + network
  // Validate the key by reading agents (any non-revoked key can do this).
  await api.request<{ data: unknown[] }>("/v1/agents", { key });
  // Admin keys can list API keys; non-admin keys get 403 here.
  let tier: AccessTier = "member";
  try {
    await api.listKeys(key);
    tier = "admin";
  } catch (e) {
    if (!(e instanceof ApiError) || (e.status !== 403 && e.status !== 401)) throw e;
    tier = "member";
  }
  return { tier, network: health.network, version: health.version };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [tier, setTier] = useState<AccessTier>("member");
  const [network, setNetwork] = useState("");
  const [version, setVersion] = useState("");
  const [error, setError] = useState<string | null>(null);

  // On mount, try the stored key.
  useEffect(() => {
    const stored = getStoredKey();
    if (!stored) {
      setStatus("unauthed");
      return;
    }
    let alive = true;
    probe(stored)
      .then(({ tier, network, version }) => {
        if (!alive) return;
        setApiKey(stored);
        setTier(tier);
        setNetwork(network);
        setVersion(version);
        setStatus("authed");
      })
      .catch((e) => {
        if (!alive) return;
        // Invalid key → drop it. Network error → keep it for a retry from the login screen.
        if (e instanceof ApiError && e.status === 401) clearStoredKey();
        setError(e instanceof Error ? e.message : "Connection failed");
        setStatus("unauthed");
      });
    return () => {
      alive = false;
    };
  }, []);

  const connect = useCallback(async (key: string) => {
    setError(null);
    const trimmed = key.trim();
    if (!trimmed) {
      setError("Enter an API key.");
      throw new Error("empty key");
    }
    const { tier, network, version } = await probe(trimmed).catch((e: unknown) => {
      const msg =
        e instanceof ApiError && e.status === 401
          ? "That API key was rejected (401). Check the key and try again."
          : e instanceof Error
            ? e.message
            : "Connection failed";
      setError(msg);
      throw e;
    });
    setStoredKey(trimmed);
    setApiKey(trimmed);
    setTier(tier);
    setNetwork(network);
    setVersion(version);
    setStatus("authed");
  }, []);

  const disconnect = useCallback(() => {
    clearStoredKey();
    setApiKey(null);
    setTier("member");
    setError(null);
    setStatus("unauthed");
  }, []);

  return (
    <AuthCtx.Provider
      value={{ status, apiKey, tier, network, version, error, connect, disconnect }}
    >
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
