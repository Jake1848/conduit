"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, Landmark, RefreshCw, ShieldAlert, ShieldCheck } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useBtcPrice } from "@/lib/price";
import { useToast } from "@/lib/toast";
import { fmtDate, fmtSatsFull, fmtUsd, satsToBtc, satsToUsd, truncHash } from "@/lib/format";
import type { TreasuryOverview } from "@/lib/types";
import { StatCard } from "@/components/StatCard";
import { BarChart } from "@/components/charts/BarChart";

export default function TreasuryPage() {
  const { tier } = useAuth();
  const price = useBtcPrice();
  const toast = useToast();

  const [ov, setOv] = useState<TreasuryOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);

  const [amount, setAmount] = useState("");
  const [address, setAddress] = useState("");
  const [feeRate, setFeeRate] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // Stable across retries of the SAME withdrawal so a lost-response retry
  // dedupes instead of double-broadcasting; rotated only after a success.
  const idemKeyRef = useRef<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getTreasury();
      setOv(data);
      setForbidden(false);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 403 || e.status === 401)) setForbidden(true);
      else toast.err(e instanceof Error ? e.message : "Failed to load treasury");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const amountSats = Math.max(0, Math.floor(Number(amount)) || 0);
  const maxWithdraw = ov?.withdrawable_sats ?? 0;
  const overMax = amountSats > maxWithdraw;
  const validAddr = address.trim().length >= 10;
  const canSubmit = amountSats > 0 && validAddr && !overMax && !submitting && !!ov;

  async function submitWithdraw() {
    if (!ov || !canSubmit) return;
    // Re-fetch the overview right before confirming so the dialog (and the
    // headroom check) reflect the latest liquidity, not a stale page load.
    let fresh: TreasuryOverview;
    try {
      fresh = await api.getTreasury();
      setOv(fresh);
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "Could not refresh treasury");
      return;
    }
    if (amountSats > fresh.withdrawable_sats) {
      toast.err(
        `Withdrawable dropped to ${fmtSatsFull(fresh.withdrawable_sats)} sats — adjust the amount.`,
      );
      return;
    }
    const ok = window.confirm(
      `Withdraw ${fmtSatsFull(amountSats)} sats on-chain to:\n${address.trim()}\n\n` +
        `After this, node assets ≈ ${fmtSatsFull(fresh.assets_sats - amountSats)} sats vs ` +
        `${fmtSatsFull(fresh.agent_liabilities_sats)} owed to agents.\n\n` +
        `This broadcasts a real on-chain transaction and is irreversible. Continue?`,
    );
    if (!ok) return;
    // Reuse the key on a retry of this same intent; only mint one if none held.
    if (!idemKeyRef.current) idemKeyRef.current = api.uuid();
    setSubmitting(true);
    try {
      const r = await api.withdraw(
        amountSats,
        address.trim(),
        feeRate ? Math.floor(Number(feeRate)) : undefined,
        idemKeyRef.current,
      );
      toast.ok(`Broadcast ${truncHash(r.txid)} — ${fmtSatsFull(r.amount_sats)} sats sent`);
      idemKeyRef.current = null; // next withdrawal is a fresh intent
      setAmount("");
      setAddress("");
      setFeeRate("");
      load();
    } catch (e) {
      // Keep the key so a retry of THIS withdrawal dedupes against any broadcast.
      toast.err(e instanceof Error ? e.message : "Withdrawal failed");
    } finally {
      setSubmitting(false);
    }
  }

  // Revenue-by-day chart, chronological (API returns most-recent-first).
  const feeDays = useMemo(() => (ov ? [...ov.revenue_by_day].reverse() : []), [ov]);
  const feeBars = feeDays.map((d) => d.sats);
  const feeLabels = feeDays.map((d) => {
    const dt = new Date(d.date + "T00:00:00");
    return String(dt.getMonth() + 1) + "/" + String(dt.getDate());
  });

  if (tier !== "admin" || forbidden) {
    return (
      <div className="coming-soon">
        <div className="cs-inner">
          <div className="cs-ico">
            <Landmark size={24} />
          </div>
          <h2>Admin access required</h2>
          <p>
            The treasury — revenue and on-chain withdrawals — is operator-only. Connect an
            admin-scope API key to view and move accrued funds.
          </p>
        </div>
      </div>
    );
  }

  // 1 decimal so a sub-1% insolvency can't render as a clean "100%".
  const ratioPct =
    ov?.solvency_ratio != null ? (ov.solvency_ratio * 100).toFixed(1) + "%" : "∞";

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
          label="Revenue (all-time)"
          value={ov ? fmtSatsFull(ov.revenue_total_sats) : "—"}
          unit="sats"
          sub={ov ? fmtUsd(satsToUsd(ov.revenue_total_sats, price)) : "platform fees collected"}
        />
        <StatCard
          label="Revenue today"
          value={ov ? fmtSatsFull(ov.revenue_today_sats) : "—"}
          unit="sats"
          sub={ov ? fmtUsd(satsToUsd(ov.revenue_today_sats, price)) : "since 00:00 UTC"}
        />
        <StatCard
          label="Node assets"
          value={ov ? satsToBtc(ov.assets_sats) : "—"}
          unit="BTC"
          sub={ov ? `${fmtSatsFull(ov.assets_sats)} sats on-chain + channels` : "liquidity"}
        />
        <StatCard
          label="Solvency"
          value={
            <span style={{ color: ov ? (ov.solvent ? "var(--green)" : "var(--red)") : undefined }}>
              {ratioPct}
            </span>
          }
          sub={
            ov ? (
              <span style={{ color: ov.solvent ? "var(--green)" : "var(--red)" }}>
                {ov.solvent ? "solvent" : "INSOLVENT"} · {fmtSatsFull(ov.agent_liabilities_sats)} owed
              </span>
            ) : (
              "assets / liabilities"
            )
          }
        />
      </div>

      {ov?.error && (
        <div
          className="panel"
          style={{ borderColor: "rgba(239,68,68,0.4)", marginBottom: 16, padding: 14 }}
        >
          <span style={{ color: "var(--red)" }}>
            Liquidity could not be read from LND ({ov.error}) — figures are partial and solvency is
            reported conservatively. Withdrawals are blocked until this clears.
          </span>
        </div>
      )}

      <div className="treasury-cols">
        {/* Liquidity & solvency */}
        <div className="panel">
          <div className="panel-head">
            <h3 style={{ display: "inline-flex", alignItems: "center", gap: 6, margin: 0 }}>
              {ov?.solvent ? (
                <ShieldCheck size={15} style={{ color: "var(--green)" }} />
              ) : (
                <ShieldAlert size={15} style={{ color: "var(--red)" }} />
              )}
              Liquidity &amp; solvency
            </h3>
          </div>
          <table className="data">
            <tbody>
              <tr>
                <td className="t-muted">On-chain confirmed</td>
                <td className="right t-mono">{ov ? fmtSatsFull(ov.onchain_confirmed_sats) : "—"}</td>
              </tr>
              <tr>
                <td className="t-muted">Channel local</td>
                <td className="right t-mono">{ov ? fmtSatsFull(ov.channel_local_sats) : "—"}</td>
              </tr>
              <tr>
                <td className="t-muted">Total assets</td>
                <td className="right t-mono t-gold">{ov ? fmtSatsFull(ov.assets_sats) : "—"}</td>
              </tr>
              <tr>
                <td className="t-muted">Agent liabilities (owed)</td>
                <td className="right t-mono">{ov ? fmtSatsFull(ov.agent_liabilities_sats) : "—"}</td>
              </tr>
              <tr>
                <td className="t-muted">Withdrawable now</td>
                <td className="right t-mono" style={{ color: "var(--green)" }}>
                  {ov ? fmtSatsFull(ov.withdrawable_sats) : "—"}
                </td>
              </tr>
            </tbody>
          </table>
          <p className="t-muted" style={{ fontSize: 11.5, padding: "10px 14px 0", lineHeight: 1.5 }}>
            Revenue is an accounting figure — accrued platform fees live in your node, commingled
            with liquidity. A withdrawal moves your on-chain balance and is capped so assets never
            drop below what you owe agents (minus a {ov ? fmtSatsFull(ov.fee_reserve_sats) : "—"}-sat
            fee reserve).
          </p>
        </div>

        {/* Withdraw accrued BTC */}
        <div className="panel">
          <div className="panel-head">
            <h3 style={{ display: "inline-flex", alignItems: "center", gap: 6, margin: 0 }}>
              <ArrowUpRight size={15} /> Withdraw accrued BTC
            </h3>
          </div>
          <div style={{ padding: 16 }}>
            <div className="field">
              <label>Amount (sats)</label>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  className="mono"
                  inputMode="numeric"
                  placeholder="0"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value.replace(/[^0-9]/g, ""))}
                />
                <button
                  className="tb-btn"
                  type="button"
                  onClick={() => setAmount(String(maxWithdraw))}
                  disabled={!ov || maxWithdraw <= 0}
                >
                  Max
                </button>
              </div>
              <div className="t-muted" style={{ fontSize: 11.5, marginTop: 6 }}>
                Max {ov ? fmtSatsFull(maxWithdraw) : "—"} sats
                {amountSats > 0 && <> · ≈ {fmtUsd(satsToUsd(amountSats, price))}</>}
                {overMax && <span style={{ color: "var(--red)" }}> · exceeds withdrawable</span>}
              </div>
            </div>

            <div className="field">
              <label>Destination address</label>
              <input
                className="mono"
                placeholder="bc1q… / bcrt1q…"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
              />
            </div>

            <div className="field">
              <label>Fee rate (sat/vB, optional)</label>
              <input
                className="mono"
                inputMode="numeric"
                placeholder="LND estimates if blank"
                value={feeRate}
                onChange={(e) => setFeeRate(e.target.value.replace(/[^0-9]/g, ""))}
              />
            </div>

            <button
              className="tb-btn gold"
              onClick={submitWithdraw}
              disabled={!canSubmit}
              style={{ justifyContent: "center", width: "100%" }}
            >
              {submitting ? (
                <>
                  <span className="spinner" /> Broadcasting…
                </>
              ) : (
                <>
                  <ArrowUpRight size={14} /> Withdraw on-chain
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Revenue by day */}
      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-head">
          <h3 style={{ margin: 0 }}>Revenue — last {feeDays.length} days</h3>
        </div>
        <div style={{ padding: 16 }}>
          {feeBars.some((s) => s > 0) ? (
            <BarChart data={feeBars} labels={feeLabels} unit="sats/day" />
          ) : (
            <div className="empty">No settled platform fees in this window yet.</div>
          )}
        </div>
      </div>

      {/* BTC transfers (on-chain withdrawal history) */}
      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-head">
          <h3 style={{ margin: 0 }}>Bitcoin transfers</h3>
        </div>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>When</th>
                <th>Amount</th>
                <th>Address</th>
                <th>Txid</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {(ov?.recent_withdrawals ?? []).map((w) => (
                <tr key={w.id}>
                  <td className="t-mono t-muted" style={{ fontSize: 12 }}>
                    {fmtDate(w.created_at)}
                  </td>
                  <td className="t-mono">{fmtSatsFull(w.amount_sats)}</td>
                  <td className="t-mono t-muted" style={{ fontSize: 12 }}>
                    {w.address.length > 18 ? w.address.slice(0, 10) + "…" + w.address.slice(-6) : w.address}
                  </td>
                  <td className="t-mono t-gold" style={{ fontSize: 12 }}>
                    {truncHash(w.txid)}
                  </td>
                  <td>
                    <span
                      style={{
                        color:
                          w.status === "broadcast"
                            ? "var(--green)"
                            : w.status === "failed"
                              ? "var(--red)"
                              : "var(--t2)",
                      }}
                    >
                      {w.status}
                    </span>
                  </td>
                </tr>
              ))}
              {(!ov || ov.recent_withdrawals.length === 0) && (
                <tr>
                  <td colSpan={5}>
                    <div className="empty">No on-chain withdrawals yet.</div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
