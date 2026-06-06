"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import {
  api,
  ApiError,
  clearStoredKey,
  getStoredApiUrl,
  getStoredKey,
  setStoredApiUrl,
  setStoredKey,
} from "./api";
import type { AccessTier } from "./types";

type Status = "loading" | "unauthed" | "authed";

interface AuthState {
  status: Status;
  apiKey: string | null;
  apiUrl: string; // operator-configured base URL the dashboard is talking to
  tier: AccessTier;
  network: string; // regtest | testnet | mainnet
  version: string;
  error: string | null;
  connect: (key: string, apiUrl?: string) => Promise<void>;
  disconnect: () => void;
}

const AuthCtx = createContext<AuthState | null>(null);

/** Probe a candidate key against a base URL: validate it can read agents, then
 *  detect admin tier. The baseUrl override lets us probe before committing it. */
async function probe(
  key: string,
  baseUrl: string,
): Promise<{ tier: AccessTier; network: string; version: string }> {
  const health = await api.request<{ network: string; version: string }>("/v1/health", { baseUrl }); // public — confirms the API is reachable + network
  // Validate the key by reading agents (any non-revoked key can do this).
  await api.request<{ data: unknown[] }>("/v1/agents", { key, baseUrl });
  // Admin keys can list API keys; non-admin keys get 403 here.
  let tier: AccessTier = "member";
  try {
    await api.request<{ data: unknown[] }>("/v1/api-keys", { key, baseUrl });
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
  const [apiUrl, setApiUrl] = useState<string>(getStoredApiUrl());
  const [tier, setTier] = useState<AccessTier>("member");
  const [network, setNetwork] = useState("");
  const [version, setVersion] = useState("");
  const [error, setError] = useState<string | null>(null);

  // On mount, try the stored key against the stored API URL.
  useEffect(() => {
    const stored = getStoredKey();
    const storedUrl = getStoredApiUrl();
    setApiUrl(storedUrl);
    if (!stored) {
      setStatus("unauthed");
      return;
    }
    let alive = true;
    probe(stored, storedUrl)
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

  const connect = useCallback(async (key: string, url?: string) => {
    setError(null);
    const trimmed = key.trim();
    if (!trimmed) {
      setError("Enter an API key.");
      throw new Error("empty key");
    }
    // Use the supplied URL if given, otherwise keep the currently stored one.
    const targetUrl = (url ?? getStoredApiUrl()).trim().replace(/\/+$/, "");
    if (!targetUrl) {
      setError("Enter an API URL.");
      throw new Error("empty url");
    }
    const { tier, network, version } = await probe(trimmed, targetUrl).catch((e: unknown) => {
      const msg =
        e instanceof ApiError && e.status === 401
          ? "That API key was rejected (401). Check the key and try again."
          : e instanceof Error
            ? e.message
            : "Connection failed";
      setError(msg);
      throw e;
    });
    // Persist BOTH the URL and the key only after a successful probe.
    setStoredApiUrl(targetUrl);
    setStoredKey(trimmed);
    setApiUrl(targetUrl);
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
      value={{ status, apiKey, apiUrl, tier, network, version, error, connect, disconnect }}
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
