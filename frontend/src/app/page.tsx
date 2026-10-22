"use client";

import { ArrowRight, CalendarDays, Database, Flame, Trophy } from "lucide-react";
import Link from "next/link";
import useSWR from "swr";

import { PlayerAvatar } from "@/components/common/player-avatar";
import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { TeamLogo } from "@/components/common/team-logo";
import { GameCard } from "@/components/games/game-card";
import { PlayerSearch } from "@/components/search/player-search";
import { api } from "@/lib/api";
import { fmtDateTime, fmtDayHeading, fmtRelative } from "@/lib/format";
import { useSyncStatus } from "@/lib/hooks";
import type { Game } from "@/lib/types";

function groupByDate(games: Game[]) {
  const groups = new Map<string, Game[]>();
  for (const g of games) groups.set(g.game_date, [...(groups.get(g.game_date) ?? []), g]);
  return [...groups.entries()];
}

export default function DashboardPage() {
  const upcoming = useSWR("upcoming-3", () => api.upcomingGames(3), { refreshInterval: 60_000 });
  const performers = useSWR("top-performers", () => api.topPerformers(8));
  const recent = useSWR("recent-games", () => api.recentGames(1));

  return (
    <div className="space-y-8">
      <section className="panel relative z-10 px-6 py-8 sm:px-10 sm:py-10">
        <div className="pointer-events-none absolute inset-0 overflow-hidden rounded-2xl">
          <div className="absolute -top-24 right-0 h-72 w-72 rounded-full bg-violet/20 blur-3xl" />
          <div className="absolute -bottom-24 left-10 h-64 w-64 rounded-full bg-electric/20 blur-3xl" />
        </div>
        <div className="relative max-w-2xl">
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
            Every line, <span className="text-gradient">tested against history.</span>
          </h1>
          <p className="mt-2 text-muted-foreground">
            Search a player, set any line, and see exactly how often they cleared it: recent form,
            full seasons, or head-to-head against tonight&apos;s opponent.
          </p>
          <PlayerSearch size="lg" className="mt-6" placeholder="Search players, e.g. Jalen Brunson" />
        </div>
      </section>

      <DataStatusStrip />

      <section>
        <SectionHeader icon={<CalendarDays className="size-4 text-electric" />} title="Upcoming games" href="/matchups" />
        {upcoming.error ? (
          <ErrorState error={upcoming.error} onRetry={() => upcoming.mutate()} />
        ) : !upcoming.data ? (
          <LoadingRows rows={3} />
        ) : upcoming.data.length === 0 ? (
          <EmptyState title="No games in the next three days" description="The schedule refreshes automatically during sync." />
        ) : (
          <div className="space-y-6">
            {groupByDate(upcoming.data).slice(0, 2).map(([date, games]) => (
              <div key={date}>
                <h3 className="mb-3 text-sm font-medium text-muted-foreground">{fmtDayHeading(date)}</h3>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  {games.map((g) => (
                    <GameCard key={g.id} game={g} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_420px]">
        <section>
          <SectionHeader icon={<Flame className="size-4 text-under" />} title="Top performers · latest game day" />
          {performers.error ? (
            <ErrorState error={performers.error} />
          ) : !performers.data ? (
            <LoadingRows rows={4} />
          ) : performers.data.length === 0 ? (
            <EmptyState title="No box scores synced yet" />
          ) : (
            <div className="grid gap-2 sm:grid-cols-2">
              {performers.data.map(({ player, game, pts, reb, ast }) => {
                const isHome = player.team?.id === game.home_team.id;
                const opp = isHome ? game.away_team : game.home_team;
                return (
                  <Link
                    key={`${player.id}-${game.id}`}
                    href={`/players/${player.id}`}
                    className="flex items-center gap-3 rounded-xl border border-border bg-card/70 p-3 transition hover:border-primary/40"
                  >
                    <PlayerAvatar name={player.full_name} src={player.headshot_url} size={44} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{player.full_name}</p>
                      <p className="flex items-center gap-1 text-xs text-muted-foreground">
                        vs <TeamLogo team={opp} size={14} /> {opp.abbreviation}
                      </p>
                    </div>
                    <div className="text-right text-sm tabular">
                      <p className="text-lg font-bold">{pts}</p>
                      <p className="text-xs text-muted-foreground">
                        {reb} reb · {ast} ast
                      </p>
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </section>

        <section>
          <SectionHeader icon={<Trophy className="size-4 text-push" />} title="Latest results" />
          {recent.error ? (
            <ErrorState error={recent.error} />
          ) : !recent.data ? (
            <LoadingRows rows={4} />
          ) : recent.data.length === 0 ? (
            <EmptyState title="No completed games synced yet" />
          ) : (
            <div className="panel divide-y divide-border">
              {recent.data.map((g) => (
                <Link key={g.id} href={`/matchups/${g.id}`} className="flex items-center gap-3 px-4 py-3 text-sm hover:bg-secondary/30">
                  <ScoreLine game={g} />
                </Link>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function ScoreLine({ game }: { game: Game }) {
  const awayWon = (game.away_score ?? 0) > (game.home_score ?? 0);
  return (
    <div className="flex w-full items-center gap-2 tabular">
      <TeamLogo team={game.away_team} size={22} />
      <span className={awayWon ? "font-semibold" : "text-muted-foreground"}>
        {game.away_team.abbreviation} {game.away_score}
      </span>
      <span className="text-muted-foreground">@</span>
      <span className={!awayWon ? "font-semibold" : "text-muted-foreground"}>
        {game.home_team.abbreviation} {game.home_score}
      </span>
      <TeamLogo team={game.home_team} size={22} />
      <span className="ml-auto text-xs text-muted-foreground">{game.status_detail ?? "Final"}</span>
    </div>
  );
}

function SectionHeader({ icon, title, href }: { icon: React.ReactNode; title: string; href?: string }) {
  return (
    <div className="mb-3 flex items-center justify-between">
      <h2 className="flex items-center gap-2 font-semibold">
        {icon}
        {title}
      </h2>
      {href && (
        <Link href={href} className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          View all <ArrowRight className="size-3.5" />
        </Link>
      )}
    </div>
  );
}

function DataStatusStrip() {
  const { data, error } = useSyncStatus();
  if (error) {
    return (
      <ErrorState
        error={error}
        title="Backend unavailable"
        className="py-5"
      />
    );
  }
  if (!data) return <LoadingRows rows={1} />;
  const pending = data.seasons.reduce((n, s) => n + s.boxscores_pending, 0);
  const synced = data.seasons.reduce((n, s) => n + s.boxscores_synced, 0);
  return (
    <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <StatusTile
        label="Last data update"
        value={data.last_successful_sync_at ? fmtRelative(data.last_successful_sync_at) : "Never"}
        hint={data.last_successful_sync_at ? fmtDateTime(data.last_successful_sync_at) : "Run make sync"}
      />
      <StatusTile label="Games with box scores" value={synced.toLocaleString()} hint={`${data.seasons.length} seasons tracked`} />
      <StatusTile label="Player game logs" value={data.player_game_rows.toLocaleString()} hint={`${data.players.toLocaleString()} players`} />
      <StatusTile
        label="Historical backfill"
        value={pending === 0 ? "Complete" : `${pending.toLocaleString()} pending`}
        hint={data.is_running ? "Sync in progress…" : data.provider}
      />
    </section>
  );
}

function StatusTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="panel flex items-start gap-3 px-4 py-3.5">
      <Database className="mt-0.5 size-4 text-muted-foreground" />
      <div className="min-w-0">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-lg font-semibold">{value}</p>
        {hint && <p className="truncate text-xs text-muted-foreground">{hint}</p>}
      </div>
    </div>
  );
}
