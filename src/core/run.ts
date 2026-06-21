/**
 * run.ts — pure run lifecycle state machine + drift-free pause/resume clock.
 * REQ-RUN-01..03. No Phaser.
 */

import type { Clock } from "./timing";

export type RunPhase = "Loading" | "Countdown" | "Playing" | "Results";

/** REQ-RUN-01: legal one-way transitions (Results->Loading allowed for retry). */
export const TRANSITIONS: Record<RunPhase, readonly RunPhase[]> = {
  Loading: ["Countdown"],
  Countdown: ["Playing"],
  Playing: ["Results"],
  Results: ["Loading"],
};

export class RunError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RunError";
  }
}

/** REQ-RUN-01: return `to` if the transition is legal, else throw RunError. */
export function nextState(from: RunPhase, to: RunPhase): RunPhase {
  if (TRANSITIONS[from].includes(to)) return to;
  throw new RunError(`illegal transition ${from} -> ${to}`);
}

export interface RunControllerOptions {
  /** Source-of-truth clock in seconds (REQ-TIME-04). */
  clock: Clock;
  /** Track length in seconds; the run ends when elapsed >= this (REQ-RUN-03). */
  trackDuration: number;
}

/**
 * Drives a single run: state machine + a pause/resume-safe elapsed clock.
 * REQ-RUN-02: elapsed() advances from the same offset across pause/resume (no drift).
 * REQ-RUN-03: tick() ends the run exactly once when the track ends.
 */
export class RunController {
  private _state: RunPhase = "Loading";
  private readonly clock: Clock;
  private readonly trackDuration: number;

  private origin = 0;
  private pausedAccum = 0;
  private pauseStart = 0;
  private _paused = false;
  private _ended = false;

  constructor(opts: RunControllerOptions) {
    this.clock = opts.clock;
    this.trackDuration = opts.trackDuration;
  }

  get state(): RunPhase {
    return this._state;
  }

  /** Loading -> Countdown. */
  start(): void {
    this._state = nextState(this._state, "Countdown");
  }

  /** Countdown -> Playing; anchors the clock origin. */
  beginPlay(): void {
    this._state = nextState(this._state, "Playing");
    this.origin = this.clock();
    this.pausedAccum = 0;
    this.pauseStart = 0;
    this._paused = false;
  }

  /** Freeze elapsed time. */
  pause(): void {
    if (this._state !== "Playing" || this._paused) return;
    this._paused = true;
    this.pauseStart = this.clock();
  }

  /** Resume from the frozen offset with no drift. */
  resume(): void {
    if (!this._paused) return;
    this.pausedAccum += this.clock() - this.pauseStart;
    this._paused = false;
  }

  /** Whether the run is currently paused. */
  isPaused(): boolean {
    return this._paused;
  }

  /** Audio-clock elapsed seconds since play began, excluding paused spans. */
  elapsed(): number {
    const raw = this.clock() - this.origin - this.pausedAccum;
    // While paused, subtract the in-progress paused span so elapsed stays frozen.
    if (this._paused) return raw - (this.clock() - this.pauseStart);
    return raw;
  }

  /** Advance lifecycle; transitions Playing -> Results once at track end. Returns current state. */
  tick(): RunPhase {
    if (this._ended) return this._state;
    if (this._state === "Playing" && this.elapsed() >= this.trackDuration) {
      this._state = nextState(this._state, "Results");
      this._ended = true;
    }
    return this._state;
  }

  isEnded(): boolean {
    return this._ended;
  }
}
