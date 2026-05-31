"use client";

import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useAppData } from "@/lib/appdata";
import { useToast } from "@/lib/toast";
import { downloadCsv } from "@/lib/csv";
import { fmtDate } from "@/lib/format";

const META: Record<string, { title: string; sub: string }> = {
  "/": { title: "Overview", sub: "Real-time fleet metrics" },
  "/wallets": { title: "Wallets", sub: "Agent wallet directory" },
  "/audit": { title: "Audit Log", sub: "Signed transaction record · all agents" },
  "/keys": { title: "API Keys", sub: "Programmatic access credentials" },
  "/policies": { title: "Policies", sub: "Spending rule sets" },
  "/network": { title: "Network", sub: "Lightning routing topology" },
  "/webhooks": { title: "Webhooks", sub: "Event subscriptions" },
  "/sandbox": { title: "Sandbox", sub: "Test environment" },
  "/docs": { title: "Docs", sub: "Developer documentation" },
};

function metaFor(pathname: string): { title: string; sub: string } {
  if (pathname.startsWith("/wallets/")) return { title: "Agent Detail", sub: "Wallet · policy · history" };
  return META[pathname] || META["/"];
}

export function Topbar() {
  const pathname = usePathname();
  const { network } = useAuth();
  const { agents, balances } = useAppData();
  const toast = useToast();
  const meta = metaFor(pathname);

  function exportAgents() {
    const rows = agents.map((a) => [
      a.name,
      a.id,
      a.active ? "live" : "frozen",
      balances[a.id]?.available_sats ?? "",
      fmtDate(a.created_at),
    ]);
    downloadCsv("conduit-agents.csv", ["name", "id", "status", "available_sats", "created"], rows);
    toast.ok(`Exported ${rows.length} agents`);
  }

  function share() {
    if (typeof window !== "undefined") {
      navigator.clipboard?.writeText(window.location.href);
      toast.ok("Link copied to clipboard");
    }
  }

  return (
    <header className="topbar">
      <div>
        <div className="tb-title">{meta.title}</div>
        <div className="tb-sub">{meta.sub}</div>
      </div>
      <div className="spacer" />
      <span className="pill-mainnet">
        <span className="d" />
        {network || "—"}
      </span>
      {pathname === "/" && (
        <>
          <button className="tb-btn" onClick={share}>
            Share
          </button>
          <button className="tb-btn gold" onClick={exportAgents}>
            Export
          </button>
        </>
      )}
    </header>
  );
}
