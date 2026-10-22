"use client";

import type { StatCategory } from "@/lib/types";
import { cn } from "@/lib/utils";

export function StatPicker({
  categories,
  value,
  onChange,
}: {
  categories: StatCategory[];
  value: string;
  onChange: (key: string) => void;
}) {
  const groups = [
    { label: "Individual", items: categories.filter((c) => !c.is_combined) },
    { label: "Combined", items: categories.filter((c) => c.is_combined) },
  ];
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2" role="radiogroup" aria-label="Stat category">
      {groups.map((group) => (
        <div key={group.label} className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-[10px] font-semibold tracking-wider text-muted-foreground/70 uppercase">
            {group.label}
          </span>
          {group.items.map((c) => {
            const active = c.key === value;
            return (
              <button
                key={c.key}
                type="button"
                role="radio"
                aria-checked={active}
                title={c.label}
                onClick={() => onChange(c.key)}
                className={cn(
                  "rounded-lg border px-2.5 py-1 text-xs font-semibold tracking-wide transition-all",
                  active
                    ? "border-primary/60 bg-primary/20 text-foreground shadow-[0_0_0_3px_rgb(79_124_255/0.12)]"
                    : "border-border bg-surface text-muted-foreground hover:border-primary/30 hover:text-foreground",
                )}
              >
                {c.short_label}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
