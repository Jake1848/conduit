"use client";

import { useCallback, useEffect, useState } from "react";
import { RefreshCw, TrendingUp } from "lucide-react";
import { api } from "@/lib/api";
import { useBtcPrice } from "@/lib/price";
import { fmtSats, fmtUsd, satsToUsd } from "@/lib/format";
import { ProGate } from "@/components/ProGate";
import { StatCard } from "@/components/StatCard";
import type { Fees, Metrics } from "@/lib/types";

export default function AnalyticsPage() {
  return (
    <ProGate
      feature="analytics"
      title="Analytics"
      blurb="A deeper read than the Overview: revenue trend over time, settlement-latency percentiles, throughput, and your most active agents — the operating picture a business running a fleet wants to watch."
      bullets={[
        "Platform-fee revenue trend (30 days)",
        "24-hour volume & transaction count",
        "Settlement latency (avg / p99)",
        "Top agents by activity",
      ]}
    >
      <AnalyticsView />
    </ProGate>
  );
}

function Bars({ data, color }: { data: { label: string; value: number }[]; color: string }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 120, padding: "8px 0" }}>
      {data.map((d, i) => (
        <div key={i} title={`${d.label}: ${d.value.toLocaleString()}`}
          style={{ flex: 1, minWidth: 2, display: "flex", flexDirection: "column", justifyContent: "flex-end", height: "100%" }}>
          <div style={{
            height: `${Math.round((d.value / max) * 100)}%`,
            minHeight: d.value > 0 ? 2 : 0,
            background: color, borderRadius: "2px 2px 0 0", transition: "height .2s",
          }} />
        </div>
      ))}
    </div>
  );
}

function AnalyticsView() {
  const price = useBtcPrice();
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [fees, setFees] = useState<Fees | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [m, f] = await Promise.all([api.getMetrics(), api.getFees().catch(() => null)]);
      setMetrics(m);
      setFees(f);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  if (loading && !metrics) return <div className="loading-row"><span className="spinner" /> Loading analytics…</div>;

  const revBars = (fees?.fees_by_day ?? []).slice().reverse().map((d) => ({ label: d.date, value: d.sats }));
  const volBars = (metrics?.hourly ?? []).map((h) => ({ label: h.hour.slice(11, 16), value: h.volume_sats }));
  const usd = (sats: number) => (price > 0 ? fmtUsd(satsToUsd(sats, price)) : "—");

  return (
    <>
      <div className="toolbar">
        <span className="t-muted" style={{ fontSize: 13 }}>
          <TrendingUp size={14} style={{ verticalAlign: "-2px", marginRight: 6 }} /> Operator analytics
        </span>
        <div style={{ flex: 1 }} />
        <button className="tb-btn" onClick={load} disabled={loading}><RefreshCw size={14} /> Refresh</button>
      </div>

      <div className="stat-grid">
        <StatCard label="Fee revenue (total)" value={metrics ? fmtSats(metrics.fee_revenue_total_sats) : "—"} unit="sats"
          sub={metrics ? usd(metrics.fee_revenue_total_sats) : "platform fee"} />
        <StatCard label="Revenue today" value={fees ? fmtSats(fees.today_sats) : "—"} unit="sats"
          sub={fees ? usd(fees.today_sats) : "today"} />
        <StatCard label="Avg settlement" value={metrics?.avg_settlement_ms != null ? String(metrics.avg_settlement_ms) : "—"} unit="ms"
          sub={metrics?.p99_settlement_ms != null ? `p99 ${metrics.p99_settlement_ms} ms` : "latency"} />
        <StatCard label="Throughput" value={metrics ? String(metrics.tx_per_min) : "—"} unit="tx/min"
          sub={metrics ? `${metrics.active_agents}/${metrics.total_agents} agents active` : "agents"} />
      </div>

      <div className="treasury-cols">
        <div className="panel">
          <div className="panel-head"><h3 style={{ margin: 0 }}>Platform-fee revenue · 30 days</h3></div>
          <div style={{ padding: 16 }}>
            <Bars data={revBars.length ? revBars : [{ label: "—", value: 0 }]} color="var(--gold)" />
            <div className="t-muted" style={{ fontSize: 11.5, marginTop: 4 }}>
              {revBars.length ? `${revBars[0].label} → ${revBars[revBars.length - 1].label}` : "no revenue yet"}
            </div>
          </div>
        </div>
        <div className="panel">
          <div className="panel-head"><h3 style={{ margin: 0 }}>Payment volume · last 24h</h3></div>
          <div style={{ padding: 16 }}>
            <Bars data={volBars.length ? volBars : [{ label: "—", value: 0 }]} color="var(--green)" />
            <div className="t-muted" style={{ fontSize: 11.5, marginTop: 4 }}>sats settled per hour (UTC)</div>
          </div>
        </div>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-head"><h3 style={{ margin: 0 }}>Top agents today</h3></div>
        <table className="data">
          <thead><tr><th>Agent</th><th className="right">Tx today</th><th className="right">Balance</th><th className="right">Status</th></tr></thead>
          <tbody>
            {(metrics?.top_agents ?? []).map((a) => (
              <tr key={a.agent_id}>
                <td>{a.name} <span className="t-muted t-mono" style={{ fontSize: 11 }}>{a.agent_id.slice(0, 14)}…</span></td>
                <td className="right t-mono">{a.tx_today}</td>
                <td className="right t-mono">{fmtSats(a.balance_sats)}</td>
                <td className="right"><span className={"st " + (a.active ? "st-live" : "st-frozen")}>{a.active ? "active" : "frozen"}</span></td>
              </tr>
            ))}
            {(!metrics?.top_agents || metrics.top_agents.length === 0) && (
              <tr><td colSpan={4}><div className="empty">No agent activity today.</div></td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
