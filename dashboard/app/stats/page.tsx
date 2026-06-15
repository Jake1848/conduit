"use client";

import { useEffect, useState } from "react";

/**
 * PUBLIC transparency page (no auth — rendered standalone by AppShell). It reads
 * ONLY /stats.json, which the project curates by hand, plus a live health probe of
 * the project's OWN public endpoints. It never reads other operators' data and
 * never exposes private ledger figures. Aggregates render only if explicitly set.
 */

interface NetworkEntry { network: string; status: string; version: string }
interface Stats {
  published_at?: string;
  project?: { version?: string; license?: string; repo?: string };
  networks?: NetworkEntry[];
  highlights?: string[];
  aggregates?: { payments_settled?: number | null; volume_sats?: number | null; uptime_pct?: number | null };
}

const PUBLIC_HEALTH: Record<string, string> = {
  mainnet: "https://api-mainnet.conduit.energy/v1/health",
  testnet: "https://api.conduit.energy/v1/health",
  regtest: "https://api-test.conduit.energy/v1/health",
};

export default function StatsPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [live, setLive] = useState<Record<string, { ok: boolean; version?: string }>>({});

  useEffect(() => {
    fetch("/stats.json").then((r) => r.json()).then(setStats).catch(() => setStats({}));
    Object.entries(PUBLIC_HEALTH).forEach(([net, url]) => {
      fetch(url, { signal: AbortSignal.timeout(8000) })
        .then((r) => r.json())
        .then((h) => setLive((s) => ({ ...s, [net]: { ok: !!h.ok, version: h.version } })))
        .catch(() => setLive((s) => ({ ...s, [net]: { ok: false } })));
    });
  }, []);

  const agg = stats?.aggregates ?? {};
  const hasAgg = [agg.payments_settled, agg.volume_sats, agg.uptime_pct].some((v) => v != null);

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "56px 20px", color: "var(--t1)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
        <div style={{ width: 22, height: 22, borderRadius: 6, background: "var(--gold)" }} />
        <span style={{ fontWeight: 700, letterSpacing: "0.18em", fontSize: 13 }}>CONDUIT</span>
      </div>
      <h1 style={{ fontSize: 26, margin: "10px 0 4px" }}>Ecosystem status</h1>
      <p className="t-muted" style={{ fontSize: 13.5, lineHeight: 1.6, maxWidth: 560 }}>
        Self-hosted, non-custodial Bitcoin Lightning payments for AI agents — MIT licensed.
        This page publishes only aggregate, opt-in proof-of-life about the project's own
        instances. It is not a ledger and contains no operator-private data.
      </p>

      <div className="panel" style={{ marginTop: 24, padding: 18 }}>
        <h3 style={{ margin: "0 0 12px", fontSize: 13 }}>Networks</h3>
        <table className="data">
          <tbody>
            {(stats?.networks ?? []).map((n) => {
              const l = live[n.network];
              return (
                <tr key={n.network}>
                  <td style={{ textTransform: "capitalize", fontWeight: 500 }}>{n.network}</td>
                  <td className="right">
                    <span className={"st " + (l ? (l.ok ? "st-live" : "st-frozen") : "st-frozen")}>
                      {l ? (l.ok ? "live" : "checking…") : "…"}
                    </span>
                  </td>
                  <td className="right t-mono t-muted" style={{ fontSize: 12.5 }}>{l?.version ?? n.version}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {hasAgg && (
        <div className="stat-grid" style={{ marginTop: 16 }}>
          {agg.payments_settled != null && <div className="stat-card"><div className="sc-label">Payments settled</div><div className="sc-value">{agg.payments_settled.toLocaleString()}</div></div>}
          {agg.volume_sats != null && <div className="stat-card"><div className="sc-label">Volume (sats)</div><div className="sc-value">{agg.volume_sats.toLocaleString()}</div></div>}
          {agg.uptime_pct != null && <div className="stat-card"><div className="sc-label">Uptime</div><div className="sc-value">{agg.uptime_pct}%</div></div>}
        </div>
      )}

      {stats?.highlights && stats.highlights.length > 0 && (
        <div className="panel" style={{ marginTop: 16, padding: 18 }}>
          <h3 style={{ margin: "0 0 10px", fontSize: 13 }}>Highlights</h3>
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13.5, lineHeight: 1.7 }}>
            {stats.highlights.map((h) => <li key={h}>{h}</li>)}
          </ul>
        </div>
      )}

      <p className="t-muted" style={{ fontSize: 11.5, marginTop: 22, lineHeight: 1.6 }}>
        Status: early, single-operator, mainnet-validated. Published {stats?.published_at ?? "—"} ·{" "}
        {stats?.project?.repo && <a href={stats.project.repo} style={{ color: "var(--gold)" }}>source on GitHub</a>}
        {" "}· MIT licensed. Aggregate figures appear only if the project explicitly opted to publish them.
      </p>
    </div>
  );
}
