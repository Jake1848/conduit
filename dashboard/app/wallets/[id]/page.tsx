"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Copy, Minus, Plus, X } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useAppData } from "@/lib/appdata";
import { useBtcPrice } from "@/lib/price";
import { useToast } from "@/lib/toast";
import { fmtDate, fmtTime, fmtUsd, satsToUsd, txDestination } from "@/lib/format";
import { roleFromName } from "@/lib/useTxCounts";
import type { Agent, Balance, Policy, Transaction, Invoice } from "@/lib/types";
import { Avatar } from "@/components/Avatar";
import { StatusBadge } from "@/components/StatusBadge";

interface PolicyForm {
  maxPerTx: string;
  maxPerHour: string;
  dailyLimit: string;
  allowlist: string;
  blocklist: string;
}

const EMPTY_POLICY: PolicyForm = { maxPerTx: "", maxPerHour: "", dailyLimit: "", allowlist: "", blocklist: "" };

export default function AgentDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const price = useBtcPrice();
  const toast = useToast();
  const { refresh: refreshFleet } = useAppData();

  const [agent, setAgent] = useState<Agent | null>(null);
  const [balance, setBalance] = useState<Balance | null>(null);
  const [txs, setTxs] = useState<Transaction[]>([]);
  const [policy, setPolicy] = useState<PolicyForm>(EMPTY_POLICY);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const [adjust, setAdjust] = useState<null | "credit" | "debit">(null);
  const [invoice, setInvoice] = useState({ amount: "", memo: "" });
  const [createdInvoice, setCreatedInvoice] = useState<Invoice | null>(null);
  const [invBusy, setInvBusy] = useState(false);

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const loadBalanceTx = useCallback(async () => {
    const [b, t] = await Promise.all([api.getBalance(id), api.getTransactions(id, 12)]);
    if (!mountedRef.current) return;
    setBalance(b);
    setTxs(t.data);
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setNotFound(false);
    (async () => {
      try {
        const a = await api.getAgent(id);
        if (cancelled) return;
        setAgent(a);
        await loadBalanceTx();
        // policy is optional (404 when none attached)
        try {
          const p: Policy = await api.getPolicy(id);
          if (!cancelled)
            setPolicy({
              maxPerTx: p.max_per_transaction?.toString() ?? "",
              maxPerHour: p.max_per_hour?.toString() ?? "",
              dailyLimit: p.max_per_day?.toString() ?? "",
              allowlist: p.allowlist.join("\n"),
              blocklist: p.blocklist.join("\n"),
            });
        } catch (e) {
          if (!(e instanceof ApiError) || e.status !== 404) throw e;
        }
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) setNotFound(true);
        else toast.err(e instanceof Error ? e.message : "Failed to load agent");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function savePolicy() {
    setSaving(true);
    try {
      const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);
      const num = (s: string) => (s.trim() === "" ? undefined : parseInt(s));
      await api.savePolicy(id, {
        max_per_transaction: num(policy.maxPerTx) ?? null,
        max_per_hour: num(policy.maxPerHour) ?? null,
        max_per_day: num(policy.dailyLimit) ?? null,
        allowlist: lines(policy.allowlist),
        blocklist: lines(policy.blocklist),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 1600);
      toast.ok("Policy saved");
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "Failed to save policy");
    } finally {
      setSaving(false);
    }
  }

  async function doAdjust(sats: number) {
    if (!adjust) return;
    try {
      if (adjust === "credit") await api.credit(id, sats);
      else await api.debit(id, sats);
      toast.ok(`${adjust === "credit" ? "Credited" : "Debited"} ${sats.toLocaleString()} sats`);
      setAdjust(null);
      await loadBalanceTx();
      refreshFleet();
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "Adjustment failed");
    }
  }

  async function createInvoice() {
    const amt = parseInt(invoice.amount);
    if (!amt || amt < 1) {
      toast.err("Enter an amount in sats.");
      return;
    }
    setInvBusy(true);
    try {
      const inv = await api.createInvoice(id, amt, invoice.memo || undefined);
      setCreatedInvoice(inv);
      setInvoice({ amount: "", memo: "" });
      toast.ok("Invoice created");
      await loadBalanceTx();
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "Failed to create invoice");
    } finally {
      setInvBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="loading-row">
        <span className="spinner" /> Loading agent…
      </div>
    );
  }

  if (notFound || !agent) {
    return (
      <>
        <Link className="back-link" href="/wallets">
          <ArrowLeft size={14} /> Back to Wallets
        </Link>
        <div className="panel">
          <div className="empty">Agent “{id}” was not found.</div>
        </div>
      </>
    );
  }

  const usd = balance ? satsToUsd(balance.available_sats, price) : 0;

  return (
    <>
      <Link className="back-link" href="/wallets">
        <ArrowLeft size={14} /> Back to Wallets
      </Link>

      <div className="detail-head">
        <Avatar name={agent.name} />
        <div className="info">
          <h2>{agent.name}</h2>
          <div className="meta-row">
            <StatusBadge s={agent.active ? "live" : "frozen"} />
            <span className="t-mono t-gold" style={{ fontSize: 12 }}>
              scope: {roleFromName(agent.name)}
            </span>
            <span className="created">created {fmtDate(agent.created_at)}</span>
          </div>
        </div>
      </div>

      <div className="detail-grid">
        {/* Balance */}
        <div className="panel">
          <div className="panel-head">
            <h3>Balance</h3>
            {balance && balance.pending_sats > 0 && (
              <>
                <div className="spacer" />
                <span className="st st-pending">
                  <span className="d" />
                  {balance.pending_sats.toLocaleString()} PENDING
                </span>
              </>
            )}
          </div>
          <div className="bal-big mono">
            {balance ? balance.available_sats.toLocaleString() : "—"}{" "}
            <span style={{ fontSize: 18, color: "var(--t2)" }}>sats</span>
          </div>
          <div className="bal-usd">≈ {fmtUsd(usd)}</div>
          <div className="btn-pair">
            <button className="btn-out" onClick={() => setAdjust("credit")}>
              + Credit
            </button>
            <button className="btn-out" onClick={() => setAdjust("debit")}>
              − Debit
            </button>
          </div>
        </div>

        {/* Policy */}
        <div className="panel">
          <div className="panel-head">
            <h3>Spending Policy</h3>
            <div className="spacer" />
            {saved && (
              <span className="badge-live">
                <span className="d" />
                SAVED
              </span>
            )}
          </div>
          <div className="field-row">
            <div className="field">
              <label>Max / Tx (sats)</label>
              <input value={policy.maxPerTx} onChange={(e) => setPolicy({ ...policy, maxPerTx: e.target.value })} />
            </div>
            <div className="field">
              <label>Max / Hour (sats)</label>
              <input value={policy.maxPerHour} onChange={(e) => setPolicy({ ...policy, maxPerHour: e.target.value })} />
            </div>
          </div>
          <div className="field">
            <label>Daily Limit (sats)</label>
            <input value={policy.dailyLimit} onChange={(e) => setPolicy({ ...policy, dailyLimit: e.target.value })} />
          </div>
          <div className="field-row">
            <div className="field">
              <label>Allowlist</label>
              <textarea value={policy.allowlist} onChange={(e) => setPolicy({ ...policy, allowlist: e.target.value })} />
            </div>
            <div className="field">
              <label>Blocklist</label>
              <textarea value={policy.blocklist} onChange={(e) => setPolicy({ ...policy, blocklist: e.target.value })} />
            </div>
          </div>
          <button className="btn-save" onClick={savePolicy} disabled={saving}>
            {saving ? <><span className="spinner dark" /> Saving…</> : "Save Policy"}
          </button>
        </div>
      </div>

      {/* History */}
      <div className="panel">
        <div className="panel-head">
          <h3>Transaction History</h3>
          <div className="spacer" />
          <span className="t-muted t-mono" style={{ fontSize: 12 }}>
            {txs.length} records
          </span>
        </div>
        <div className="table-wrap" style={{ border: "none" }}>
          <table className="data">
            <thead>
              <tr>
                <th>Time</th>
                <th>Direction</th>
                <th>Destination</th>
                <th className="right">Amount</th>
                <th className="right">Fee</th>
                <th>Status</th>
                <th className="right">Latency</th>
              </tr>
            </thead>
            <tbody>
              {txs.map((h) => {
                const dir = h.direction === "send" ? "out" : "in";
                return (
                  <tr key={h.id}>
                    <td className="t-mono t-muted" style={{ fontSize: 12 }}>
                      {fmtTime(h.created_at)}
                    </td>
                    <td>
                      <span className={"dir-cell " + dir}>{dir === "out" ? "→ send" : "← recv"}</span>
                    </td>
                    <td className="t-mono" style={{ fontSize: 12 }}>
                      {txDestination(h)}
                    </td>
                    <td className="right t-mono t-gold">{h.amount_sats.toLocaleString()}</td>
                    <td className="right fee" style={{ fontSize: 12 }}>
                      {h.fee_sats}
                    </td>
                    <td>
                      <StatusBadge s={h.status} />
                    </td>
                    <td
                      className="right t-mono"
                      style={{ color: h.latency_ms == null ? "var(--t3)" : "var(--green)", fontSize: 12 }}
                    >
                      {h.latency_ms == null ? "—" : h.latency_ms + "ms"}
                    </td>
                  </tr>
                );
              })}
              {txs.length === 0 && (
                <tr>
                  <td colSpan={7}>
                    <div className="empty">No transactions yet.</div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Create invoice */}
      <div className="section-title">Create Invoice</div>
      <div className="panel">
        <div className="field-row">
          <div className="field">
            <label>Amount (sats)</label>
            <input
              placeholder="0"
              value={invoice.amount}
              onChange={(e) => setInvoice({ ...invoice, amount: e.target.value })}
              inputMode="numeric"
            />
          </div>
          <div className="field">
            <label>Memo</label>
            <input
              placeholder="inference · 1.2K tokens"
              value={invoice.memo}
              onChange={(e) => setInvoice({ ...invoice, memo: e.target.value })}
            />
          </div>
        </div>
        <button className="btn-save" onClick={createInvoice} disabled={invBusy}>
          {invBusy ? <><span className="spinner dark" /> Creating…</> : "Create Invoice"}
        </button>

        {createdInvoice && (
          <div className="key-box" style={{ marginTop: 18 }}>
            <code>{createdInvoice.payment_request}</code>
            <button
              className="copy-btn"
              onClick={() => {
                navigator.clipboard?.writeText(createdInvoice.payment_request);
                toast.ok("Invoice copied");
              }}
            >
              <Copy size={12} /> Copy
            </button>
          </div>
        )}
      </div>

      {adjust && (
        <AdjustModal kind={adjust} onClose={() => setAdjust(null)} onConfirm={doAdjust} />
      )}
    </>
  );
}

function AdjustModal({
  kind,
  onClose,
  onConfirm,
}: {
  kind: "credit" | "debit";
  onClose: () => void;
  onConfirm: (sats: number) => Promise<void>;
}) {
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  async function go() {
    const sats = parseInt(amount);
    if (!sats || sats < 1) return;
    setBusy(true);
    await onConfirm(sats);
    setBusy(false);
  }
  return (
    <div className="modal-overlay" onClick={busy ? undefined : onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 420 }}>
        <h3>
          {kind === "credit" ? <Plus size={18} /> : <Minus size={18} />}{" "}
          {kind === "credit" ? "Credit agent" : "Debit agent"}
        </h3>
        <div className="modal-sub">
          {kind === "credit"
            ? "Add virtual balance to this agent's ledger."
            : "Remove virtual balance from this agent's ledger."}
        </div>
        <div className="field" style={{ marginTop: 18 }}>
          <label>Amount (sats)</label>
          <input autoFocus value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="numeric" placeholder="0" />
        </div>
        <div className="modal-actions">
          <button className="tb-btn" onClick={onClose} disabled={busy}>
            <X size={14} /> Cancel
          </button>
          <button className="tb-btn gold" onClick={go} disabled={busy}>
            {busy ? <><span className="spinner dark" /> Working…</> : kind === "credit" ? "Credit" : "Debit"}
          </button>
        </div>
      </div>
    </div>
  );
}
