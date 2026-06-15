"use client";

import { useCallback, useEffect, useState } from "react";
import { Plus, RefreshCw, Server, Trash2, X } from "lucide-react";
import { fmtSats } from "@/lib/format";
import { useToast } from "@/lib/toast";
import { ProGate } from "@/components/ProGate";

const STORE = "conduit_fleet_instances";

interface Instance {
  id: string;
  name: string;
  url: string;
  key: string;
}
interface InstanceState {
  loading: boolean;
  reachable: boolean;
  version?: string;
  network?: string;
  agents?: number;
  revenueSats?: number;
  solvent?: boolean | null;
  solvencyRatio?: number | null;
  error?: string;
}

export default function FleetPage() {
  return (
    <ProGate
      feature="fleet"
      title="Multi-instance Fleet"
      blurb="Run more than one Conduit instance? See them all in one place — version, network, agent count, fee revenue and solvency — by pointing at each instance's API URL + key. Read-only aggregation of YOUR OWN instances; nothing is centralized and no funds are touched."
      bullets={[
        "One pane across all your instances",
        "Version / network / agent count at a glance",
        "Revenue + solvency per instance",
        "Read-only — your URLs + keys stay in this browser",
      ]}
    >
      <FleetView />
    </ProGate>
  );
}

function FleetView() {
  const toast = useToast();
  const [instances, setInstances] = useState<Instance[]>([]);
  const [states, setStates] = useState<Record<string, InstanceState>>({});
  const [modal, setModal] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORE);
      if (raw) setInstances(JSON.parse(raw));
    } catch { /* ignore */ }
  }, []);

  const persist = (next: Instance[]) => {
    setInstances(next);
    localStorage.setItem(STORE, JSON.stringify(next));
  };

  const probe = useCallback(async (inst: Instance) => {
    setStates((s) => ({ ...s, [inst.id]: { ...s[inst.id], loading: true } }));
    const base = inst.url.replace(/\/+$/, "");
    const headers = { Authorization: `Bearer ${inst.key}` };
    try {
      const h = await fetch(`${base}/v1/health`, { signal: AbortSignal.timeout(10000) }).then((r) => r.json());
      let agents: number | undefined, revenueSats: number | undefined, solvent: boolean | null | undefined, ratio: number | null | undefined;
      try {
        const m = await fetch(`${base}/v1/metrics`, { headers, signal: AbortSignal.timeout(10000) }).then((r) => r.json());
        agents = m.total_agents; revenueSats = m.fee_revenue_total_sats; solvent = m.solvent ?? null; ratio = m.solvency_ratio ?? null;
      } catch { /* metrics may be admin-gated; health is enough to show reachable */ }
      setStates((s) => ({ ...s, [inst.id]: { loading: false, reachable: true, version: h.version, network: h.network, agents, revenueSats, solvent, solvencyRatio: ratio } }));
    } catch (e) {
      setStates((s) => ({ ...s, [inst.id]: { loading: false, reachable: false, error: e instanceof Error ? e.message : "unreachable" } }));
    }
  }, []);

  const probeAll = useCallback(() => { instances.forEach(probe); }, [instances, probe]);
  useEffect(() => { probeAll(); /* eslint-disable-next-line */ }, [instances]);

  function add(inst: Omit<Instance, "id">) {
    const id = "inst_" + Math.random().toString(36).slice(2, 9);
    persist([...instances, { ...inst, id }]);
    setModal(false);
  }
  function remove(id: string) {
    persist(instances.filter((i) => i.id !== id));
  }

  const totalRevenue = instances.reduce((sum, i) => sum + (states[i.id]?.revenueSats ?? 0), 0);
  const totalAgents = instances.reduce((sum, i) => sum + (states[i.id]?.agents ?? 0), 0);

  return (
    <>
      <div className="toolbar">
        <span className="t-muted" style={{ fontSize: 13 }}>
          <Server size={14} style={{ verticalAlign: "-2px", marginRight: 6 }} />
          {instances.length} instance{instances.length === 1 ? "" : "s"} · {fmtSats(totalRevenue)} sats revenue · {totalAgents} agents
        </span>
        <div style={{ flex: 1 }} />
        <button className="tb-btn" onClick={probeAll}><RefreshCw size={14} /> Refresh all</button>
        <button className="tb-btn gold" onClick={() => setModal(true)}><Plus size={14} /> Add instance</button>
      </div>

      <div className="table-wrap">
        <table className="data">
          <thead><tr><th>Instance</th><th>Version</th><th>Network</th><th className="right">Agents</th><th className="right">Revenue</th><th className="right">Solvency</th><th className="right">Action</th></tr></thead>
          <tbody>
            {instances.map((i) => {
              const st = states[i.id];
              return (
                <tr key={i.id}>
                  <td>
                    <div style={{ fontWeight: 500 }}>{i.name}</div>
                    <div className="t-muted t-mono" style={{ fontSize: 11 }}>{i.url}</div>
                  </td>
                  <td>
                    {st?.loading ? <span className="spinner" /> :
                      st?.reachable ? <span className="t-mono">{st.version}</span> :
                      <span className="st st-frozen">unreachable</span>}
                  </td>
                  <td className="t-mono">{st?.network ?? "—"}</td>
                  <td className="right t-mono">{st?.agents ?? "—"}</td>
                  <td className="right t-mono">{st?.revenueSats != null ? fmtSats(st.revenueSats) : "—"}</td>
                  <td className="right">
                    {st?.solvent == null ? <span className="t-muted">—</span> :
                      <span className={"st " + (st.solvent ? "st-live" : "st-frozen")}>
                        {st.solvencyRatio != null ? st.solvencyRatio.toFixed(1) + "×" : (st.solvent ? "ok" : "INSOLVENT")}
                      </span>}
                  </td>
                  <td className="right">
                    <button className="copy-btn" style={{ color: "var(--red)", borderColor: "rgba(239,68,68,0.3)" }} onClick={() => remove(i.id)}>
                      <Trash2 size={12} />
                    </button>
                  </td>
                </tr>
              );
            })}
            {instances.length === 0 && (
              <tr><td colSpan={7}><div className="empty">No instances yet. Add one to aggregate it here.</div></td></tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="t-muted" style={{ fontSize: 11.5, padding: "10px 2px 0", lineHeight: 1.5 }}>
        Instance URLs + keys are stored only in this browser’s localStorage and queried
        directly from here — there is no central Conduit server in the path, and no funds
        are ever held or moved. This is a read-only view of instances <b>you</b> operate.
      </p>

      {modal && <AddModal onClose={() => setModal(false)} onAdd={add} />}
    </>
  );
}

function AddModal({ onClose, onAdd }: { onClose: () => void; onAdd: (i: { name: string; url: string; key: string }) => void }) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3><Server size={18} /> Add a Conduit instance</h3>
        <div className="modal-sub">Aggregate one of your own instances (read-only). Stored in this browser only.</div>
        <div className="field" style={{ marginTop: 16 }}>
          <label>Name</label>
          <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="prod-eu" />
        </div>
        <div className="field">
          <label>API URL</label>
          <input className="mono" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://api.your-domain.com" />
        </div>
        <div className="field">
          <label>API key (read scope is enough)</label>
          <input className="mono" value={key} onChange={(e) => setKey(e.target.value)} placeholder="ck_live_…" />
        </div>
        <div className="modal-actions">
          <button className="tb-btn" onClick={onClose}><X size={14} /> Cancel</button>
          <button className="tb-btn gold" disabled={!name.trim() || !url.trim() || !key.trim()}
            onClick={() => onAdd({ name: name.trim(), url: url.trim(), key: key.trim() })}>
            Add instance
          </button>
        </div>
      </div>
    </div>
  );
}
