// Mirrors backend/app/schemas/*. Keep in sync with the FastAPI response models.

export interface Team {
  id: number;
  abbreviation: string;
  display_name: string;
  short_name: string;
  location: string;
  color: string | null;
  alternate_color: string | null;
  logo_url: string | null;
}

export interface PlayerSummary {
  id: number;
  full_name: string;
  position: string | null;
  jersey: string | null;
  headshot_url: string | null;
  is_active: boolean;
  team: Team | null;
}

export type GameStatus =
  | "scheduled"
  | "in_progress"
  | "final"
  | "postponed"
  | "canceled"
  | "suspended";

export interface Game {
  id: number;
  season: number;
  season_label: string;
  season_type: number;
  season_type_label: string;
  start_time: string;
  game_date: string;
  status: GameStatus;
  status_detail: string | null;
  home_team: Team;
  away_team: Team;
  home_score: number | null;
  away_score: number | null;
  venue_name: string | null;
  venue_city: string | null;
  venue_state: string | null;
  neutral_site: boolean;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface SeasonAverages {
  season: number;
  season_label: string;
  games: number;
  starts: number;
  minutes: number | null;
  pts: number | null;
  reb: number | null;
  ast: number | null;
  stl: number | null;
  blk: number | null;
  tov: number | null;
  fg3m: number | null;
  fg_pct: number | null;
  fg3_pct: number | null;
  ft_pct: number | null;
}

export interface TeamSeason {
  season: number;
  season_label: string;
  team: Team;
  games_played: number;
}

export interface PlayerProfile {
  player: PlayerSummary;
  height_in: number | null;
  weight_lb: number | null;
  birth_date: string | null;
  current_season: number | null;
  available_seasons: number[];
  season_averages: SeasonAverages | null;
  team_history: TeamSeason[];
  upcoming_games: Game[];
  last_game_date: string | null;
  total_games_tracked: number;
}

export interface DirectoryRow {
  player: PlayerSummary;
  season: number | null;
  games: number;
  minutes: number | null;
  pts: number | null;
  reb: number | null;
  ast: number | null;
}

export interface GameLogEntry {
  game_id: number;
  game_date: string;
  season: number;
  season_label: string;
  season_type: number;
  opponent: Team;
  is_home: boolean;
  team_score: number | null;
  opponent_score: number | null;
  result: "W" | "L" | null;
  starter: boolean;
  did_not_play: boolean;
  dnp_reason: string | null;
  minutes: number | null;
  pts: number | null;
  reb: number | null;
  ast: number | null;
  stl: number | null;
  blk: number | null;
  tov: number | null;
  fgm: number | null;
  fga: number | null;
  fg3m: number | null;
  fg3a: number | null;
  ftm: number | null;
  fta: number | null;
  plus_minus: number | null;
}

export interface StatCategory {
  key: string;
  label: string;
  short_label: string;
  components: string[];
  is_combined: boolean;
}

export type WindowKind = "last_n" | "season" | "date_range" | "all";
export type Outcome = "over" | "under" | "push";
export type SeasonScope = "all" | "regular" | "postseason";

export interface AnalysisGame {
  game_id: number;
  game_date: string;
  season: number;
  season_label: string;
  season_type: number;
  opponent: Team;
  is_home: boolean;
  result: "W" | "L" | null;
  team_score: number | null;
  opponent_score: number | null;
  minutes: number | null;
  value: number;
  outcome: Outcome;
  components: Record<string, number | null>;
}

export interface Distribution {
  count: number;
  mean: number | null;
  median: number | null;
  std_dev: number | null;
  minimum: number | null;
  maximum: number | null;
}

export interface LineResult {
  line: number;
  total: number;
  over: number;
  under: number;
  push: number;
  over_pct: number | null;
  under_pct: number | null;
  push_pct: number | null;
  over_pct_excluding_pushes: number | null;
}

export interface StatAnalysis {
  player_id: number;
  category: StatCategory;
  window: {
    kind: WindowKind;
    n: number | null;
    season: number | null;
    start_date: string | null;
    end_date: string | null;
    opponent_team_id: number | null;
    season_types: number[];
  };
  opponent: Team | null;
  games: AnalysisGame[];
  distribution: Distribution;
  line_result: LineResult;
  small_sample: boolean;
  available_games: number;
  note: string;
}

export interface MatchupComparison {
  player_id: number;
  opponent: Team;
  recent: StatAnalysis;
  head_to_head: StatAnalysis;
}

export interface RecentForm {
  games: number;
  minutes: number | null;
  pts: number | null;
  reb: number | null;
  ast: number | null;
}

export interface GamePlayer {
  player: PlayerSummary;
  recent: RecentForm | null;
}

export interface BoxScoreLine {
  player: PlayerSummary;
  starter: boolean;
  did_not_play: boolean;
  dnp_reason: string | null;
  minutes: number | null;
  pts: number | null;
  reb: number | null;
  ast: number | null;
  stl: number | null;
  blk: number | null;
  tov: number | null;
  fg3m: number | null;
  plus_minus: number | null;
}

export interface GameDetail {
  game: Game;
  home_players: GamePlayer[];
  away_players: GamePlayer[];
  players_source: "boxscore" | "current_roster";
  home_boxscore: BoxScoreLine[];
  away_boxscore: BoxScoreLine[];
  previous_meetings: Game[];
}

export interface TopPerformer {
  player: PlayerSummary;
  game: Game;
  pts: number;
  reb: number;
  ast: number;
}

export interface SyncRun {
  id: number;
  kind: string;
  status: "running" | "success" | "partial" | "failed";
  started_at: string;
  finished_at: string | null;
  games_updated: number;
  boxscores_synced: number;
  requests_made: number;
  error: string | null;
}

export interface SeasonCoverage {
  season: number;
  season_label: string;
  games_scheduled: number;
  games_final: number;
  boxscores_synced: number;
  boxscores_pending: number;
}

export interface SyncStatus {
  provider: string;
  current_season: number | null;
  last_successful_sync_at: string | null;
  last_run: SyncRun | null;
  is_running: boolean;
  is_stale: boolean;
  players: number;
  player_game_rows: number;
  seasons: SeasonCoverage[];
  scheduler_enabled: boolean;
  next_scheduled_sync_at: string | null;
}

export interface TrendRow {
  player: PlayerSummary;
  opponent: Team | null;
  game_id: number | null;
  game_start: string | null;
  distribution: Distribution;
  line_result: LineResult;
  recent_values: number[];
}

export interface TrendExplorer {
  category: StatCategory;
  line: number;
  last_n: number;
  min_games: number;
  scope: string;
  rows: TrendRow[];
  note: string;
}

export interface HistoricalWindowHit {
  window: "L5" | "L10" | "L20";
  games: number;
  over_pct: number | null;
  under_pct: number | null;
  small_sample: boolean;
}

export interface PlayerPropRecommendation {
  player: PlayerSummary;
  opponent: Team;
  game: Game;
  category: string;
  category_label: string;
  line: number;
  line_source: string;
  predicted_mean: number;
  predicted_std_dev: number;
  pick_side: "over" | "under";
  model_probability: number;
  p_over: number | null;
  p_under: number | null;
  probability_status: "available" | "experimental" | "unavailable";
  games_used: number;
  historical_hit_rates: HistoricalWindowHit[];
  model_version: string;
  player_analysis_href: string;
}

export interface GameWinnerWarning {
  code: string;
  message: string;
}

export interface GameWinnerFactors {
  home_elo: number;
  away_elo: number;
  elo_home_win_prob: number;
  home_win_pct_season: number;
  away_win_pct_season: number;
  home_rest_days: number;
  away_rest_days: number;
  home_b2b: boolean;
  away_b2b: boolean;
  h2h_home_win_pct: number;
  neutral_site: boolean;
  games_before_home?: number;
  games_before_away?: number;
}

export interface GameWinnerRecommendation {
  game: Game;
  home_win_probability: number;
  away_win_probability: number;
  model_home_win_probability_raw: number;
  calibration_applied: boolean;
  elo_home_win_probability: number;
  predicted_winner_team_id: number;
  selected_model: string;
  model_version: string;
  probability_status: "available" | "experimental" | "unavailable";
  factors: GameWinnerFactors;
  warnings: GameWinnerWarning[];
  matchup_href: string;
}

export interface RecommendationsPipeline {
  upcoming_games: number;
  rotation_player_slots: number;
  ml_prop_attempts: number;
  props_skipped_no_line: number;
  props_skipped_ml: number;
  props_candidates_before_dedupe: number;
  props_after_dedupe: number;
  props_filtered_by_query: number;
  player_game_prepares: number;
}

export interface RecommendationsMeta {
  generated_at: string;
  player_model_version: string | null;
  game_winner_model_version: string | null;
  upcoming_games_scanned: number;
  player_props_generated: number;
  game_winners_generated: number;
  data_sync_reference: string | null;
  disclaimer: string;
  pipeline: RecommendationsPipeline;
  generation_ms?: number | null;
}

export interface Recommendations {
  meta: RecommendationsMeta;
  player_props: PlayerPropRecommendation[];
  game_winners: GameWinnerRecommendation[];
  categories: string[];
  errors: string[];
}

export interface PlayerStatPrediction {
  player_id: number;
  player_name: string;
  game_id: number;
  opponent_team_id: number;
  category: string;
  category_label: string;
  line: number;
  predicted_mean: number;
  predicted_std_dev: number;
  p_over: number | null;
  p_under: number | null;
  p_push: number | null;
  probability_status: string;
  model_version: string;
  selected_model_summary: string;
  predicted_at: string;
  disclaimer: string;
}
