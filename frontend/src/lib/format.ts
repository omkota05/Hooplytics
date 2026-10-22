import { format, formatDistanceToNowStrict, parseISO } from "date-fns";

import type { Game } from "./types";

/** Parse a backend calendar date ("2026-10-21") without timezone shifting. */
export function parseCalendarDate(value: string): Date {
  const [y, m, d] = value.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export const fmtShortDate = (value: string) => format(parseCalendarDate(value), "MMM d");
export const fmtLongDate = (value: string) => format(parseCalendarDate(value), "EEE, MMM d, yyyy");
export const fmtDayHeading = (value: string) => format(parseCalendarDate(value), "EEEE, MMMM d");
export const fmtTipoff = (iso: string) => format(parseISO(iso), "h:mm a");
export const fmtDateTime = (iso: string) => format(parseISO(iso), "MMM d, h:mm a");
export const fmtRelative = (iso: string) => `${formatDistanceToNowStrict(parseISO(iso))} ago`;

export function fmtNum(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

export function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(value % 1 === 0 ? 0 : 1)}%`;
}

export function fmtHeight(inches: number | null): string | null {
  if (!inches) return null;
  return `${Math.floor(inches / 12)}'${Math.round(inches % 12)}"`;
}

export function ageFrom(birthDate: string | null): number | null {
  if (!birthDate) return null;
  const dob = parseCalendarDate(birthDate);
  const now = new Date();
  let age = now.getFullYear() - dob.getFullYear();
  const beforeBirthday =
    now.getMonth() < dob.getMonth() ||
    (now.getMonth() === dob.getMonth() && now.getDate() < dob.getDate());
  if (beforeBirthday) age -= 1;
  return age;
}

export function gameStatusLabel(game: Game): string {
  switch (game.status) {
    case "scheduled":
      return fmtTipoff(game.start_time);
    case "in_progress":
      return game.status_detail ?? "Live";
    case "final":
      return game.status_detail ?? "Final";
    case "postponed":
      return "Postponed";
    case "canceled":
      return "Canceled";
    case "suspended":
      return "Suspended";
  }
}

export function venueLabel(game: Game): string | null {
  const place = [game.venue_city, game.venue_state].filter(Boolean).join(", ");
  if (!game.venue_name) return place || null;
  return place ? `${game.venue_name} · ${place}` : game.venue_name;
}

/** Snap free-typed lines to 0.5 increments when committing. */
export function normalizeLine(value: number): number {
  return Math.max(0, Math.min(200, Math.round(value * 2) / 2));
}
