"use client";

import { useState } from "react";
import useSWR from "swr";

import { EmptyState, ErrorState, LoadingRows } from "@/components/common/states";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { mlApi } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";

import { CATEGORY_ORDER, CATEGORY_SHORT, StatusBadge, WarningList, fmt, pct } from "./ml-shared";

const CONTEXT_LABELS: Record<string, string> = {
  minutes_l10: "Minutes L10",
  minutes_trend: "Minutes trend (L5−L20)",
  pts_l10: "PTS L10",
  pts_season: "PTS season",
  reb_l10: "REB L10",
  ast_l10: "AST L10",
  fg3m_l10: "3PM L10",
  fga_l10: "FGA L10",
  fg3a_l10: "3PA L10",
  fga_share_l10: "Team FGA share L10",
  start_rate_l10: "Start rate L10",
  team_rest_days: "Team rest days",
  b2b: "Back-to-back",
  days_since_last_app: "Days since last appearance",
  opp_allowed_pts_l10: "Opp pts allowed L10",
  opp_allowed_reb_l10: "Opp reb allowed L10",
  opp_allowed_ast_l10: "Opp ast allowed L10",
  opp_allowed_fg3m_l10: "Opp 3PM allowed L10",
  opp_team_pace_l10: "Opp pace proxy L10",
  h2h_n: "Prior meetings",
  h2h_delta_pts: "H2H pts adj (shrunk)",
};

export function PlayerExplorer() {
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<{ playerId: number; gameId: number } | null>(null);
  const list = useSWR(["ml-upcoming", q], () => mlApi.upcoming({ q: q || undefined, limit: 60 }));
  return (
    <div className="grid gap-4 md:grid-cols-[280px_minmax(0,1fr)]">
      <Card className="p-3">
        <Input placeholder="Search upcoming players" value={q} onChange={(e) => setQ(e.target.value)} />
        <p className="mt-2 text-[11px] text-muted-foreground">
          {list.data ? `${list.data.total} players with an upcoming game · batch ${list.data.batch_seconds ?? "cached"}s` : "Loading…"}
        </p>
        {list.error && <ErrorState error={list.error} />}
        <div className="mt-2 max-h-[520px] overflow-y-auto">
          {list.data?.rows.map((r) => (
            <button
              key={`${r.player_id}-${r.game_id}`}
              onClick={() => setSelected({ playerId: r.player_id, gameId: r.game_id })}
              className="flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-left text-sm hover:bg-secondary/60"
            >
              <span>
                <span className="font-medium">{r.player_name}</span>{" "}
                <span className="text-xs text-muted-foreground">{r.team_abbreviation} vs {r.opponent_abbreviation}</span>
              </span>
              <span className="text-xs text-muted-foreground">PRA {r.pra.toFixed(1)}</span>
            </button>
          ))}
        </div>
      </Card>
      {selected ? <ProjectionPanel {...selected} /> : <EmptyState title="Select a player" description="Projections are for each player's next scheduled game." />}
    </div>
  );
}

function ProjectionPanel({ playerId, gameId }: { playerId: number; gameId: number }) {
  const proj = useSWR(["ml-player", playerId, gameId], () => mlApi.player(playerId, gameId));
  const lines = useSWR(proj.data ? ["ml-lines", proj.data.player_name] : null, () => mlApi.comparison({ q: proj.data!.player_name, limit: 60 }));
  const [cat, setCat] = useState("pts");
  const [line, setLine] = useState("");
  const est = useSWR(line && !Number.isNaN(Number(line)) ? ["ml-prop", playerId, gameId, cat, line] : null, () =>
    mlApi.prop({ playerId, gameId, category: cat, line: Number(line) }),
  );
  if (proj.error) return <ErrorState error={proj.error} />;
  if (!proj.data) return <LoadingRows />;
  const p = proj.data;
  const myLines = (lines.data?.rows ?? []).filter((r) => r.player_id === playerId);
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-lg font-semibold">
            {p.player_name} <span className="text-sm text-muted-foreground">{p.team_abbreviation} {p.is_home ? "vs" : "@"} {p.opponent_abbreviation} · {fmtDateTime(p.start_time)}</span>
          </p>
          <p className="text-xs text-muted-foreground">
            projected minutes {p.projected_minutes} · {p.appearances} prior appearances ({p.season_appearances} this season) · model {p.model_version}
          </p>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {CATEGORY_ORDER.map((c) => {
            const x = p.categories.find((k) => k.category === c)!;
            return (
              <div key={c} className="rounded-lg border border-border/60 p-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-muted-foreground">{CATEGORY_SHORT[c]}</span>
                  <StatusBadge status={x.probability_status} />
                </div>
                <p className="mt-1 text-xl font-semibold">{x.mean.toFixed(1)}</p>
                <p className="text-[11px] text-muted-foreground">median {x.median} · 80% range {x.p10}–{x.p90}</p>
              </div>
            );
          })}
        </div>
        <p className="mt-3 text-[11px] text-muted-foreground">{p.disclaimer} Data synced {p.data_last_sync_at ? fmtDateTime(p.data_last_sync_at) : "—"}.</p>
        {p.warnings.length > 0 && <div className="mt-2"><WarningList warnings={p.warnings} /></div>}
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="p-4">
          <p className="mb-2 text-sm font-semibold">Pregame context used by the model</p>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            {Object.entries(CONTEXT_LABELS).map(([k, label]) => (
              <div key={k} className="flex justify-between border-b border-border/30 py-0.5">
                <span className="text-muted-foreground">{label}</span>
                <span>{fmt(p.context[k] ?? null, k.includes("share") || k.includes("rate") ? 3 : 1)}</span>
              </div>
            ))}
          </div>
        </Card>
        <Card className="p-4">
          <p className="mb-2 text-sm font-semibold">Distribution at a custom line</p>
          <div className="flex gap-2">
            <select className="rounded-md border border-border bg-background px-2 text-sm" value={cat} onChange={(e) => setCat(e.target.value)}>
              {CATEGORY_ORDER.map((c) => <option key={c} value={c}>{CATEGORY_SHORT[c]}</option>)}
            </select>
            <Input placeholder="Line, e.g. 24.5" value={line} onChange={(e) => setLine(e.target.value)} className="max-w-36" />
          </div>
          {est.data && (
            <div className="mt-3 space-y-1 text-sm">
              <p>Over {pct(est.data.p_over)} · Under {pct(est.data.p_under)} · Push {pct(est.data.p_push)}</p>
              <StatusBadge status={est.data.probability_status} />
              <p className="text-xs text-muted-foreground">{est.data.probability_note} ({est.data.n_samples} residual vectors)</p>
            </div>
          )}
          {est.error && <ErrorState error={est.error} />}
          <p className="mt-4 mb-1 text-sm font-semibold">Imported sportsbook lines for this game</p>
          {myLines.length === 0 ? (
            <p className="text-xs text-muted-foreground">No active imported lines for this player (lines appear after the next scheduled odds import).</p>
          ) : (
            <table className="w-full text-xs">
              <tbody>
                {myLines.slice(0, 20).map((r) => (
                  <tr key={r.offer_id} className="border-t border-border/40">
                    <td className="py-0.5">{r.sportsbook}</td><td>{CATEGORY_SHORT[r.category] ?? r.category}</td>
                    <td>{r.side} {r.line}</td><td>proj {r.projected_mean.toFixed(1)}</td><td>lean {r.model_leans}</td>
                    <td>{r.p_side != null ? pct(r.p_side) : <StatusBadge status={r.probability_status} />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  );
}
