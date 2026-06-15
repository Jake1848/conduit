"use client";

import { useCallback, useEffect, useState } from "react";
import { Bell, RefreshCw, Save } from "lucide-react";
import { api } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { ProGate } from "@/components/ProGate";
import type { Metrics, NodeStatus } from "@/lib/types";

const CFG_KEY = "conduit_alert_config";

interface AlertConfig {
  solvencyRatioMin: number;
  alertInsolvent: boolean;
  alertDesync: boolean;
  workerStaleSeconds: number;
  destination: string; // operator wires their own webhook/pager
}
const DEFAULT_CFG: AlertConfig = {
  solvencyRatioMin: 1.1,
  alertInsolvent: true,
  alertDesync: true,
  workerStaleSeconds: 900,
  destination: "",
};

interface Check {
  name: string;
  ok: boolean;
  detail: string;
}

export default function AlertsPage() {
  return (
    <ProGate
      feature="alerts"
      title="Monitoring & Alerts"
      blurb="Watch the signals a money system can't afford to miss — solvency, node chain-sync, and money-path worker liveness — with configurable thresholds and a pluggable notification destination. The free core already computes these; Pro turns them into alerts you'll actually see."
      bullets={[
        "Solvency-ratio + insolvency alerting",
        "LND chain-desync detection",
        "Stale money-path worker detection",
        "Pluggable destination (your webhook / pager)",
      ]}
    >
      <AlertsPanel />
    </ProGate>
  );
}

function AlertsPanel() {
  const toast = useToast();
  const [cfg, setCfg] = useState<AlertConfig>(DEFAULT_CFG);
  const [status, setStatus] = useState<NodeStatus | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(CFG_KEY);
      if (raw) setCfg({ ...DEFAULT_CFG, ...JSON.parse(raw) });
    } catch { /* ignore */ }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [st, m] = await Promise.all([api.getStatus(), api.getMetrics().catch(() => null)]);
      setStatus(st);
      setMetrics(m);
    } catch {
      /* surfaced by appdata error handling elsewhere */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function save() {
    localStorage.setItem(CFG_KEY, JSON.stringify(cfg));
    toast.ok("Alert config saved (local to this browser)");
  }

  // Evaluate the checks against the live signals + thresholds.
  const checks: Check[] = [];
  if (metrics) {
    const ratio = metrics.solvency_ratio;
    if (cfg.alertInsolvent)
      checks.push({
        name: "Solvency",
        ok: metrics.solvent !== false,
        detail: metrics.solvent === false ? "INSOLVENT — liabilities exceed node assets" : "solvent",
      });
    if (ratio != null)
      checks.push({
        name: "Solvency ratio",
        ok: ratio >= cfg.solvencyRatioMin,
        detail: `${ratio.toFixed(2)}× (min ${cfg.solvencyRatioMin}×)`,
      });
  }
  if (status && cfg.alertDesync)
    checks.push({
      name: "LND chain sync",
      ok: status.node.synced_to_chain,
      detail: status.node.synced_to_chain ? "synced" : "NOT synced to chain",
    });

  const firing = checks.filter((c) => !c.ok);

  return (
    <>
      <div className="toolbar">
        <span className="t-muted" style={{ fontSize: 13 }}>
          <Bell size={14} style={{ verticalAlign: "-2px", marginRight: 6 }} />
          Live signal monitoring · thresholds stored in this browser
        </span>
        <div style={{ flex: 1 }} />
        <button className="tb-btn" onClick={load} disabled={loading}>
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      <div className={"panel"} style={{ marginBottom: 16, borderColor: firing.length ? "var(--red)" : undefined }}>
        <div className="panel-head">
          <h3 style={{ margin: 0 }}>
            {firing.length ? `🔴 ${firing.length} alert${firing.length > 1 ? "s" : ""} firing` : "🟢 All clear"}
          </h3>
        </div>
        <table className="data">
          <tbody>
            {checks.map((c) => (
              <tr key={c.name}>
                <td style={{ fontWeight: 500 }}>{c.name}</td>
                <td className="right">
                  <span className={"st " + (c.ok ? "st-live" : "st-frozen")}>{c.ok ? "OK" : "ALERT"}</span>
                </td>
                <td className="right t-muted" style={{ fontSize: 12.5 }}>{c.detail}</td>
              </tr>
            ))}
            {checks.length === 0 && (
              <tr><td colSpan={3}><div className="empty">{loading ? "Loading signals…" : "No checks enabled."}</div></td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="treasury-cols">
        <div className="panel">
          <div className="panel-head"><h3 style={{ margin: 0 }}>Thresholds</h3></div>
          <div style={{ padding: 16 }}>
            <div className="field">
              <label>Minimum solvency ratio</label>
              <input className="mono" inputMode="decimal" value={cfg.solvencyRatioMin}
                onChange={(e) => setCfg({ ...cfg, solvencyRatioMin: parseFloat(e.target.value) || 0 })} />
            </div>
            <div className="field">
              <label>Worker-stale threshold (seconds)</label>
              <input className="mono" inputMode="numeric" value={cfg.workerStaleSeconds}
                onChange={(e) => setCfg({ ...cfg, workerStaleSeconds: parseInt(e.target.value) || 0 })} />
            </div>
            <div style={{ display: "flex", gap: 18, margin: "6px 0 4px" }}>
              <label style={{ display: "inline-flex", gap: 7, alignItems: "center", fontSize: 13, cursor: "pointer" }}>
                <input type="checkbox" checked={cfg.alertInsolvent} onChange={(e) => setCfg({ ...cfg, alertInsolvent: e.target.checked })} /> Alert on insolvency
              </label>
              <label style={{ display: "inline-flex", gap: 7, alignItems: "center", fontSize: 13, cursor: "pointer" }}>
                <input type="checkbox" checked={cfg.alertDesync} onChange={(e) => setCfg({ ...cfg, alertDesync: e.target.checked })} /> Alert on LND desync
              </label>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-head"><h3 style={{ margin: 0 }}>Notification destination</h3></div>
          <div style={{ padding: 16 }}>
            <div className="field">
              <label>Webhook / pager URL (you wire your own)</label>
              <input className="mono" placeholder="https://hooks.example.com/conduit-alerts"
                value={cfg.destination} onChange={(e) => setCfg({ ...cfg, destination: e.target.value })} />
            </div>
            <p className="t-muted" style={{ fontSize: 12, lineHeight: 1.55, margin: "4px 0 0" }}>
              Delivery runs on your box via <code className="t-gold">infra/scripts/alert_check.sh</code>
              (cron → scrapes the internal <code>/metrics</code> → POSTs here on a firing
              alert). This panel configures the thresholds; the script does the paging.
              Conduit never sends your data anywhere you didn’t configure.
            </p>
            <button className="tb-btn gold" onClick={save} style={{ marginTop: 14 }}>
              <Save size={14} /> Save config
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
