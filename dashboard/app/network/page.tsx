"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, Copy, RefreshCw, Share2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useBtcPrice } from "@/lib/price";
import { useToast } from "@/lib/toast";
import { fmtSatsFull, fmtUsd, satsToBtc, satsToUsd, truncPubkey } from "@/lib/format";
import type { Metrics, NodeStatus } from "@/lib/types";
import { StatCard } from "@/components/StatCard";

export default function NetworkPage() {
  const { tier } = useAuth();
  const price = useBtcPrice();
  const toast = useToast();
  const [status, setStatus] = useState<NodeStatus | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [st, m] = await Promise.all([api.getStatus(), api.getMetrics().catch(() => null)]);
      setStatus(st);
      setMetrics(m);
      setForbidden(false);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 403 || e.status === 401)) setForbidden(true);
      else toast.err(e instanceof Error ? e.message : "Failed to load node status");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (tier !== "admin" || forbidden) {
    return (
      <div className="coming-soon">
        <div className="cs-inner">
          <div className="cs-ico">
            <Share2 size={24} />
          </div>
          <h2>Admin access required</h2>
          <p>Node status &amp; liquidity are operator-only. Connect an admin-scope API key.</p>
        </div>
      </div>
    );
  }

  const usd = (sats: number) => (price > 0 ? fmtUsd(satsToUsd(sats, price)) : "—");
  const bal = status?.balance;
  const totalLiquidity = bal ? bal.confirmed_sats + bal.channel_local_sats : 0;

  return (
    <>
      <div className="toolbar">
        <div style={{ flex: 1 }} />
        <button className="tb-btn" onClick={load} disabled={loading}>
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      <div className="stat-grid">
        <StatCard
          label="Chain sync"
          value={
            <span style={{ color: status?.node.synced_to_chain ? "var(--green)" : "var(--amber)" }}>
              {status ? (status.node.synced_to_chain ? "Synced" : "Syncing") : "—"}
            </span>
          }
          sub={status ? `block ${status.node.block_height.toLocaleString()}` : "blockchain"}
        />
        <StatCard
          label="Active channels"
          value={status ? String(status.channels.num_active) : "—"}
          sub={status ? status.network : "lightning"}
        />
        <StatCard
          label="Total liquidity"
          value={status ? satsToBtc(totalLiquidity) : "—"}
          unit="BTC"
          sub={status ? `${usd(totalLiquidity)} · on-chain + channels` : "node funds"}
        />
        <StatCard
          label="Solvency"
          value={
            metrics ? (
              <span style={{ color: metrics.solvent ? "var(--green)" : "var(--red)" }}>
                {metrics.solvency_ratio != null
                  ? metrics.solvency_ratio.toFixed(1) + "×"
                  : "∞"}
              </span>
            ) : (
              "—"
            )
          }
          sub={
            metrics ? (
              <span style={{ color: metrics.solvent ? "var(--green)" : "var(--red)" }}>
                {metrics.solvent ? "solvent" : "INSOLVENT"} · backs agent balances
              </span>
            ) : (
              "assets / liabilities"
            )
          }
        />
      </div>

      <div className="treasury-cols">
        {/* Node identity */}
        <div className="panel">
          <div className="panel-head">
            <h3 style={{ display: "inline-flex", alignItems: "center", gap: 6, margin: 0 }}>
              <Activity size={15} style={{ color: "var(--gold)" }} /> Node
            </h3>
          </div>
          <table className="data">
            <tbody>
              <tr>
                <td className="t-muted">Alias</td>
                <td className="right t-mono">{status?.node.alias || "—"}</td>
              </tr>
              <tr>
                <td className="t-muted">Network</td>
                <td className="right t-mono">{status?.network || "—"}</td>
              </tr>
              <tr>
                <td className="t-muted">Pubkey</td>
                <td className="right t-mono" style={{ fontSize: 12 }}>
                  {status ? (
                    <button
                      className="copy-btn"
                      onClick={() => {
                        navigator.clipboard?.writeText(status.node.pubkey);
                        toast.ok("Pubkey copied");
                      }}
                      title={status.node.pubkey}
                    >
                      {truncPubkey(status.node.pubkey)} <Copy size={11} />
                    </button>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
              <tr>
                <td className="t-muted">Block height</td>
                <td className="right t-mono">
                  {status ? status.node.block_height.toLocaleString() : "—"}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Liquidity breakdown */}
        <div className="panel">
          <div className="panel-head">
            <h3 style={{ margin: 0 }}>Liquidity</h3>
          </div>
          <table className="data">
            <tbody>
              {[
                ["On-chain confirmed", bal?.confirmed_sats],
                ["On-chain unconfirmed", bal?.unconfirmed_sats],
                ["Channel local (outbound)", bal?.channel_local_sats],
                ["Channel remote (inbound)", bal?.channel_remote_sats],
              ].map(([label, v]) => (
                <tr key={label as string}>
                  <td className="t-muted">{label}</td>
                  <td className="right t-mono">{bal ? fmtSatsFull(v as number) : "—"}</td>
                  <td className="right t-muted t-mono" style={{ fontSize: 11.5 }}>
                    {bal ? usd(v as number) : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="t-muted" style={{ fontSize: 11.5, padding: "10px 14px 0", lineHeight: 1.5 }}>
            Outbound (local) can send; inbound (remote) can receive. A per-channel
            topology view is on the roadmap.
          </p>
        </div>
      </div>
    </>
  );
}
