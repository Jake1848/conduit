"use client";

import { useMemo, useState } from "react";
import { Download } from "lucide-react";
import { useAppData } from "@/lib/appdata";
import { useAuditLog } from "@/lib/useAuditLog";
import { fmtTime, truncHash, txDestination } from "@/lib/format";
import { downloadCsv } from "@/lib/csv";
import { Avatar } from "@/components/Avatar";
import { StatusBadge } from "@/components/StatusBadge";
import { Dropdown } from "@/components/Dropdown";

const PAGE_SIZE = 24;

export default function AuditPage() {
  const { agents } = useAppData();
  const { rows, loading } = useAuditLog(agents);
  const [agent, setAgent] = useState("All");
  const [status, setStatus] = useState("All");
  const [dir, setDir] = useState("All");
  const [page, setPage] = useState(0);

  const agentNames = useMemo(
    () => ["All", ...Array.from(new Set(rows.map((r) => r.agentName))).sort()],
    [rows],
  );

  const filtered = useMemo(
    () =>
      rows.filter(
        (r) =>
          (agent === "All" || r.agentName === agent) &&
          (status === "All" || r.status === status.toLowerCase()) &&
          (dir === "All" || (dir === "Send" ? r.direction === "send" : r.direction === "receive")),
      ),
    [rows, agent, status, dir],
  );

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const pageRows = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);

  function exportCsv() {
    downloadCsv(
      "conduit-audit.csv",
      ["time", "agent", "direction", "destination", "amount_sats", "fee_sats", "status", "latency_ms", "payment_hash"],
      filtered.map((r) => [
        new Date(r.created_at).toISOString(),
        r.agentName,
        r.direction,
        txDestination(r),
        r.amount_sats,
        r.fee_sats,
        r.status,
        r.latency_ms ?? "",
        r.payment_hash ?? "",
      ]),
    );
  }

  return (
    <>
      <div className="toolbar">
        <Dropdown label="Agent" value={agent} options={agentNames} onChange={(v) => { setAgent(v); setPage(0); }} maxValueChars={16} />
        <Dropdown label="Status" value={status} options={["All", "Settled", "Pending", "Failed"]} onChange={(v) => { setStatus(v); setPage(0); }} />
        <Dropdown label="Direction" value={dir} options={["All", "Send", "Receive"]} onChange={(v) => { setDir(v); setPage(0); }} />
        <div className="select" style={{ cursor: "default" }}>
          Date: <b>Recent</b>
        </div>
        <div style={{ flex: 1 }} />
        <button className="tb-btn gold" onClick={exportCsv}>
          <Download size={14} /> Export CSV
        </button>
      </div>

      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Time</th>
              <th>Agent</th>
              <th>Direction</th>
              <th>Destination</th>
              <th className="right">Amount</th>
              <th className="right">Fee</th>
              <th>Status</th>
              <th className="right">Latency</th>
              <th>Payment Hash</th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((r) => {
              const dirc = r.direction === "send" ? "out" : "in";
              return (
                <tr key={r.id}>
                  <td className="t-mono t-muted" style={{ fontSize: 12 }}>
                    {fmtTime(r.created_at)}
                  </td>
                  <td>
                    <div className="cell-agent">
                      <Avatar name={r.agentName} />
                      <span className="nm">{r.agentName}</span>
                    </div>
                  </td>
                  <td>
                    <span className={"dir-cell " + dirc}>{dirc === "out" ? "→ send" : "← recv"}</span>
                  </td>
                  <td className="t-mono" style={{ fontSize: 12 }}>
                    {txDestination(r)}
                  </td>
                  <td className="right t-mono t-gold">{r.amount_sats.toLocaleString()}</td>
                  <td className="right fee" style={{ fontSize: 12 }}>
                    {r.fee_sats}
                  </td>
                  <td>
                    <StatusBadge s={r.status} />
                  </td>
                  <td
                    className="right t-mono"
                    style={{ color: r.status === "failed" || r.latency_ms == null ? "var(--t3)" : "var(--green)", fontSize: 12 }}
                  >
                    {r.status === "failed" || r.latency_ms == null ? "—" : r.latency_ms + "ms"}
                  </td>
                  <td>
                    <span className="hash">{truncHash(r.payment_hash)}</span>
                  </td>
                </tr>
              );
            })}
            {loading && (
              <tr>
                <td colSpan={9}>
                  <div className="loading-row">
                    <span className="spinner" /> Aggregating transactions across the fleet…
                  </div>
                </td>
              </tr>
            )}
            {!loading && filtered.length === 0 && (
              <tr>
                <td colSpan={9}>
                  <div className="empty">No events match your filters.</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
        <div className="table-foot">
          <span>
            Showing {pageRows.length} of {filtered.length} events
          </span>
          <div className="pager">
            <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={safePage === 0}>
              ‹
            </button>
            {Array.from({ length: Math.min(pageCount, 5) }, (_, i) => {
              const start = Math.max(0, Math.min(safePage - 2, pageCount - 5));
              const n = start + i;
              return (
                <button key={n} className={n === safePage ? "active" : ""} onClick={() => setPage(n)}>
                  {n + 1}
                </button>
              );
            })}
            <button onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))} disabled={safePage >= pageCount - 1}>
              ›
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
