import raw from "@/data/demo.json";

export type DayId = "quiet" | "setup" | "degraded";

export interface Day {
  id: DayId;
  title: string;
  summary: string;
  briefing_date: string;
  date_label: string;
  sent: string;
  healthy: boolean;
  setups: string[];
  sections: string[];
  messages: string[];
}

export interface Reason {
  code: string;
  label: string;
}

export interface Arrival {
  symbol: string;
  name: string;
  session: string;
  close: string;
  quality: "verified" | "single_source" | "disputed" | "suspect" | "invalid" | "corporate_action_pending";
  reasons: Reason[];
  ready: boolean;
}

export interface RuleStep extends Reason {
  passed: boolean;
}

export interface Pipeline {
  series: Record<"close" | "sma50" | "sma200", (number | null)[]>;
  briefing_date: string;
  arrivals: Arrival[];
  indicators: { symbol: string; values: { name: string; value: string }[] };
  rules: { symbol: string; trail: RuleStep[] }[];
  setup: Record<"symbol" | "entry" | "stop" | "t1" | "t2" | "reward_risk" | "size_pct", string>;
}

export interface Summary {
  resolved: number;
  open: number;
  t1_touch_rate_pct?: string;
  win_rate_pct?: string;
  expectancy_r?: string;
  expectancy_ci90_r?: [string, string];
  max_drawdown_r?: string;
  median_sessions_held?: number;
}

export interface Backtest {
  strategy: string;
  version: string;
  period: [string, string];
  out_of_sample_from: string;
  full_to_t2: { all: Summary; out_of_sample: Summary };
  half_at_t1_breakeven: { all: Summary; out_of_sample: Summary };
  random_entry_baseline: { runs: number; mean_expectancy_r: string; p05_r: string; p95_r: string } | null;
  assumptions: string[];
  caveats: string[];
  trades: number;
  cumulative_r: { day: string; r: number; label: string }[];
  report_hash: string;
}

export type Table = string[][];

export interface Demo {
  label: string;
  notice: string;
  seed: number;
  days: Day[];
  pipeline: Pipeline;
  backtest: Backtest;
  method: Record<"readiness" | "quality" | "rules" | "reviews" | "scorecard", Table>;
  reasons: Record<string, string>;
  traces: number[][];
  ticker: { symbol: string; close: string; change: string; direction: "up" | "down" | "flat" }[];
}

export const demo = raw as unknown as Demo;
