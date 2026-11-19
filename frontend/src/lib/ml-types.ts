export type ProbabilityStatus = "validated_real_lines" | "experimental" | "unavailable" | "disabled_by_flag";

export interface MlFlags {
  enable_ml_inference: boolean;
  enable_ml_experimental_ui: boolean;
  enable_ml_recommendations: boolean;
  enable_ml_probabilities: boolean;
}

export interface MlStatus {
  loaded: boolean;
  active_version: string | null;
  previous_version: string | null;
  versions: string[];
  trained_at: string | null;
  dataset_cutoff: string | null;
  feature_version: string | null;
  split: {
    method: string;
    train_dates: [string, string];
    val_dates: [string, string];
    test_dates: [string, string];
    rows: { train: number; val_eval: number; test_eval: number; deploy_fit: number };
  } | null;
  selected_models: Record<string, string> | null;
  probability_status: Record<string, ProbabilityStatus> | null;
  probability_gates: { rules: Record<string, string>; detail: Record<string, Record<string, number | boolean | null>> } | null;
  acceptance_checks: Record<string, boolean> | null;
  timings_seconds: Record<string, number> | null;
  final_games_since_training_cutoff: number | null;
  last_sync_at: string | null;
  model_load_seconds: number | null;
  last_batch_seconds: number | null;
  odds_archive: { snapshots: number; graded: number; games: number; from_live_imports: number; from_prop_offers_last_seen: number; by_result: Record<string, number> } | null;
  flags: MlFlags;
  warnings: string[];
}

export interface RegressionMetrics {
  n: number;
  mae: number;
  rmse: number;
  median_ae: number;
  bias: number;
}

export interface ReliabilityBin {
  bin_start: number;
  bin_end: number;
  predicted_mean: number;
  observed_rate: number;
  count: number;
}

export interface ProbMetrics {
  n: number;
  brier: number;
  log_loss: number;
  ece: number;
  reliability?: ReliabilityBin[];
}

export interface MlMetrics {
  version: string;
  test: Record<
    string,
    {
      model: RegressionMetrics;
      baselines: Record<string, RegressionMetrics>;
      best_baseline: string;
      mae_improvement_vs_best_baseline_pct: number;
      old_model?: { version: string; rows_compared: number; old: RegressionMetrics; new_same_rows: RegressionMetrics; note: string };
      slices: Record<string, Record<string, { n: number; mae: number; bias: number }>>;
    }
  >;
  synthetic_thresholds: Record<
    string,
    {
      empirical_joint: ProbMetrics;
      normal_legacy: ProbMetrics;
      climatology_constant: ProbMetrics;
      interval_80_coverage: number;
      interval_80_mean_width: number;
    }
  >;
  real_lines: {
    available: boolean;
    games?: number;
    date_range?: [string, string];
    categories?: Record<
      string,
      {
        unique_lines: number;
        model: ProbMetrics;
        constant_half: ProbMetrics;
        market_comparison: { n_book_lines: number; model: ProbMetrics; market_devigged: ProbMetrics; mean_overround: number } | null;
      }
    >;
  };
  feature_importance_validation: Record<string, { feature: string; mae_increase: number }[]>;
  selection: Record<string, { selected: string; best_baseline: string; best_ml: string; validation: Record<string, RegressionMetrics> }>;
}

export interface CategoryProjection {
  category: string;
  label: string;
  mean: number;
  median: number;
  p10: number;
  p90: number;
  sd: number;
  probability_status: ProbabilityStatus;
}

export interface PlayerProjection {
  player_id: number;
  player_name: string;
  team_abbreviation: string | null;
  opponent_abbreviation: string | null;
  game_id: number;
  start_time: string;
  is_home: boolean;
  appearances: number;
  season_appearances: number;
  projected_minutes: number;
  categories: CategoryProjection[];
  context: Record<string, number | null>;
  warnings: string[];
  model_version: string;
  data_last_sync_at: string | null;
  dataset_cutoff: string;
  disclaimer: string;
}

export interface PropEstimate {
  category: string;
  line: number;
  mean: number;
  median: number;
  p10: number;
  p90: number;
  p_over: number | null;
  p_under: number | null;
  p_push: number | null;
  probability_status: ProbabilityStatus;
  probability_note: string;
  n_samples: number;
  warnings: string[];
}

export interface UpcomingProjectionRow {
  player_id: number;
  player_name: string;
  team_abbreviation: string | null;
  opponent_abbreviation: string | null;
  game_id: number;
  start_time: string;
  projected_minutes: number;
  pts: number;
  reb: number;
  ast: number;
  fg3m: number;
  pra: number;
  appearances: number;
  warnings: string[];
}

export interface ComparisonRow {
  offer_id: number;
  player_id: number;
  player_name: string;
  team_abbreviation: string | null;
  opponent_abbreviation: string | null;
  game_id: number;
  start_time: string;
  sportsbook: string;
  category: string;
  category_label: string;
  line: number;
  side: "over" | "under";
  american_odds: number | null;
  projected_mean: number;
  projected_median: number;
  p10: number;
  p90: number;
  projection_gap: number;
  model_leans: "over" | "under" | "neutral";
  agrees_with_side: boolean;
  p_side: number | null;
  probability_status: ProbabilityStatus;
  l10_hit_pct: number | null;
  l20_hit_pct: number | null;
  l10_games: number | null;
  l20_games: number | null;
  hcs_score: number | null;
  appearances: number;
  eligible: boolean;
  ineligible_reasons: string[];
  warnings: string[];
}

export interface ComparisonResponse {
  mode: "validated" | "experimental_comparison" | "disabled";
  mode_explanation: string;
  rows: ComparisonRow[];
  total: number;
  total_offers_considered: number;
  model_version: string | null;
  last_import_finished_at: string | null;
  sportsbooks: string[];
  gating: { probability_status?: Record<string, ProbabilityStatus>; rules?: Record<string, string>; flags?: MlFlags };
}

export interface ProspectiveCategory {
  n: number;
  games: number;
  mae: number;
  rmse: number;
  bias: number;
  baselines: Record<string, { n: number; mae: number; model_mae_same_rows: number }>;
  coverage_50: number;
  coverage_80: number;
  coverage_90: number;
  mean_width_50: number;
  mean_width_80: number;
  mean_width_90: number;
}

type SliceStats = Record<string, Record<string, { n: number; games: number; mae: number; bias: number; coverage_80: number }>>;

export interface ProspectiveSummary {
  forecasts_recorded: number;
  by_status: Record<string, number>;
  forecasts_settled: number;
  forecasts_unresolved: number;
  forecasts_pending: number;
  games_forecast: number;
  games_settled?: number;
  first_predicted_at: string | null;
  last_predicted_at: string | null;
  lines_recorded: number;
  forecasts_with_lines: number;
  warnings: string[];
  categories: Record<string, ProspectiveCategory>;
  by_model_version: SliceStats;
  by_minutes_tier: SliceStats;
  by_usage_tier: SliceStats;
}
