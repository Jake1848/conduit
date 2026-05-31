import type { LucideIcon } from "lucide-react";

export function Placeholder({
  title,
  description,
  icon: Icon,
}: {
  title: string;
  description: string;
  icon: LucideIcon;
}) {
  return (
    <div className="coming-soon">
      <div className="cs-inner">
        <div className="cs-ico">
          <Icon size={24} strokeWidth={1.7} />
        </div>
        <h2>{title}</h2>
        <p>{description}</p>
        <p className="t-mono" style={{ color: "var(--t3)", marginTop: 14, fontSize: 11.5, letterSpacing: "0.08em" }}>
          COMING SOON
        </p>
      </div>
    </div>
  );
}
