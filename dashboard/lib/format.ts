/* Formatting + presentation helpers (mirrors the handoff's ds-data.jsx formatters). */

export function fmtSats(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  return n.toLocaleString("en-US");
}

export function fmtSatsFull(n: number): string {
  return n.toLocaleString("en-US");
}

export function fmtUsd(n: number): string {
  return (
    "$" +
    n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  );
}

export function fmtUsdCompact(n: number): string {
  if (n >= 1000) return "$" + n.toLocaleString("en-US", { maximumFractionDigits: 0 });
  return fmtUsd(n);
}

/** sats → BTC string with up to 4 decimals (treasury display). */
export function satsToBtc(sats: number): string {
  return (sats / 1e8).toLocaleString("en-US", {
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  });
}

export function satsToUsd(sats: number, btcPrice: number): number {
  return (sats / 1e8) * btcPrice;
}

const AV_COLORS = ["cyan", "purple", "gold", "amber", "green", "red"] as const;
export type AvColor = (typeof AV_COLORS)[number];

/** Deterministic avatar color from a string (stable per agent). */
export function avColor(seed: string): AvColor {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return AV_COLORS[h % AV_COLORS.length];
}

export function initials(name: string): string {
  const parts = name
    .replace(/[^a-zA-Z0-9 -]/g, "")
    .split(/[-\s]/)
    .filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase();
}

/** HH:MM:SS in local time (feeds + history). */
export function fmtTime(iso: string | Date): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
}

/** "Mon D, YYYY" (created dates). */
export function fmtDate(iso: string | Date): string {
  const d = typeof iso === "string" ? new Date(iso) : iso;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/** Relative "x min ago" (api-key last-used column). */
export function fmtRelative(iso: string | null): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  const sec = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (sec < 60) return sec <= 3 ? "just now" : `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} min ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} hr ago`;
  const day = Math.floor(hr / 24);
  return `${day} day${day === 1 ? "" : "s"} ago`;
}

/** mempool.space tx link, network-aware. Regtest has no public explorer → null. */
export function explorerTxUrl(network: string, txid: string | null): string | null {
  if (!txid) return null;
  if (network === "mainnet") return `https://mempool.space/tx/${txid}`;
  if (network === "testnet") return `https://mempool.space/testnet/tx/${txid}`;
  return null;
}

/** mempool.space address link, network-aware. Regtest → null. */
export function explorerAddrUrl(network: string, address: string): string | null {
  if (network === "mainnet") return `https://mempool.space/address/${address}`;
  if (network === "testnet") return `https://mempool.space/testnet/address/${address}`;
  return null;
}

/** Truncate a payment hash to "abcd1234…ef12". */
export function truncHash(h: string | null): string {
  if (!h) return "—";
  if (h.length <= 14) return h;
  return h.slice(0, 8) + "…" + h.slice(-4);
}

/** Map the API direction to the design's out/in classes + arrow. */
export function dirClass(d: TxDirectionLike): "out" | "in" {
  return d === "send" ? "out" : "in";
}
type TxDirectionLike = "send" | "receive";

/** Truncate a long hex pubkey to "02001bbe…c0c0"; pass node aliases through. */
export function truncPubkey(s: string): string {
  if (s.length >= 20 && /^[0-9a-fA-F]+$/.test(s)) return s.slice(0, 8) + "…" + s.slice(-4);
  return s;
}

/** Resolve a transaction's destination to a human label for the feed/history.
 *  send → external pubkey (truncated) or memo; receive → memo or "incoming". */
export function txDestination(t: { destination: string | null; memo: string | null; direction: string }): string {
  if (t.destination) return truncPubkey(t.destination);
  if (t.memo) return t.memo;
  return t.direction === "receive" ? "incoming" : "lightning";
}

/** Scope → pill color class. */
export function scopeColorClass(scope: string): string {
  switch (scope) {
    case "admin":
    case "full":
      return "scope-gold";
    case "write":
      return "scope-amber";
    case "read":
      return "scope-cyan";
    case "sandbox":
      return "scope-purple";
    default:
      return "scope-gold";
  }
}
