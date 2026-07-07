// Shared types for the My-Trade operator console.
// Mirrors the backend REST contract documented in the project spec.

export type AssetClass = "crypto" | "equities";
export type BotStatus = "RUNNING" | "STOPPED" | "HALTED" | "ERROR";
export type EventKind =
  | "entry_submitted"
  | "entry_rejected"
  | "exit_submitted"
  | "halt"
  | "error"
  | "heartbeat"
  | "daily_rollover"
  | "research_not_approved"
  | "research_reflection"
  | string;

export interface Health {
  status: string;
  bot_running: boolean;
  asset_class: AssetClass;
  paper_trading: boolean;
}

export interface Status {
  bot: {
    running: boolean;
    pid: number | null;
    started_at: string | null;
    last_cycle_at: string | null;
    cycles_today: number;
  };
  session: { open: boolean; asset_class: AssetClass };
  halted: boolean;
  halt_reason: string | null;
  research?: {
    enabled: boolean;
    active: boolean;
    require_approval: boolean;
    tier_mode?: string;
    claude_enabled?: boolean;
    claude_model?: string | null;
    workhorse_provider?: string | null;
    workhorse_model?: string | null;
    model: string | null;
  };
}

export interface Position {
  symbol: string;
  qty: number;
  avg_entry_price: number;
  market_value: number;
  unrealized_pl: number;
}

export interface Account {
  equity: number;
  broker_equity?: number | null;
  trading_capital?: number | null;
  cash: number;
  buying_power: number;
  day_pnl: number;
  peak_equity: number;
  open_positions: number;
  positions: Position[];
}

export interface Strategy {
  rsi_oversold: number;
  rsi_overbought: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  max_hold_minutes: number;
  require_15m_uptrend: boolean;
  require_volume_spike: boolean;
}

export interface RiskConfig {
  max_risk_per_trade_pct: number;
  max_open_risk_pct: number;
  daily_loss_limit_pct: number;
  daily_profit_target_pct?: number;
  max_drawdown_pct: number;
  max_concurrent_positions: number;
  max_daily_entries?: number;
  max_entries_per_symbol_per_day?: number;
  trading_capital?: number;
  max_notional_pct?: number;
}

export interface ScreenerConfig {
  enabled: boolean;
  top_n: number;
  refresh_seconds: number;
  min_atr_pct: number;
  min_dollar_volume: number;
  use_movers: boolean;
  movers_source: "actives" | "gainers" | "losers" | "both";
}

export interface RuntimeConfig {
  scan_interval_seconds: number;
  log_level: "DEBUG" | "INFO" | "WARNING" | "ERROR";
}

export interface AppConfig {
  asset_class: AssetClass;
  symbols: string[];
  paper_trading: boolean;
  screener: ScreenerConfig;
  strategy: Strategy;
  risk: RiskConfig;
  runtime: RuntimeConfig;
}

export interface ActivityEvent {
  ts: string;
  kind: EventKind;
  symbol: string | null;
  detail: string;
  equity: number | null;
  day_pnl: number | null;
}

export interface Stats {
  today: {
    entries: number;
    exits: number;
    halts: number;
    errors: number;
    research_proposals?: number;
    research_skipped?: number;
    research_reflections?: number;
  };
  daily_state: {
    trading_day: string;
    start_of_day_equity: number;
    peak_equity: number;
    entries_today: Record<string, number>;
  };
  latest_equity: { equity: number; day_pnl: number } | null;
}

export interface WatchlistKnowledge {
  symbol: string;
  action?: string | null;
  confidence?: number | null;
  instrument?: string | null;
  time_horizon?: string | null;
  thesis?: string;
  provider?: string | null;
  updated_at?: string | null;
  why_watch?: string;
  recent_lesson?: string;
  source?: string;
}

export interface Watchlist {
  symbols: string[];
  ranked: { symbol: string; atr_pct: number; dollar_volume: number; score: number }[];
  knowledge?: WatchlistKnowledge[];
  refreshed_at: string | null;
  universe_source?: string;
}

export interface TradeKnowledgeStats {
  entries: number;
  exits: number;
  wins: number;
  losses: number;
  flats: number;
  rejections: number;
  exit_failures: number;
  vetoes: number;
}

export interface TradeKnowledgeDailySummary {
  trading_day: string;
  closed_at: string;
  virtual_equity: number | null;
  day_pnl: number | null;
  entries: number;
  exits: number;
  wins: number;
  losses: number;
  flats: number;
  key_lessons: string[];
  narrative: string;
}

export interface TradeKnowledgeRecord {
  id: string;
  ts: string;
  trading_day: string;
  event_kind: string;
  symbol: string;
  outcome: string;
  pnl_estimate: number | null;
  equity: number | null;
  day_pnl: number | null;
  what_happened: string;
  how_it_happened: string;
  why_it_happened: string;
  research_action: string | null;
  research_confidence: number | null;
  research_thesis: string | null;
  lessons: string[];
}

export interface TradeKnowledgeResponse {
  file: string;
  record_count: number;
  last_updated: string | null;
  stats: TradeKnowledgeStats;
  daily_summaries: TradeKnowledgeDailySummary[];
  records: TradeKnowledgeRecord[];
}

export interface LogsResponse {
  lines: string[];
}

export interface BotActionResult {
  ok: boolean;
  message?: string;
  summary?: string;
  actions?: unknown[];
  checks?: { account: boolean; data: boolean; execution: boolean };
}

export interface SettingsPatchResult {
  ok: boolean;
  requires_restart: boolean;
  message: string;
}
