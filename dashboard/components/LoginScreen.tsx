"use client";

import { useState } from "react";
import { ArrowRight, KeyRound } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { getStoredKey, API_BASE } from "@/lib/api";

export function LoginScreen() {
  const { connect, error } = useAuth();
  const [key, setKey] = useState(getStoredKey() || "");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await connect(key);
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
          Enter your Conduit API key to manage your agent fleet. The key is stored in your
          browser and sent directly to the Conduit API.
        </p>

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
          API: {API_BASE}
          <br />
          regtest sandbox key: ck_test_regtest_root_key
        </div>
      </form>
    </div>
  );
}
