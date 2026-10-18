"use client";

import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import type { ApiRecord } from "@/lib/types/api";

type Props = {
  rows: ApiRecord[];
};

export function MetricChart({ rows }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    const names = rows.map((row, index) => String(row.entity_name || row.campaign_name || row.name || `Item ${index + 1}`)).slice(0, 8);
    const spends = rows
      .map((row) => {
        const metrics = typeof row.metrics === "object" && row.metrics !== null ? (row.metrics as ApiRecord) : {};
        return Number(row.spend || metrics.spend || 0);
      })
      .slice(0, 8);
    chart.setOption({
      grid: { left: 36, right: 14, top: 24, bottom: 42 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: names, axisLabel: { interval: 0, rotate: 28, fontSize: 10 } },
      yAxis: { type: "value" },
      series: [{ type: "bar", data: spends, itemStyle: { color: "#0f766e", borderRadius: [4, 4, 0, 0] } }],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [rows]);

  return <div ref={ref} className="h-64 w-full" />;
}
