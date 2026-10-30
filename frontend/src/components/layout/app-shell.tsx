"use client";

import { CalendarDays, Layers, LayoutDashboard, TrendingUp, Users } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { PlayerSearch } from "@/components/search/player-search";
import { cn } from "@/lib/utils";

import { SyncIndicator } from "./sync-indicator";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/players", label: "Players", icon: Users },
  { href: "/matchups", label: "Matchups", icon: CalendarDays },
  { href: "/prop-finder", label: "Prop Finder", icon: TrendingUp },
  { href: "/parlay-builder", label: "Parlay Builder", icon: Layers },
];

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2.5">
      <span className="relative flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-electric to-violet shadow-[0_8px_24px_-8px_rgb(79_124_255/0.8)]">
        <svg viewBox="0 0 24 24" className="size-5 text-white" fill="none" stroke="currentColor" strokeWidth="1.8">
          <circle cx="12" cy="12" r="9" />
          <path d="M3 12h18M12 3v18M5.6 5.6c3.4 3.4 3.4 9.4 0 12.8M18.4 5.6c-3.4 3.4-3.4 9.4 0 12.8" />
        </svg>
      </span>
      <span className="text-lg font-semibold tracking-tight">
        Hoop<span className="text-gradient">lytics</span>
      </span>
    </Link>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-border bg-surface/60 px-4 py-5 backdrop-blur lg:flex">
        <Logo />
        <nav className="mt-8 flex flex-col gap-1">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = isActive(pathname, href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all",
                  active
                    ? "bg-gradient-to-r from-primary/25 to-violet/10 text-foreground ring-1 ring-primary/30"
                    : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                )}
              >
                <Icon className={cn("size-4", active ? "text-electric" : "group-hover:text-foreground")} />
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="mt-auto space-y-3">
          <SyncIndicator />
          <p className="px-1 text-[11px] leading-relaxed text-muted-foreground/70">
            Historical analytics only — not betting advice.
          </p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 border-b border-border bg-background/75 backdrop-blur-xl">
          <div className="mx-auto flex h-16 max-w-[1400px] items-center gap-4 px-4 sm:px-6">
            <div className="lg:hidden">
              <Logo />
            </div>
            <PlayerSearch className="max-w-xl" />
            <div className="ml-auto lg:hidden">
              <SyncIndicator compact />
            </div>
          </div>
          <nav className="flex gap-1 overflow-x-auto px-4 pb-2 lg:hidden">
            {NAV.map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-sm whitespace-nowrap",
                  isActive(pathname, href) ? "bg-primary/20 text-foreground" : "text-muted-foreground",
                )}
              >
                {label}
              </Link>
            ))}
          </nav>
        </header>
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 sm:px-6 lg:py-8">{children}</main>
      </div>
    </div>
  );
}
