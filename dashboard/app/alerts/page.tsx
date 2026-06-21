"use client";

import { useCallback, useEffect, useState } from "react";
import { Bell, Copy, RefreshCw, Save } from "lucide-react";
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
  destination: string; // operator's pager/Slack webhook — feeds the cron line
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
      blurb="Watch the signals a money system can't afford to miss — solvency, node chain-sync, and money-path worker liveness. This page reads them live, and generates the exact cron command that pages you continuously via the bundled alert script. The free core already computes these signals; Pro turns them into alerts you'll actually see."
      bullets={[
        "Live solvency + solvency-ratio read",
        "LND chain-desync detection",
        "Stale money-path worker detection (via the cron script)",
        "Generates the exact alert_check.sh cron line for your pager",
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
    toast.ok("Settings saved (local to this browser)");
  }

  // Live, in-browser checks — evaluated from the JSON API on each refresh.
  // Worker-liveness is NOT in the JSON API (only Prometheus /metrics), so it is
  // paged by the cron script below rather than shown live here.
  const checks: Check[] = [];
  if (metrics) {
    if (cfg.alertInsolvent)
      checks.push({
        name: "Solvency",
        ok: metrics.solvent !== false,
        detail: metrics.solvent === false ? "INSOLVENT — liabilities exceed node assets" : "solvent",
      });
    const ratio = metrics.solvency_ratio;
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

  // The cron line that alert_check.sh actually consumes — values come from its
  // own env vars, NOT this browser's localStorage. Filling the inputs below just
  // builds the command for you to paste into crontab on your server.
  const cron =
    `* * * * * ALERT_WEBHOOK_URL=${cfg.destination || "<your-webhook-url>"} ` +
    `WORKER_STALE_SECONDS=${cfg.workerStaleSeconds} ` +
    `METRICS_URL=http://127.0.0.1:8000/metrics ` +
    `bash /home/conduit/conduit/infra/scripts/alert_check.sh`;

  return (
    <>
      <div className="toolbar">
        <span className="t-muted" style={{ fontSize: 13 }}>
          <Bell size={14} style={{ verticalAlign: "-2px", marginRight: 6 }} />
          Live signal read · continuous paging via the cron below
        </span>
        <div style={{ flex: 1 }} />
        <button className="tb-btn" onClick={load} disabled={loading}>
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      <div className={"panel"} style={{ marginBottom: 16, borderColor: firing.length ? "var(--red)" : undefined }}>
        <div className="panel-head">
          <h3 style={{ margin: 0 }}>
            {checks.length === 0
              ? loading ? "Checking signals…" : "No signals evaluated"
              : firing.length
                ? `🔴 ${firing.length} alert${firing.length > 1 ? "s" : ""} firing`
                : "🟢 All clear"}
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
        <div className="t-muted" style={{ fontSize: 11.5, padding: "10px 14px", borderTop: "1px solid var(--border)", lineHeight: 1.5 }}>
          Live read from this browser on each refresh. Worker-liveness and
          round-the-clock paging run on your server via{" "}
          <code className="t-gold">alert_check.sh</code> — set it up below.
        </div>
      </div>

      <div className="treasury-cols">
        <div className="panel">
          <div className="panel-head"><h3 style={{ margin: 0 }}>Live-panel thresholds</h3></div>
          <div style={{ padding: 16 }}>
            <div className="field">
              <label>Minimum solvency ratio</label>
              <input className="mono" inputMode="decimal" value={cfg.solvencyRatioMin}
                onChange={(e) => setCfg({ ...cfg, solvencyRatioMin: parseFloat(e.target.value) || 0 })} />
            </div>
            <div style={{ display: "flex", gap: 18, margin: "6px 0 4px" }}>
              <label style={{ display: "inline-flex", gap: 7, alignItems: "center", fontSize: 13, cursor: "pointer" }}>
                <input type="checkbox" checked={cfg.alertInsolvent} onChange={(e) => setCfg({ ...cfg, alertInsolvent: e.target.checked })} /> Show insolvency
              </label>
              <label style={{ display: "inline-flex", gap: 7, alignItems: "center", fontSize: 13, cursor: "pointer" }}>
                <input type="checkbox" checked={cfg.alertDesync} onChange={(e) => setCfg({ ...cfg, alertDesync: e.target.checked })} /> Show LND desync
              </label>
            </div>
            <p className="t-muted" style={{ fontSize: 12, lineHeight: 1.55, margin: "4px 0 0" }}>
              These tune the live panel above and persist in this browser only.
            </p>
            <button className="tb-btn gold" onClick={save} style={{ marginTop: 14 }}>
              <Save size={14} /> Save
            </button>
          </div>
        </div>

        <div className="panel">
          <div className="panel-head"><h3 style={{ margin: 0 }}>Continuous alerting · alert_check.sh</h3></div>
          <div style={{ padding: 16 }}>
            <div className="field">
              <label>Pager / Slack webhook URL</label>
              <input className="mono" placeholder="https://hooks.example.com/conduit-alerts"
                value={cfg.destination} onChange={(e) => setCfg({ ...cfg, destination: e.target.value })} />
            </div>
            <div className="field">
              <label>Worker-stale threshold (seconds)</label>
              <input className="mono" inputMode="numeric" value={cfg.workerStaleSeconds}
                onChange={(e) => setCfg({ ...cfg, workerStaleSeconds: parseInt(e.target.value) || 0 })} />
            </div>
            <label className="t-muted" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Cron line (runs on your server)
            </label>
            <pre className="hash" style={{ marginTop: 6, whiteSpace: "pre-wrap", fontSize: 11.5 }}>{cron}</pre>
            <button className="copy-btn" onClick={() => { navigator.clipboard?.writeText(cron); toast.ok("cron line copied"); }}>
              <Copy size={11} /> Copy
            </button>
            <p className="t-muted" style={{ fontSize: 12, lineHeight: 1.55, margin: "10px 0 0" }}>
              The script scrapes the internal <code>/metrics</code> and POSTs to your
              webhook when solvency, chain-sync, or worker-liveness breaches — reading
              these values from its own env (above), not this browser. Point{" "}
              <code>METRICS_URL</code> at your instance’s internal metrics port. Conduit
              never sends your data anywhere you didn’t configure.
            </p>
          </div>
        </div>
      </div>
    </>
  );
}
