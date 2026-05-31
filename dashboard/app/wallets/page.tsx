"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Download, Plus, Search } from "lucide-react";
import { useAppData } from "@/lib/appdata";
import { useBtcPrice } from "@/lib/price";
import { useTxCounts, roleFromName } from "@/lib/useTxCounts";
import { fmtDate, fmtSats, fmtUsd, satsToUsd } from "@/lib/format";
import { downloadCsv } from "@/lib/csv";
import { Avatar } from "@/components/Avatar";
import { StatusBadge } from "@/components/StatusBadge";
import { Dropdown } from "@/components/Dropdown";
import { BulkCreateModal } from "@/components/BulkCreateModal";

const PAGE_SIZE = 12;

export default function WalletsPage() {
  const { agents, balances, loadingAgents, refresh } = useAppData();
  const price = useBtcPrice();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("All");
  const [scope, setScope] = useState("All");
  const [page, setPage] = useState(0);
  const [bulk, setBulk] = useState(false);

  const scopes = useMemo(
    () => ["All", ...Array.from(new Set(agents.map((a) => roleFromName(a.name)))).sort()],
    [agents],
  );

  const filtered = useMemo(() => {
    return agents.filter(
      (a) =>
        (q === "" || a.name.toLowerCase().includes(q.toLowerCase()) || a.id.toLowerCase().includes(q.toLowerCase())) &&
        (status === "All" || (status === "Live" ? a.active : !a.active)) &&
        (scope === "All" || roleFromName(a.name) === scope),
    );
  }, [agents, q, status, scope]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const pageRows = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);
  const counts = useTxCounts(pageRows.map((a) => a.id));

  function exportCsv() {
    downloadCsv(
      "conduit-wallets.csv",
      ["name", "id", "scope", "available_sats", "status", "created"],
      filtered.map((a) => [
        a.name,
        a.id,
        roleFromName(a.name),
        balances[a.id]?.available_sats ?? "",
        a.active ? "live" : "frozen",
        fmtDate(a.created_at),
      ]),
    );
  }

  return (
    <>
      <div className="toolbar">
        <div className="search">
          <span className="ico">
            <Search size={15} />
          </span>
          <input
            placeholder="Search agents by name or ID…"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(0);
            }}
          />
        </div>
        <Dropdown
          label="Status"
          value={status}
          options={["All", "Live", "Frozen"]}
          onChange={(v) => {
            setStatus(v);
            setPage(0);
          }}
        />
        <Dropdown
          label="Scope"
          value={scope}
          options={scopes}
          onChange={(v) => {
            setScope(v);
            setPage(0);
          }}
          maxValueChars={16}
        />
        <div style={{ flex: 1 }} />
        <button className="tb-btn gold" onClick={() => setBulk(true)}>
          <Plus size={14} /> Bulk create
        </button>
        <button className="tb-btn" onClick={exportCsv}>
          <Download size={14} /> Export
        </button>
      </div>

      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Scope</th>
              <th className="right">Balance</th>
              <th className="right">Tx Today</th>
              <th>Policy</th>
              <th>Status</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((a) => {
              const bal = balances[a.id];
              const tc = counts[a.id];
              return (
                <tr key={a.id} className="clickable" onClick={() => router.push(`/wallets/${a.id}`)}>
                  <td>
                    <div className="cell-agent">
                      <Avatar name={a.name} />
                      <span className="nm">{a.name}</span>
                    </div>
                  </td>
                  <td>
                    <span className="t-mono t-gold" style={{ fontSize: 12 }}>
                      {roleFromName(a.name)}
                    </span>
                  </td>
                  <td className="right">
                    <div className="t-mono" style={{ fontSize: 13 }}>
                      {bal ? fmtSats(bal.available_sats) + " sats" : <span className="skel" />}
                    </div>
                    <div className="t-mono t-muted" style={{ fontSize: 11, marginTop: 2 }}>
                      {bal ? fmtUsd(satsToUsd(bal.available_sats, price)) : ""}
                    </div>
                  </td>
                  <td className="right t-mono">{tc ? `${tc.count}${tc.hasMore ? "+" : ""}` : "…"}</td>
                  <td>
                    <span className="t-mono t-muted" style={{ fontSize: 12 }}>
                      {a.active ? "standard" : "frozen"}
                    </span>
                  </td>
                  <td>
                    <StatusBadge s={a.active ? "live" : "frozen"} />
                  </td>
                  <td className="t-mono t-muted" style={{ fontSize: 12 }}>
                    {fmtDate(a.created_at)}
                  </td>
                </tr>
              );
            })}
            {loadingAgents && (
              <tr>
                <td colSpan={7}>
                  <div className="loading-row">
                    <span className="spinner" /> Loading agents…
                  </div>
                </td>
              </tr>
            )}
            {!loadingAgents && filtered.length === 0 && (
              <tr>
                <td colSpan={7}>
                  <div className="empty">No agents match your filters.</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
        <div className="table-foot">
          <span>
            Showing {pageRows.length} of {filtered.length} agents
          </span>
          <div className="pager">
            <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={safePage === 0}>
              ‹
            </button>
            {Array.from({ length: Math.min(pageCount, 5) }, (_, i) => {
              const start = Math.max(0, Math.min(safePage - 2, pageCount - 5));
              const n = start + i;
              return (
                <button
                  key={n}
                  className={n === safePage ? "active" : ""}
                  onClick={() => setPage(n)}
                >
                  {n + 1}
                </button>
              );
            })}
            <button
              onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
              disabled={safePage >= pageCount - 1}
            >
              ›
            </button>
          </div>
        </div>
      </div>

      {bulk && <BulkCreateModal onClose={() => setBulk(false)} onCreated={refresh} />}
    </>
  );
}
