import { avColor, initials, type AvColor } from "@/lib/format";

export function Avatar({
  name,
  color,
  className = "",
}: {
  name: string;
  color?: AvColor;
  className?: string;
}) {
  const c = color || avColor(name);
  return <div className={`av av-${c} ${className}`.trim()}>{initials(name)}</div>;
}
