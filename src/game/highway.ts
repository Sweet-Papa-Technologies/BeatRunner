/** Pure faux-3D projection for the OVERDRIVE highway. No Phaser. */

import { HIGHWAY, LANE_OFFSET } from "./config";

export interface Projected {
  x: number;
  y: number;
  /** Visual scale of a note at this depth (≈0.15 far → 1.0 at hit-line). */
  scale: number;
  /** Opacity ramp so notes fade in from the vanishing point. */
  alpha: number;
}

/** Lateral screen x of a lane at the hit-line. */
export function laneX(lane: number): number {
  return HIGHWAY.vpX + (LANE_OFFSET[lane] ?? 0) * HIGHWAY.spread;
}

/**
 * Project a note onto the highway.
 * @param lane lane index
 * @param p    time progress 0 (just spawned at the vanishing point) → 1 (on the hit-line).
 *             Values >1 let a missed note keep flying past the camera.
 */
export function project(lane: number, p: number): Projected {
  // Perspective easing: notes hang near the horizon, then accelerate toward you.
  const clamped = Math.max(0, p);
  const d = clamped <= 1 ? Math.pow(clamped, HIGHWAY.depthPow) : 1 + (clamped - 1) * 2.2;
  const targetX = laneX(lane);
  return {
    x: HIGHWAY.vpX + (targetX - HIGHWAY.vpX) * d,
    y: HIGHWAY.vpY + (HIGHWAY.hitY - HIGHWAY.vpY) * d,
    scale: 0.15 + 0.95 * Math.min(d, 1.35),
    alpha: Math.max(0, Math.min(1, 0.18 + d * 1.4)),
  };
}
