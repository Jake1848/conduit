"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useAppData } from "@/lib/appdata";
import { useBtcPrice } from "@/lib/price";
import { useOverview } from "@/lib/useOverview";
import { useTxCounts, roleFromName } from "@/lib/useTxCounts";
import {
  fmtSats,
  fmtTime,
  fmtUsd,
  satsToBtc,
  satsToUsd,
  txDestination,
} from "@/lib/format";
import { StatCard } from "@/components/StatCard";
import { StatusBadge } from "@/components/StatusBadge";
import { Avatar } from "@/components/Avatar";
import { AreaChart } from "@/components/charts/AreaChart";
import { BarChart } from "@/components/charts/BarChart";

const kSats = (n: number) => (n >= 1000 ? (n / 1000).toFixed(1) + "K" : String(Math.round(n)));

function seriesStats(arr: number[]) {
  const nz = arr.filter((x) => x > 0);
  const max = arr.length ? Math.max(...arr) : 0;
  const min = nz.length ? Math.min(...nz) : 0;
  const avg = arr.length ? arr.reduce((s, x) => s + x, 0) / arr.length : 0;
  const now = arr.length ? arr[arr.length - 1] : 0;
  return { max, min, avg, now };
}

export default function OverviewPage() {
  const { agents, treasurySats, activeCount, balancesReady, balances } = useAppData();
  const price = useBtcPrice();
  const ov = useOverview(agents);
  const [filter, setFilter] = useState<"ALL" | "LIVE" | "FROZEN">("ALL");

  const wallets = useMemo(() => {
    const f = agents.filter((a) =>
      filter === "ALL" ? true : filter === "LIVE" ? a.active : !a.active,
    );
    return f.slice(0, 5);
  }, [agents, filter]);

  const walletCounts = useTxCounts(wallets.map((a) => a.id));

  const treasuryUsd = satsToUsd(treasurySats, price);
  const areaStat = seriesStats(ov.area);
  const barStat = seriesStats(ov.bars);

  return (
    <>
      {/* ---- stat cards ---- */}
      <div className="stat-grid">
        <StatCard
          label="Treasury Balance"
          value={satsToBtc(treasurySats)}
          unit="BTC"
          sub={
            <>
              <span>≈ {fmtUsd(treasuryUsd)}</span>
              <span className="dot">·</span>
              {balancesReady ? (
                <span className="up">live</span>
              ) : (
                <span className="t-muted">summing…</span>
              )}
            </>
          }
        />
        <StatCard
          label="Active Agents"
          value={activeCount.toLocaleString()}
          sub={
            <>
              <span className="t-muted">of</span>
              <span>{agents.length.toLocaleString()}</span>
              <span className="t-muted">total</span>
            </>
          }
        />
        <StatCard
          label="Tx / Minute"
          value={ov.ready ? ov.txPerMin.toLocaleString() : <span className="skel" />}
          sub={
            <>
              <span className="t-muted">sampled live feed</span>
            </>
          }
        />
        <StatCard
          label="Avg Settlement"
          value={ov.avgSettlementMs != null ? ov.avgSettlementMs : ov.ready ? "—" : <span className="skel" />}
          unit={ov.avgSettlementMs != null ? "ms" : undefined}
          sub={
            <>
              <span className="t-muted">p99</span>
              <span className="t-gold">{ov.p99SettlementMs != null ? ov.p99SettlementMs + "ms" : "—"}</span>
            </>
          }
        />
      </div>

      {/* ---- charts ---- */}
      <div className="row-2">
        <div className="panel">
          <div className="panel-head">
            <h3>Routed Volume</h3>
            <span className="sub">· 24h</span>
            <div className="spacer" />
            <span className="badge-live">
              <span className="d" />
              LIVE
            </span>
          </div>
          <AreaChart data={ov.area} labels={ov.areaLabels} />
          <div className="chart-stats">
            <div className="chart-stat">
              <div className="l">High</div>
              <div className="v">{kSats(areaStat.max)}</div>
            </div>
            <div className="chart-stat">
              <div className="l">Low</div>
              <div className="v">{kSats(areaStat.min)}</div>
            </div>
            <div className="chart-stat">
              <div className="l">Avg</div>
              <div className="v">{kSats(areaStat.avg)}</div>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <h3>Hourly Throughput</h3>
            <span className="sub">· tx/h</span>
            <div className="spacer" />
            <span className="badge-live">
              <span className="d" />
              24h
            </span>
          </div>
          <BarChart data={ov.bars} labels={ov.barLabels} />
          <div className="chart-stats">
            <div className="chart-stat">
              <div className="l">Peak</div>
              <div className="v">{kSats(barStat.max)}</div>
            </div>
            <div className="chart-stat">
              <div className="l">Mean</div>
              <div className="v">{kSats(barStat.avg)}</div>
            </div>
            <div className="chart-stat">
              <div className="l">Now</div>
              <div className="v">{kSats(barStat.now)}</div>
            </div>
          </div>
        </div>
      </div>

      {/* ---- wallets + live feed ---- */}
      <div className="row-2">
        <div className="panel">
          <div className="panel-head">
            <h3>Agent Wallets</h3>
            <div className="spacer" />
            <div className="tabs">
              {(["ALL", "LIVE", "FROZEN"] as const).map((t) => (
                <button
                  key={t}
                  className={"tab" + (filter === t ? " active" : "")}
                  onClick={() => setFilter(t)}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
          <div className="agent-list">
            {wallets.map((a) => {
              const bal = balances[a.id];
              const tc = walletCounts[a.id];
              return (
                <Link className="agent-row" key={a.id} href={`/wallets/${a.id}`}>
                  <Avatar name={a.name} />
                  <div className="agent-meta">
                    <div className="nm">{a.name}</div>
                    <div className="scope">
                      <span className="tag">scope: {roleFromName(a.name)}</span> &nbsp;{" "}
                      {tc ? `${tc.count}${tc.hasMore ? "+" : ""} tx today` : "…"}
                    </div>
                  </div>
                  <div className="agent-bal">
                    <div className="sats">{bal ? fmtSats(bal.available_sats) + " sats" : <span className="skel" />}</div>
                    <div className="usd">{bal ? fmtUsd(satsToUsd(bal.available_sats, price)) : ""}</div>
                  </div>
                  <StatusBadge s={a.active ? "live" : "frozen"} />
                </Link>
              );
            })}
            {agents.length === 0 && <div className="empty">No agents in this fleet yet.</div>}
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <h3>Live Transactions</h3>
            <div className="spacer" />
            <span className="badge-stream">
              <span className="d" />
              STREAMING
            </span>
          </div>
          <div className="tx-feed">
            {ov.feed.map((t) => {
              const dir = t.direction === "send" ? "out" : "in";
              return (
                <div className={"tx-item" + (t.isNew ? " enter" : "")} key={t.id}>
                  <div className={"tx-dir " + dir}>{dir === "out" ? "→" : "←"}</div>
                  <div style={{ minWidth: 0 }}>
                    <div className="tx-route">
                      {t.agentName}
                      <span className="arrow">→</span>
                      <span className="dest">{txDestination(t)}</span>
                    </div>
                    <div className="tx-ts">{fmtTime(t.created_at)}</div>
                  </div>
                  <div className="tx-amt">{t.amount_sats.toLocaleString()} sats</div>
                  <div className="tx-lat">{t.latency_ms != null ? t.latency_ms + "ms" : "—"}</div>
                </div>
              );
            })}
            {!ov.ready && <div className="loading-row"><span className="spinner" /> Subscribing to live feed…</div>}
            {ov.ready && ov.feed.length === 0 && <div className="empty">No recent transactions.</div>}
          </div>
        </div>
      </div>
    </>
  );
}
