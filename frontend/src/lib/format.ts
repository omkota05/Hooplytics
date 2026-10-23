import { format, formatDistanceToNowStrict, parseISO } from "date-fns";

import type { Game } from "./types";

/** Leading YYYY-MM-DD from backend calendar dates or ISO datetimes (e.g. game start_time). */
const CALENDAR_DATE_PREFIX = /^(\d{4})-(\d{2})-(\d{2})/;

/** Parse a backend calendar date ("2026-10-21") without timezone shifting. */
export function parseCalendarDate(value: string): Date {
  const trimmed = value.trim();
  const match = CALENDAR_DATE_PREFIX.exec(trimmed);
  if (!match) {
    throw new RangeError(`Invalid calendar date: "${value}"`);
  }
  const y = Number(match[1]);
  const m = Number(match[2]);
  const d = Number(match[3]);
  const date = new Date(y, m - 1, d);
  if (date.getFullYear() !== y || date.getMonth() !== m - 1 || date.getDate() !== d) {
    throw new RangeError(`Invalid calendar date: "${value}"`);
  }
  return date;
}

function formatCalendarDate(
  value: string | null | undefined,
  pattern: string,
  formatterName: string,
): string {
  if (value == null || value.trim() === "") return "—";
  try {
    return format(parseCalendarDate(value), pattern);
  } catch (error) {
    if (process.env.NODE_ENV === "development") {
      console.warn(`[${formatterName}] invalid date`, { value, error });
    }
    return "—";
  }
}

export const fmtShortDate = (value: string | null | undefined) =>
  formatCalendarDate(value, "MMM d", "fmtShortDate");
export const fmtLongDate = (value: string | null | undefined) =>
  formatCalendarDate(value, "EEE, MMM d, yyyy", "fmtLongDate");
export const fmtDayHeading = (value: string | null | undefined) =>
  formatCalendarDate(value, "EEEE, MMMM d", "fmtDayHeading");
export const fmtTipoff = (iso: string) => format(parseISO(iso), "h:mm a");
export const fmtDateTime = (iso: string) => format(parseISO(iso), "MMM d, h:mm a");
export const fmtRelative = (iso: string) => `${formatDistanceToNowStrict(parseISO(iso))} ago`;

export function fmtNum(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(digits);
}

function formatPercentPoints(pctPoints: number): string {
  const rounded = Math.round(pctPoints * 10) / 10;
  const decimals = rounded % 1 === 0 ? 0 : 1;
  return `${rounded.toFixed(decimals)}%`;
}

/** Format analytics hit rates already on a 0–100 scale (e.g. `over_pct`). */
export function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return formatPercentPoints(value);
}

/** Format ML probabilities on a 0–1 scale (e.g. `model_probability`, `p_over`). */
export function fmtProbability(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return formatPercentPoints(value * 100);
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
