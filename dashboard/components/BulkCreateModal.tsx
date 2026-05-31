"use client";

import { useState } from "react";
import { Plus, X } from "lucide-react";
import { api } from "@/lib/api";
import { useToast } from "@/lib/toast";

export function BulkCreateModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const toast = useToast();
  const [count, setCount] = useState("5");
  const [prefix, setPrefix] = useState("agent");
  const [dailyLimit, setDailyLimit] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(0);
  const [errors, setErrors] = useState(0);

  const total = Math.max(0, Math.min(200, parseInt(count) || 0));

  async function run() {
    if (total < 1) {
      toast.err("Enter a count between 1 and 200.");
      return;
    }
    setBusy(true);
    setDone(0);
    setErrors(0);
    const limit = parseInt(dailyLimit) || undefined;
    let ok = 0;
    let err = 0;
    const stamp = Date.now().toString(36).slice(-4);
    for (let i = 1; i <= total; i++) {
      try {
        await api.createAgent(`${prefix}-${stamp}-${i}`, limit);
        ok++;
      } catch {
        err++;
      }
      setDone(ok);
      setErrors(err);
    }
    setBusy(false);
    toast.ok(`Created ${ok} agent${ok === 1 ? "" : "s"}${err ? ` · ${err} failed` : ""}`);
    onCreated();
    onClose();
  }

  const pct = total ? Math.round(((done + errors) / total) * 100) : 0;

  return (
    <div className="modal-overlay" onClick={busy ? undefined : onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>
          <Plus size={18} /> Bulk Create Agents
        </h3>
        <div className="modal-sub">
          Provisions agent wallets via sequential, idempotent <code className="mono">POST /v1/agents</code>{" "}
          calls. Each gets a unique name from the prefix.
        </div>

        <div className="field-row" style={{ marginTop: 18 }}>
          <div className="field">
            <label>Count (max 200)</label>
            <input value={count} onChange={(e) => setCount(e.target.value)} disabled={busy} inputMode="numeric" />
          </div>
          <div className="field">
            <label>Name prefix</label>
            <input value={prefix} onChange={(e) => setPrefix(e.target.value)} disabled={busy} />
          </div>
        </div>
        <div className="field">
          <label>Daily limit (sats, optional)</label>
          <input
            value={dailyLimit}
            onChange={(e) => setDailyLimit(e.target.value)}
            placeholder="e.g. 500000"
            disabled={busy}
            inputMode="numeric"
          />
        </div>

        {busy && (
          <>
            <div className="progress">
              <span style={{ width: `${pct}%` }} />
            </div>
            <div className="t-muted t-mono" style={{ fontSize: 12, marginTop: 8 }}>
              {done + errors} / {total} · {done} created{errors ? ` · ${errors} failed` : ""}
            </div>
          </>
        )}

        <div className="modal-actions">
          <button className="tb-btn" onClick={onClose} disabled={busy}>
            <X size={14} /> Cancel
          </button>
          <button className="tb-btn gold" onClick={run} disabled={busy}>
            {busy ? <><span className="spinner dark" /> Creating…</> : <>Create {total || ""}</>}
          </button>
        </div>
      </div>
    </div>
  );
}
