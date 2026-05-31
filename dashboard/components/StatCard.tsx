import type { ReactNode } from "react";

export function StatCard({
  label,
  value,
  unit,
  sub,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  sub: ReactNode;
}) {
  return (
    <div className="stat-card">
      <div className="label">{label}</div>
      <div className="value mono">
        {value}
        {unit && <span className="unit">{unit}</span>}
      </div>
      <div className="sub">{sub}</div>
    </div>
  );
}
