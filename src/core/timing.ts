/**
 * timing.ts — pure, framework-free timing & judgment.
 * REQ-TIME-01..04. No Phaser, no Date.now; all timing derives from an injected clock.
 */

export type Judgment = "Perfect" | "Good" | "Miss";

/** Judgment windows in seconds (inclusive upper bounds). Config constants. */
export interface TimingWindows {
  /** |t-b| <= perfect  => Perfect */
  perfect: number;
  /** |t-b| <= good     => Good */
  good: number;
}

export const DEFAULT_WINDOWS: TimingWindows = { perfect: 0.05, good: 0.12 };

/**
 * Tolerance applied to the (inclusive) window boundaries so float representation
 * error never pushes an exactly-on-boundary input out of its band, e.g.
 * `2.12 - 2.0 === 0.12000000000000011`. Far smaller than any meaningful timing
 * difference (~1ms), so it cannot flip a genuinely off-beat input.
 */
const BOUNDARY_EPSILON = 1e-9;

/** A clock returns the current time in seconds (e.g. AudioContext.currentTime). */
export type Clock = () => number;

/** REQ-TIME-01: beatTime(n, bpm, offset) = offset + (n / bpm) * 60, in seconds. */
export function beatTime(n: number, bpm: number, offset = 0): number {
  return offset + (n / bpm) * 60;
}

/** REQ-TIME-02: classify input time `t` against target beat time `b` by d=|t-b|. */
export function judge(t: number, b: number, windows: TimingWindows = DEFAULT_WINDOWS): Judgment {
  const d = Math.abs(t - b);
  if (d <= windows.perfect + BOUNDARY_EPSILON) return "Perfect";
  if (d <= windows.good + BOUNDARY_EPSILON) return "Good";
  return "Miss";
}

/**
 * REQ-TIME-03: return the closest candidate beat time to `t`.
 * Ties (exactly equidistant) resolve to the earlier (smaller) beat.
 * Throws on an empty candidate list.
 */
export function nearestBeat(t: number, beatTimes: readonly number[]): number {
  if (beatTimes.length === 0) {
    throw new RangeError("nearestBeat: no candidate beats");
  }
  let best = beatTimes[0];
  let bestDist = Math.abs(t - best);
  for (let i = 1; i < beatTimes.length; i++) {
    const candidate = beatTimes[i];
    const dist = Math.abs(t - candidate);
    // strictly closer wins; on an exact tie keep the earlier (smaller) beat
    if (dist < bestDist || (dist === bestDist && candidate < best)) {
      best = candidate;
      bestDist = dist;
    }
  }
  return best;
}

/**
 * REQ-TIME-04: wrap an injected now() source as the single source of truth.
 * Tests drive `now` deterministically with no real audio.
 */
export function createClock(now: () => number): Clock {
  return () => now();
}
