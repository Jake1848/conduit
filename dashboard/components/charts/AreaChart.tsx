"use client";

import { useEffect, useRef } from "react";
import { Chart, registerables, type Chart as ChartType } from "chart.js";

Chart.register(...registerables);

/** Gold area chart matching the handoff (line #D4A843, gradient fill, tension 0.4). */
export function AreaChart({
  data,
  labels,
  height = 200,
}: {
  data: number[];
  labels: string[];
  height?: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const chartRef = useRef<ChartType | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const ctx = ref.current.getContext("2d");
    if (!ctx) return;
    const grad = ctx.createLinearGradient(0, 0, 0, height);
    grad.addColorStop(0, "rgba(212,168,67,0.32)");
    grad.addColorStop(1, "rgba(212,168,67,0)");

    chartRef.current = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            data,
            borderColor: "#D4A843",
            borderWidth: 2,
            backgroundColor: grad,
            fill: true,
            tension: 0.4,
            pointRadius: 0,
            pointHoverRadius: 4,
            pointHoverBackgroundColor: "#D4A843",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "#111820",
            borderColor: "#1A2333",
            borderWidth: 1,
            titleColor: "#6B7B8D",
            bodyColor: "#E8E6E0",
            bodyFont: { family: "JetBrains Mono" },
            padding: 10,
            displayColors: false,
            callbacks: { title: () => "", label: (c) => (c.parsed.y ?? 0).toLocaleString() + " sats" },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              color: "#4A5568",
              font: { family: "JetBrains Mono", size: 10 },
              maxRotation: 0,
              autoSkip: false,
              callback: function (v) {
                const l = (this as { getLabelForValue: (x: number) => string }).getLabelForValue(
                  v as number,
                );
                return l || null;
              },
            },
            border: { display: false },
          },
          y: {
            grid: { color: "#1A2333" },
            ticks: {
              color: "#4A5568",
              font: { family: "JetBrains Mono", size: 10 },
              maxTicksLimit: 4,
              callback: (v) => {
                const n = Number(v);
                if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
                return n >= 1000 ? (n / 1000).toFixed(0) + "K" : n;
              },
            },
            border: { display: false },
          },
        },
        animation: false,
      },
    });
    return () => {
      chartRef.current?.destroy();
    };
  }, [data, labels, height]);

  return (
    <div className="chart-box" style={{ height }}>
      <canvas ref={ref} />
    </div>
  );
}
