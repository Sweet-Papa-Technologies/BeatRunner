/**
 * scoring.ts — pure scoring, combo & grade. REQ-SCORE-01..05. No Phaser.
 */

import type { Judgment } from "./timing";

/** REQ-SCORE-01: base points per judgment. */
export const BASE_POINTS: Record<Judgment, number> = { Perfect: 100, Good: 50, Miss: 0 };

export type Grade = "S" | "A" | "B" | "C" | "D";

/** Grade thresholds on accuracy% (config), highest-first. */
export const GRADE_THRESHOLDS: { grade: Grade; min: number }[] = [
  { grade: "S", min: 95 },
  { grade: "A", min: 85 },
  { grade: "B", min: 70 },
  { grade: "C", min: 50 },
  { grade: "D", min: 0 },
];

export interface ScoreState {
  score: number;
  combo: number;
  perfects: number;
  goods: number;
  misses: number;
}

export function initialScore(): ScoreState {
  return { score: 0, combo: 0, perfects: 0, goods: 0, misses: 0 };
}

/** REQ-SCORE-01: base points for a judgment. */
export function basePoints(j: Judgment): number {
  return BASE_POINTS[j];
}

/** REQ-SCORE-03: combo multiplier tiers. x1 0-9, x2 10-19, x3 20-29, x4 30+. */
export function multiplier(combo: number): number {
  if (combo < 10) return 1;
  if (combo < 20) return 2;
  if (combo < 30) return 3;
  return 4;
}

/**
 * Apply one judged hit, returning a NEW state (pure).
 * REQ-SCORE-02 combo, REQ-SCORE-03 multiplier (on the combo at the time of the hit),
 * REQ-SCORE-04 non-decreasing score (awards are always >= 0).
 */
export function applyHit(state: ScoreState, j: Judgment): ScoreState {
  const isMiss = j === "Miss";
  const award = basePoints(j) * multiplier(state.combo);
  return {
    score: state.score + award,
    combo: isMiss ? 0 : state.combo + 1,
    perfects: state.perfects + (j === "Perfect" ? 1 : 0),
    goods: state.goods + (j === "Good" ? 1 : 0),
    misses: state.misses + (isMiss ? 1 : 0),
  };
}

/** Accuracy% = (perfects + goods) / total events * 100. 0 when no events. */
export function accuracy(state: ScoreState): number {
  const total = state.perfects + state.goods + state.misses;
  if (total === 0) return 0;
  return ((state.perfects + state.goods) / total) * 100;
}

/** REQ-SCORE-05: final grade from accuracy%. */
export function gradeFor(accuracyPct: number): Grade {
  for (const { grade, min } of GRADE_THRESHOLDS) {
    if (accuracyPct >= min) return grade;
  }
  return "D";
}
