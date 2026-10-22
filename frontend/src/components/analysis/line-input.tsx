"use client";

import { Minus, Plus } from "lucide-react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

const MIN = 0;
const MAX = 200;

function parseLine(raw: string): number | null {
  if (raw.trim() === "") return null;
  const value = Number(raw);
  if (!Number.isFinite(value) || value < MIN || value > MAX) return null;
  return Math.round(value * 10) / 10;
}

/** Free-typed betting line. Commits valid values on a short pause, blur, or Enter. */
export function LineInput({
  value,
  onChange,
  className,
}: {
  value: number;
  onChange: (value: number) => void;
  className?: string;
}) {
  const [draft, setDraft] = useState(String(value));
  const parsed = parseLine(draft);
  const invalid = parsed === null;

  useEffect(() => setDraft(String(value)), [value]);

  useEffect(() => {
    if (parsed === null || parsed === value) return;
    const id = setTimeout(() => onChange(parsed), 350);
    return () => clearTimeout(id);
  }, [parsed, value, onChange]);

  const step = (delta: number) => {
    const base = parsed ?? value;
    const next = Math.min(MAX, Math.max(MIN, Math.round((base + delta) * 2) / 2));
    setDraft(String(next));
    onChange(next);
  };

  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <div
        className={cn(
          "flex h-10 items-center rounded-xl border bg-surface transition focus-within:ring-4",
          invalid
            ? "border-under/70 focus-within:ring-under/15"
            : "border-border focus-within:border-primary/70 focus-within:ring-primary/15",
        )}
      >
        <button
          type="button"
          onClick={() => step(-0.5)}
          aria-label="Decrease line by 0.5"
          className="flex h-full w-9 items-center justify-center text-muted-foreground hover:text-foreground"
        >
          <Minus className="size-4" />
        </button>
        <input
          inputMode="decimal"
          type="number"
          step="0.5"
          min={MIN}
          max={MAX}
          value={draft}
          aria-label="Custom line"
          aria-invalid={invalid}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => parsed !== null && onChange(parsed)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && parsed !== null) onChange(parsed);
            if (e.key === "ArrowUp") {
              e.preventDefault();
              step(0.5);
            }
            if (e.key === "ArrowDown") {
              e.preventDefault();
              step(-0.5);
            }
          }}
          className="w-16 bg-transparent text-center text-base font-semibold tabular outline-none"
        />
        <button
          type="button"
          onClick={() => step(0.5)}
          aria-label="Increase line by 0.5"
          className="flex h-full w-9 items-center justify-center text-muted-foreground hover:text-foreground"
        >
          <Plus className="size-4" />
        </button>
      </div>
      {invalid && <span className="text-[11px] text-under">Enter a line from 0 to 200</span>}
    </div>
  );
}
