"use client";

import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";

import { fmtLongDate, fmtNum } from "@/lib/format";
import type { OpportunityGame } from "@/lib/types";

export type OpportunityMetric = "minutes" | "fga" | "fg3a";

const METRIC_LABEL: Record<OpportunityMetric, string> = {
  minutes: "Minutes",
  fga: "FGA",
  fg3a: "3PA",
};

interface Datum {
  index: number;
  value: number;
  game: OpportunityGame;
}

function TooltipBody({
  active,
  payload,
  metric,
}: Pick<TooltipContentProps, "active" | "payload"> & { metric: OpportunityMetric }) {
  if (!active || !payload?.length) return null;
  const { game, value } = payload[0].payload as Datum;
  return (
    <div className="min-w-48 rounded-xl border border-border bg-popover/95 p-3 text-sm shadow-2xl shadow-black/50 backdrop-blur-xl">
      <p className="font-medium">
        {game.is_home ? "vs" : "@"} {game.opponent.display_name}
      </p>
      <p className="text-xs text-muted-foreground">{fmtLongDate(game.game_date)}</p>
      <p className="mt-2 text-2xl font-semibold tabular text-electric">
        {fmtNum(value, metric === "minutes" ? 1 : 0)} {METRIC_LABEL[metric]}
      </p>
    </div>
  );
}

export function OpportunityBarChart({
  games,
  metric,
  height = 280,
}: {
  games: OpportunityGame[];
  metric: OpportunityMetric;
  height?: number;
}) {
  const data = useMemo(() => {
    const out: Datum[] = [];
    games.forEach((game, index) => {
      const raw = game[metric];
      if (raw == null) return;
      out.push({ index, value: raw, game });
    });
    return out;
  }, [games, metric]);

  if (data.length === 0) {
    return <p className="py-12 text-center text-sm text-muted-foreground">No {METRIC_LABEL[metric]} data in this window.</p>;
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="rgba(255,255,255,0.06)" />
        <XAxis dataKey="index" tick={false} axisLine={false} />
        <YAxis tick={{ fontSize: 11 }} width={36} />
        <Tooltip content={(p) => <TooltipBody {...p} metric={metric} />} />
        <Bar dataKey="value" fill="#6366f1" radius={[4, 4, 0, 0]} maxBarSize={28} />
      </BarChart>
    </ResponsiveContainer>
  );
}
