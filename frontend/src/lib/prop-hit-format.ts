import { fmtPct } from "@/lib/format";

/** Display historical hit rate as `8/10 (80%)`; never inflate sample size. */
export function fmtHitSample(
  hits: number | null | undefined,
  attempts: number | null | undefined,
  pct: number | null | undefined,
): string {
  if (attempts == null || attempts <= 0 || hits == null) {
    return "—";
  }
  const pctPart = pct != null ? ` (${fmtPct(pct)})` : "";
  return `${hits}/${attempts}${pctPart}`;
}
