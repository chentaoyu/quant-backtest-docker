import type {
  BacktestPayload,
  Checkup,
  Holding,
  HoldingsAnalysis,
  ImportRow,
  Job,
  KlineResponse,
  Meta,
  RunResult,
  RunSummary,
  StockListResponse,
} from "./types";

function errorText(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => (item && typeof item === "object" && "msg" in item ? String(item.msg) : ""))
      .filter(Boolean);
    if (parts.length) return parts.join("；");
  }
  return `请求失败（HTTP ${status}）`;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(errorText((data as { detail?: unknown }).detail, res.status));
  return data as T;
}

export const api = {
  meta: () => request<Meta>("/api/meta"),
  stocks: (refresh = false) => request<StockListResponse>(`/api/stocks${refresh ? "?refresh=true" : ""}`),
  runs: (limit = 30) => request<RunSummary[]>(`/api/runs?limit=${limit}`),
  run: (id: string) => request<RunResult>(`/api/runs/${encodeURIComponent(id)}`),
  backtest: (payload: BacktestPayload) =>
    request<RunResult>("/api/backtest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  holdings: () => request<Holding[]>("/api/holdings"),
  saveHolding: (holding: Partial<Holding>) => request<Holding>("/api/holdings", json("PUT", holding)),
  deleteHolding: (symbol: string) =>
    request<{ ok: boolean }>(`/api/holdings/${encodeURIComponent(symbol)}`, { method: "DELETE" }),
  previewImport: (text: string) =>
    request<{ rows: ImportRow[]; valid: number }>("/api/holdings/import", json("POST", { text, dry_run: true })),
  commitImport: (text: string, mode: "append" | "replace") =>
    request<{ holdings: Holding[]; job: Job | null }>(
      "/api/holdings/import",
      json("POST", { text, mode, dry_run: false }),
    ),
  analysis: () => request<HoldingsAnalysis>("/api/holdings/analysis"),
  checkup: (force: boolean, symbols?: string[]) =>
    request<{ job: Job | null; message?: string }>("/api/holdings/checkup", json("POST", { force, symbols })),
  job: (id: string) => request<Job>(`/api/jobs/${encodeURIComponent(id)}`),
  checkupDetail: (symbol: string) => request<Checkup>(`/api/checkups/${encodeURIComponent(symbol)}`),
  kline: (symbol: string, days: number, strategy?: string) =>
    request<KlineResponse>(
      `/api/kline/${encodeURIComponent(symbol)}?days=${days}${strategy ? `&strategy=${strategy}` : ""}`,
    ),
};
