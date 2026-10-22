"use client";

import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";

import { fmtLongDate, fmtNum, fmtShortDate } from "@/lib/format";
import type { AnalysisGame, Outcome } from "@/lib/types";

const OUTCOME_COLORS: Record<Outcome, { top: string; bottom: string; text: string }> = {
  over: { top: "#34d399", bottom: "#0f9f6e", text: "#22c58b" },
  under: { top: "#fb7185", bottom: "#c42d48", text: "#f2556b" },
  push: { top: "#fcd34d", bottom: "#c98a1a", text: "#f5b84a" },
};

const COMPONENT_LABELS: Record<string, string> = {
  pts: "PTS",
  reb: "REB",
  ast: "AST",
  fg3m: "3PM",
  stl: "STL",
  blk: "BLK",
  tov: "TOV",
};

interface ChartDatum {
  index: number;
  value: number;
  game: AnalysisGame;
}

function ChartTooltip({
  active,
  payload,
  line,
  statLabel,
}: Pick<TooltipContentProps, "active" | "payload"> & { line: number; statLabel: string }) {
  if (!active || !payload?.length) return null;
  const { game } = payload[0].payload as ChartDatum;
  const color = OUTCOME_COLORS[game.outcome];
  const components = Object.entries(game.components);
  return (
    <div className="min-w-52 rounded-xl border border-border bg-popover/95 p-3 text-sm shadow-2xl shadow-black/50 backdrop-blur-xl">
      <div className="flex items-center justify-between gap-4">
        <span className="font-medium">
          {game.is_home ? "vs" : "@"} {game.opponent.display_name}
        </span>
        {game.result && (
          <span className={game.result === "W" ? "text-over" : "text-under"}>{game.result}</span>
        )}
      </div>
      <p className="mt-0.5 text-xs text-muted-foreground">
        {fmtLongDate(game.game_date)} · {game.season_label}
        {game.season_type !== 2 && " · Playoffs"}
      </p>
      <div className="mt-3 flex items-end justify-between">
        <div>
          <p className="text-xs text-muted-foreground">{statLabel}</p>
          <p className="text-2xl font-semibold tabular" style={{ color: color.text }}>
            {fmtNum(game.value, game.value % 1 === 0 ? 0 : 1)}
          </p>
        </div>
        <span
          className="rounded-md px-2 py-0.5 text-xs font-semibold uppercase"
          style={{ background: `${color.text}22`, color: color.text }}
        >
          {game.outcome} {line}
        </span>
      </div>
      {components.length > 1 && (
        <p className="mt-2 text-xs text-muted-foreground tabular">
          {components.map(([k, v]) => `${v ?? "—"} ${COMPONENT_LABELS[k] ?? k}`).join(" · ")}
        </p>
      )}
      <p className="mt-2 border-t border-border pt-2 text-xs text-muted-foreground tabular">
        {fmtNum(game.minutes, 0)} min
        {game.team_score !== null && ` · Final ${game.team_score}–${game.opponent_score}`}
      </p>
    </div>
  );
}

function GameTick({
  x,
  y,
  payload,
  data,
  compact,
  dense,
}: {
  x?: number;
  y?: number;
  payload?: { value: number };
  data: ChartDatum[];
  compact: boolean;
  dense: boolean;
}) {
  const datum = data[payload?.value ?? -1];
  if (!datum || x === undefined || y === undefined) return null;
  const { game } = datum;
  return (
    <g transform={`translate(${x},${y})`}>
      <text
        y={12}
        textAnchor="middle"
        className={dense ? "fill-foreground text-[9px] font-medium" : "fill-foreground text-[11px] font-medium"}
      >
        {game.is_home || dense ? "" : "@"}
        {game.opponent.abbreviation}
      </text>
      {!compact && (
        <text y={26} textAnchor="middle" className="fill-muted-foreground text-[10px]">
          {fmtShortDate(game.game_date)}
        </text>
      )}
    </g>
  );
}

export function StatBarChart({
  games,
  line,
  statLabel,
  height = 340,
  dense = false,
}: {
  games: AnalysisGame[];
  line: number;
  statLabel: string;
  height?: number;
  /** Narrow layouts: smaller axis labels, dates only in tooltips. */
  dense?: boolean;
}) {
  const data = useMemo<ChartDatum[]>(
    () => games.map((game, index) => ({ index, value: game.value, game })),
    [games],
  );
  const maxValue = Math.max(line, ...games.map((g) => g.value), 1) * 1.12;
  const step = [1, 2, 5, 10, 15, 20, 25, 50].find((s) => maxValue / s <= 6) ?? 100;
  const yMax = Math.ceil(maxValue / step) * step;
  const ticks = Array.from({ length: yMax / step + 1 }, (_, i) => i * step);
  const many = games.length > 20;
  const maxTicks = dense ? 10 : 20;
  const tickInterval = games.length > maxTicks ? Math.ceil(games.length / maxTicks) - 1 : 0;
  const compactTicks = many || dense;

  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 22, right: 40, bottom: 8, left: -8 }} barCategoryGap={many ? "12%" : "22%"}>
          <defs>
            {(Object.keys(OUTCOME_COLORS) as Outcome[]).map((k) => (
              <linearGradient key={k} id={`bar-${k}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={OUTCOME_COLORS[k].top} stopOpacity={0.95} />
                <stop offset="100%" stopColor={OUTCOME_COLORS[k].bottom} stopOpacity={0.75} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid vertical={false} stroke="rgb(148 163 255 / 0.08)" />
          <XAxis
            dataKey="index"
            tickLine={false}
            axisLine={{ stroke: "rgb(148 163 255 / 0.15)" }}
            interval={tickInterval}
            height={compactTicks ? 28 : 40}
            tick={<GameTick data={data} compact={compactTicks} dense={dense} />}
          />
          <YAxis
            domain={[0, yMax]}
            ticks={ticks}
            tickLine={false}
            axisLine={false}
            width={44}
            tick={{ fill: "#8792b8", fontSize: 11 }}
            allowDecimals={false}
          />
          <Tooltip
            cursor={{ fill: "rgb(79 124 255 / 0.08)", radius: 8 }}
            content={({ active, payload }) => (
              <ChartTooltip active={active} payload={payload} line={line} statLabel={statLabel} />
            )}
            animationDuration={120}
          />
          <Bar dataKey="value" radius={[6, 6, 2, 2]} maxBarSize={56} animationDuration={450}>
            {data.map((d) => (
              <Cell key={d.game.game_id} fill={`url(#bar-${d.game.outcome})`} />
            ))}
            {!many && !(dense && games.length > 12) && (
              <LabelList
                dataKey="value"
                position="top"
                offset={6}
                className="fill-foreground text-[11px] font-semibold tabular"
              />
            )}
          </Bar>
          <ReferenceLine
            y={line}
            stroke="#c7d2fe"
            strokeDasharray="6 5"
            strokeWidth={1.5}
            ifOverflow="extendDomain"
            label={{
              value: String(line),
              position: "right",
              fill: "#c7d2fe",
              fontSize: 11,
              fontWeight: 600,
            }}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
