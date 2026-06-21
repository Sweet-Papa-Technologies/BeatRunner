/** Gameplay constants & look. Pure data; no Phaser types needed. */

export const VIEW = { width: 1280, height: 720 } as const;

/** World geometry (in view pixels). */
export const STAGE = {
  groundY: 568,
  /** x where an obstacle is "in the pocket" and the hero acts. */
  actionX: 340,
  /** x where obstacles enter from the right. */
  spawnX: VIEW.width + 80,
} as const;

/** Seconds an obstacle travels from spawn to the action line. Couples to beatmap spawn lead. */
export const LEAD_TIME = 2.0;

/** The three player actions and the obstacle (event) type each one answers. */
export type ActionName = "Jump" | "Duck" | "Strike";
import type { EventType } from "../core/beatmap";

export const ACTION_FOR_TYPE: Record<EventType, ActionName> = {
  GAP: "Jump",
  BAR: "Duck",
  NOTE: "Strike",
};
export const TYPE_FOR_ACTION: Record<ActionName, EventType> = {
  Jump: "GAP",
  Duck: "BAR",
  Strike: "NOTE",
};

/** Neon palette. */
export const COLORS = {
  bg0: 0x05030d,
  perfect: 0xfff27a,
  good: 0x7af2c4,
  miss: 0xff5d7a,
  gap: 0xff7a3c,
  bar: 0x4cc9ff,
  note: 0xffd23c,
  hero: 0x4cc9ff,
  heroAccent: 0xff5dcb,
} as const;

/** Combo tier -> accent color (matches multiplier tiers in scoring.ts). */
export const TIER_COLORS = [0x9b8cff, 0x4cc9ff, 0x7af2c4, 0xfff27a, 0xff5dcb];
export function tierColor(combo: number): number {
  const tier = combo < 10 ? 0 : combo < 20 ? 1 : combo < 30 ? 2 : combo < 50 ? 3 : 4;
  return TIER_COLORS[tier];
}

/** Countdown length in beats before play starts. */
export const COUNT_IN_BEATS = 4;
