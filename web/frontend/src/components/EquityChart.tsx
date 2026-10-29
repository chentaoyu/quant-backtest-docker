import ReactECharts from "echarts-for-react";
import { useMemo } from "react";
import type { EChartsOption } from "echarts";
import type { EquityPoint } from "../types";

interface Props {
  data: EquityPoint[];
}

export default function EquityChart({ data }: Props) {
  const option = useMemo<EChartsOption>(() => {
    const dates = data.map((item) => item.t);
    const equity = data.map((item) => item.e);
    const drawdown = data.map((item) => item.dd);
    const base = equity[0] ?? 1;
    const minDd = Math.min(...drawdown, -1);

    return {
      animation: false,
      backgroundColor: "transparent",
      grid: [
        { left: 62, right: 22, top: 26, height: "48%" },
        { left: 62, right: 22, top: "68%", height: "16%" },
      ],
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross", link: [{ xAxisIndex: "all" }] },
        backgroundColor: "rgba(15, 23, 42, 0.94)",
        borderWidth: 0,
        padding: [8, 11],
        textStyle: { color: "#e2e8f0", fontSize: 12 },
        formatter: (params: any) => {
          const list = Array.isArray(params) ? params : [params];
          const index = list[0]?.dataIndex ?? 0;
          const point = data[index];
          if (!point) return "";
          const change = (point.e / base - 1) * 100;
          const color = change >= 0 ? "#4ade80" : "#f87171";
          return [
            `<div style="font-weight:600;margin-bottom:5px">${point.t}</div>`,
            `<div>净值 <b>¥${point.e.toLocaleString("zh-CN", { maximumFractionDigits: 0 })}</b></div>`,
            `<div>累计收益 <b style="color:${color}">${change >= 0 ? "+" : ""}${change.toFixed(2)}%</b></div>`,
            `<div>回撤 <b style="color:#fca5a5">${point.dd.toFixed(2)}%</b></div>`,
          ].join("");
        },
      },
      axisPointer: {
        link: [{ xAxisIndex: "all" }],
        label: { backgroundColor: "#334155" },
      },
      xAxis: [
        {
          type: "category",
          data: dates,
          boundaryGap: false,
          axisLine: { lineStyle: { color: "#dbe3ee" } },
          axisTick: { show: false },
          axisLabel: { show: false },
        },
        {
          type: "category",
          data: dates,
          boundaryGap: false,
          gridIndex: 1,
          axisLine: { lineStyle: { color: "#dbe3ee" } },
          axisTick: { show: false },
          axisLabel: {
            color: "#94a3b8",
            fontSize: 10.5,
            formatter: (value: string) => value.slice(0, 7),
          },
        },
      ],
      yAxis: [
        {
          type: "value",
          scale: true,
          splitLine: { lineStyle: { color: "#eef2f7" } },
          axisLabel: {
            color: "#94a3b8",
            fontSize: 10.5,
            formatter: (value: number) => {
              if (Math.abs(value) >= 1e8) return `${(value / 1e8).toFixed(1)}亿`;
              if (Math.abs(value) >= 1e4) return `${(value / 1e4).toFixed(0)}万`;
              return value.toFixed(0);
            },
          },
        },
        {
          type: "value",
          gridIndex: 1,
          max: 0,
          min: minDd * 1.15,
          splitLine: { show: false },
          axisLabel: {
            color: "#cbd5e1",
            fontSize: 10,
            formatter: (value: number) => `${value.toFixed(0)}%`,
          },
        },
      ],
      dataZoom: [{ type: "inside", xAxisIndex: [0, 1], start: 0, end: 100 }],
      series: [
        {
          name: "策略净值",
          type: "line",
          data: equity,
          showSymbol: false,
          lineStyle: { width: 2, color: "#2563eb" },
          areaStyle: { color: "rgba(37, 99, 235, 0.10)" },
          emphasis: { focus: "series" },
          markLine: {
            silent: true,
            symbol: "none",
            label: { show: false },
            lineStyle: { type: "dashed", color: "#94a3b8", width: 1 },
            data: [{ yAxis: base }],
          },
        },
        {
          name: "回撤",
          type: "line",
          data: drawdown,
          xAxisIndex: 1,
          yAxisIndex: 1,
          showSymbol: false,
          lineStyle: { width: 1.2, color: "#ef4444" },
          areaStyle: { color: "rgba(239, 68, 68, 0.18)" },
        },
      ],
    };
  }, [data]);

  return <ReactECharts option={option} className="chart-box" notMerge lazyUpdate />;
}
