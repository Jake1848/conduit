"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Box,
  ExternalLink,
  FileText,
  KeyRound,
  Landmark,
  LayoutGrid,
  LogOut,
  ScrollText,
  Share2,
  ShieldCheck,
  Wallet,
  Webhook,
  type LucideIcon,
} from "lucide-react";
import { useAuth } from "@/lib/auth";
import { useAppData } from "@/lib/appdata";

interface NavItem {
  id: string;
  label: string;
  href: string;
  icon: LucideIcon;
  badge?: string;
  ext?: boolean;
  adminOnly?: boolean;
}

export function Sidebar() {
  const pathname = usePathname();
  const { apiKey, tier, network, disconnect } = useAuth();
  const { agents } = useAppData();

  const agentCount = agents.length ? agents.length.toLocaleString() : undefined;

  const workspace: NavItem[] = [
    { id: "overview", label: "Overview", href: "/", icon: LayoutGrid },
    { id: "wallets", label: "Wallets", href: "/wallets", icon: Wallet, badge: agentCount },
    { id: "treasury", label: "Treasury", href: "/treasury", icon: Landmark, adminOnly: true },
    { id: "policies", label: "Policies", href: "/policies", icon: ShieldCheck },
    { id: "network", label: "Network", href: "/network", icon: Share2 },
    { id: "audit", label: "Audit Log", href: "/audit", icon: ScrollText },
    { id: "webhooks", label: "Webhooks", href: "/webhooks", icon: Webhook },
  ];
  const developer: NavItem[] = [
    { id: "keys", label: "API Keys", href: "/keys", icon: KeyRound, adminOnly: true },
    { id: "sandbox", label: "Sandbox", href: "/sandbox", icon: Box },
    { id: "docs", label: "Docs", href: "/docs", icon: FileText },
  ];

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(href + "/");

  const masked = apiKey
    ? apiKey.length > 18
      ? apiKey.slice(0, 14) + "…"
      : apiKey
    : "—";

  const renderItem = (n: NavItem) => {
    if (n.adminOnly && tier !== "admin") return null;
    return (
      <Link key={n.id} href={n.href} className={"sb-item" + (isActive(n.href) ? " active" : "")}>
        <span className="sb-ico">
          <n.icon size={16} strokeWidth={1.7} />
        </span>
        <span className="label">{n.label}</span>
        {n.badge && <span className="badge">{n.badge}</span>}
        {n.ext && (
          <span className="sb-ext">
            <ExternalLink size={12} strokeWidth={1.7} />
          </span>
        )}
      </Link>
    );
  };

  return (
    <aside className="sidebar">
      <div className="sb-brand">
        <div className="sb-logo" />
        <span className="wm">CONDUIT</span>
      </div>
      <div className="sb-breadcrumb">
        conduit.energy / console / <b>agent-fleet-prod</b>
      </div>
      <nav className="sb-nav">
        <div className="sb-section">
          <div className="sb-section-h">Workspace</div>
          {workspace.map(renderItem)}
        </div>
        <div className="sb-section">
          <div className="sb-section-h">Developer</div>
          {developer.map(renderItem)}
        </div>
      </nav>
      <div className="sb-user">
        <div className="sb-avatar">{tier === "admin" ? "AD" : "MB"}</div>
        <div style={{ minWidth: 0 }}>
          <div className="nm" style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {masked}
          </div>
          <div className="role">
            {tier} · {network || "—"}
          </div>
        </div>
        <button className="sb-disconnect" title="Disconnect" onClick={disconnect}>
          <LogOut size={15} strokeWidth={1.7} />
        </button>
      </div>
    </aside>
  );
}
