"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import { api } from "@/lib/api";
import { useAppData } from "@/lib/appdata";
import { fmtDate, fmtTime, truncHash } from "@/lib/format";
import { Avatar } from "@/components/Avatar";
import type { Decision, DecisionOutcome, Threshold } from "@/lib/types";

const PAGE_SIZE = 24;
const FEED_LIMIT = 200; // newest decisions across the fleet, in ONE call
const NEAR_MISS_PCT = 25; // a positive margin tighter than this is flagged as a near-miss

type OutcomeFilter = DecisionOutcome | "all";

const OUTCOMES: { label: string; value: OutcomeFilter }[] = [
  { label: "All", value: "all" },
  { label: "Settled", value: "settled" },
  { label: "Failed", value: "failed" },
  { label: "Rejected", value: "rejected" },
];

const RULE_LABELS: Record<string, string> = {
  per_transaction: "Per-transaction",
  hourly: "Hourly",
  daily: "Daily",
  rate: "Rate",
  balance: "Balance",
};

function ruleLabel(rule: string | null): string {
  if (!rule) return "—";
  return RULE_LABELS[rule] || rule;
}

/** Percent with at most one decimal, never a trailing ".0". */
function fmtPct(n: number): string {
  const r = Math.round(Math.abs(n) * 10) / 10;
  return (Number.isInteger(r) ? r.toString() : r.toFixed(1)) + "%";
}

/** Amount rendered in the threshold's own unit (sats vs a payment count). */
function withUnit(n: number, t: Threshold): string {
  if (t.unit === "sats") return `${n.toLocaleString()} sats`;
  return `${n.toLocaleString()} ${Math.abs(n) === 1 ? "payment" : "payments"}`;
}

// Three tones: a violation (red), a near-miss-that-passed (amber — the headline),
// and a comfortable pass (green). Reuses the design-system color vars only.
type Tone = "violated" | "near" | "clear";
const TONE_COLOR: Record<Tone, string> = {
  violated: "var(--red)",
  near: "var(--amber)",
  clear: "var(--green)",
};
const TONE_BG: Record<Tone, string> = {
  violated: "var(--red-soft)",
  near: "var(--amber-soft)",
  clear: "var(--green-soft)",
};

function toneOf(t: Threshold): Tone {
  if (t.violated) return "violated";
  if (t.margin_pct < NEAR_MISS_PCT) return "near";
  return "clear";
}

/** Plain-language verdict for one limit. */
function marginPhrase(t: Threshold): string {
  if (t.violated) {
    const over = Math.abs(t.margin_abs);
    return `BLOCKED — ${withUnit(over, t)} over the ${withUnit(t.limit, t)} cap`;
  }
  return `passed with ${withUnit(t.margin_abs, t)} of headroom (${fmtPct(t.margin_pct)} of cap)`;
}

/** How full the window is: (current + attempted) / limit, clamped to 0–100%. */
function fillPct(t: Threshold): number {
  if (t.limit <= 0) return t.violated ? 100 : 0;
  return Math.max(0, Math.min(100, ((t.current + t.attempted) / t.limit) * 100));
}

/** The headline limit for a decision: the binding (tightest) rule, else the
 *  smallest margin across thresholds. */
function headline(d: Decision): Threshold | null {
  if (d.thresholds.length === 0) return null;
  if (d.binding_rule) {
    const b = d.thresholds.find((t) => t.rule === d.binding_rule);
    if (b) return b;
  }
  return d.thresholds.reduce((a, b) => (b.margin_pct < a.margin_pct ? b : a));
}

function shortDest(dest: string | null): string {
  if (!dest) return "—";
  if (dest.length <= 22) return dest;
  return dest.slice(0, 12) + "…" + dest.slice(-6);
}

/** Outcome pill. settled = green, failed = red, rejected (a guardrail catch) =
 *  amber — reuses the existing .st / .st-* classes. */
function OutcomeBadge({ outcome }: { outcome: DecisionOutcome }) {
  const cls =
    outcome === "settled" ? "st-settled" : outcome === "failed" ? "st-failed" : "st-pending";
  return (
    <span className={"st " + cls}>
      <span className="d" />
      {outcome.toUpperCase()}
    </span>
  );
}

/** Compact margin chip for a feed row. */
function MarginChip({ t }: { t: Threshold }) {
  const tone = toneOf(t);
  const text = t.violated
    ? `−${Math.abs(t.margin_abs).toLocaleString()}`
    : `+${t.margin_abs.toLocaleString()} · ${fmtPct(t.margin_pct)}`;
  return (
    <span
      style={{
        fontFamily: "var(--f-mono)",
        fontSize: 11,
        letterSpacing: "0.04em",
        padding: "3px 9px",
        borderRadius: 999,
        whiteSpace: "nowrap",
        color: TONE_COLOR[tone],
        background: TONE_BG[tone],
      }}
    >
      {text}
    </span>
  );
}

export default function DecisionsPage() {
  const { agents } = useAppData();
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [loading, setLoading] = useState(true);
  const [outcome, setOutcome] = useState<OutcomeFilter>("all");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Decision | null>(null);

  const nameById = useMemo(() => new Map(agents.map((a) => [a.id, a.name])), [agents]);
  const nameFor = (id: string) => nameById.get(id) || id;

  // Fleet feed via /v1/decisions/recent, refreshed on a 15s poll. The outcome
  // filter is applied server-side so a rejected attempt can't be windowed out.
  useEffect(() => {
    let cancelled = false;
    const ctrl = new AbortController();
    setLoading(true);
    async function load() {
      try {
        const r = await api.getDecisions(
          { outcome: outcome === "all" ? undefined : outcome, limit: FEED_LIMIT },
          ctrl.signal,
        );
        if (!cancelled) {
          setDecisions(r.data);
          setLoading(false);
        }
      } catch (e) {
        if ((e as Error)?.name === "AbortError") return;
        if (!cancelled) setLoading(false);
      }
    }
    load();
    const t = setInterval(load, 15_000);
    return () => {
      cancelled = true;
      clearInterval(t);
      ctrl.abort();
    };
  }, [outcome]);

  const pageCount = Math.max(1, Math.ceil(decisions.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const pageRows = decisions.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);

  return (
    <>
      <div className="toolbar">
        <div className="tabs">
          {OUTCOMES.map((o) => (
            <button
              key={o.value}
              className={"tab" + (outcome === o.value ? " active" : "")}
              onClick={() => {
                setOutcome(o.value);
                setPage(0);
              }}
            >
              {o.label}
            </button>
          ))}
        </div>
        <span className="t-muted" style={{ fontSize: 12.5, alignSelf: "center", paddingLeft: 2 }}>
          Newest first · the margin is the headroom that was left to each limit
        </span>
        <div style={{ flex: 1 }} />
        <span className="badge-stream">
          <span className="d" /> LIVE
        </span>
      </div>

      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Time</th>
              <th>Agent</th>
              <th>Outcome</th>
              <th className="right">Requested</th>
              <th>Destination</th>
              <th>Binding limit</th>
              <th className="right">Margin</th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((d) => {
              const h = headline(d);
              return (
                <tr key={d.id} className="clickable" onClick={() => setSelected(d)}>
                  <td className="t-mono t-muted" style={{ fontSize: 12 }}>
                    {fmtTime(d.created_at)}
                  </td>
                  <td>
                    <div className="cell-agent">
                      <Avatar name={nameFor(d.agent_id)} />
                      <span className="nm">{nameFor(d.agent_id)}</span>
                    </div>
                  </td>
                  <td>
                    <OutcomeBadge outcome={d.outcome} />
                  </td>
                  <td className="right t-mono t-gold">{d.requested_sats.toLocaleString()}</td>
                  <td className="t-mono" style={{ fontSize: 12 }}>
                    {shortDest(d.destination)}
                  </td>
                  <td className="t-mono t-muted" style={{ fontSize: 12 }}>
                    {ruleLabel(d.binding_rule)}
                  </td>
                  <td className="right">{h ? <MarginChip t={h} /> : <span className="t-muted">—</span>}</td>
                </tr>
              );
            })}
            {loading && decisions.length === 0 && (
              <tr>
                <td colSpan={7}>
                  <div className="loading-row">
                    <span className="spinner" /> Loading decisions across the fleet…
                  </div>
                </td>
              </tr>
            )}
            {!loading && decisions.length === 0 && (
              <tr>
                <td colSpan={7}>
                  <div className="empty">No decisions recorded for this filter yet.</div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
        <div className="table-foot">
          <span>
            Showing {pageRows.length} of {decisions.length}
            {decisions.length >= FEED_LIMIT ? `+ (most recent ${FEED_LIMIT})` : ""} decisions
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
            <button
              onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
              disabled={safePage >= pageCount - 1}
            >
              ›
            </button>
          </div>
        </div>
      </div>

      {selected && (
        <DecisionDetail
          decision={selected}
          agentName={nameFor(selected.agent_id)}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}

function KV({ label, value, mono = true }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div>
      <div
        style={{
          fontSize: 10.5,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--t2)",
          fontWeight: 600,
          marginBottom: 5,
        }}
      >
        {label}
      </div>
      <div
        className={mono ? "t-mono" : ""}
        style={{ fontSize: 13, color: "var(--t1)", wordBreak: "break-all" }}
      >
        {value}
      </div>
    </div>
  );
}

function ThresholdCard({ t, binding }: { t: Threshold; binding: boolean }) {
  const tone = toneOf(t);
  const color = TONE_COLOR[tone];
  return (
    <div
      style={{
        background: "var(--surface-2)",
        border: "1px solid var(--border)",
        borderLeft: `3px solid ${color}`,
        borderRadius: "var(--r-sm)",
        padding: "12px 14px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 9 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{ruleLabel(t.rule)}</span>
        {binding && (
          <span
            style={{
              fontFamily: "var(--f-mono)",
              fontSize: 9.5,
              letterSpacing: "0.06em",
              color: "var(--gold)",
              background: "var(--gold-soft)",
              border: "1px solid var(--gold-line)",
              padding: "1px 6px",
              borderRadius: 999,
            }}
          >
            BINDING
          </span>
        )}
        <div style={{ flex: 1 }} />
        <span
          style={{
            fontFamily: "var(--f-mono)",
            fontSize: 12,
            fontWeight: 600,
            color,
            textAlign: "right",
          }}
        >
          {marginPhrase(t)}
        </span>
      </div>
      <div className="progress">
        <span style={{ width: `${fillPct(t)}%`, background: color }} />
      </div>
      <div
        className="t-mono t-muted"
        style={{ fontSize: 11, marginTop: 8, display: "flex", gap: 14, flexWrap: "wrap" }}
      >
        <span>cap {withUnit(t.limit, t)}</span>
        <span>already used {withUnit(t.current, t)}</span>
        <span>this payment {withUnit(t.attempted, t)}</span>
      </div>
    </div>
  );
}

function DecisionDetail({
  decision: d,
  agentName,
  onClose,
}: {
  decision: Decision;
  agentName: string;
  onClose: () => void;
}) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 680, maxHeight: "88vh", overflowY: "auto" }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <OutcomeBadge outcome={d.outcome} />
          <h3 style={{ fontSize: 17 }}>Decision</h3>
          <div style={{ flex: 1 }} />
          <button className="copy-btn" onClick={onClose} aria-label="Close">
            <X size={14} />
          </button>
        </div>
        <div className="modal-sub">
          <span className="t-mono">{d.id}</span> · {agentName} · {fmtDate(d.created_at)}{" "}
          {fmtTime(d.created_at)}
          {d.reason_code ? (
            <>
              {" "}
              · <span style={{ color: "var(--amber)" }}>{d.reason_code}</span>
            </>
          ) : null}
        </div>

        <div className="section-title">Margin to each limit</div>
        {d.thresholds.length > 0 ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {d.thresholds.map((t, i) => (
              <ThresholdCard key={`${t.rule}-${i}`} t={t} binding={t.rule === d.binding_rule} />
            ))}
          </div>
        ) : (
          <div className="empty" style={{ padding: 24 }}>
            No quantitative limits were evaluated for this attempt.
          </div>
        )}

        <div className="section-title">Decision detail</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <KV label="Requested" value={`${d.requested_sats.toLocaleString()} sats`} />
          <KV
            label="Balance at decision"
            value={
              d.balance_at_decision_sats == null
                ? "—"
                : `${d.balance_at_decision_sats.toLocaleString()} sats`
            }
          />
          <KV
            label="Destination"
            value={
              <>
                {shortDest(d.destination)}
                {d.destination_kind ? (
                  <span className="t-muted" style={{ marginLeft: 6 }}>
                    ({d.destination_kind})
                  </span>
                ) : null}
              </>
            }
          />
          <KV
            label="Allowlist"
            value={
              <span style={{ color: allowlistColor(d.allowlist_status) }}>
                {d.allowlist_status ?? "—"}
              </span>
            }
          />
          <KV label="Caller" value={d.caller_tag ?? "—"} mono={!!d.caller_tag} />
          <KV label="API key" value={d.api_key_id ?? "—"} />
          <KV
            label="Binding limit"
            value={
              d.binding_rule
                ? `${ruleLabel(d.binding_rule)}${
                    d.min_margin_pct == null ? "" : ` · ${fmtPct(d.min_margin_pct)}`
                  }`
                : "—"
            }
          />
          <KV label="Transaction" value={d.tx_id ? truncHash(d.tx_id) : "—"} />
        </div>

        <div className="section-title">Applied policy</div>
        {d.policy_snapshot ? (
          <pre
            style={{
              background: "var(--surface-2)",
              border: "1px solid var(--border)",
              borderRadius: "var(--r-sm)",
              padding: 14,
              fontFamily: "var(--f-mono)",
              fontSize: 12,
              lineHeight: 1.6,
              color: "var(--t1)",
              overflowX: "auto",
              margin: 0,
            }}
          >
            {JSON.stringify(d.policy_snapshot, null, 2)}
          </pre>
        ) : (
          <div className="t-muted" style={{ fontSize: 13 }}>
            No policy applied — this agent had no spending limits set.
          </div>
        )}
        {d.policy_hash && (
          <div className="t-mono t-muted" style={{ fontSize: 11, marginTop: 8 }}>
            policy_hash {truncHash(d.policy_hash)}
          </div>
        )}
      </div>
    </div>
  );
}

function allowlistColor(status: string | null): string {
  switch (status) {
    case "blocklisted":
    case "not_allowlisted":
      return "var(--red)";
    case "allowed":
      return "var(--green)";
    default:
      return "var(--t1)";
  }
}
