import type { Dayjs } from "dayjs";

export type Source = "auto" | "tushare" | "akshare";

// ---------------- 在线版本更新 ----------------

export interface LatestRelease {
  tag: string;
  name: string;
  published_at: string | null;
  html_url: string | null;
  notes: string;
}

export interface LastUpdateSummary {
  state: string;
  from_tag: string | null;
  to_tag: string | null;
  last_good_tag: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

export interface VersionInfo {
  current_version: string;
  current_commit: string;
  latest: LatestRelease | null;
  has_update: boolean | null;
  update_mode: string; // none | host-updater
  token_required: boolean; // 服务器是否要求更新令牌（UPDATE_TOKEN 留空 = false）
  warning: string | null;
  last_update: LastUpdateSummary | null;
}

export interface UpdateStatus extends LastUpdateSummary {
  stale?: boolean;
  log_tail?: string;
  mode?: string;
}

export interface TriggerResult {
  triggered: boolean;
  target: string;
}

export interface Stock {
  symbol: string;
  name: string;
  exchange: string;
}

export interface StockListResponse {
  stocks: Stock[];
  count: number;
  source: string;
  fetched_at: string | null;
  warning: string | null;
}

export interface StrategyParam {
  name: string;
  label: string;
  default: number;
  min: number;
  max: number;
  step: number;
}

export interface RangeSpec {
  start: number;
  stop: number;
  step: number;
}

export interface StrategyNotes {
  logic?: string;
  entry?: string;
  exit?: string;
  regime?: string;
  risk?: string;
}

export interface StrategyMeta {
  name: string;
  label: string;
  description: string;
  notes?: StrategyNotes;
  params: StrategyParam[];
  defaults: Record<string, number>;
  default_ranges: Record<string, RangeSpec>;
}

export interface CachedSymbol {
  symbol: string;
  sources: string[];
  rows: number;
  start: string;
  end: string;
}

export interface Meta {
  auto_source: string;
  tushare_token: boolean;
  sources: { value: string; label: string }[];
  defaults: {
    start: string;
    end: string;
    cash: number;
    commission: number;
  };
  strategies: StrategyMeta[];
  strategy_count: number;
  symbols: CachedSymbol[];
}

export interface EquityPoint {
  t: string;
  e: number;
  dd: number;
}

export interface Trade {
  entry: string;
  exit: string;
  size: number;
  entry_price: number;
  exit_price: number;
  pnl: number;
  return_pct: number;
  duration: string;
}

export type Metrics = Record<string, number | string | boolean | null>;

export interface RunConfig {
  symbol: string;
  strategy: string;
  source: string;
  start: string;
  end: string;
  cash: number;
  commission: number;
  optimize: boolean;
  split: string | null;
  params: Record<string, number>;
  ranges: Record<string, RangeSpec>;
  refresh: boolean;
}

export interface DataMeta {
  symbol: string;
  source: string;
  adjust: string;
  cached: boolean;
  cache_file: string;
  fetched_at: string;
  rows: number;
  start: string;
  end: string;
  partial_bar_dropped: string | null;
  warnings: string[];
}

export interface OosSegment {
  rows: number;
  start: string;
  end: string;
  params: Record<string, number>;
  metrics: Metrics;
}

export interface OosBlock {
  split: string;
  mode: string;
  train: OosSegment;
  test_params: OosSegment;
  test_default: OosSegment | null;
  test_oracle: OosSegment | null;
  sharpe_decay: number | null;
  sharpe_decay_note: string;
}

export interface RunResult {
  run_id: string;
  created_at: string;
  config: RunConfig;
  data: DataMeta;
  params: Record<string, number>;
  metrics: Metrics;
  equity: EquityPoint[];
  trades: Trade[];
  oos: OosBlock | null;
  warnings: string[];
  report_file: string;
  report_url: string;
  duration_sec: number;
}

export interface RunSummary {
  run_id: string;
  created_at: string;
  symbol: string;
  strategy: string;
  source: string;
  split: string | null;
  return_pct: number | null;
  sharpe: number | null;
  report_url: string;
}

export interface FormValues {
  symbol: string;
  source: Source;
  start: Dayjs;
  end: Dayjs;
  cash: number;
  commissionPct: number;
  strategy: string;
  params: Record<string, number>;
  optimize: boolean;
  splitEnabled: boolean;
  split: Dayjs | null;
  ranges: Record<string, RangeSpec>;
  refresh: boolean;
}

export interface BacktestPayload {
  symbol: string;
  source: string;
  start: string;
  end: string;
  cash: number;
  commission: number;
  strategy: string;
  optimize: boolean;
  split: string | null;
  params: Record<string, number>;
  ranges: Record<string, RangeSpec>;
  refresh: boolean;
}
// ---------------------------------------------------------------- 持仓
export interface Holding {
  symbol: string;
  name: string;
  shares: number;
  cost_price: number;
  buy_date: string | null;
  stop_loss_pct: number | null;
  take_profit_pct: number | null;
  strategy: string | null;
  note: string;
}

export interface Triggers {
  action: "BUY" | "SELL";
  fires_flat: boolean;
  below: number | null;
  above: number | null;
}

export interface SignalTrade {
  entry_date: string;
  entry_price: number;
  exit_date: string | null;
  exit_price: number | null;
  return_pct: number | null;
}

export interface StrategySignal {
  name: string;
  label: string;
  params: Record<string, number>;
  oos_sharpe: number | null;
  action: "BUY" | "SELL" | null;
  hold: boolean;
  hold_after: boolean;
  since: string | null;
  trades?: SignalTrade[];
  triggers?: Triggers;
}

export type AdviceCode =
  | "STOP_LOSS"
  | "TAKE_PROFIT"
  | "SELL"
  | "BUY"
  | "HOLD"
  | "WAIT"
  | "NO_STRATEGY"
  | "UNCHECKED";

export interface HoldingAnalysis extends Holding {
  error: string | null;
  data_date?: string;
  close?: number;
  prev_close?: number;
  change_pct?: number | null;
  market_value?: number;
  pnl?: number;
  pnl_pct?: number | null;
  day_pnl?: number;
  weight_pct?: number | null;
  advice: { code: AdviceCode; label: string; color: string; reason: string } | null;
  main?: StrategySignal | null;
  consensus?: { bull: number; bear: number; total: number };
  strategies?: StrategySignal[];
  since_buy?: {
    hold_return_pct: number | null;
    max_dd_pct: number | null;
    first_exit: { date: string; price: number; return_pct: number | null } | null;
  } | null;
  checkup?: { checked_at: string; stale: boolean; best: string | null } | null;
  warnings?: string[];
}

export interface Job {
  id: string;
  status: "running" | "done";
  total: number;
  done: number;
  current: string | null;
  errors: Record<string, string>;
  symbols: string[];
  pending: string[];
  avg_sec: number;
  current_elapsed: number;
}

export interface HoldingsAnalysis {
  summary: {
    count: number;
    market_value: number;
    cost: number;
    pnl: number;
    pnl_pct: number | null;
    day_pnl: number;
    advice_counts: Partial<Record<AdviceCode, number>>;
    data_date: string | null;
  };
  rows: HoldingAnalysis[];
  job: Job | null;
}

export interface ImportRow {
  line: number;
  ok: boolean;
  error: string | null;
  merged: boolean;
  raw: Record<string, string>;
  item?: Holding;
}

export interface CheckupStrategy {
  oos_sharpe: number | null;
  oos_return_pct?: number | null;
  oos_max_dd_pct?: number | null;
  oos_trades?: number;
  bh_return_pct?: number | null;
  live_params: Record<string, number>;
  error: string | null;
}

export interface Checkup {
  symbol: string;
  checked_at: string;
  data_end: string;
  best: string | null;
  strategies: Record<string, CheckupStrategy>;
}

export type KlineBar = [string, number, number, number, number, number]; // 日期, 开, 收, 低, 高, 量

export interface KlineResponse {
  symbol: string;
  bars: KlineBar[];
  signal:
    | (Omit<StrategySignal, "name" | "label" | "oos_sharpe"> & {
        strategy: string;
        trades: SignalTrade[];
        triggers: Triggers;
      })
    | null;
}

// ---------------------------------------------------------------- 自选股
export interface WatchItem {
  symbol: string;
  name: string;
  group: string;
  strategy: string | null;
  params: Record<string, number> | null;
  note: string;
}

export interface WatchRow extends WatchItem {
  error: string | null;
  data_date?: string;
  close?: number;
  change_pct?: number | null;
  used: {
    name: string;
    label: string;
    params: Record<string, number>;
    source: "auto" | "checkup" | "default" | "manual";
    oos_sharpe: number | null;
  } | null;
  signal: {
    action: "BUY" | "SELL" | null;
    hold: boolean;
    hold_after: boolean;
    since: string | null;
    triggers: Triggers;
    last_event: { date: string; action: "BUY" | "SELL"; price: number } | null;
  } | null;
  sharpes?: Record<string, number | null>;
  checkup?: { checked_at: string; best: string | null } | null;
  sim: { account_id: string; account: string; slot_id: string }[];
}

export interface WatchlistResponse {
  rows: WatchRow[];
  groups: string[];
  signal_count: number;
  job: Job | null;
}

// ---------------------------------------------------------------- 模拟仓
export interface SimAccountBrief {
  id: string;
  name: string;
  initial_cash: number;
  created_date: string;
}

export interface SimTrade {
  date: string;
  symbol: string;
  name: string;
  side: "BUY" | "SELL";
  price: number;
  shares: number;
  fee: number;
  pnl: number | null;
  return_pct?: number;
  source: "strategy" | "manual";
  strategy?: string;
}

export interface SimSlot {
  id: string;
  symbol: string;
  name: string;
  strategy: string;
  label?: string;
  params: Record<string, number>;
  cash: number;
  start_date: string;
  end_date: string | null;
  entry_on_start: boolean;
  status: "active" | "stopping" | "stopped" | "error";
  shares: number;
  cost?: number | null;
  close?: number;
  value: number;
  pending: "BUY" | "SELL" | null;
  notes: { date: string; note: string }[];
  error?: string;
}

export interface SimOrder {
  id: string;
  symbol: string;
  name: string;
  side: "BUY" | "SELL";
  shares: number;
  placed_date: string;
  status: "pending" | "filled" | "failed" | "cancelled";
  fill: { date: string; price: number; fee: number } | null;
  reason: string | null;
}

export interface SimPosition {
  symbol: string;
  name: string;
  source: "strategy" | "manual";
  strategy: string | null;
  shares: number;
  cost: number;
  close: number;
  market_value: number;
  pnl: number;
}

export interface SimScore {
  strategy: string;
  label: string;
  slots: number;
  closed_trades: number;
  win_rate_pct: number | null;
  avg_return_pct: number | null;
  profit_factor: number | null;
  pnl: number;
  checkup_sharpe: number | null;
}

export interface SimState {
  account: SimAccountBrief & { fees: Record<string, number> };
  summary: {
    equity: number;
    cash: number;
    slot_cash: number;
    market_value: number;
    pnl: number;
    pnl_pct: number;
    day_pnl: number;
    max_dd_pct: number | null;
    days: number;
    data_date: string | null;
  };
  curve: { date: string; equity: number }[];
  benchmark: { name: string; series: Record<string, number>; return_pct: number } | null;
  slots: SimSlot[];
  positions: SimPosition[];
  orders: SimOrder[];
  trades: SimTrade[];
  scorecard: SimScore[];
}
