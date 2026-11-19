import type { ProbabilityStatus } from "@/lib/ml-types";
import { cn } from "@/lib/utils";

const STATUS_STYLE: Record<ProbabilityStatus, string> = {
  validated_real_lines: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  experimental: "border-amber-500/40 bg-amber-500/10 text-amber-200",
  unavailable: "border-red-500/40 bg-red-500/10 text-red-300",
  disabled_by_flag: "border-border bg-secondary/40 text-muted-foreground",
};

const STATUS_LABEL: Record<ProbabilityStatus, string> = {
  validated_real_lines: "Validated (real lines)",
  experimental: "Experimental",
  unavailable: "Withheld",
  disabled_by_flag: "Probabilities off",
};

export function StatusBadge({ status, className }: { status: ProbabilityStatus; className?: string }) {
  return (
    <span className={cn("inline-flex rounded-full border px-2 py-0.5 text-[11px] font-medium", STATUS_STYLE[status], className)}>
      {STATUS_LABEL[status]}
    </span>
  );
}

export function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border/70 bg-surface/50 p-3">
      <p className="text-[11px] tracking-wide text-muted-foreground uppercase">{label}</p>
      <p className="mt-1 text-base font-semibold">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function WarningList({ warnings }: { warnings: string[] }) {
  if (!warnings.length) return null;
  return (
    <ul className="space-y-1">
      {warnings.map((w) => {
        const [kind, ...rest] = w.split(":");
        return (
          <li key={w} className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-1.5 text-xs">
            <span className="font-semibold text-amber-200">{kind.replaceAll("_", " ")}</span>
            {rest.length ? <span className="text-muted-foreground">:{rest.join(":")}</span> : null}
          </li>
        );
      })}
    </ul>
  );
}

export const CATEGORY_ORDER = ["pts", "reb", "ast", "fg3m", "pts_reb", "pts_ast", "reb_ast", "pts_reb_ast"];
export const CATEGORY_SHORT: Record<string, string> = {
  pts: "PTS",
  reb: "REB",
  ast: "AST",
  fg3m: "3PM",
  pts_reb: "P+R",
  pts_ast: "P+A",
  reb_ast: "R+A",
  pts_reb_ast: "PRA",
};

export const fmt = (v: number | null | undefined, d = 2) => (v == null || Number.isNaN(v) ? "—" : v.toFixed(d));
export const pct = (v: number | null | undefined, d = 1) => (v == null ? "—" : `${(v * 100).toFixed(d)}%`);
