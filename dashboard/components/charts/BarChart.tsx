"use client";

import { useEffect, useRef } from "react";
import { Chart, registerables, type Chart as ChartType } from "chart.js";

Chart.register(...registerables);

/** Gold bar chart matching the handoff — last 5 bars solid, the rest at 0.32 alpha. */
export function BarChart({
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

    chartRef.current = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            data,
            backgroundColor: data.map((_, i) =>
              i >= data.length - 5 ? "#D4A843" : "rgba(212,168,67,0.32)",
            ),
            borderRadius: 3,
            borderSkipped: false,
            barPercentage: 0.74,
            categoryPercentage: 0.82,
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
            callbacks: { title: () => "", label: (c) => (c.parsed.y ?? 0).toLocaleString() + " tx/h" },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: "#4A5568", font: { family: "JetBrains Mono", size: 10 } },
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
