"use client";

import { useState, type ReactNode } from "react";
import { Sparkles, KeyRound, Check } from "lucide-react";
import { usePro, type ProFeature } from "@/lib/pro";

/**
 * Wraps a Pro-only dashboard panel. If a valid license grants `feature`, the
 * children render. Otherwise an honest "Pro feature" upgrade card renders with an
 * inline license-key field. This NEVER affects the core payment functionality —
 * it only gates this convenience surface in the dashboard.
 */
export function ProGate({
  feature,
  title,
  blurb,
  bullets,
  children,
}: {
  feature: ProFeature;
  title: string;
  blurb: string;
  bullets?: string[];
  children: ReactNode;
}) {
  const { has, loading } = usePro();

  if (loading) {
    return (
      <div className="loading-row">
        <span className="spinner" /> Checking license…
      </div>
    );
  }
  if (has(feature)) return <>{children}</>;
  return <UpgradeCard title={title} blurb={blurb} bullets={bullets} />;
}

function UpgradeCard({ title, blurb, bullets }: { title: string; blurb: string; bullets?: string[] }) {
  const { setLicenseToken } = usePro();
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function activate() {
    setBusy(true);
    setErr(null);
    const ok = await setLicenseToken(key);
    setBusy(false);
    if (!ok) setErr("That license key is not valid (or has expired).");
  }

  return (
    <div className="panel" style={{ maxWidth: 640, margin: "32px auto", padding: 28 }}>
      <div style={{ display: "inline-flex", alignItems: "center", gap: 8, color: "var(--gold)", fontWeight: 600 }}>
        <Sparkles size={18} /> {title} <span className="badge" style={{ marginLeft: 4 }}>PRO</span>
      </div>
      <p className="t-muted" style={{ fontSize: 13.5, lineHeight: 1.6, marginTop: 12 }}>{blurb}</p>
      {bullets && bullets.length > 0 && (
        <ul style={{ margin: "6px 0 16px", padding: 0, listStyle: "none" }}>
          {bullets.map((b) => (
            <li key={b} style={{ display: "flex", gap: 8, fontSize: 13, padding: "3px 0" }}>
              <Check size={15} style={{ color: "var(--green)", flexShrink: 0, marginTop: 2 }} /> {b}
            </li>
          ))}
        </ul>
      )}
      <div className="panel" style={{ background: "rgba(0,0,0,0.15)", padding: 16, marginTop: 8 }}>
        <div className="t-muted" style={{ fontSize: 12, marginBottom: 8 }}>
          Already have a Pro license? Paste the key — it’s verified locally on your
          machine (no data leaves the browser).
        </div>
        <div className="field-row" style={{ display: "flex", gap: 8 }}>
          <input
            className="mono"
            placeholder="paste license key…"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            style={{ flex: 1 }}
          />
          <button className="tb-btn gold" onClick={activate} disabled={busy || !key.trim()}>
            {busy ? <span className="spinner dark" /> : <KeyRound size={14} />} Activate
          </button>
        </div>
        {err && <div className="warn" style={{ marginTop: 8 }}>⚠ {err}</div>}
      </div>
      <p className="t-muted" style={{ fontSize: 11.5, marginTop: 14, lineHeight: 1.5 }}>
        Pro unlocks convenience tooling in this dashboard. It does <b>not</b> change
        or gate any payment functionality — the open-source SDK and the full money
        path work the same with or without a license.
      </p>
    </div>
  );
}
