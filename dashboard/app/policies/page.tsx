"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ShieldCheck, Trash2, X } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useAppData } from "@/lib/appdata";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";
import { fmtSats } from "@/lib/format";
import type { Agent, Policy } from "@/lib/types";

const PAGE_SIZE = 12;

function summary(p: Policy | null | undefined): { text: string; cls: string } {
  if (p === undefined) return { text: "…", cls: "t-muted" };
  if (p === null) return { text: "no policy", cls: "t-muted" };
  if (!p.enabled) return { text: "disabled", cls: "" };
  const bits: string[] = [];
  if (p.max_per_transaction) bits.push(`tx≤${fmtSats(p.max_per_transaction)}`);
  if (p.max_per_day) bits.push(`day≤${fmtSats(p.max_per_day)}`);
  if (p.allowlist?.length) bits.push(`allow ${p.allowlist.length}`);
  if (p.blocklist?.length) bits.push(`block ${p.blocklist.length}`);
  if (p.require_memo) bits.push("memo");
  return { text: bits.length ? bits.join(" · ") : "no limits", cls: "t-gold" };
}

export default function PoliciesPage() {
  const { agents } = useAppData();
  const { tier } = useAuth();
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  // agent_id -> Policy | null (no policy) | undefined (loading)
  const [policies, setPolicies] = useState<Record<string, Policy | null | undefined>>({});
  const [editing, setEditing] = useState<Agent | null>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = q ? agents.filter((a) => a.name.toLowerCase().includes(q) || a.id.includes(q)) : agents;
    return list;
  }, [agents, query]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const pageRows = filtered.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE);

  // Fetch policies only for the VISIBLE page (bounded — no fleet-wide fan-out).
  useEffect(() => {
    let cancelled = false;
    const missing = pageRows.filter((a) => policies[a.id] === undefined);
    if (missing.length === 0) return;
    (async () => {
      const entries = await Promise.all(
        missing.map(async (a) => {
          try {
            return [a.id, await api.getPolicy(a.id)] as const;
          } catch (e) {
            if (e instanceof ApiError && e.status === 404) return [a.id, null] as const;
            return [a.id, null] as const;
          }
        }),
      );
      if (!cancelled) setPolicies((cur) => ({ ...cur, ...Object.fromEntries(entries) }));
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [safePage, query, agents]);

  const refreshOne = useCallback((id: string, p: Policy | null) => {
    setPolicies((cur) => ({ ...cur, [id]: p }));
  }, []);

  return (
    <>
      <div className="toolbar">
        <div className="search">
          <input
            placeholder="Search agents…"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(0);
            }}
          />
        </div>
        <div style={{ flex: 1 }} />
        <span className="t-muted" style={{ fontSize: 12 }}>
          {filtered.length} agent{filtered.length === 1 ? "" : "s"}
        </span>
      </div>

      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Policy</th>
              <th>Status</th>
              <th className="right">Action</th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((a) => {
              const s = summary(policies[a.id]);
              return (
                <tr key={a.id}>
                  <td>
                    <div style={{ fontWeight: 500 }}>{a.name}</div>
                    <div className="t-muted t-mono" style={{ fontSize: 11 }}>
                      {a.id}
                    </div>
                  </td>
                  <td className={s.cls} style={{ fontSize: 12.5 }}>
                    {s.text}
                  </td>
                  <td>
                    <span className={"st " + (a.active ? "st-live" : "st-frozen")}>
                      {a.active ? "active" : "frozen"}
                    </span>
                  </td>
                  <td className="right">
                    <button className="copy-btn" onClick={() => setEditing(a)}>
                      {policies[a.id] ? "Edit policy" : "Set policy"}
                    </button>
                  </td>
                </tr>
              );
            })}
            {agents.length === 0 && (
              <tr>
                <td colSpan={4}>
                  <div className="empty">No agents yet.</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
        {pageCount > 1 && (
          <div className="table-foot">
            <span className="t-muted" style={{ fontSize: 12 }}>
              Page {safePage + 1} / {pageCount}
            </span>
            <div className="pager">
              <button disabled={safePage === 0} onClick={() => setPage(safePage - 1)}>
                ‹
              </button>
              <button disabled={safePage >= pageCount - 1} onClick={() => setPage(safePage + 1)}>
                ›
              </button>
            </div>
          </div>
        )}
      </div>

      {editing && (
        <PolicyModal
          agent={editing}
          policy={policies[editing.id] ?? null}
          isAdmin={tier === "admin"}
          onClose={() => setEditing(null)}
          onSaved={(p) => {
            refreshOne(editing.id, p);
            setEditing(null);
          }}
        />
      )}
    </>
  );
}

function numOrNull(s: string): number | null {
  const n = Math.floor(Number(s));
  return s.trim() === "" || !Number.isFinite(n) || n < 1 ? null : n;
}

function PolicyModal({
  agent,
  policy,
  isAdmin,
  onClose,
  onSaved,
}: {
  agent: Agent;
  policy: Policy | null;
  isAdmin: boolean;
  onClose: () => void;
  onSaved: (p: Policy | null) => void;
}) {
  const toast = useToast();
  const [perTx, setPerTx] = useState(policy?.max_per_transaction?.toString() ?? "");
  const [perHour, setPerHour] = useState(policy?.max_per_hour?.toString() ?? "");
  const [perDay, setPerDay] = useState(policy?.max_per_day?.toString() ?? "");
  const [rate, setRate] = useState(policy?.max_per_minute_count?.toString() ?? "");
  const [allow, setAllow] = useState((policy?.allowlist ?? []).join("\n"));
  const [block, setBlock] = useState((policy?.blocklist ?? []).join("\n"));
  const [requireMemo, setRequireMemo] = useState(policy?.require_memo ?? false);
  const [enabled, setEnabled] = useState(policy?.enabled ?? true);
  const [busy, setBusy] = useState(false);

  const lines = (s: string) => s.split(/[\n,]/).map((x) => x.trim()).filter(Boolean);

  async function save() {
    setBusy(true);
    try {
      const p = await api.savePolicy(agent.id, {
        max_per_transaction: numOrNull(perTx),
        max_per_hour: numOrNull(perHour),
        max_per_day: numOrNull(perDay),
        max_per_minute_count: numOrNull(rate),
        allowlist: lines(allow),
        blocklist: lines(block),
        require_memo: requireMemo,
        enabled,
      });
      toast.ok("Policy saved");
      onSaved(p);
    } catch (e) {
      const msg =
        e instanceof ApiError && e.status === 403
          ? "Admin scope required to edit policies."
          : e instanceof Error
            ? e.message
            : "Save failed";
      toast.err(msg);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Remove the spending policy for ${agent.name}?`)) return;
    setBusy(true);
    try {
      await api.deletePolicy(agent.id);
      toast.ok("Policy removed");
      onSaved(null);
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={busy ? undefined : onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 560 }}>
        <h3>
          <ShieldCheck size={18} /> Policy — {agent.name}
        </h3>
        <div className="modal-sub">
          Guardrails enforced server-side before every payment. Leave a limit blank for no cap.
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 16 }}>
          <div className="field" style={{ margin: 0 }}>
            <label>Max per transaction (sats)</label>
            <input className="mono" inputMode="numeric" value={perTx}
              onChange={(e) => setPerTx(e.target.value.replace(/[^0-9]/g, ""))} placeholder="—" />
          </div>
          <div className="field" style={{ margin: 0 }}>
            <label>Max per hour (sats)</label>
            <input className="mono" inputMode="numeric" value={perHour}
              onChange={(e) => setPerHour(e.target.value.replace(/[^0-9]/g, ""))} placeholder="—" />
          </div>
          <div className="field" style={{ margin: 0 }}>
            <label>Max per day (sats)</label>
            <input className="mono" inputMode="numeric" value={perDay}
              onChange={(e) => setPerDay(e.target.value.replace(/[^0-9]/g, ""))} placeholder="—" />
          </div>
          <div className="field" style={{ margin: 0 }}>
            <label>Max payments / minute</label>
            <input className="mono" inputMode="numeric" value={rate}
              onChange={(e) => setRate(e.target.value.replace(/[^0-9]/g, ""))} placeholder="60" />
          </div>
        </div>

        <div className="field" style={{ marginTop: 12 }}>
          <label>Allowlist — destination pubkeys (one per line; empty = allow any)</label>
          <textarea className="mono" rows={2} value={allow}
            onChange={(e) => setAllow(e.target.value)} placeholder="02beef…" />
        </div>
        <div className="field">
          <label>Blocklist — destination pubkeys</label>
          <textarea className="mono" rows={2} value={block}
            onChange={(e) => setBlock(e.target.value)} placeholder="03dead…" />
        </div>

        <div style={{ display: "flex", gap: 18, marginTop: 4 }}>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 13, cursor: "pointer" }}>
            <input type="checkbox" checked={requireMemo} onChange={(e) => setRequireMemo(e.target.checked)} />
            Require memo
          </label>
          <label style={{ display: "inline-flex", alignItems: "center", gap: 7, fontSize: 13, cursor: "pointer" }}>
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            Policy enabled
          </label>
        </div>

        {!isAdmin && (
          <div className="warn" style={{ marginTop: 14 }}>
            ⚠ Editing policies requires an <b>admin</b>-scope key. You can view but not save.
          </div>
        )}

        <div className="modal-actions">
          {policy && (
            <button
              className="tb-btn"
              style={{ color: "var(--red)", borderColor: "rgba(239,68,68,0.3)", marginRight: "auto" }}
              onClick={remove}
              disabled={busy}
            >
              <Trash2 size={14} /> Remove
            </button>
          )}
          <button className="tb-btn" onClick={onClose} disabled={busy}>
            <X size={14} /> Cancel
          </button>
          <button className="tb-btn gold" onClick={save} disabled={busy || !isAdmin}>
            {busy ? <><span className="spinner dark" /> Saving…</> : "Save policy"}
          </button>
        </div>
      </div>
    </div>
  );
}
