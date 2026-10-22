"use client";

import { Search, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import useSWR from "swr";

import { PlayerAvatar } from "@/components/common/player-avatar";
import { Spinner } from "@/components/common/states";
import { TeamLogo } from "@/components/common/team-logo";
import { api } from "@/lib/api";
import { useDebounced } from "@/lib/hooks";
import type { PlayerSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

export function PlayerSearch({
  size = "md",
  placeholder = "Search any NBA player…",
  onSelect,
  autoFocus,
  className,
}: {
  size?: "md" | "lg";
  placeholder?: string;
  onSelect?: (player: PlayerSummary) => void;
  autoFocus?: boolean;
  className?: string;
}) {
  const router = useRouter();
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const debounced = useDebounced(query.trim(), 150);

  const { data, error, isLoading } = useSWR(
    debounced.length >= 2 ? ["search", debounced] : null,
    () => api.searchPlayers(debounced, 8),
    { keepPreviousData: true },
  );
  const results = debounced.length >= 2 ? (data ?? []) : [];

  useEffect(() => setActive(0), [debounced]);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  const choose = (player: PlayerSummary) => {
    setOpen(false);
    setQuery("");
    if (onSelect) onSelect(player);
    else router.push(`/players/${player.id}`);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => (i + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => (i - 1 + results.length) % results.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(results[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const showPanel = open && debounced.length >= 2;

  return (
    <div ref={containerRef} className={cn("relative w-full", className)}>
      <div
        className={cn(
          "flex items-center gap-2 rounded-xl border border-input bg-surface/80 transition focus-within:border-primary/70 focus-within:ring-4 focus-within:ring-primary/15",
          size === "lg" ? "h-14 px-4" : "h-10 px-3",
        )}
      >
        <Search className={cn("shrink-0 text-muted-foreground", size === "lg" ? "size-5" : "size-4")} />
        <input
          ref={inputRef}
          value={query}
          autoFocus={autoFocus}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          role="combobox"
          aria-expanded={showPanel}
          aria-controls={listId}
          aria-autocomplete="list"
          className={cn(
            "w-full bg-transparent outline-none placeholder:text-muted-foreground/70",
            size === "lg" ? "text-lg" : "text-sm",
          )}
        />
        {isLoading && <Spinner />}
        {query && !isLoading && (
          <button aria-label="Clear search" onClick={() => setQuery("")}>
            <X className="size-4 text-muted-foreground hover:text-foreground" />
          </button>
        )}
        {!query && size === "md" && (
          <kbd className="hidden rounded border border-border px-1.5 text-[10px] text-muted-foreground sm:block">
            /
          </kbd>
        )}
      </div>

      {showPanel && (
        <div
          id={listId}
          role="listbox"
          className="absolute z-50 mt-2 w-full overflow-hidden rounded-xl border border-border bg-popover/95 shadow-2xl shadow-black/40 backdrop-blur-xl animate-in fade-in-0 slide-in-from-top-1"
        >
          {error ? (
            <p className="px-4 py-3 text-sm text-under">{(error as Error).message}</p>
          ) : results.length === 0 && !isLoading ? (
            <p className="px-4 py-3 text-sm text-muted-foreground">No players match “{debounced}”.</p>
          ) : (
            results.map((p, i) => (
              <button
                key={p.id}
                role="option"
                aria-selected={i === active}
                onMouseEnter={() => setActive(i)}
                onClick={() => choose(p)}
                className={cn(
                  "flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors",
                  i === active ? "bg-primary/15" : "hover:bg-secondary/60",
                )}
              >
                <PlayerAvatar name={p.full_name} src={p.headshot_url} size={36} />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{p.full_name}</p>
                  <p className="truncate text-xs text-muted-foreground">
                    {[p.position, p.team?.display_name ?? (p.is_active ? null : "Not on a current roster")]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                </div>
                {p.team && <TeamLogo team={p.team} size={24} />}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
