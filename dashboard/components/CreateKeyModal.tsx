"use client";

import { useState } from "react";
import { Copy, KeyRound, X } from "lucide-react";
import { api } from "@/lib/api";
import { useToast } from "@/lib/toast";
import type { ApiKeyCreated, Scope } from "@/lib/types";

const SCOPES: { value: Scope; label: string; hint: string }[] = [
  { value: "read", label: "read", hint: "read-only access" },
  { value: "write", label: "write", hint: "create + pay" },
  { value: "admin", label: "admin", hint: "full control incl. keys" },
];

export function CreateKeyModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const toast = useToast();
  const [label, setLabel] = useState("");
  const [scope, setScope] = useState<Scope>("read");
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);

  async function create() {
    setBusy(true);
    try {
      const key = await api.createKey(scope, label || "console key");
      setCreated(key);
      onCreated();
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "Failed to create key");
    } finally {
      setBusy(false);
    }
  }

  function copy() {
    if (!created) return;
    navigator.clipboard?.writeText(created.secret);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  // ---- phase 2: reveal the secret once ----
  if (created) {
    return (
      <div className="modal-overlay" onClick={onClose}>
        <div className="modal" onClick={(e) => e.stopPropagation()}>
          <h3>
            <KeyRound size={18} /> New API Key Created
          </h3>
          <div className="modal-sub">
            Copy your secret key now. For security,{" "}
            <b style={{ color: "var(--t1)" }}>it will not be shown again</b>. Store it in a secrets
            manager.
          </div>
          <div className="key-box">
            <code>{created.secret}</code>
            <button className="copy-btn" onClick={copy}>
              {copied ? "COPIED ✓" : <><Copy size={12} /> Copy</>}
            </button>
          </div>
          <div className="warn">
            ⚠ This key has <b>{created.scope}</b> scope. Treat it like a password — never commit it
            to source control.
          </div>
          <div className="modal-actions">
            <button className="tb-btn gold" onClick={onClose}>
              Done
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ---- phase 1: form ----
  return (
    <div className="modal-overlay" onClick={busy ? undefined : onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>
          <KeyRound size={18} /> Create API Key
        </h3>
        <div className="modal-sub">Mint a new programmatic credential for this fleet.</div>

        <div className="field" style={{ marginTop: 18 }}>
          <label>Label</label>
          <input
            autoFocus
            placeholder="Production · agent-fleet"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
        </div>
        <div className="field">
          <label>Scope</label>
          <div style={{ display: "flex", gap: 8 }}>
            {SCOPES.map((s) => (
              <button
                key={s.value}
                type="button"
                className={"tab" + (scope === s.value ? " active" : "")}
                style={{ flex: 1, padding: "9px 10px", textAlign: "center" }}
                onClick={() => setScope(s.value)}
                title={s.hint}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        <div className="modal-actions">
          <button className="tb-btn" onClick={onClose} disabled={busy}>
            <X size={14} /> Cancel
          </button>
          <button className="tb-btn gold" onClick={create} disabled={busy}>
            {busy ? <><span className="spinner dark" /> Creating…</> : "Create key"}
          </button>
        </div>
      </div>
    </div>
  );
}
