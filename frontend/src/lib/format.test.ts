import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { fmtPct, fmtProbability, fmtShortDate, parseCalendarDate } from "./format";

/** Snippet from GET /api/recommendations player_props[0].game (local backend). */
const RECOMMENDATION_GAME_START_TIME = "2026-10-22T23:00:00Z";
const RECOMMENDATION_GAME_DATE = "2026-10-22";

describe("parseCalendarDate", () => {
  it("parses backend calendar dates", () => {
    const d = parseCalendarDate(RECOMMENDATION_GAME_DATE);
    assert.equal(d.getFullYear(), 2026);
    assert.equal(d.getMonth(), 9);
    assert.equal(d.getDate(), 22);
  });

  it("parses ISO start_time via date prefix (regression: PropCard used start_time)", () => {
    assert.equal(parseCalendarDate(RECOMMENDATION_GAME_START_TIME).getDate(), 22);
  });

  it("rejects legacy split-on-dash bug input", () => {
    assert.throws(() => parseCalendarDate("not-a-date"), RangeError);
  });
});

describe("fmtShortDate", () => {
  it("formats game_date from recommendations API", () => {
    assert.equal(fmtShortDate(RECOMMENDATION_GAME_DATE), "Oct 22");
  });

  it("does not throw when given ISO start_time (regression)", () => {
    assert.equal(fmtShortDate(RECOMMENDATION_GAME_START_TIME), "Oct 22");
  });

  it("returns em dash for missing values", () => {
    assert.equal(fmtShortDate(null), "—");
    assert.equal(fmtShortDate(""), "—");
  });

  it("returns em dash for unparseable values without throwing", () => {
    assert.equal(fmtShortDate("bad"), "—");
  });
});

describe("fmtProbability", () => {
  it("formats 0–1 ML probabilities as display percentages", () => {
    assert.equal(fmtProbability(0.01), "1%");
    assert.equal(fmtProbability(0.55), "55%");
    assert.equal(fmtProbability(0.736), "73.6%");
    assert.equal(fmtProbability(0.99), "99%");
    assert.equal(fmtProbability(1), "100%");
  });

  it("returns em dash for missing values", () => {
    assert.equal(fmtProbability(null), "—");
  });
});

describe("fmtPct", () => {
  it("formats analytics hit rates already on 0–100 scale", () => {
    assert.equal(fmtPct(80), "80%");
    assert.equal(fmtPct(73.6), "73.6%");
  });
});
