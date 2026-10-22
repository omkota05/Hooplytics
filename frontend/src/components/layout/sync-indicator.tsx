"use client";

import { RefreshCw } from "lucide-react";
import { useState } from "react";

import { api } from "@/lib/api";
import { fmtDateTime, fmtRelative } from "@/lib/format";
import { useSyncStatus } from "@/lib/hooks";
import { cn } from "@/lib/utils";

export function SyncIndicator({ compact = false }: { compact?: boolean }) {
  const { data, error, mutate } = useSyncStatus();
  const [queued, setQueued] = useState(false);

  const trigger = async () => {
    setQueued(true);
    try {
      await api.triggerSync();
      setTimeout(() => mutate(), 3000);
    } finally {
      setTimeout(() => setQueued(false), 5000);
    }
  };

  let dot = "bg-muted-foreground";
  let label = "Checking data…";
  let title = "";
  if (error) {
    dot = "bg-under";
    label = "API offline";
    title = (error as Error).message;
  } else if (data) {
    const last = data.last_successful_sync_at;
    dot = data.is_running ? "bg-electric animate-pulse" : data.is_stale ? "bg-push" : "bg-over";
    label = data.is_running
      ? "Syncing…"
      : last
        ? `Updated ${fmtRelative(last)}`
        : "Never synced";
    title = last
      ? `Last successful sync: ${fmtDateTime(last)} · Source: ${data.provider}`
      : `Source: ${data.provider}`;
  }

  return (
    <div
      className="flex items-center gap-2 rounded-lg border border-border bg-surface/70 px-2.5 py-1.5 text-xs text-muted-foreground"
      title={title}
    >
      <span className={cn("size-2 rounded-full", dot)} />
      {!compact && <span className="whitespace-nowrap">{label}</span>}
      <button
        onClick={trigger}
        disabled={queued || !!error}
        aria-label="Sync now"
        className="rounded p-0.5 hover:text-foreground disabled:opacity-50"
      >
        <RefreshCw className={cn("size-3.5", (queued || data?.is_running) && "animate-spin")} />
      </button>
    </div>
  );
}
