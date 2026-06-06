"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useAppData } from "@/lib/appdata";
import { useBtcPrice } from "@/lib/price";
import { useOverview } from "@/lib/useOverview";
import { roleFromName } from "@/lib/useTxCounts";
import { fmtSats, fmtTime, fmtUsd, satsToBtc, satsToUsd, txDestination } from "@/lib/format";
import type { TopAgent } from "@/lib/types";
import { StatCard } from "@/components/StatCard";
import { StatusBadge } from "@/components/StatusBadge";
import { Avatar } from "@/components/Avatar";
import { AreaChart } from "@/components/charts/AreaChart";
import { BarChart } from "@/components/charts/BarChart";

const kSats = (n: number) =>
  n >= 1_000_000 ? (n / 1_000_000).toFixed(1) + "M" : n >= 1000 ? (n / 1000).toFixed(1) + "K" : String(Math.round(n));

function seriesStats(arr: number[]) {
  const nz = arr.filter((x) => x > 0);
  return {
    max: arr.length ? Math.max(...arr) : 0,
    min: nz.length ? Math.min(...nz) : 0,
    avg: arr.length ? arr.reduce((s, x) => s + x, 0) / arr.length : 0,
    now: arr.length ? arr[arr.length - 1] : 0,
  };
}

export default function OverviewPage() {
  const { treasurySats: fleetTreasury, agents } = useAppData();
  const price = useBtcPrice();
  const { metrics, fees, feed, ready } = useOverview(agents);
  const [filter, setFilter] = useState<"ALL" | "LIVE" | "FROZEN">("ALL");

  // chart series from the server's 24h hourly buckets
  const area = metrics?.hourly.map((h) => h.volume_sats) ?? [];
  const bars = metrics?.hourly.map((h) => h.count) ?? [];
  const labels =
    metrics?.hourly.map((h, i) => (i % 4 === 0 ? String(new Date(h.hour).getHours()).padStart(2, "0") : "")) ?? [];
  const areaStat = seriesStats(area);
  const barStat = seriesStats(bars);

  const treasurySats = metrics?.treasury_sats ?? fleetTreasury;
  const treasuryUsd = satsToUsd(treasurySats, price);

  // ---- platform-fee revenue (operator earnings) ----
  // Total/today come from /v1/fees when available, else the metrics fallback.
  const feeTotalSats = fees?.total_collected_sats ?? metrics?.fee_revenue_total_sats ?? null;
  const feeTodaySats = fees?.today_sats ?? metrics?.fee_revenue_today_sats ?? null;
  // Daily fee chart: /v1/fees.fees_by_day is most-recent-first → reverse to chronological.
  const feeDays = useMemo(() => (fees ? [...fees.fees_by_day].reverse() : []), [fees]);
  const feeBars = feeDays.map((d) => d.sats);
  const feeLabels = feeDays.map((d) => {
    const dt = new Date(d.date + "T00:00:00");
    return String(dt.getMonth() + 1) + "/" + String(dt.getDate());
  });
  const feeStat = seriesStats(feeBars);
  const feeTotalUsd = feeTotalSats != null ? satsToUsd(feeTotalSats, price) : 0;

  const wallets: TopAgent[] = useMemo(() => {
    const list = metrics?.top_agents ?? [];
    const f = list.filter((a) => (filter === "ALL" ? true : filter === "LIVE" ? a.active : !a.active));
    return f.slice(0, 5);
  }, [metrics, filter]);

  return (
    <>
      {/* ---- stat cards ---- */}
      <div className="stat-grid">
        <StatCard
          label="Treasury Balance"
          value={metrics ? satsToBtc(treasurySats) : <span className="skel" />}
          unit={metrics ? "BTC" : undefined}
          sub={
            <>
              <span>≈ {fmtUsd(treasuryUsd)}</span>
              <span className="dot">·</span>
              <span className="up">live</span>
            </>
          }
        />
        <StatCard
          label="Active Agents"
          value={metrics ? metrics.active_agents.toLocaleString() : <span className="skel" />}
          sub={
            <>
              <span className="t-muted">of</span>
              <span>{(metrics?.total_agents ?? agents.length).toLocaleString()}</span>
              <span className="t-muted">total</span>
            </>
          }
        />
        <StatCard
          label="Tx / Minute"
          value={metrics ? metrics.tx_per_min.toLocaleString() : <span className="skel" />}
          sub={
            <>
              <span className="t-muted">rolling 60s</span>
            </>
          }
        />
        <StatCard
          label="Avg Settlement"
          value={metrics ? (metrics.avg_settlement_ms ?? "—") : <span className="skel" />}
          unit={metrics?.avg_settlement_ms != null ? "ms" : undefined}
          sub={
            <>
              <span className="t-muted">p99</span>
              <span className="t-gold">
                {metrics?.p99_settlement_ms != null ? metrics.p99_settlement_ms + "ms" : "—"}
              </span>
            </>
          }
        />
        <StatCard
          label="Fee Revenue"
          value={feeTotalSats != null ? fmtSats(feeTotalSats) : <span className="skel" />}
          unit={feeTotalSats != null ? "sats" : undefined}
          sub={
            <>
              <span>≈ {fmtUsd(feeTotalUsd)}</span>
              <span className="dot">·</span>
              <span className="t-gold">
                {feeTodaySats != null ? "+" + fmtSats(feeTodaySats) + " today" : "—"}
              </span>
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
          {metrics ? (
            <AreaChart data={area} labels={labels} />
          ) : (
            <div className="chart-box" style={{ display: "grid", placeItems: "center" }}>
              <span className="spinner" />
            </div>
          )}
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
          {metrics ? (
            <BarChart data={bars} labels={labels} />
          ) : (
            <div className="chart-box" style={{ display: "grid", placeItems: "center" }}>
              <span className="spinner" />
            </div>
          )}
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

      {/* ---- platform-fee revenue (operator earnings) ---- */}
      <div className="row-2">
        <div className="panel">
          <div className="panel-head">
            <h3>Fee Revenue</h3>
            <span className="sub">· platform fees / day</span>
            <div className="spacer" />
            <span className="badge-live">
              <span className="d" />
              SATS
            </span>
          </div>
          {fees ? (
            feeDays.length ? (
              <BarChart data={feeBars} labels={feeLabels} unit="sats" />
            ) : (
              <div className="chart-box" style={{ display: "grid", placeItems: "center" }}>
                <span className="empty">No platform fees collected yet.</span>
              </div>
            )
          ) : (
            <div className="chart-box" style={{ display: "grid", placeItems: "center" }}>
              <span className="spinner" />
            </div>
          )}
          <div className="chart-stats">
            <div className="chart-stat">
              <div className="l">Total</div>
              <div className="v">{feeTotalSats != null ? kSats(feeTotalSats) : "—"}</div>
            </div>
            <div className="chart-stat">
              <div className="l">Today</div>
              <div className="v">{feeTodaySats != null ? kSats(feeTodaySats) : "—"}</div>
            </div>
            <div className="chart-stat">
              <div className="l">Best Day</div>
              <div className="v">{fees ? kSats(feeStat.max) : "—"}</div>
            </div>
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <h3>Revenue Summary</h3>
            <span className="sub">· your earnings</span>
            <div className="spacer" />
          </div>
          <div className="agent-list" style={{ flex: 1, justifyContent: "center" }}>
            <div className="stat-card" style={{ boxShadow: "none" }}>
              <div className="label">Total Platform Fees</div>
              <div className="value mono">
                {feeTotalSats != null ? fmtSats(feeTotalSats) : <span className="skel" />}
                {feeTotalSats != null && <span className="unit">sats</span>}
              </div>
              <div className="sub">
                <span>≈ {fmtUsd(feeTotalUsd)}</span>
                {fees && (
                  <>
                    <span className="dot">·</span>
                    <span className="t-muted">{fees.total_collected_btc.toFixed(8)} BTC</span>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ---- wallets + live feed ---- */}
      <div className="row-2">
        <div className="panel">
          <div className="panel-head">
            <h3>Agent Wallets</h3>
            <span className="sub">· most active</span>
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
            {wallets.map((a) => (
              <Link className="agent-row" key={a.agent_id} href={`/wallets/${a.agent_id}`}>
                <Avatar name={a.name} />
                <div className="agent-meta">
                  <div className="nm">{a.name}</div>
                  <div className="scope">
                    <span className="tag">scope: {roleFromName(a.name)}</span> &nbsp;{" "}
                    {a.tx_today.toLocaleString()} tx today
                  </div>
                </div>
                <div className="agent-bal">
                  <div className="sats">{fmtSats(a.balance_sats)} sats</div>
                  <div className="usd">{fmtUsd(satsToUsd(a.balance_sats, price))}</div>
                </div>
                <StatusBadge s={a.active ? "live" : "frozen"} />
              </Link>
            ))}
            {!metrics && (
              <div className="loading-row">
                <span className="spinner" /> Loading agents…
              </div>
            )}
            {metrics && wallets.length === 0 && <div className="empty">No agents match this filter.</div>}
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
            {feed.map((t) => {
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
            {!ready && (
              <div className="loading-row">
                <span className="spinner" /> Subscribing to live feed…
              </div>
            )}
            {ready && feed.length === 0 && <div className="empty">No recent transactions.</div>}
          </div>
        </div>
      </div>
    </>
  );
}
