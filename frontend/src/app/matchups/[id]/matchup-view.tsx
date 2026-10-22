"use client";

import { CalendarClock, History, MapPin, Users } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";

import { MatchupComparison } from "@/components/analysis/matchup-comparison";
import { PlayerAvatar } from "@/components/common/player-avatar";
import { EmptyState, ErrorState } from "@/components/common/states";
import { TeamLogo } from "@/components/common/team-logo";
import { StatusBadge } from "@/components/games/game-card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError } from "@/lib/api";
import { fmtDateTime, fmtLongDate, fmtNum, venueLabel } from "@/lib/format";
import { useCategories } from "@/lib/hooks";
import type { BoxScoreLine, GameDetail, GamePlayer, Team } from "@/lib/types";
import { cn } from "@/lib/utils";

export function MatchupView({ gameId, initialPlayerId }: { gameId: number; initialPlayerId: number | null }) {
  const { data, error, mutate } = useSWR(["game", gameId], () => api.gameDetail(gameId), { refreshInterval: 120_000 });
  const categories = useCategories();
  const [selectedId, setSelectedId] = useState<number | null>(initialPlayerId);

  if (error && !data) {
    const notFound = error instanceof ApiError && error.status === 404;
    return <ErrorState error={error} title={notFound ? "Game not found" : "Could not load game"} onRetry={() => mutate()} />;
  }
  if (!data) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-40 rounded-2xl bg-secondary/40" />
        <Skeleton className="h-96 rounded-2xl bg-secondary/40" />
      </div>
    );
  }

  const { game } = data;
  const all = [...data.away_players, ...data.home_players];
  const selected = all.find((p) => p.player.id === selectedId) ?? null;
  const selectedIsHome = selected ? data.home_players.includes(selected) : false;
  const opponent = selected ? (selectedIsHome ? game.away_team : game.home_team) : null;

  return (
    <div className="space-y-6">
      <GameHeader detail={data} />

      <div className="grid gap-6 xl:grid-cols-[340px_minmax(0,1fr)]">
        <aside className="space-y-4">
          <div className="panel p-4">
            <h2 className="mb-1 flex items-center gap-2 font-semibold">
              <Users className="size-4 text-electric" /> Select a player
            </h2>
            <p className="mb-3 text-xs text-muted-foreground">
              {data.players_source === "boxscore"
                ? "Players who appeared in this game."
                : "Current rosters. Availability and injuries are not tracked."}{" "}
              Sorted by recent minutes.
            </p>
            <RosterList team={game.away_team} players={data.away_players} selectedId={selectedId} onSelect={setSelectedId} />
            <div className="my-3 border-t border-border" />
            <RosterList team={game.home_team} players={data.home_players} selectedId={selectedId} onSelect={setSelectedId} />
          </div>
        </aside>

        <div className="min-w-0 space-y-6">
          {selected && opponent && categories.data ? (
            <MatchupComparison
              key={selected.player.id}
              player={selected.player}
              recentForm={selected.recent}
              opponent={opponent}
              categories={categories.data}
            />
          ) : (
            <EmptyState
              className="panel h-80"
              icon={<Users className="size-6 text-muted-foreground" />}
              title="Pick a player to analyze"
              description="Compare their recent production against their history versus this opponent, at any line."
            />
          )}
          {(data.home_boxscore.length > 0 || data.away_boxscore.length > 0) && (
            <div className="grid gap-6 lg:grid-cols-2">
              <BoxScoreTable team={game.away_team} lines={data.away_boxscore} />
              <BoxScoreTable team={game.home_team} lines={data.home_boxscore} />
            </div>
          )}
          <PreviousMeetings detail={data} />
        </div>
      </div>
    </div>
  );
}

function GameHeader({ detail }: { detail: GameDetail }) {
  const { game } = detail;
  const showScore = game.status === "final" || game.status === "in_progress";
  const venue = venueLabel(game);
  const side = (team: Team, score: number | null, align: "left" | "right") => (
    <div className={cn("flex flex-1 items-center gap-4", align === "right" && "flex-row-reverse text-right")}>
      <TeamLogo team={team} size={72} />
      <div>
        <p className="text-sm text-muted-foreground">{team.location}</p>
        <p className="text-xl font-bold sm:text-2xl">{team.short_name}</p>
      </div>
      {showScore && <p className="mx-2 text-4xl font-bold tabular">{score}</p>}
    </div>
  );
  return (
    <section
      className="panel overflow-hidden"
      style={{
        backgroundImage: `linear-gradient(100deg, #${game.away_team.color ?? "1b2656"}30, transparent 40%, transparent 60%, #${game.home_team.color ?? "1b2656"}30)`,
      }}
    >
      <div className="flex flex-col items-center gap-6 p-6 sm:flex-row">
        {side(game.away_team, game.away_score, "left")}
        <div className="flex flex-col items-center gap-2 text-center">
          <StatusBadge game={game} />
          <span className="text-xs text-muted-foreground">{game.season_type_label} · {game.season_label}</span>
        </div>
        {side(game.home_team, game.home_score, "right")}
      </div>
      <div className="flex flex-wrap justify-center gap-x-6 gap-y-1 border-t border-border px-6 py-3 text-sm text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <CalendarClock className="size-4" /> {fmtDateTime(game.start_time)}
        </span>
        {venue && (
          <span className="flex items-center gap-1.5">
            <MapPin className="size-4" /> {venue}
            {game.neutral_site && " (neutral site)"}
          </span>
        )}
      </div>
    </section>
  );
}

function RosterList({
  team,
  players,
  selectedId,
  onSelect,
}: {
  team: Team;
  players: GamePlayer[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  return (
    <div>
      <p className="mb-2 flex items-center gap-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
        <TeamLogo team={team} size={18} /> {team.display_name}
      </p>
      {players.length === 0 ? (
        <p className="text-sm text-muted-foreground">No roster data.</p>
      ) : (
        <ul className="space-y-1">
          {players.map(({ player, recent }) => (
            <li key={player.id}>
              <button
                onClick={() => onSelect(player.id)}
                className={cn(
                  "flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition",
                  selectedId === player.id ? "bg-primary/20 ring-1 ring-primary/40" : "hover:bg-secondary/60",
                )}
              >
                <PlayerAvatar name={player.full_name} src={player.headshot_url} size={30} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{player.full_name}</span>
                  <span className="block text-[11px] text-muted-foreground tabular">
                    {recent
                      ? `L${recent.games}: ${fmtNum(recent.pts)} pts · ${fmtNum(recent.reb)} reb · ${fmtNum(recent.ast)} ast`
                      : "No synced games"}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function BoxScoreTable({ team, lines }: { team: Team; lines: BoxScoreLine[] }) {
  return (
    <section className="panel overflow-hidden">
      <h3 className="flex items-center gap-2 border-b border-border px-4 py-3 text-sm font-semibold">
        <TeamLogo team={team} size={20} /> {team.display_name} box score
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs tabular">
          <thead className="text-[10px] tracking-wide text-muted-foreground uppercase">
            <tr>
              {["Player", "MIN", "PTS", "REB", "AST", "3PM", "STL", "BLK", "TOV"].map((h, i) => (
                <th key={h} className={cn("px-2 py-2", i === 0 ? "text-left" : "text-right")}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => (
              <tr key={l.player.id} className="border-t border-border/50 hover:bg-secondary/30">
                <td className="px-2 py-1.5">
                  <Link href={`/players/${l.player.id}`} className="hover:text-electric">
                    {l.player.full_name}
                    {l.starter && <span className="ml-1 text-muted-foreground">·S</span>}
                  </Link>
                </td>
                {l.did_not_play ? (
                  <td colSpan={8} className="px-2 py-1.5 text-right text-muted-foreground">
                    DNP
                  </td>
                ) : (
                  [l.minutes, l.pts, l.reb, l.ast, l.fg3m, l.stl, l.blk, l.tov].map((v, i) => (
                    <td key={i} className={cn("px-2 py-1.5 text-right", i === 1 && "font-semibold")}>
                      {v === null ? "—" : i === 0 ? Math.round(v) : v}
                    </td>
                  ))
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function PreviousMeetings({ detail }: { detail: GameDetail }) {
  const { game, previous_meetings: meetings } = detail;
  return (
    <section className="panel p-5">
      <h3 className="mb-3 flex items-center gap-2 font-semibold">
        <History className="size-4 text-violet" /> Previous meetings
      </h3>
      {meetings.length === 0 ? (
        <p className="text-sm text-muted-foreground">No earlier meetings in the synced seasons.</p>
      ) : (
        <ul className="divide-y divide-border text-sm">
          {meetings.map((m) => {
            const winner = (m.home_score ?? 0) > (m.away_score ?? 0) ? m.home_team : m.away_team;
            return (
              <li key={m.id}>
                <Link href={`/matchups/${m.id}`} className="flex items-center gap-3 py-2 hover:text-electric">
                  <span className="w-32 text-muted-foreground">{fmtLongDate(m.game_date).replace(/^\w+, /, "")}</span>
                  <span className="tabular">
                    {m.away_team.abbreviation} {m.away_score} @ {m.home_team.abbreviation} {m.home_score}
                  </span>
                  <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
                    <TeamLogo team={winner} size={16} /> {winner.abbreviation} won
                    {m.season_type !== 2 && " · Playoffs"}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
      <p className="mt-3 text-xs text-muted-foreground">
        Team results between {game.away_team.short_name} and {game.home_team.short_name} across synced seasons.
      </p>
    </section>
  );
}
