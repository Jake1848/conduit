"use client";

import {
  BookOpen,
  Boxes,
  ExternalLink,
  FileCode,
  Github,
  Plug,
  Rocket,
  Terminal,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

const REPO = "https://github.com/Jake1848/conduit";

interface DocLink {
  icon: LucideIcon;
  title: string;
  desc: string;
  href: string;
  cta: string;
}

const SECTIONS: { heading: string; links: DocLink[] }[] = [
  {
    heading: "Get started",
    links: [
      {
        icon: Github,
        title: "Repository",
        desc: "Source, issues, and the full README. MIT licensed — self-host it on your own LND node.",
        href: REPO,
        cta: "github.com/Jake1848/conduit",
      },
      {
        icon: Rocket,
        title: "Quickstart",
        desc: "Five-minute Docker bring-up (mock-LND for local dev, or wired to your own node) to a settled payment.",
        href: `${REPO}/blob/main/QUICKSTART.md`,
        cta: "QUICKSTART.md",
      },
      {
        icon: Terminal,
        title: "Agent demo",
        desc: "Watch an AI agent autonomously pay over Lightning via MCP — config + prompts, with an SDK fallback.",
        href: `${REPO}/blob/main/DEMO.md`,
        cta: "DEMO.md",
      },
    ],
  },
  {
    heading: "SDKs & integrations",
    links: [
      {
        icon: FileCode,
        title: "Python SDK",
        desc: "pip install conduit-lightning (import conduit). Agent + ConduitClient, policies, payments.",
        href: `${REPO}/blob/main/sdk-python/README.md`,
        cta: "sdk-python/README",
      },
      {
        icon: Boxes,
        title: "TypeScript SDK",
        desc: "npm install @conduit-btc/sdk. Same shape as the Python SDK, browser-friendly.",
        href: `${REPO}/blob/main/sdk-js/README.md`,
        cta: "sdk-js/README",
      },
      {
        icon: Plug,
        title: "MCP server",
        desc: "conduit-mcp — 8 stdio tools so any MCP agent (Claude Desktop, Cursor) can pay over Lightning.",
        href: `${REPO}/blob/main/mcp-server/README.md`,
        cta: "mcp-server/README",
      },
    ],
  },
  {
    heading: "Reference",
    links: [
      {
        icon: BookOpen,
        title: "API & operator guide",
        desc: "The core API endpoints, scopes, the policy engine, the platform-fee model, and treasury withdrawals.",
        href: `${REPO}/blob/main/core/README.md`,
        cta: "core/README",
      },
      {
        icon: FileCode,
        title: "Treasury guide",
        desc: "How to view revenue, check solvency, and withdraw accrued BTC safely from the console.",
        href: `${REPO}/blob/main/dashboard/TREASURY.md`,
        cta: "dashboard/TREASURY.md",
      },
    ],
  },
];

export default function DocsPage() {
  return (
    <>
      <div className="toolbar">
        <span className="t-muted" style={{ fontSize: 13 }}>
          Documentation lives in the repository — these open the latest on GitHub.
        </span>
        <div style={{ flex: 1 }} />
        <a className="tb-btn gold" href={REPO} target="_blank" rel="noopener noreferrer">
          <Github size={14} /> Open repo <ExternalLink size={13} />
        </a>
      </div>

      {SECTIONS.map((sec) => (
        <div key={sec.heading} style={{ marginTop: 18 }}>
          <h3 style={{ margin: "0 0 12px", fontSize: 13, letterSpacing: "0.04em" }}>
            {sec.heading}
          </h3>
          <div className="stat-grid">
            {sec.links.map((l) => (
              <a
                key={l.title}
                href={l.href}
                target="_blank"
                rel="noopener noreferrer"
                className="panel"
                style={{ padding: 18, textDecoration: "none", display: "block" }}
              >
                <div
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 8,
                    fontWeight: 600,
                    fontSize: 14,
                  }}
                >
                  <l.icon size={16} style={{ color: "var(--gold)" }} /> {l.title}
                </div>
                <p
                  className="t-muted"
                  style={{ fontSize: 12.5, lineHeight: 1.5, margin: "8px 0 12px" }}
                >
                  {l.desc}
                </p>
                <span
                  className="t-gold t-mono"
                  style={{ fontSize: 11.5, display: "inline-flex", alignItems: "center", gap: 4 }}
                >
                  {l.cta} <ExternalLink size={11} />
                </span>
              </a>
            ))}
          </div>
        </div>
      ))}
    </>
  );
}
