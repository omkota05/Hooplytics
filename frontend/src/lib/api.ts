import type {
  DirectoryRow,
  Game,
  GameDetail,
  GameLogEntry,
  MatchupComparison,
  Page,
  PlayerProfile,
  PlayerSummary,
  SeasonScope,
  StatAnalysis,
  StatCategory,
  SyncStatus,
  Team,
  TopPerformer,
  Recommendations,
  ParlaySearchRequest,
  ParlaySearchResult,
  PropAnalyzer,
  PropFinderDetail,
  PropFinderList,
  PlayerOpportunity,
  PropImportStatus,
  PlayerStatPrediction,
  TrendExplorer,
  WindowKind,
} from "./types";

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

const REQUEST_TIMEOUT_MS = 15_000;

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number | null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Params = Record<string, string | number | boolean | null | undefined>;

function buildUrl(path: string, params?: Params): string {
  const url = new URL(`${API_BASE_URL}/api${path}`);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function request<T>(
  path: string,
  params?: Params,
  init?: RequestInit,
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(buildUrl(path, params), { ...init, signal: controller.signal });
  } catch (err) {
    const timedOut = err instanceof DOMException && err.name === "AbortError";
    throw new ApiError(
      timedOut
        ? "The Hooplytics API took too long to respond."
        : `Cannot reach the Hooplytics API at ${API_BASE_URL}. Is the backend running?`,
      null,
    );
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      // non-JSON error body
    }
    throw new ApiError(detail || `Request failed (${response.status})`, response.status);
  }
  return response.json() as Promise<T>;
}

export interface AnalysisQuery {
  stat: string;
  line: number;
  window: WindowKind;
  n?: number;
  season?: number;
  startDate?: string;
  endDate?: string;
  opponentId?: number | null;
  seasonScope?: SeasonScope;
}

export const api = {
  searchPlayers: (q: string, limit = 8) =>
    request<PlayerSummary[]>("/players/search", { q, limit }),
  listPlayers: (params: {
    q?: string;
    teamId?: number | null;
    activeOnly?: boolean;
    sort?: string;
    page?: number;
    pageSize?: number;
  }) =>
    request<Page<DirectoryRow>>("/players", {
      q: params.q,
      team_id: params.teamId,
      active_only: params.activeOnly ?? true,
      sort: params.sort,
      page: params.page,
      page_size: params.pageSize,
    }),
  playerProfile: (id: number, season?: number) =>
    request<PlayerProfile>(`/players/${id}`, { season }),
  playerOpportunity: (id: number, q?: { season?: number; beforeGameId?: number }) =>
    request<PlayerOpportunity>(`/players/${id}/opportunity`, {
      season: q?.season,
      before_game_id: q?.beforeGameId,
    }),
  gameLogs: (id: number, limit = 25, season?: number) =>
    request<GameLogEntry[]>(`/players/${id}/game-logs`, { limit, season }),
  statAnalysis: (id: number, q: AnalysisQuery) =>
    request<StatAnalysis>(`/players/${id}/stat-analysis`, {
      stat: q.stat,
      line: q.line,
      window: q.window,
      n: q.window === "last_n" ? q.n : undefined,
      season: q.season,
      start_date: q.startDate,
      end_date: q.endDate,
      opponent_id: q.opponentId,
      season_scope: q.seasonScope,
    }),
  matchupComparison: (
    id: number,
    q: { opponentId: number; stat: string; line: number; recentN: number; h2hN?: number | null },
  ) =>
    request<MatchupComparison>(`/players/${id}/matchup-comparison`, {
      opponent_id: q.opponentId,
      stat: q.stat,
      line: q.line,
      recent_n: q.recentN,
      h2h_n: q.h2hN,
    }),
  categories: () => request<StatCategory[]>("/stats/categories"),
  teams: () => request<Team[]>("/teams"),
  upcomingGames: (days = 7) => request<Game[]>("/games/upcoming", { days }),
  recentGames: (days = 1) => request<Game[]>("/games/recent", { days }),
  topPerformers: (limit = 8) => request<TopPerformer[]>("/games/top-performers", { limit }),
  gameDetail: (id: number) => request<GameDetail>(`/games/${id}`),
  syncStatus: () => request<SyncStatus>("/sync/status"),
  triggerSync: () => request<{ queued: boolean }>("/sync/run", undefined, { method: "POST" }),
  recommendations: (q: {
    days?: number;
    expandPlayerProps?: boolean;
    gameId?: number | null;
    teamId?: number | null;
    category?: string;
    side?: "over" | "under";
    minProbability?: number;
    q?: string;
    gameDate?: string;
    sort?: "probability" | "time" | "player";
  }) =>
    request<Recommendations>(
      "/recommendations",
      {
      days: q.days ?? 7,
      expand_player_props: q.expandPlayerProps,
      game_id: q.gameId,
      team_id: q.teamId,
      category: q.category,
      side: q.side,
      min_probability: q.minProbability,
      q: q.q,
      game_date: q.gameDate,
      sort: q.sort,
      },
      undefined,
      240_000,
    ),
  customPlayerProp: (q: { playerId: number; gameId: number; category: string; line: number }) =>
    request<PlayerStatPrediction>("/recommendations/player-prop", {
      player_id: q.playerId,
      game_id: q.gameId,
      category: q.category,
      line: q.line,
    }),
  propFinderStatus: () => request<PropImportStatus>("/prop-finder/status"),
  refreshPropOdds: () =>
    request<PropImportStatus>("/prop-finder/import", undefined, { method: "POST" }),
  propFinder: (q: {
    sportsbook?: string;
    gameId?: number;
    playerId?: number;
    teamId?: number;
    category?: string;
    pickSide?: "over" | "under";
    gameDate?: string;
    minHitPct?: number;
    minGames?: number;
    minSample?: number;
    sort?: string;
    limit?: number;
    offset?: number;
  }) =>
    request<PropFinderList>("/prop-finder", {
      sportsbook: q.sportsbook,
      game_id: q.gameId,
      player_id: q.playerId,
      team_id: q.teamId,
      category: q.category,
      pick_side: q.pickSide,
      game_date: q.gameDate,
      min_hit_pct: q.minHitPct,
      min_games: q.minGames,
      min_sample: q.minSample,
      sort: q.sort ?? "hcs",
      limit: q.limit ?? 10,
      offset: q.offset ?? 0,
    }),
  propFinderDetail: (id: number) => request<PropFinderDetail>(`/prop-finder/${id}`),
  propFinderAnalyzer: (id: number) => request<PropAnalyzer>(`/prop-finder/${id}/analyzer`),
  parlaySearch: (body: ParlaySearchRequest) =>
    request<ParlaySearchResult>("/parlay-builder/search", undefined, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }, 60_000),
  propFinderManual: (body: {
    player_id: number;
    game_id: number;
    category_key: string;
    line: number;
    pick_side: "over" | "under";
    american_odds?: number;
    sportsbook_label?: string;
  }) =>
    request<PropFinderDetail>("/prop-finder/manual", undefined, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  trends: (q: {
    stat: string;
    line: number;
    lastN: number;
    minGames: number;
    days: number;
    sort: string;
  }) =>
    request<TrendExplorer>("/explorer/trends", {
      stat: q.stat,
      line: q.line,
      last_n: q.lastN,
      min_games: q.minGames,
      days: q.days,
      sort: q.sort,
    }),
};
