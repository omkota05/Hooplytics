import { MapPin } from "lucide-react";
import Link from "next/link";

import { TeamLogo } from "@/components/common/team-logo";
import { fmtShortDate, gameStatusLabel, venueLabel } from "@/lib/format";
import type { Game, Team } from "@/lib/types";
import { cn } from "@/lib/utils";

function TeamRow({ team, score, winner, showScore }: { team: Team; score: number | null; winner: boolean; showScore: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <TeamLogo team={team} size={30} />
      <span className={cn("flex-1 truncate font-medium", showScore && !winner && "text-muted-foreground")}>
        {team.display_name}
      </span>
      {showScore && <span className={cn("text-lg font-semibold tabular", !winner && "text-muted-foreground")}>{score}</span>}
    </div>
  );
}

export function StatusBadge({ game }: { game: Game }) {
  const styles: Record<Game["status"], string> = {
    scheduled: "bg-primary/15 text-[#9db5ff]",
    in_progress: "bg-over/15 text-over",
    final: "bg-secondary text-muted-foreground",
    postponed: "bg-push/15 text-push",
    canceled: "bg-under/15 text-under",
    suspended: "bg-push/15 text-push",
  };
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-semibold", styles[game.status])}>
      {game.status === "in_progress" && <span className="size-1.5 animate-pulse rounded-full bg-over" />}
      {gameStatusLabel(game)}
    </span>
  );
}

export function GameCard({ game, showDate = false }: { game: Game; showDate?: boolean }) {
  const showScore = game.status === "final" || game.status === "in_progress";
  const homeWins = (game.home_score ?? 0) > (game.away_score ?? 0);
  const venue = venueLabel(game);
  return (
    <Link
      href={`/matchups/${game.id}`}
      className="group block rounded-2xl border border-border bg-card/70 p-4 transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:bg-card hover:shadow-[0_16px_40px_-20px_rgb(79_124_255/0.55)]"
    >
      <div className="mb-3 flex items-center justify-between">
        <StatusBadge game={game} />
        <span className="text-xs text-muted-foreground">
          {showDate && `${fmtShortDate(game.game_date)} · `}
          {game.season_type !== 2 ? game.season_type_label : ""}
        </span>
      </div>
      <div className="space-y-2.5">
        <TeamRow team={game.away_team} score={game.away_score} winner={!homeWins} showScore={showScore} />
        <TeamRow team={game.home_team} score={game.home_score} winner={homeWins} showScore={showScore} />
      </div>
      {venue && (
        <p className="mt-3 flex items-center gap-1.5 truncate text-xs text-muted-foreground">
          <MapPin className="size-3 shrink-0" />
          {venue}
        </p>
      )}
      <p className="mt-2 text-xs font-medium text-electric opacity-0 transition-opacity group-hover:opacity-100">
        Analyze matchup →
      </p>
    </Link>
  );
}
