"use client";

import { CalendarClock, History } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";

import { PlayerAnalysis } from "@/components/analysis/player-analysis";
import { PlayerAvatar } from "@/components/common/player-avatar";
import { Segmented } from "@/components/common/segmented";
import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { TeamLogo } from "@/components/common/team-logo";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError } from "@/lib/api";
import { ageFrom, fmtDateTime, fmtHeight, fmtLongDate, fmtNum, fmtShortDate } from "@/lib/format";
import { useCategories, useTeams } from "@/lib/hooks";
import type { PlayerProfile } from "@/lib/types";
import { cn } from "@/lib/utils";

export function PlayerProfileView({
  playerId,
  initialStat,
  initialOpponentId,
}: {
  playerId: number;
  initialStat?: string;
  initialOpponentId: number | null;
}) {
  const [season, setSeason] = useState<number | undefined>(undefined);
  const profile = useSWR(["profile", playerId, season], () => api.playerProfile(playerId, season), {
    keepPreviousData: true,
  });
  const categories = useCategories();
  const teams = useTeams();

  if (profile.error && !profile.data) {
    const notFound = profile.error instanceof ApiError && profile.error.status === 404;
    return (
      <ErrorState
        error={profile.error}
        title={notFound ? "Player not found" : "Could not load player"}
        onRetry={notFound ? undefined : () => profile.mutate()}
      />
    );
  }
  if (!profile.data) return <ProfileSkeleton />;

  const p = profile.data;
  return (
    <div className="space-y-6">
      <ProfileHeader profile={p} />
      <SeasonAveragesCard profile={p} onSeasonChange={setSeason} />

      {p.total_games_tracked === 0 ? (
        <EmptyState
          title="No synced games for this player yet"
          description="Box scores are still downloading, or this player has not appeared in a game in the synced seasons."
        />
      ) : categories.error || teams.error ? (
        <ErrorState error={categories.error ?? teams.error} title="Could not load filters" />
      ) : categories.data && teams.data ? (
        <PlayerAnalysis
          key={playerId}
          profile={p}
          categories={categories.data}
          teams={teams.data}
          initialStat={initialStat}
          initialOpponentId={initialOpponentId}
        />
      ) : (
        <Skeleton className="h-[520px] rounded-2xl bg-secondary/40" />
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
        <RecentGames playerId={playerId} />
        <div className="space-y-6">
          <UpcomingGames profile={p} />
          <TeamHistory profile={p} />
        </div>
      </div>
    </div>
  );
}

function ProfileHeader({ profile }: { profile: PlayerProfile }) {
  const { player } = profile;
  const team = player.team;
  const age = ageFrom(profile.birth_date);
  const facts = [
    player.position,
    player.jersey ? `#${player.jersey}` : null,
    fmtHeight(profile.height_in),
    profile.weight_lb ? `${Math.round(profile.weight_lb)} lb` : null,
    age ? `Age ${age}` : null,
  ].filter(Boolean);

  return (
    <section
      className="panel relative overflow-hidden"
      style={team?.color ? { backgroundImage: `linear-gradient(110deg, #${team.color}33, transparent 55%)` } : undefined}
    >
      {team && (
        <div className="pointer-events-none absolute -top-10 -right-10 opacity-[0.07]">
          <TeamLogo team={team} size={280} />
        </div>
      )}
      <div className="relative flex flex-col gap-5 p-5 sm:flex-row sm:items-end sm:p-6">
        <PlayerAvatar name={player.full_name} src={player.headshot_url} size={120} className="ring-2 ring-white/10" />
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex items-center gap-2 text-sm text-muted-foreground">
            {team ? (
              <>
                <TeamLogo team={team} size={20} />
                {team.display_name}
              </>
            ) : (
              <span>Not on a current NBA roster</span>
            )}
          </div>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">{player.full_name}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{facts.join(" · ")}</p>
        </div>
        <div className="text-sm text-muted-foreground sm:text-right">
          <p>
            <span className="font-semibold text-foreground tabular">{profile.total_games_tracked}</span> games
            synced
          </p>
          {profile.last_game_date && <p>Last game {fmtLongDate(profile.last_game_date)}</p>}
        </div>
      </div>
    </section>
  );
}

function SeasonAveragesCard({
  profile,
  onSeasonChange,
}: {
  profile: PlayerProfile;
  onSeasonChange: (season: number) => void;
}) {
  const avg = profile.season_averages;
  const tiles = avg
    ? [
        ["PTS", fmtNum(avg.pts)],
        ["REB", fmtNum(avg.reb)],
        ["AST", fmtNum(avg.ast)],
        ["3PM", fmtNum(avg.fg3m)],
        ["STL", fmtNum(avg.stl)],
        ["BLK", fmtNum(avg.blk)],
        ["TOV", fmtNum(avg.tov)],
        ["MIN", fmtNum(avg.minutes)],
        ["FG%", fmtNum(avg.fg_pct)],
        ["3P%", fmtNum(avg.fg3_pct)],
        ["FT%", fmtNum(avg.ft_pct)],
      ]
    : [];
  return (
    <section className="panel p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold">Season averages</h2>
          {avg && (
            <p className="text-sm text-muted-foreground">
              {avg.season_label} · {avg.games} games played · {avg.starts} starts
            </p>
          )}
        </div>
        {profile.available_seasons.length > 1 && avg && (
          <Segmented
            size="sm"
            options={profile.available_seasons.map((s) => ({ value: String(s), label: `${s - 1}-${String(s).slice(2)}` }))}
            value={String(avg.season)}
            onChange={(v) => onSeasonChange(Number(v))}
            ariaLabel="Season"
          />
        )}
      </div>
      {avg ? (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-6 lg:grid-cols-11">
          {tiles.map(([label, value], i) => (
            <div
              key={label}
              className={cn(
                "rounded-xl border border-border px-3 py-2.5",
                i < 3 ? "bg-gradient-to-b from-primary/15 to-transparent" : "bg-surface/60",
              )}
            >
              <p className="text-[11px] font-medium text-muted-foreground">{label}</p>
              <p className="text-xl font-semibold tabular">{value}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No games played in the synced seasons.</p>
      )}
    </section>
  );
}

function RecentGames({ playerId }: { playerId: number }) {
  const { data, error, mutate } = useSWR(["gamelog", playerId], () => api.gameLogs(playerId, 15));
  return (
    <section className="panel p-5">
      <h2 className="mb-3 flex items-center gap-2 font-semibold">
        <History className="size-4 text-electric" /> Recent game log
      </h2>
      {error ? (
        <ErrorState error={error} onRetry={() => mutate()} />
      ) : !data ? (
        <LoadingRows rows={6} />
      ) : data.length === 0 ? (
        <EmptyState title="No games synced yet" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm tabular">
            <thead className="text-[11px] tracking-wide text-muted-foreground uppercase">
              <tr className="border-b border-border">
                {["Date", "Opp", "Result", "MIN", "PTS", "REB", "AST", "3PM", "STL", "BLK", "TOV", "FG", "+/-"].map((h, i) => (
                  <th key={h} className={cn("px-2 py-2 font-medium", i < 3 ? "text-left" : "text-right")}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((g) => (
                <tr key={g.game_id} className="border-b border-border/50 hover:bg-secondary/30">
                  <td className="px-2 py-2 whitespace-nowrap">{fmtShortDate(g.game_date)}</td>
                  <td className="px-2 py-2">
                    <Link href={`/matchups/${g.game_id}`} className="flex items-center gap-1.5 hover:text-electric">
                      <span className="text-muted-foreground">{g.is_home ? "vs" : "@"}</span>
                      <TeamLogo team={g.opponent} size={18} />
                      {g.opponent.abbreviation}
                    </Link>
                  </td>
                  <td className="px-2 py-2 whitespace-nowrap">
                    {g.result && (
                      <span className={g.result === "W" ? "text-over" : "text-under"}>
                        {g.result} {g.team_score}–{g.opponent_score}
                      </span>
                    )}
                  </td>
                  {g.did_not_play ? (
                    <td colSpan={10} className="px-2 py-2 text-right text-xs text-muted-foreground">
                      DNP{g.dnp_reason ? ` — ${g.dnp_reason.toLowerCase()}` : ""}
                    </td>
                  ) : (
                    <>
                      <td className="px-2 py-2 text-right text-muted-foreground">{fmtNum(g.minutes, 0)}</td>
                      <td className="px-2 py-2 text-right font-semibold">{g.pts}</td>
                      <td className="px-2 py-2 text-right">{g.reb}</td>
                      <td className="px-2 py-2 text-right">{g.ast}</td>
                      <td className="px-2 py-2 text-right">{g.fg3m}</td>
                      <td className="px-2 py-2 text-right">{g.stl}</td>
                      <td className="px-2 py-2 text-right">{g.blk}</td>
                      <td className="px-2 py-2 text-right">{g.tov}</td>
                      <td className="px-2 py-2 text-right text-muted-foreground">
                        {g.fgm}-{g.fga}
                      </td>
                      <td className={cn("px-2 py-2 text-right", (g.plus_minus ?? 0) > 0 ? "text-over" : (g.plus_minus ?? 0) < 0 ? "text-under" : "")}>
                        {g.plus_minus !== null && g.plus_minus > 0 ? `+${g.plus_minus}` : g.plus_minus}
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function UpcomingGames({ profile }: { profile: PlayerProfile }) {
  const team = profile.player.team;
  return (
    <section className="panel p-5">
      <h2 className="mb-3 flex items-center gap-2 font-semibold">
        <CalendarClock className="size-4 text-violet" /> Upcoming games
      </h2>
      {!team ? (
        <p className="text-sm text-muted-foreground">Not on a current roster.</p>
      ) : profile.upcoming_games.length === 0 ? (
        <p className="text-sm text-muted-foreground">No scheduled games in the next two weeks.</p>
      ) : (
        <ul className="space-y-2">
          {profile.upcoming_games.map((g) => {
            const home = g.home_team.id === team.id;
            const opp = home ? g.away_team : g.home_team;
            return (
              <li key={g.id}>
                <Link
                  href={`/matchups/${g.id}?player=${profile.player.id}`}
                  className="flex items-center gap-3 rounded-xl border border-border bg-surface/60 px-3 py-2.5 transition hover:border-primary/40"
                >
                  <TeamLogo team={opp} size={28} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      {home ? "vs" : "@"} {opp.display_name}
                    </p>
                    <p className="text-xs text-muted-foreground">{fmtDateTime(g.start_time)}</p>
                  </div>
                  <span className="text-xs text-electric">H2H →</span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function TeamHistory({ profile }: { profile: PlayerProfile }) {
  if (profile.team_history.length === 0) return null;
  return (
    <section className="panel p-5">
      <h2 className="mb-3 font-semibold">Team history</h2>
      <ul className="space-y-2 text-sm">
        {profile.team_history.map((h) => (
          <li key={`${h.season}-${h.team.id}`} className="flex items-center gap-3">
            <span className="w-16 text-muted-foreground tabular">{h.season_label}</span>
            <TeamLogo team={h.team} size={20} />
            <span className="flex-1">{h.team.display_name}</span>
            <span className="text-muted-foreground tabular">{h.games_played} GP</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function ProfileSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-44 rounded-2xl bg-secondary/40" />
      <Skeleton className="h-36 rounded-2xl bg-secondary/40" />
      <Skeleton className="h-[520px] rounded-2xl bg-secondary/40" />
    </div>
  );
}
