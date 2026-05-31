"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { fmtDate, fmtRelative, scopeColorClass } from "@/lib/format";
import type { ApiKey } from "@/lib/types";
import { StatusBadge } from "@/components/StatusBadge";
import { CreateKeyModal } from "@/components/CreateKeyModal";

export default function KeysPage() {
  const toast = useToast();
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [modal, setModal] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listKeys();
      setKeys(data);
      setForbidden(false);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 403 || e.status === 401)) setForbidden(true);
      else toast.err(e instanceof Error ? e.message : "Failed to load keys");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function revoke(k: ApiKey) {
    if (!window.confirm(`Revoke key "${k.label || k.prefix}"? This cannot be undone.`)) return;
    try {
      await api.revokeKey(k.id);
      toast.ok("Key revoked");
      load();
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "Failed to revoke key");
    }
  }

  if (forbidden) {
    return (
      <div className="coming-soon">
        <div className="cs-inner">
          <div className="cs-ico">
            <Plus size={24} />
          </div>
          <h2>Admin access required</h2>
          <p>The connected API key does not have admin scope, so it cannot manage API keys.</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="toolbar">
        <div style={{ flex: 1 }} />
        <button className="tb-btn gold" onClick={() => setModal(true)}>
          <Plus size={14} /> Create new key
        </button>
      </div>

      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Prefix</th>
              <th>Label</th>
              <th>Scope</th>
              <th>Created</th>
              <th>Last Used</th>
              <th>Status</th>
              <th className="right">Action</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k.id}>
                <td>
                  <span className="t-mono t-gold" style={{ fontSize: 12.5 }}>
                    {k.prefix}…
                  </span>
                </td>
                <td>{k.label || <span className="t-muted">—</span>}</td>
                <td>
                  <span className={"scope-pill " + scopeColorClass(k.scope)}>{k.scope.toUpperCase()}</span>
                </td>
                <td className="t-mono t-muted" style={{ fontSize: 12 }}>
                  {fmtDate(k.created_at)}
                </td>
                <td className="t-mono t-muted" style={{ fontSize: 12 }}>
                  {fmtRelative(k.last_used_at)}
                </td>
                <td>
                  <StatusBadge s={k.revoked ? "revoked" : "active"} />
                </td>
                <td className="right">
                  {!k.revoked ? (
                    <button
                      className="copy-btn"
                      style={{ color: "var(--red)", borderColor: "rgba(239,68,68,0.3)" }}
                      onClick={() => revoke(k)}
                    >
                      Revoke
                    </button>
                  ) : (
                    <span className="t-muted t-mono" style={{ fontSize: 11 }}>
                      revoked
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {loading && (
              <tr>
                <td colSpan={7}>
                  <div className="loading-row">
                    <span className="spinner" /> Loading keys…
                  </div>
                </td>
              </tr>
            )}
            {!loading && keys.length === 0 && (
              <tr>
                <td colSpan={7}>
                  <div className="empty">No API keys yet.</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {modal && <CreateKeyModal onClose={() => setModal(false)} onCreated={load} />}
    </>
  );
}
