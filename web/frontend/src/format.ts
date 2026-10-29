export function num(value: unknown): number | null {
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

export function pct(value: unknown, digits = 2, plus = true): string {
  const n = num(value);
  if (n === null) return "—";
  const sign = plus && n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}%`;
}

export function plainPct(value: unknown, digits = 2): string {
  const n = num(value);
  if (n === null) return "—";
  return `${n.toFixed(digits)}%`;
}

export function ratio(value: unknown, digits = 2): string {
  const n = num(value);
  return n === null ? "—" : n.toFixed(digits);
}

export function money(value: unknown, digits = 0): string {
  const n = num(value);
  if (n === null) return "—";
  return `¥${n.toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`;
}

export function compact(value: unknown): string {
  const n = num(value);
  if (n === null) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e8) return `${(n / 1e8).toFixed(2)} 亿`;
  if (abs >= 1e4) return `${(n / 1e4).toFixed(1)} 万`;
  return n.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

export function signed(value: unknown, digits = 2): string {
  const n = num(value);
  if (n === null) return "—";
  return `${n > 0 ? "+" : ""}${n.toFixed(digits)}`;
}

export function tone(value: unknown): "up" | "down" | "flat" {
  const n = num(value);
  if (n === null || n === 0) return "flat";
  return n > 0 ? "up" : "down";
}

export function toneColor(value: unknown): string {
  const t = tone(value);
  return t === "up" ? "#15803d" : t === "down" ? "#b91c1c" : "#475569";
}

export function paramsText(params: Record<string, number> | undefined | null): string {
  if (!params) return "—";
  return Object.entries(params)
    .map(([key, value]) => `${key}=${value}`)
    .join(" · ");
}

export function durationText(value: unknown): string {
  const text = String(value ?? "");
  const match = text.match(/^(\d+) days?/);
  return match ? `${match[1]} 天` : text || "—";
}

/** A 股配色：红涨绿跌 */
export function cnColor(value: unknown): string {
  const t = tone(value);
  return t === "up" ? "#dc2626" : t === "down" ? "#16a34a" : "#475569";
}
