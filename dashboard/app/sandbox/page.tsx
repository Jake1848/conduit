"use client";

import { useState } from "react";
import { Copy, Play } from "lucide-react";
import { api, ApiError, getStoredApiUrl } from "@/lib/api";
import { useToast } from "@/lib/toast";

// READ-ONLY GET endpoints only — the sandbox never moves money. Each is a safe,
// idempotent read you can run against your live instance with the session key.
const ENDPOINTS: { path: string; label: string }[] = [
  { path: "/v1/health", label: "Health (public)" },
  { path: "/v1/agents?limit=5", label: "List agents" },
  { path: "/v1/metrics", label: "Fleet metrics" },
  { path: "/v1/status", label: "Node status (admin)" },
  { path: "/v1/treasury/overview", label: "Treasury overview (admin)" },
  { path: "/v1/fees", label: "Platform-fee revenue (admin)" },
  { path: "/v1/transactions/recent?limit=10", label: "Recent transactions" },
  { path: "/v1/api-keys", label: "API keys (admin)" },
];

export default function SandboxPage() {
  const toast = useToast();
  const [path, setPath] = useState(ENDPOINTS[1].path);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string>("");
  const [statusLine, setStatusLine] = useState<{ ok: boolean; text: string } | null>(null);

  const curl = `curl -s ${getStoredApiUrl()}${path} \\\n  -H "Authorization: Bearer ck_…"`;

  async function run() {
    setBusy(true);
    setStatusLine(null);
    try {
      const data = await api.request<unknown>(path);
      setResult(JSON.stringify(data, null, 2));
      setStatusLine({ ok: true, text: "200 OK" });
    } catch (e) {
      if (e instanceof ApiError) {
        setStatusLine({ ok: false, text: `${e.status} ${e.code ?? "ERROR"}` });
        setResult(e.message);
      } else {
        setStatusLine({ ok: false, text: "error" });
        setResult(e instanceof Error ? e.message : "Request failed");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="toolbar">
        <span className="t-muted" style={{ fontSize: 13 }}>
          Read-only API explorer — runs GET requests with your connected key. No money moves here.
        </span>
      </div>

      <div className="treasury-cols">
        <div className="panel">
          <div className="panel-head">
            <h3 style={{ margin: 0 }}>Request</h3>
          </div>
          <div style={{ padding: 16 }}>
            <div className="field">
              <label>Endpoint (GET)</label>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {ENDPOINTS.map((ep) => (
                  <button
                    key={ep.path}
                    type="button"
                    className={"tab" + (path === ep.path ? " active" : "")}
                    style={{ padding: "5px 10px", fontSize: 11.5 }}
                    onClick={() => setPath(ep.path)}
                    title={ep.path}
                  >
                    {ep.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="field">
              <label>Path</label>
              <input
                className="mono"
                value={path}
                onChange={(e) => setPath(e.target.value)}
                spellCheck={false}
              />
            </div>
            <button
              className="tb-btn gold"
              onClick={run}
              disabled={busy}
              style={{ justifyContent: "center", width: "100%" }}
            >
              {busy ? <><span className="spinner" /> Running…</> : <><Play size={14} /> Run GET</>}
            </button>

            <div style={{ marginTop: 16 }}>
              <label
                className="t-muted"
                style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em" }}
              >
                Equivalent curl
              </label>
              <pre className="hash" style={{ marginTop: 6, whiteSpace: "pre-wrap", fontSize: 11.5 }}>
                {curl}
              </pre>
              <button
                className="copy-btn"
                onClick={() => {
                  navigator.clipboard?.writeText(curl);
                  toast.ok("curl copied");
                }}
              >
                <Copy size={11} /> Copy
              </button>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <h3 style={{ margin: 0 }}>Response</h3>
            {statusLine && (
              <span
                className="t-mono"
                style={{ marginLeft: 8, color: statusLine.ok ? "var(--green)" : "var(--red)" }}
              >
                {statusLine.text}
              </span>
            )}
          </div>
          <div style={{ padding: 16 }}>
            {result ? (
              <pre
                className="t-mono"
                style={{
                  fontSize: 12,
                  lineHeight: 1.5,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  maxHeight: 520,
                  overflow: "auto",
                  margin: 0,
                }}
              >
                {result}
              </pre>
            ) : (
              <div className="empty">Pick an endpoint and Run to see the live response.</div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
