"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  ExternalLink,
  Landmark,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  X,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useBtcPrice } from "@/lib/price";
import { useToast } from "@/lib/toast";
import {
  explorerAddrUrl,
  explorerTxUrl,
  fmtDate,
  fmtSatsFull,
  fmtUsd,
  satsToBtc,
  satsToUsd,
  truncHash,
} from "@/lib/format";
import type { NodeStatus, TreasuryOverview } from "@/lib/types";
import { StatCard } from "@/components/StatCard";
import { BarChart } from "@/components/charts/BarChart";

/** Solvency at-a-glance: ratio → a human health label + color. */
function solvencyHealth(ratio: number | null, solvent: boolean): { label: string; color: string } {
  if (!solvent) return { label: "INSOLVENT", color: "var(--red)" };
  if (ratio == null) return { label: "healthy", color: "var(--green)" };
  if (ratio >= 2) return { label: "healthy", color: "var(--green)" };
  if (ratio >= 1.25) return { label: "caution", color: "var(--amber)" };
  return { label: "tight", color: "var(--red)" };
}

function shortAddr(a: string): string {
  return a.length > 18 ? a.slice(0, 10) + "…" + a.slice(-6) : a;
}

export default function TreasuryPage() {
  const { tier, network } = useAuth();
  const isMainnet = network === "mainnet";
  const price = useBtcPrice();
  const toast = useToast();

  const [ov, setOv] = useState<TreasuryOverview | null>(null);
  const [status, setStatus] = useState<NodeStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);

  const [amount, setAmount] = useState("");
  const [address, setAddress] = useState("");
  const [feeRate, setFeeRate] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // Stable across retries of the SAME withdrawal so a lost-response retry
  // dedupes instead of double-broadcasting; rotated only after a success.
  const idemKeyRef = useRef<string | null>(null);

  // Confirmation modal holds the fresh snapshot the dialog summarizes.
  const [confirm, setConfirm] = useState<TreasuryOverview | null>(null);
  const [typed, setTyped] = useState(""); // mainnet type-to-confirm input

  const [revWindow, setRevWindow] = useState<7 | 30>(30);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [data, st] = await Promise.all([
        api.getTreasury(),
        api.getStatus().catch(() => null), // node status is best-effort
      ]);
      setOv(data);
      setStatus(st);
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

  // A change to the withdrawal INTENT (amount/address/fee) invalidates the
  // idempotency key, so a genuinely-new withdrawal gets a fresh key. A
  // same-intent retry (inputs unchanged after a failed/lost send) keeps the key
  // so it dedupes against any broadcast instead of 409-ing on a body mismatch.
  useEffect(() => {
    idemKeyRef.current = null;
  }, [amount, address, feeRate]);

  const usd = (sats: number) => (price > 0 ? fmtUsd(satsToUsd(sats, price)) : "—");

  const amountSats = Math.max(0, Math.floor(Number(amount)) || 0);
  const maxWithdraw = ov?.withdrawable_sats ?? 0;
  const overMax = amountSats > maxWithdraw;
  const validAddr = address.trim().length >= 10;
  const canSubmit = amountSats > 0 && validAddr && !overMax && !submitting && !!ov;

  // Open the confirmation modal — re-fetch a fresh snapshot first so the dialog
  // (and the headroom check) reflect current liquidity, not a stale page load.
  async function openConfirm() {
    if (!ov || !canSubmit) return;
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
    setTyped("");
    setConfirm(fresh);
  }

  async function doWithdraw() {
    if (!confirm) return;
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
      setConfirm(null);
      setTyped("");
      load();
    } catch (e) {
      // Keep the key so a retry of THIS withdrawal dedupes against any broadcast.
      toast.err(e instanceof Error ? e.message : "Withdrawal failed");
    } finally {
      setSubmitting(false);
    }
  }

  // Revenue window (7 / 30 days), chronological (API returns most-recent-first).
  const revDays = useMemo(
    () => (ov ? [...ov.revenue_by_day].slice(0, revWindow).reverse() : []),
    [ov, revWindow],
  );
  const revBars = revDays.map((d) => d.sats);
  const revLabels = revDays.map((d) => {
    const dt = new Date(d.date + "T00:00:00");
    return String(dt.getMonth() + 1) + "/" + String(dt.getDate());
  });
  const revTotal = revBars.reduce((s, x) => s + x, 0);
  const revAvg = revBars.length ? Math.round(revTotal / revBars.length) : 0;

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

  const ratioX = ov?.solvency_ratio != null ? ov.solvency_ratio.toFixed(1) + "×" : "∞";
  const health = ov ? solvencyHealth(ov.solvency_ratio, ov.solvent) : null;

  // Solvency AFTER the pending withdrawal (for the confirm dialog). Subtract the
  // fee reserve too, so the preview matches the server-side guard
  // (assets - amount - reserve >= liabilities), not a rosier picture.
  const afterAssets = confirm ? confirm.assets_sats - amountSats - confirm.fee_reserve_sats : 0;
  const afterRatio =
    confirm && confirm.agent_liabilities_sats > 0
      ? afterAssets / confirm.agent_liabilities_sats
      : null;
  const afterHealth = confirm ? solvencyHealth(afterRatio, afterAssets >= confirm.agent_liabilities_sats) : null;
  // Mainnet requires typing the exact amount to arm the confirm button.
  const confirmArmed = !!confirm && (!isMainnet || typed.trim() === String(amountSats));

  return (
    <>
      <div className="toolbar">
        {isMainnet ? (
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "4px 10px",
              borderRadius: 6,
              fontSize: 11.5,
              fontWeight: 600,
              letterSpacing: "0.04em",
              color: "var(--red)",
              background: "rgba(239,68,68,0.10)",
              border: "1px solid rgba(239,68,68,0.4)",
            }}
          >
            <AlertTriangle size={13} /> MAINNET · REAL FUNDS
          </span>
        ) : (
          <span className="t-muted t-mono" style={{ fontSize: 11.5, textTransform: "uppercase" }}>
            {network || "—"} · test funds
          </span>
        )}
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
          sub={ov ? usd(ov.revenue_total_sats) : "platform fees collected"}
        />
        <StatCard
          label="Revenue today"
          value={ov ? fmtSatsFull(ov.revenue_today_sats) : "—"}
          unit="sats"
          sub={ov ? `${usd(ov.revenue_today_sats)} · since 00:00 UTC` : "since 00:00 UTC"}
        />
        <StatCard
          label="Node assets"
          value={ov ? satsToBtc(ov.assets_sats) : "—"}
          unit="BTC"
          sub={ov ? `${usd(ov.assets_sats)} · on-chain + channels` : "liquidity"}
        />
        <StatCard
          label="Solvency"
          value={
            <span style={{ color: health?.color }}>{ratioX}</span>
          }
          sub={
            ov && health ? (
              <span style={{ color: health.color }}>
                {health.label} · {fmtSatsFull(ov.agent_liabilities_sats)} owed
              </span>
            ) : (
              "assets / liabilities"
            )
          }
        />
      </div>

      {/* Node health */}
      <div className="panel" style={{ marginTop: 16, padding: "12px 16px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap", fontSize: 12.5 }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 7, fontWeight: 600 }}>
            <Activity size={14} style={{ color: "var(--gold)" }} /> Node
          </span>
          {status ? (
            <>
              <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <span
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    background: status.node.synced_to_chain ? "var(--green)" : "var(--amber)",
                  }}
                />
                {status.node.synced_to_chain ? "Synced to chain" : "Syncing…"}
              </span>
              <span className="t-muted">
                block <span className="t-mono">{status.node.block_height.toLocaleString()}</span>
              </span>
              <span className="t-muted">
                <span className="t-mono">{status.channels.num_active}</span> active channel
                {status.channels.num_active === 1 ? "" : "s"}
              </span>
              <span className="t-muted t-mono" style={{ fontSize: 11.5 }}>
                {status.node.alias}
              </span>
            </>
          ) : (
            <span className="t-muted">node status unavailable</span>
          )}
        </div>
      </div>

      {ov?.error && (
        <div
          className="panel"
          style={{ borderColor: "rgba(239,68,68,0.4)", marginTop: 16, padding: 14 }}
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
              {health && (
                <span style={{ color: health.color, fontSize: 12, fontWeight: 600 }}>
                  · {ratioX} {health.label}
                </span>
              )}
            </h3>
          </div>
          <table className="data">
            <tbody>
              {[
                ["On-chain confirmed", ov?.onchain_confirmed_sats, undefined],
                ["Channel local", ov?.channel_local_sats, undefined],
                ["Total assets", ov?.assets_sats, "t-gold"],
                ["Agent liabilities (owed)", ov?.agent_liabilities_sats, undefined],
              ].map(([label, val, cls]) => (
                <tr key={label as string}>
                  <td className="t-muted">{label}</td>
                  <td className={"right t-mono " + (cls || "")}>
                    {ov ? fmtSatsFull(val as number) : "—"}
                  </td>
                  <td className="right t-muted t-mono" style={{ fontSize: 11.5 }}>
                    {ov ? usd(val as number) : ""}
                  </td>
                </tr>
              ))}
              <tr>
                <td className="t-muted">Withdrawable now</td>
                <td className="right t-mono" style={{ color: "var(--green)" }}>
                  {ov ? fmtSatsFull(ov.withdrawable_sats) : "—"}
                </td>
                <td className="right t-muted t-mono" style={{ fontSize: 11.5 }}>
                  {ov ? usd(ov.withdrawable_sats) : ""}
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
                {amountSats > 0 && <> · ≈ {usd(amountSats)}</>}
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
              onClick={openConfirm}
              disabled={!canSubmit}
              style={{ justifyContent: "center", width: "100%" }}
            >
              <ArrowUpRight size={14} /> Review withdrawal
            </button>
          </div>
        </div>
      </div>

      {/* Revenue by day */}
      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-head">
          <h3 style={{ margin: 0 }}>Revenue</h3>
          <span className="sub">
            · {fmtSatsFull(revTotal)} sats over {revDays.length}d · avg {fmtSatsFull(revAvg)}/day
          </span>
          <div style={{ flex: 1 }} />
          <div style={{ display: "flex", gap: 6 }}>
            {([7, 30] as const).map((w) => (
              <button
                key={w}
                type="button"
                className={"tab" + (revWindow === w ? " active" : "")}
                style={{ padding: "4px 12px", fontSize: 12 }}
                onClick={() => setRevWindow(w)}
              >
                {w}d
              </button>
            ))}
          </div>
        </div>
        <div style={{ padding: 16 }}>
          {revBars.some((s) => s > 0) ? (
            <BarChart data={revBars} labels={revLabels} unit="sats/day" />
          ) : (
            <div className="empty">No settled platform fees in this window yet.</div>
          )}
        </div>
      </div>

      {/* BTC transfers (on-chain withdrawal history) */}
      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-head">
          <h3 style={{ margin: 0 }}>Bitcoin transfers</h3>
          <span className="sub">· accrued BTC moved on-chain</span>
        </div>
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>When</th>
                <th className="right">Amount</th>
                <th>Address</th>
                <th>Txid</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {(ov?.recent_withdrawals ?? []).map((w) => {
                const txUrl = explorerTxUrl(network, w.txid);
                const addrUrl = explorerAddrUrl(network, w.address);
                return (
                  <tr key={w.id}>
                    <td className="t-mono t-muted" style={{ fontSize: 12 }}>
                      {fmtDate(w.created_at)}
                    </td>
                    <td className="right t-mono">
                      {fmtSatsFull(w.amount_sats)}
                      <div className="t-muted" style={{ fontSize: 11 }}>{usd(w.amount_sats)}</div>
                    </td>
                    <td className="t-mono t-muted" style={{ fontSize: 12 }}>
                      {addrUrl ? (
                        <a href={addrUrl} target="_blank" rel="noopener noreferrer" className="t-muted">
                          {shortAddr(w.address)}
                        </a>
                      ) : (
                        shortAddr(w.address)
                      )}
                    </td>
                    <td className="t-mono t-gold" style={{ fontSize: 12 }}>
                      {w.txid && txUrl ? (
                        <a
                          href={txUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="t-gold"
                          style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
                        >
                          {truncHash(w.txid)} <ExternalLink size={11} />
                        </a>
                      ) : (
                        truncHash(w.txid)
                      )}
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
                );
              })}
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

      {/* Withdrawal confirmation modal */}
      {confirm && (
        <div className="modal-overlay" onClick={submitting ? undefined : () => setConfirm(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>
              <ArrowUpRight size={18} /> Confirm withdrawal
            </h3>
            <div className="modal-sub">
              This broadcasts a <b style={{ color: "var(--t1)" }}>real, irreversible</b> on-chain
              transaction.
            </div>

            {isMainnet && (
              <div
                className="warn"
                style={{ borderColor: "rgba(239,68,68,0.45)", color: "var(--red)" }}
              >
                <AlertTriangle size={13} style={{ verticalAlign: "-2px" }} /> <b>MAINNET — real
                funds.</b> Double-check the amount and address. This cannot be undone.
              </div>
            )}

            <table className="data" style={{ marginTop: 14 }}>
              <tbody>
                <tr>
                  <td className="t-muted">Amount</td>
                  <td className="right t-mono">
                    {fmtSatsFull(amountSats)} sats
                    <span className="t-muted"> · {usd(amountSats)}</span>
                  </td>
                </tr>
                <tr>
                  <td className="t-muted">To</td>
                  <td className="right t-mono" style={{ fontSize: 12, wordBreak: "break-all" }}>
                    {address.trim()}
                  </td>
                </tr>
                <tr>
                  <td className="t-muted">Fee rate</td>
                  <td className="right t-mono">
                    {feeRate ? `${feeRate} sat/vB` : "LND estimate"}
                  </td>
                </tr>
                <tr>
                  <td className="t-muted">Solvency after</td>
                  <td className="right t-mono" style={{ color: afterHealth?.color }}>
                    {afterRatio != null ? afterRatio.toFixed(1) + "×" : "∞"}{" "}
                    {afterHealth?.label}
                  </td>
                </tr>
                <tr>
                  <td className="t-muted">Assets after</td>
                  <td className="right t-mono">
                    {fmtSatsFull(afterAssets)} vs {fmtSatsFull(confirm.agent_liabilities_sats)} owed
                  </td>
                </tr>
              </tbody>
            </table>

            {isMainnet && (
              <div className="field" style={{ marginTop: 16 }}>
                <label>
                  Type the amount <span className="t-mono t-gold">{amountSats}</span> to confirm
                </label>
                <input
                  className="mono"
                  inputMode="numeric"
                  autoFocus
                  placeholder={String(amountSats)}
                  value={typed}
                  onChange={(e) => setTyped(e.target.value.replace(/[^0-9]/g, ""))}
                />
              </div>
            )}

            <div className="modal-actions">
              <button className="tb-btn" onClick={() => setConfirm(null)} disabled={submitting}>
                <X size={14} /> Cancel
              </button>
              <button
                className="tb-btn gold"
                onClick={doWithdraw}
                disabled={!confirmArmed || submitting}
              >
                {submitting ? (
                  <>
                    <span className="spinner dark" /> Broadcasting…
                  </>
                ) : (
                  <>
                    <ArrowUpRight size={14} /> Withdraw {fmtSatsFull(amountSats)} sats
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
