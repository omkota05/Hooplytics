import { AlertTriangle, Inbox, Loader2 } from "lucide-react";
import type { ReactNode } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export function ErrorState({
  error,
  title = "Something went wrong",
  onRetry,
  className,
}: {
  error: unknown;
  title?: string;
  onRetry?: () => void;
  className?: string;
}) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-xl border border-under/30 bg-under/5 px-6 py-8 text-center",
        className,
      )}
    >
      <AlertTriangle className="size-6 text-under" />
      <p className="font-medium">{title}</p>
      <p className="max-w-md text-sm text-muted-foreground">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-2 rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-secondary"
        >
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  icon,
  className,
}: {
  title: string;
  description?: ReactNode;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border px-6 py-10 text-center",
        className,
      )}
    >
      {icon ?? <Inbox className="size-6 text-muted-foreground" />}
      <p className="font-medium">{title}</p>
      {description && <div className="max-w-md text-sm text-muted-foreground">{description}</div>}
    </div>
  );
}

export function LoadingRows({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)}>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-12 w-full rounded-lg bg-secondary/60" />
      ))}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("size-4 animate-spin text-muted-foreground", className)} />;
}
