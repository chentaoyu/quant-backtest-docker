import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts";
import { useMemo } from "react";
import type { KlineBar, SignalTrade } from "../types";

const UP = "#dc2626";
const DOWN = "#16a34a";
const MAS = [
  { n: 5, color: "#f59e0b" },
  { n: 10, color: "#3b82f6" },
  { n: 20, color: "#a855f7" },
  { n: 60, color: "#64748b" },
];

export interface PriceLine {
  label: string;
  price: number;
  color: string;
}

interface Props {
  bars: KlineBar[];
  trades?: SignalTrade[];
  lines?: PriceLine[];
  height?: number;
  visibleBars?: number;
}

function movingAverage(bars: KlineBar[], n: number): (number | null)[] {
  let sum = 0;
  return bars.map((bar, i) => {
    sum += bar[2];
    if (i >= n) sum -= bars[i - n][2];
    return i >= n - 1 ? Number((sum / n).toFixed(3)) : null;
  });
}

export default function KlineChart({ bars, trades = [], lines = [], height = 460, visibleBars = 120 }: Props) {
  const option = useMemo<EChartsOption>(() => {
    const dates = bars.map((b) => b[0]);
    const inRange = new Set(dates);
    const start = Math.max(0, 100 - (visibleBars / Math.max(bars.length, 1)) * 100);

    const marks = trades.flatMap((t) => {
      const points = [];
      if (inRange.has(t.entry_date)) {
        points.push({ name: "买", coord: [t.entry_date, t.entry_price], value: "买", itemStyle: { color: UP } });
      }
      if (t.exit_date && t.exit_price !== null && inRange.has(t.exit_date)) {
        points.push({
          name: "卖",
          coord: [t.exit_date, t.exit_price],
          value: "卖",
          symbolRotate: 180,
          label: { offset: [0, 6] },
          itemStyle: { color: DOWN },
        });
      }
      return points;
    });

    return {
      animation: false,
      legend: { top: 0, left: 8, itemWidth: 14, textStyle: { fontSize: 11 }, data: MAS.map((m) => `MA${m.n}`) },
      grid: [
        { left: 56, right: 70, top: 28, height: "62%" },
        { left: 56, right: 70, top: "78%", height: "13%" },
      ],
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross", link: [{ xAxisIndex: "all" }] },
        backgroundColor: "rgba(15, 23, 42, 0.94)",
        borderWidth: 0,
        textStyle: { color: "#e2e8f0", fontSize: 12 },
        formatter: (params: any) => {
          const i = (Array.isArray(params) ? params[0] : params)?.dataIndex ?? 0;
          const [date, open, close, low, high, volume] = bars[i];
          const prev = i > 0 ? bars[i - 1][2] : open;
          const change = (close / prev - 1) * 100;
          const color = change >= 0 ? "#f87171" : "#4ade80";
          return [
            `<b>${date}</b>`,
            `开 ${open}　收 <span style="color:${color}">${close}</span>`,
            `高 ${high}　低 ${low}`,
            `涨跌 <span style="color:${color}">${change >= 0 ? "+" : ""}${change.toFixed(2)}%</span>`,
            `成交量 ${(volume / 10000).toFixed(1)} 万手`,
          ].join("<br/>");
        },
      },
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      xAxis: [
        { type: "category", data: dates, boundaryGap: true, axisLabel: { fontSize: 11 } },
        { type: "category", gridIndex: 1, data: dates, axisLabel: { show: false }, axisTick: { show: false } },
      ],
      yAxis: [
        { scale: true, splitLine: { lineStyle: { color: "#eef2f7" } }, axisLabel: { fontSize: 11 } },
        { gridIndex: 1, scale: true, splitNumber: 2, axisLabel: { show: false }, splitLine: { show: false } },
      ],
      dataZoom: [
        { type: "inside", xAxisIndex: [0, 1], start, end: 100 },
        { type: "slider", xAxisIndex: [0, 1], start, end: 100, bottom: 4, height: 18 },
      ],
      series: [
        {
          name: "K线",
          type: "candlestick",
          data: bars.map((b) => [b[1], b[2], b[3], b[4]]),
          itemStyle: { color: UP, color0: DOWN, borderColor: UP, borderColor0: DOWN },
          markPoint: {
            symbol: "pin",
            symbolSize: 30,
            label: { fontSize: 10, color: "#fff" },
            data: marks as any,
          },
          markLine: {
            symbol: "none",
            data: lines.map((l) => ({
              yAxis: l.price,
              lineStyle: { color: l.color, type: "dashed" },
              label: { formatter: `${l.label} ${l.price}`, color: l.color, fontSize: 11, position: "end" },
            })),
          },
        },
        ...MAS.map((m) => ({
          name: `MA${m.n}`,
          type: "line" as const,
          data: movingAverage(bars, m.n),
          showSymbol: false,
          smooth: true,
          lineStyle: { width: 1, color: m.color },
          itemStyle: { color: m.color },
        })),
        {
          name: "成交量",
          type: "bar",
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: bars.map((b, i) => ({
            value: b[5],
            itemStyle: { color: b[2] >= (i > 0 ? bars[i - 1][2] : b[1]) ? UP : DOWN },
          })),
        },
      ],
    };
  }, [bars, trades, lines, visibleBars]);

  return <ReactECharts option={option} style={{ height }} notMerge />;
}
