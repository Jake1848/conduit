"use client";

import { useCallback, useEffect, useState } from "react";
import { Copy, Plus, Webhook as WebhookIcon, X } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import type { Webhook } from "@/lib/types";

const EVENTS = ["payment.settled", "payment.failed", "invoice.settled", "invoice.expired"];

export default function WebhooksPage() {
  const toast = useToast();
  const [hooks, setHooks] = useState<Webhook[]>([]);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [modal, setModal] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setHooks(await api.listWebhooks());
      setForbidden(false);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 403 || e.status === 401)) setForbidden(true);
      else toast.err(e instanceof Error ? e.message : "Failed to load webhooks");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function remove(w: Webhook) {
    if (!window.confirm(`Delete the webhook for ${w.url}?`)) return;
    try {
      await api.deleteWebhook(w.id);
      toast.ok("Webhook deleted");
      load();
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "Delete failed");
    }
  }

  if (forbidden) {
    return (
      <div className="coming-soon">
        <div className="cs-inner">
          <div className="cs-ico">
            <WebhookIcon size={24} />
          </div>
          <h2>Admin access required</h2>
          <p>Webhooks are operator-only. Connect an admin-scope API key to manage them.</p>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="toolbar">
        <span className="t-muted" style={{ fontSize: 13 }}>
          Register HTTPS endpoints to receive HMAC-signed payment &amp; invoice events.
        </span>
        <div style={{ flex: 1 }} />
        <button className="tb-btn gold" onClick={() => setModal(true)}>
          <Plus size={14} /> Add webhook
        </button>
      </div>

      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>URL</th>
              <th>Events</th>
              <th>Status</th>
              <th className="right">Action</th>
            </tr>
          </thead>
          <tbody>
            {hooks.map((w) => (
              <tr key={w.id}>
                <td className="t-mono" style={{ fontSize: 12.5 }}>
                  {w.url}
                </td>
                <td className="t-muted" style={{ fontSize: 12 }}>
                  {w.events.join(", ")}
                </td>
                <td>
                  <span className={"st " + (w.active ? "st-live" : "st-frozen")}>
                    {w.active ? "active" : "disabled"}
                  </span>
                </td>
                <td className="right">
                  <button
                    className="copy-btn"
                    style={{ color: "var(--red)", borderColor: "rgba(239,68,68,0.3)" }}
                    onClick={() => remove(w)}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {loading && (
              <tr>
                <td colSpan={4}>
                  <div className="loading-row">
                    <span className="spinner" /> Loading webhooks…
                  </div>
                </td>
              </tr>
            )}
            {!loading && hooks.length === 0 && (
              <tr>
                <td colSpan={4}>
                  <div className="empty">No webhooks registered yet.</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="panel" style={{ marginTop: 16, padding: 16 }}>
        <h3 style={{ margin: "0 0 8px", fontSize: 13 }}>Verifying deliveries</h3>
        <p className="t-muted" style={{ fontSize: 12.5, lineHeight: 1.6, margin: 0 }}>
          Every delivery is a POST with{" "}
          <code className="t-gold">X-Conduit-Signature: sha256=HMAC(secret, body)</code> (plus a
          server-key signature). Verify it with the per-webhook secret shown once at creation.
          Payload: <code className="t-mono">{`{ "event", "data", "ts" }`}</code>. Delivery retries
          with exponential backoff; a delivery-history view is on the roadmap.
        </p>
      </div>

      {modal && <CreateWebhookModal onClose={() => setModal(false)} onCreated={load} />}
    </>
  );
}

function CreateWebhookModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const toast = useToast();
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<string[]>(["payment.settled", "payment.failed"]);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<Webhook | null>(null);
  const [copied, setCopied] = useState(false);

  function toggle(ev: string) {
    setEvents((cur) => (cur.includes(ev) ? cur.filter((e) => e !== ev) : [...cur, ev]));
  }

  async function create() {
    if (!url.trim().startsWith("https://")) {
      toast.err("URL must be https://");
      return;
    }
    if (events.length === 0) {
      toast.err("Select at least one event");
      return;
    }
    setBusy(true);
    try {
      const w = await api.createWebhook(url.trim(), events);
      setCreated(w);
      onCreated();
    } catch (e) {
      toast.err(e instanceof Error ? e.message : "Failed to create webhook");
    } finally {
      setBusy(false);
    }
  }

  if (created) {
    return (
      <div className="modal-overlay" onClick={onClose}>
        <div className="modal" onClick={(e) => e.stopPropagation()}>
          <h3>
            <WebhookIcon size={18} /> Webhook created
          </h3>
          <div className="modal-sub">
            Copy the signing secret now — <b style={{ color: "var(--t1)" }}>it won&apos;t be shown
            again</b>. Use it to verify the <code className="t-gold">X-Conduit-Signature</code>.
          </div>
          <div className="key-box">
            <code>{created.secret || "(no secret returned)"}</code>
            <button
              className="copy-btn"
              onClick={() => {
                navigator.clipboard?.writeText(created.secret || "");
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
            >
              {copied ? "COPIED ✓" : <><Copy size={12} /> Copy</>}
            </button>
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

  return (
    <div className="modal-overlay" onClick={busy ? undefined : onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>
          <WebhookIcon size={18} /> Add webhook
        </h3>
        <div className="modal-sub">Conduit will POST signed events to this HTTPS endpoint.</div>
        <div className="field" style={{ marginTop: 18 }}>
          <label>Endpoint URL</label>
          <input
            autoFocus
            className="mono"
            placeholder="https://hooks.example.com/conduit"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </div>
        <div className="field">
          <label>Events</label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {EVENTS.map((ev) => (
              <button
                key={ev}
                type="button"
                className={"tab" + (events.includes(ev) ? " active" : "")}
                style={{ padding: "6px 10px", fontSize: 12 }}
                onClick={() => toggle(ev)}
              >
                {ev}
              </button>
            ))}
          </div>
        </div>
        <div className="modal-actions">
          <button className="tb-btn" onClick={onClose} disabled={busy}>
            <X size={14} /> Cancel
          </button>
          <button className="tb-btn gold" onClick={create} disabled={busy}>
            {busy ? <><span className="spinner dark" /> Creating…</> : "Create webhook"}
          </button>
        </div>
      </div>
    </div>
  );
}
