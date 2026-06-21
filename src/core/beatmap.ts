/**
 * beatmap.ts — pure beat-map schema, validation, ordering & spawn timing.
 * REQ-MAP-01..03. No Phaser.
 */

import { beatTime } from "./timing";

export type EventType = "GAP" | "BAR" | "NOTE";

export const EVENT_TYPES: readonly EventType[] = ["GAP", "BAR", "NOTE"];

export interface BeatmapEvent {
  beat: number;
  type: EventType;
}

export interface Beatmap {
  track: string;
  bpm: number;
  offset: number;
  events: BeatmapEvent[];
}

/** Typed error thrown on invalid beat-map input. */
export class BeatmapError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BeatmapError";
  }
}

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function isEventType(v: unknown): v is EventType {
  return typeof v === "string" && (EVENT_TYPES as readonly string[]).includes(v);
}

/**
 * REQ-MAP-01 validation + REQ-MAP-02 ordering/dedupe.
 * Validates schema, returns events sorted ascending by beat,
 * de-duplicating same-(beat,type) pairs while keeping different types at one beat.
 * Throws BeatmapError on any invalid field.
 */
export function parseBeatmap(raw: unknown): Beatmap {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    throw new BeatmapError("beat-map must be an object");
  }
  const obj = raw as Record<string, unknown>;

  if (typeof obj.track !== "string" || obj.track.length === 0) {
    throw new BeatmapError("`track` must be a non-empty string");
  }
  if (!isFiniteNumber(obj.bpm) || obj.bpm <= 0) {
    throw new BeatmapError("`bpm` must be a number > 0");
  }
  if (!isFiniteNumber(obj.offset) || obj.offset < 0) {
    throw new BeatmapError("`offset` must be a number >= 0");
  }
  if (!Array.isArray(obj.events)) {
    throw new BeatmapError("`events` must be an array");
  }

  const parsed: BeatmapEvent[] = obj.events.map((e, i) => {
    if (typeof e !== "object" || e === null) {
      throw new BeatmapError(`event[${i}] must be an object`);
    }
    const ev = e as Record<string, unknown>;
    if (!isFiniteNumber(ev.beat) || ev.beat < 0) {
      throw new BeatmapError(`event[${i}].beat must be a number >= 0`);
    }
    if (!isEventType(ev.type)) {
      throw new BeatmapError(`event[${i}].type must be one of ${EVENT_TYPES.join("|")}`);
    }
    return { beat: ev.beat, type: ev.type };
  });

  // REQ-MAP-02: sort ascending by beat (stable), de-dupe exact (beat,type) pairs.
  parsed.sort((a, b) => a.beat - b.beat);
  const seen = new Set<string>();
  const events: BeatmapEvent[] = [];
  for (const ev of parsed) {
    const key = `${ev.beat}|${ev.type}`;
    if (seen.has(key)) continue;
    seen.add(key);
    events.push(ev);
  }

  return { track: obj.track, bpm: obj.bpm, offset: obj.offset, events };
}

/**
 * REQ-MAP-03: spawnTime = beatTime(beat) - leadTime, clamped to >= 0
 * (events whose spawn would be negative pre-spawn at t=0).
 */
export function spawnTime(beat: number, bpm: number, offset: number, leadTime: number): number {
  return Math.max(0, beatTime(beat, bpm, offset) - leadTime);
}
