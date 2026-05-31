import type { Config } from "tailwindcss";

/**
 * Design tokens from the Conduit Console handoff (design_handoff_conduit_console).
 * The full component CSS lives in app/globals.css (ported from reference/src/ds.css
 * for pixel-fidelity); these theme extensions expose the same tokens to Tailwind
 * utilities (e.g. `bg-surface`, `text-text2`, `border-border`, `rounded-lg`).
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0A0E14",
        surface: "#111820",
        surface2: "#0E141C",
        border: "#1A2333",
        border2: "#232E40",
        sidebar: "#0D1117",
        gold: "#D4A843",
        goldSoft: "rgba(212,168,67,0.14)",
        goldLine: "rgba(212,168,67,0.30)",
        text1: "#E8E6E0",
        text2: "#6B7B8D",
        text3: "#4A5568",
        green: "#22C55E",
        greenSoft: "rgba(34,197,94,0.13)",
        red: "#EF4444",
        redSoft: "rgba(239,68,68,0.13)",
        amber: "#F59E0B",
        amberSoft: "rgba(245,158,11,0.13)",
        cyan: "#38BDF8",
        purple: "#A78BFA",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "Inter", "system-ui", "sans-serif"],
        mono: ["var(--font-jetbrains)", "JetBrains Mono", "ui-monospace", "monospace"],
      },
      borderRadius: {
        sm: "6px",
        md: "10px",
        lg: "14px",
      },
      maxWidth: {
        content: "1340px",
      },
      boxShadow: {
        card: "0 1px 0 rgba(255,255,255,0.02) inset, 0 8px 28px rgba(0,0,0,0.35)",
        modal: "0 24px 80px rgba(0,0,0,0.6)",
      },
    },
  },
  plugins: [],
};

export default config;
