"use client";

import { Layers, Search } from "lucide-react";
import { useState } from "react";

import { PropAnalyzerPanel } from "@/components/prop-finder/prop-analyzer-panel";
import { ErrorState } from "@/components/common/states";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import { fmtDateTime, fmtNum } from "@/lib/format";
import { fmtHitSample } from "@/lib/prop-hit-format";
import { useCategories } from "@/lib/hooks";
import type { ParlayCombination, ParlaySearchRequest } from "@/lib/types";

const DEFAULT_REQUEST: ParlaySearchRequest = {
  legs: 3,
  analysis_window: "l20",
  min_games: 10,
  upcoming_days: 3,
  pick_side: "both",
  different_games_only: true,
  one_per_player: true,
  limit: 10,
};

export function ParlayBuilderView() {
  const [req, setReq] = useState<ParlaySearchRequest>(DEFAULT_REQUEST);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [result, setResult] = useState<Awaited<ReturnType<typeof api.parlaySearch>> | null>(null);
  const [analyzeId, setAnalyzeId] = useState<number | null>(null);
  const categories = useCategories();
  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const out = await api.parlaySearch(req);
      setResult(out);
    } catch (e) {
      setError(e instanceof Error ? e : new Error("Search failed"));
    } finally {
      setLoading(false);
    }
  };

  const patch = (partial: Partial<ParlaySearchRequest>) => setReq((r) => ({ ...r, ...partial }));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
          <Layers className="size-7 text-violet" /> Parlay Builder
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Ranked combinations using Historical Consistency (HCS) per leg and Parlay Consistency Score (PCS) for
          combinations — descriptive indexes, not win probabilities.
        </p>
      </div>

      <Card className="border-border/80 bg-surface/60 p-4 space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="text-sm">
            <span className="text-xs text-muted-foreground">Legs</span>
            <select
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-2"
              value={req.legs}
              onChange={(e) => patch({ legs: Number(e.target.value) })}
            >
              {[2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted-foreground">Analysis window</span>
            <select
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-2"
              value={req.analysis_window}
              onChange={(e) => patch({ analysis_window: e.target.value as ParlaySearchRequest["analysis_window"] })}
            >
              {["l5", "l10", "l20", "l30"].map((w) => (
                <option key={w} value={w}>{w.toUpperCase()}</option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted-foreground">Min qualifying games</span>
            <select
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-2"
              value={req.min_games}
              onChange={(e) => patch({ min_games: Number(e.target.value) as ParlaySearchRequest["min_games"] })}
            >
              {[5, 10, 15, 20].map((n) => (
                <option key={n} value={n}>{n}+</option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted-foreground">Upcoming games</span>
            <select
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-2"
              value={req.upcoming_days}
              onChange={(e) => patch({ upcoming_days: Number(e.target.value) as ParlaySearchRequest["upcoming_days"] })}
            >
              <option value={1}>Today</option>
              <option value={3}>Next 3 days</option>
              <option value={7}>Next 7 days</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted-foreground">Sportsbook (optional)</span>
            <input
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-2"
              placeholder="All books"
              value={req.sportsbook ?? ""}
              onChange={(e) => patch({ sportsbook: e.target.value || undefined })}
            />
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted-foreground">Side</span>
            <select
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-2"
              value={req.pick_side}
              onChange={(e) => patch({ pick_side: e.target.value as ParlaySearchRequest["pick_side"] })}
            >
              <option value="both">Over & under</option>
              <option value="over">Over only</option>
              <option value="under">Under only</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted-foreground">Category</span>
            <select
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-2"
              value={req.category ?? ""}
              onChange={(e) => patch({ category: e.target.value || undefined })}
            >
              <option value="">All</option>
              {categories.data?.map((c) => (
                <option key={c.key} value={c.key}>{c.label}</option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted-foreground">Min hit % (window)</span>
            <input
              type="number"
              className="mt-1 w-full rounded-md border border-border bg-background px-2 py-2"
              placeholder="Any"
              value={req.min_hit_pct ?? ""}
              onChange={(e) => patch({ min_hit_pct: e.target.value ? Number(e.target.value) : undefined })}
            />
          </label>
        </div>
        <div className="flex flex-wrap gap-4 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={req.different_games_only}
              onChange={(e) => patch({ different_games_only: e.target.checked })}
            />
            Different games only
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={req.one_per_player}
              onChange={(e) => patch({ one_per_player: e.target.checked })}
            />
            One leg per player
          </label>
        </div>
        <Button className="gap-2" size="lg" onClick={run} disabled={loading}>
          <Search className="size-4" />
          {loading ? "Searching…" : "Find Best Combinations"}
        </Button>
      </Card>

      {error && <ErrorState error={error} onRetry={run} />}

      {result && (
        <div className="space-y-4">
          <p className="text-xs text-muted-foreground">
            {result.meta.candidates_considered} legs scored · {result.meta.combinations_evaluated} combos checked ·{" "}
            {result.meta.generation_ms}ms
            {result.meta.last_import_finished_at && ` · Odds import ${fmtDateTime(result.meta.last_import_finished_at)}`}
          </p>
          {result.meta.stale_warning && (
            <Card className="border-amber-500/40 bg-amber-500/10 p-3 text-sm">{result.meta.stale_warning}</Card>
          )}
          {!req.sportsbook && (
            <p className="text-xs text-muted-foreground">
              No single sportsbook selected — combinations may mix books and are for historical comparison only.
            </p>
          )}
          {result.combinations.length === 0 && (
            <Card className="p-6 text-sm text-muted-foreground">
              No combinations matched your filters. Try lowering minimum games or widening the date window.
            </Card>
          )}
          {result.combinations.map((combo) => (
            <ParlayCard key={combo.rank} combo={combo} onAnalyze={setAnalyzeId} />
          ))}
          <p className="text-xs text-muted-foreground">{result.disclaimer}</p>
        </div>
      )}

      {analyzeId != null && <PropAnalyzerPanel propId={analyzeId} onClose={() => setAnalyzeId(null)} />}
    </div>
  );
}

function ParlayCard({
  combo,
  onAnalyze,
}: {
  combo: ParlayCombination;
  onAnalyze: (id: number) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Card className="border-border/80 overflow-hidden">
      <button
        type="button"
        className="flex w-full items-start justify-between gap-3 p-4 text-left hover:bg-primary/5"
        onClick={() => setOpen((v) => !v)}
      >
        <div>
          <p className="text-xs font-medium uppercase text-violet">#{combo.rank} · Parlay Consistency Score (PCS)</p>
          <p className="text-3xl font-bold tabular text-electric">
            {fmtNum(combo.parlay_consistency_score ?? combo.historical_consistency_score, 1)}
          </p>
          <p className="text-xs text-muted-foreground">
            {combo.legs.length} legs · weakest leg HCS {fmtNum(combo.min_leg_score, 1)} · avg leg HCS{" "}
            {fmtNum(combo.avg_leg_score, 1)}
            {combo.sportsbook && ` · ${combo.sportsbook}`}
          </p>
        </div>
      </button>
      <div className="border-t border-border/60 px-4 py-3 text-sm text-muted-foreground">{combo.explanation}</div>
      {combo.same_game_warning && (
        <p className="border-t border-border/60 px-4 py-2 text-xs text-amber-400">{combo.same_game_warning}</p>
      )}
      {combo.indicative_payout_note && (
        <p className="border-t border-border/60 px-4 py-2 text-xs text-muted-foreground">{combo.indicative_payout_note}</p>
      )}
      {open && (
        <div className="space-y-3 border-t border-border/60 p-4">
          {combo.legs.map((leg) => (
            <div key={leg.prop_offer_id} className="rounded-lg bg-secondary/30 p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-semibold">{leg.player_name}</p>
                <Button variant="outline" size="sm" onClick={() => onAnalyze(leg.prop_offer_id)}>
                  Prop Analyzer
                </Button>
              </div>
              <p className="text-muted-foreground">
                {leg.opponent_label} · {leg.category.short_label} {leg.pick_side} {leg.line} · {leg.sportsbook}
                {leg.american_odds != null && ` (${leg.american_odds > 0 ? "+" : ""}${leg.american_odds})`}
              </p>
              <p className="text-xs tabular">
                L10 {fmtHitSample(leg.l10_hits, leg.l10_attempts, leg.l10_hit_pct)} · L20{" "}
                {fmtHitSample(leg.l20_hits, leg.l20_attempts, leg.l20_hit_pct)} · HCS {fmtNum(leg.score.hcs, 1)}
              </p>
              {leg.game_start_time && (
                <p className="text-[10px] text-muted-foreground">{fmtDateTime(leg.game_start_time)}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
