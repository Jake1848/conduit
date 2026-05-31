const LABELS: Record<string, string> = {
  live: "LIVE",
  settled: "SETTLED",
  pending: "PENDING",
  failed: "FAILED",
  frozen: "FROZEN",
  active: "ACTIVE",
  revoked: "REVOKED",
};

/** Status pill matching the design's `.st .st-{s}` classes. */
export function StatusBadge({ s }: { s: string }) {
  return (
    <span className={"st st-" + s}>
      <span className="d" />
      {LABELS[s] || s.toUpperCase()}
    </span>
  );
}
