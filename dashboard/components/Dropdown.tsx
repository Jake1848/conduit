"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

export function Dropdown({
  label,
  value,
  options,
  onChange,
  maxValueChars,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
  maxValueChars?: number;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const display =
    maxValueChars && value.length > maxValueChars ? value.slice(0, maxValueChars) + "…" : value;

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="select" onClick={() => setOpen((o) => !o)} type="button">
        {label}: <b>{display}</b>{" "}
        <span className="chev">
          <ChevronDown size={12} />
        </span>
      </button>
      {open && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            left: 0,
            zIndex: 30,
            minWidth: "100%",
            maxHeight: 280,
            overflowY: "auto",
            background: "var(--surface)",
            border: "1px solid var(--border-2)",
            borderRadius: "var(--r-sm)",
            boxShadow: "var(--shadow)",
            padding: 4,
          }}
        >
          {options.map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => {
                onChange(opt);
                setOpen(false);
              }}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                padding: "7px 10px",
                borderRadius: 5,
                fontSize: 12.5,
                whiteSpace: "nowrap",
                color: opt === value ? "var(--gold)" : "var(--t1)",
                background: opt === value ? "var(--gold-soft)" : "transparent",
              }}
              onMouseEnter={(e) => {
                if (opt !== value) e.currentTarget.style.background = "rgba(255,255,255,0.04)";
              }}
              onMouseLeave={(e) => {
                if (opt !== value) e.currentTarget.style.background = "transparent";
              }}
            >
              {opt}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
