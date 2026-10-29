import type {
  BacktestPayload,
  Checkup,
  Holding,
  HoldingsAnalysis,
  ImportRow,
  Job,
  KlineResponse,
  Meta,
  SimAccountBrief,
  SimState,
  TriggerResult,
  UpdateStatus,
  VersionInfo,
  WatchItem,
  WatchlistResponse,
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

const updateHeaders = (token: string): RequestInit["headers"] =>
  token
    ? { "Content-Type": "application/json", "X-Update-Token": token }
    : { "Content-Type": "application/json" };

export const api = {
  meta: () => request<Meta>("/api/meta"),
  // ---------------- 在线版本更新 ----------------
  version: () => request<VersionInfo>("/api/version"),
  updateStatus: () => request<UpdateStatus>("/api/update/status"),
  triggerUpdate: (token: string) =>
    request<TriggerResult>("/api/update", { method: "POST", headers: updateHeaders(token), body: "{}" }),
  triggerRollback: (token: string) =>
    request<TriggerResult>("/api/rollback", { method: "POST", headers: updateHeaders(token), body: "{}" }),
  health: async (): Promise<boolean> => {
    try {
      const res = await fetch("/api/health", { cache: "no-store" });
      return res.ok;
    } catch {
      return false;
    }
  },
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
  watchlist: () => request<WatchlistResponse>("/api/watchlist"),
  saveWatch: (item: Partial<WatchItem>) =>
    request<{ item: WatchItem; job: Job | null }>("/api/watchlist", json("PUT", item)),
  addWatch: (text: string, group?: string) =>
    request<{ added: string[]; skipped: string[]; invalid: string[]; job: Job | null }>(
      "/api/watchlist/add",
      json("POST", { text, group }),
    ),
  deleteWatch: (symbol: string) =>
    request<{ ok: boolean }>(`/api/watchlist/${encodeURIComponent(symbol)}`, { method: "DELETE" }),
  klineWith: (symbol: string, days: number, strategy: string, params: Record<string, number>) =>
    request<KlineResponse>(
      `/api/kline/${encodeURIComponent(symbol)}?days=${days}&strategy=${strategy}&params=${encodeURIComponent(JSON.stringify(params))}`,
    ),
  simAccounts: () => request<SimAccountBrief[]>("/api/sim/accounts"),
  createSimAccount: (name: string, initial_cash: number) =>
    request<SimAccountBrief>("/api/sim/accounts", json("POST", { name, initial_cash })),
  deleteSimAccount: (id: string) => request<{ ok: boolean }>(`/api/sim/accounts/${id}`, { method: "DELETE" }),
  simState: (id: string) => request<SimState>(`/api/sim/accounts/${id}`),
  addSlot: (id: string, body: { symbol: string; cash: number; strategy?: string | null; params?: Record<string, number> | null; entry_on_start: boolean }) =>
    request<unknown>(`/api/sim/accounts/${id}/slots`, json("POST", body)),
  stopSlot: (id: string, slotId: string) =>
    request<{ ok: boolean }>(`/api/sim/accounts/${id}/slots/${slotId}/stop`, { method: "POST" }),
  placeOrder: (id: string, body: { symbol: string; side: "BUY" | "SELL"; shares: number }) =>
    request<unknown>(`/api/sim/accounts/${id}/orders`, json("POST", body)),
  cancelOrder: (id: string, orderId: string) =>
    request<{ ok: boolean }>(`/api/sim/accounts/${id}/orders/${orderId}`, { method: "DELETE" }),
};
