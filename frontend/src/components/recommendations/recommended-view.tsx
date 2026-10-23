"use client";

import { AlertTriangle, Sparkles, Trophy } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import useSWR from "swr";

import { LineInput } from "@/components/analysis/line-input";
import { PlayerAvatar } from "@/components/common/player-avatar";
import { Segmented } from "@/components/common/segmented";
import { EmptyState, ErrorState, LoadingRows, Spinner } from "@/components/common/states";
import { TeamLogo } from "@/components/common/team-logo";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { fmtDateTime, fmtNum, fmtPct, fmtProbability, fmtShortDate } from "@/lib/format";
import { useCategories, useTeams } from "@/lib/hooks";
import type { GameWinnerRecommendation, PlayerPropRecommendation, Recommendations } from "@/lib/types";
import { cn } from "@/lib/utils";

function propEmptyMessage(data: Recommendations, minProb: number): string {
  const p = data.meta.pipeline;
  if (p.upcoming_games === 0) {
    return "No upcoming games in this window. Run sync (make sync) or widen the date range.";
  }
  if (!data.meta.player_model_version) {
    return "Player ML models are missing. Train with make ml-train and reload predictions.";
  }
  if (p.rotation_player_slots === 0) {
    return "Upcoming games were found but no rotation players met the minutes threshold. Check roster sync.";
  }
  if (data.errors.length > 0 && p.props_after_dedupe === 0) {
    return `Prediction errors: ${data.errors.slice(0, 2).join(" ")}`;
  }
  if (p.props_after_dedupe > 0 && p.props_filtered_by_query > 0) {
    return `${p.props_after_dedupe} model picks exist but filters removed all of them (min probability ${minProb}). Lower the threshold or clear filters.`;
  }
  if (p.props_candidates_before_dedupe === 0) {
    return `Scanned ${p.rotation_player_slots} player slots across ${p.upcoming_games} games but no ML props could be built (${p.props_skipped_no_line} missing synthetic lines, ${p.props_skipped_ml} ML skips).`;
  }
  return "Try lowering min probability or widening the date window.";
}

function probClass(p: number) {
  if (p >= 0.68) return "text-over";
  if (p >= 0.58) return "text-electric";
  return "text-muted-foreground";
}

export function RecommendedView() {
  const categories = useCategories();
  const teams = useTeams();
  const [tab, setTab] = useState<"props" | "games">("props");
  const [days, setDays] = useState<"1" | "3" | "7">("3");
  const [minProb, setMinProb] = useState(0.55);
  const [side, setSide] = useState<"" | "over" | "under">("");
  const [category, setCategory] = useState("");
  const [teamId, setTeamId] = useState<number | "">("");
  const [search, setSearch] = useState("");
  const [todayOnly, setTodayOnly] = useState(false);
  const [expand, setExpand] = useState(false);
  const [view, setView] = useState<"cards" | "table">("cards");
  const [customLine, setCustomLine] = useState(19.5);
  const [selected, setSelected] = useState<PlayerPropRecommendation | null>(null);

  const gameDate = todayOnly ? new Date().toISOString().slice(0, 10) : undefined;

  const { data, error, isValidating, mutate } = useSWR(
    ["recommendations", days, minProb, side, category, teamId, search, gameDate, expand],
    () =>
      api.recommendations({
        days: Number(days),
        expandPlayerProps: expand,
        minProbability: minProb,
        side: side || undefined,
        category: category || undefined,
        teamId: teamId === "" ? undefined : teamId,
        q: search || undefined,
        gameDate,
        sort: "probability",
      }),
    { revalidateOnFocus: true, dedupingInterval: 60_000 },
  );

  const customPred = useSWR(
    selected
      ? ["custom-prop", selected.player.id, selected.game.id, selected.category, customLine]
      : null,
    () =>
      api.customPlayerProp({
        playerId: selected!.player.id,
        gameId: selected!.game.id,
        category: selected!.category,
        line: customLine,
      }),
  );

  const games = useMemo(() => data?.game_winners ?? [], [data]);

  return (
    <div className="space-y-6">
      <header className="panel relative overflow-hidden p-6">
        <div className="pointer-events-none absolute -right-10 -top-10 h-56 w-56 rounded-full bg-electric/20 blur-3xl" />
        <div className="relative flex flex-wrap items-start justify-between gap-4">
          <div className="flex gap-4">
            <span className="flex size-11 items-center justify-center rounded-2xl bg-gradient-to-br from-electric/30 to-violet/30">
              <Sparkles className="size-6 text-electric" />
            </span>
            <div>
              <h1 className="text-2xl font-bold tracking-tight">Recommended</h1>
              <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                ML-ranked player props and game-winner probabilities for upcoming games. Lines are{" "}
                <b className="text-foreground">synthetic model thresholds</b>, not sportsbook odds. High
                probability is not a guaranteed edge.
              </p>
            </div>
          </div>
          {data?.meta && (
            <div className="text-right text-xs text-muted-foreground">
              <p>Generated {fmtDateTime(data.meta.generated_at)}</p>
              <p>Player model {data.meta.player_model_version ?? "—"}</p>
              <p>Game model {data.meta.game_winner_model_version ?? "—"}</p>
            </div>
          )}
        </div>
      </header>

      <div className="panel flex flex-wrap items-end gap-4 p-4">
        <Field label="Window">
          <Segmented
            value={days}
            onChange={setDays}
            options={[
              { value: "1", label: "Today+" },
              { value: "3", label: "3 days" },
              { value: "7", label: "7 days" },
            ]}
          />
        </Field>
        <Field label="Min model prob">
          <Input
            type="number"
            min={0.5}
            max={0.95}
            step={0.01}
            value={minProb}
            onChange={(e) => setMinProb(Number(e.target.value))}
            className="w-24"
          />
        </Field>
        <Field label="Side">
          <Segmented
            value={side || "all"}
            onChange={(v) => setSide(v === "all" ? "" : (v as "over" | "under"))}
            options={[
              { value: "all", label: "Both" },
              { value: "over", label: "Over" },
              { value: "under", label: "Under" },
            ]}
          />
        </Field>
        <Field label="Search">
          <Input placeholder="Player name" value={search} onChange={(e) => setSearch(e.target.value)} className="w-40" />
        </Field>
        {categories.data && (
          <Field label="Category">
            <select
              className="h-9 rounded-lg border border-border bg-surface px-2 text-sm"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              <option value="">All</option>
              {categories.data.map((c) => (
                <option key={c.key} value={c.key}>{c.short_label}</option>
              ))}
            </select>
          </Field>
        )}
        {teams.data && (
          <Field label="Team">
            <select
              className="h-9 rounded-lg border border-border bg-surface px-2 text-sm"
              value={teamId}
              onChange={(e) => setTeamId(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">All</option>
              {teams.data.map((t) => (
                <option key={t.id} value={t.id}>{t.abbreviation}</option>
              ))}
            </select>
          </Field>
        )}
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input type="checkbox" checked={todayOnly} onChange={(e) => setTodayOnly(e.target.checked)} />
          Today only
        </label>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input type="checkbox" checked={expand} onChange={(e) => setExpand(e.target.checked)} />
          All categories / player
        </label>
        <Field label="View">
          <Segmented
            value={view}
            onChange={setView}
            options={[
              { value: "cards", label: "Cards" },
              { value: "table", label: "Table" },
            ]}
          />
        </Field>
        {isValidating && <Spinner />}
      </div>

      {data?.errors && data.errors.length > 0 && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
          {data.errors.join(" · ")}
        </div>
      )}

      <Tabs value={tab} onValueChange={(v) => setTab(v as "props" | "games")}>
        <TabsList>
          <TabsTrigger value="props">Player props</TabsTrigger>
          <TabsTrigger value="games">Game winners</TabsTrigger>
        </TabsList>

        <TabsContent value="props" className="mt-4 space-y-4">
          {error && !data ? (
            <ErrorState error={error} onRetry={() => mutate()} />
          ) : !data ? (
            <LoadingRows rows={6} />
          ) : data.player_props.length === 0 ? (
            <EmptyState title="No prop recommendations" description={propEmptyMessage(data, minProb)} />
          ) : view === "cards" ? (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {data.player_props.map((p) => (
                <PropCard key={`${p.player.id}-${p.game.id}-${p.category}`} prop={p} onSelect={() => setSelected(p)} />
              ))}
            </div>
          ) : (
            <PropsTable props={data.player_props} onSelect={setSelected} />
          )}
        </TabsContent>

        <TabsContent value="games" className="mt-4 space-y-4">
          {!data ? (
            <LoadingRows rows={4} />
          ) : games.length === 0 ? (
            <EmptyState title="No upcoming games" description="Sync schedule data or widen the window." />
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              {games.map((g) => (
                <GameWinnerCard key={g.game.id} row={g} />
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>

      {selected && (
        <div className="panel fixed inset-x-4 bottom-4 z-50 mx-auto max-w-xl space-y-3 p-5 shadow-2xl lg:static lg:inset-auto lg:max-w-none">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h3 className="font-semibold">{selected.player.full_name}</h3>
              <p className="text-sm text-muted-foreground">
                {selected.category_label} · synthetic line {selected.line} · vs {selected.opponent.abbreviation}
              </p>
            </div>
            <Button variant="ghost" size="sm" onClick={() => setSelected(null)}>Close</Button>
          </div>
          <p className={cn("text-2xl font-bold tabular", probClass(selected.model_probability))}>
            Model {selected.pick_side} {fmtProbability(selected.model_probability)}
          </p>
          <p className="text-sm text-muted-foreground">
            Projected {fmtNum(selected.predicted_mean)} (σ {fmtNum(selected.predicted_std_dev)}) · {selected.games_used}{" "}
            prior games · {selected.probability_status}
          </p>
          <div className="flex flex-wrap gap-2">
            {selected.historical_hit_rates.map((h) => (
              <Badge key={h.window} variant="secondary">
                {h.window}: {h.over_pct != null ? fmtPct(h.over_pct) : "—"} over ({h.games}g)
              </Badge>
            ))}
          </div>
          <div className="flex flex-wrap items-end gap-3 border-t border-border pt-3">
            <Field label="Custom line">
              <LineInput value={customLine} onChange={setCustomLine} />
            </Field>
            {customPred.data && (
              <p className="text-sm">
                Custom: O {fmtProbability(customPred.data.p_over)} / U {fmtProbability(customPred.data.p_under)}
              </p>
            )}
            <Link href={selected.player_analysis_href} className="ml-auto text-sm text-electric hover:underline">
              Full player analysis →
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">{label}</span>
      {children}
    </div>
  );
}

function PropCard({ prop, onSelect }: { prop: PlayerPropRecommendation; onSelect: () => void }) {
  return (
    <Card className="cursor-pointer border-border/80 bg-surface/80 p-4 transition hover:border-electric/40" onClick={onSelect}>
      <div className="flex items-start gap-3">
        <PlayerAvatar name={prop.player.full_name} src={prop.player.headshot_url} size={44} />
        <div className="min-w-0 flex-1">
          <p className="font-semibold truncate">{prop.player.full_name}</p>
          <p className="text-xs text-muted-foreground">
            {prop.category_label} · {prop.pick_side.toUpperCase()} {prop.line}
            <span className="ml-1 rounded bg-secondary px-1">synthetic</span>
          </p>
        </div>
        <span className={cn("text-lg font-bold tabular", probClass(prop.model_probability))}>
          {fmtProbability(prop.model_probability)}
        </span>
      </div>
      <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          vs <TeamLogo team={prop.opponent} size={16} /> {prop.opponent.abbreviation}
        </span>
        <span>{fmtShortDate(prop.game.game_date)}</span>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        Proj {fmtNum(prop.predicted_mean)} · L10 over {fmtPct(prop.historical_hit_rates.find((h) => h.window === "L10")?.over_pct ?? null)}
      </p>
    </Card>
  );
}

function PropsTable({
  props,
  onSelect,
}: {
  props: PlayerPropRecommendation[];
  onSelect: (p: PlayerPropRecommendation) => void;
}) {
  return (
    <div className="panel overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-xs uppercase text-muted-foreground">
          <tr>
            <th className="p-3">Player</th>
            <th className="p-3">Pick</th>
            <th className="p-3">Prob</th>
            <th className="p-3">Proj</th>
            <th className="p-3">Game</th>
          </tr>
        </thead>
        <tbody>
          {props.map((p) => (
            <tr key={`${p.player.id}-${p.game.id}-${p.category}`} className="border-t border-border/60 hover:bg-primary/5" onClick={() => onSelect(p)}>
              <td className="p-3">{p.player.full_name}</td>
              <td className="p-3">{p.category_label} {p.pick_side} {p.line}</td>
              <td className={cn("p-3 font-semibold", probClass(p.model_probability))}>{fmtProbability(p.model_probability)}</td>
              <td className="p-3">{fmtNum(p.predicted_mean)}</td>
              <td className="p-3 text-xs text-muted-foreground">{fmtDateTime(p.game.start_time)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GameWinnerCard({ row }: { row: GameWinnerRecommendation }) {
  const homeFav = row.home_win_probability >= row.away_win_probability;
  return (
    <Card className="border-border/80 bg-surface/80 p-5">
      <div className="flex items-center justify-between gap-2">
        <Link href={row.matchup_href} className="flex items-center gap-2 hover:text-electric">
          <TeamLogo team={row.game.away_team} size={28} />
          <span className="text-muted-foreground">@</span>
          <TeamLogo team={row.game.home_team} size={28} />
          <span className="font-medium">{row.game.away_team.abbreviation} @ {row.game.home_team.abbreviation}</span>
        </Link>
        <Trophy className="size-4 text-violet" />
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{fmtDateTime(row.game.start_time)}</p>
      <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <div>
          <p className="text-xs text-muted-foreground">Model ({row.selected_model})</p>
          <p className={cn("text-lg font-bold", probClass(Math.max(row.home_win_probability, row.away_win_probability)))}>
            {homeFav ? row.game.home_team.abbreviation : row.game.away_team.abbreviation}{" "}
            {fmtProbability(homeFav ? row.home_win_probability : row.away_win_probability)}
          </p>
          {row.calibration_applied && (
            <p className="text-[10px] text-muted-foreground">Raw home {fmtProbability(row.model_home_win_probability_raw)}</p>
          )}
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Elo home win</p>
          <p className="text-lg font-semibold">{fmtProbability(row.elo_home_win_probability)}</p>
        </div>
      </div>
      {row.warnings.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-amber-200/90">
          {row.warnings.map((w) => (
            <li key={w.code} className="flex gap-1">
              <AlertTriangle className="mt-0.5 size-3 shrink-0" /> {w.message}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-[11px] text-muted-foreground">
        Status: {row.probability_status} · v{row.model_version}
      </p>
    </Card>
  );
}
