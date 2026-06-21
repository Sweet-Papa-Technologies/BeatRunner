/** Gameplay constants & look for OVERDRIVE — a synthwave 3-lane rhythm highway.
 *  Pure data; no Phaser types needed. */

import type { EventType } from "../core/beatmap";

export const VIEW = { width: 1280, height: 720 } as const;

/** Seconds a note travels from the vanishing point down to the hit-line.
 *  Couples to the read-time of the highway: long enough to react, tight enough to feel fast. */
export const LEAD_TIME = 1.7;

/** Grace after a note's target time before it auto-misses (seconds). */
export const MISS_GRACE = 0.14;

/**
 * The highway: a faux-3D perspective road. Notes spawn near the vanishing
 * point (small, faint) and rush toward the hit-line (large, bright).
 */
export const HIGHWAY = {
  /** Vanishing point — where lanes converge and notes are born. */
  vpX: VIEW.width / 2,
  vpY: 232,
  /** Y of the hit-line where notes must be struck. */
  hitY: 612,
  /** Half-width of the lane fan at the hit-line (centre lane is at vpX). */
  spread: 250,
  /** Perspective exponent: >1 makes notes hang back then rush in (accelerate). */
  depthPow: 2.15,
} as const;

/** Three lanes, mapped 1:1 onto the original event types so the tested core is untouched. */
export const LANE_COUNT = 3;
export type Lane = 0 | 1 | 2;

/** EventType -> lane index. GAP=left, BAR=centre, NOTE=right. */
export const LANE_FOR_TYPE: Record<EventType, Lane> = { GAP: 0, BAR: 1, NOTE: 2 };
export const TYPE_FOR_LANE: EventType[] = ["GAP", "BAR", "NOTE"];

/** Neon palette. */
export const COLORS = {
  bg0: 0x0a0420,
  perfect: 0xfff27a,
  good: 0x6cf2c4,
  miss: 0xff4d6d,
  hero: 0x2de2e6,
  heroAccent: 0xff2d95,
  sun: 0xff5db1,
} as const;

/** Per-lane accent colors (synthwave magenta / cyan / gold). */
export const LANE_COLORS: number[] = [0xff2d95, 0x2de2e6, 0xffd23c];

/** Lane lateral offset at the hit-line, as a fraction of `spread` from centre. */
export const LANE_OFFSET: number[] = [-1, 0, 1];

/** Combo tier -> accent color (matches multiplier tiers in scoring.ts). */
export const TIER_COLORS = [0x9b8cff, 0x2de2e6, 0x6cf2c4, 0xfff27a, 0xff2d95];
export function tierColor(combo: number): number {
  const tier = combo < 10 ? 0 : combo < 20 ? 1 : combo < 30 ? 2 : combo < 50 ? 3 : 4;
  return TIER_COLORS[tier];
}

/** Countdown length in beats before play starts. */
export const COUNT_IN_BEATS = 4;
