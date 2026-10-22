"use client";

import { TeamLogo } from "@/components/common/team-logo";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { Team } from "@/lib/types";
import { cn } from "@/lib/utils";

const ALL = "all";

export function TeamSelect({
  teams,
  value,
  onChange,
  excludeTeamId,
  allLabel = "All opponents",
  className,
}: {
  teams: Team[];
  value: number | null;
  onChange: (teamId: number | null) => void;
  excludeTeamId?: number | null;
  allLabel?: string;
  className?: string;
}) {
  const options = teams.filter((t) => t.id !== excludeTeamId);
  const byId = new Map(teams.map((t) => [String(t.id), t]));

  return (
    <Select
      value={value === null ? ALL : String(value)}
      onValueChange={(v) => onChange(v === ALL || v === null ? null : Number(v))}
    >
      <SelectTrigger
        aria-label="Opponent"
        className={cn("h-10! min-w-56 rounded-xl border-border bg-surface! px-3", className)}
      >
        <SelectValue>
          {(v: string) => {
            const team = byId.get(v);
            return team ? (
              <span className="flex items-center gap-2">
                <TeamLogo team={team} size={20} />
                vs {team.display_name}
              </span>
            ) : (
              allLabel
            );
          }}
        </SelectValue>
      </SelectTrigger>
      <SelectContent className="max-h-80 bg-popover" alignItemWithTrigger={false}>
        <SelectItem value={ALL}>{allLabel}</SelectItem>
        {options.map((team) => (
          <SelectItem key={team.id} value={String(team.id)}>
            <TeamLogo team={team} size={18} />
            {team.display_name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
