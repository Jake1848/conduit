"use client";

import { useState } from "react";
import { ArrowRight, KeyRound } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { getStoredKey, getStoredApiUrl, DEFAULT_API_BASE } from "@/lib/api";

const REGTEST_URL = "https://api-test.conduit.energy";
const REGTEST_KEY = "ck_test_regtest_root_key";

export function LoginScreen() {
  const { connect, error } = useAuth();
  const [key, setKey] = useState(getStoredKey() || "");
  const [apiUrl, setApiUrl] = useState(getStoredApiUrl() || DEFAULT_API_BASE);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await connect(key, apiUrl);
    } catch {
      /* error surfaced via context */
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="login-brand">
          <div className="sb-logo" />
          <span className="wm">CONDUIT</span>
        </div>
        <h1>Connect to the console</h1>
        <p className="sub">
          Point this console at any Conduit instance — your own self-hosted node or the
          hosted demo. Your API URL and key are stored in your browser and sent directly to
          that Conduit API. Your node, your keys, your rules.
        </p>

        <div className="field">
          <label>API URL</label>
          <input
            type="text"
            inputMode="url"
            placeholder={DEFAULT_API_BASE}
            value={apiUrl}
            onChange={(e) => setApiUrl(e.target.value)}
            spellCheck={false}
            autoComplete="off"
          />
        </div>

        <div className="field">
          <label>API Key</label>
          <input
            type="password"
            autoFocus
            placeholder="ck_live_… / ck_test_…"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            spellCheck={false}
            autoComplete="off"
          />
        </div>

        {error && <div className="login-err">{error}</div>}

        <button className="login-btn" type="submit" disabled={busy}>
          {busy ? (
            <>
              <span className="spinner dark" /> Connecting…
            </>
          ) : (
            <>
              <KeyRound size={15} /> Connect <ArrowRight size={15} />
            </>
          )}
        </button>

        <div className="login-hint">
          Point at your own instance — e.g. https://api-mainnet.conduit.energy (mainnet),
          https://api.conduit.energy (testnet), https://api-test.conduit.energy (regtest
          sandbox), or http://localhost:8000 (local dev). The key must be from the SAME
          instance — a regtest key won&apos;t work against the testnet URL.
          <br />
          <button
            type="button"
            onClick={() => {
              setApiUrl(REGTEST_URL);
              setKey(REGTEST_KEY);
            }}
            style={{
              marginTop: 8,
              background: "none",
              border: "none",
              padding: 0,
              color: "var(--gold)",
              cursor: "pointer",
              textDecoration: "underline",
              font: "inherit",
            }}
          >
            ↳ Use the regtest sandbox (fills api-test URL + demo key)
          </button>
        </div>
      </form>
    </div>
  );
}
