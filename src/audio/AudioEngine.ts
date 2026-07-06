/**
 * AudioEngine — Web Audio wrapper. The single source of truth for time
 * (REQ-TIME-04): gameplay reads `songTime()` derived from AudioContext.currentTime,
 * never Date.now or frame delta.
 *
 * Also provides: a beat-locked metronome (so the groove stays tight regardless of
 * the backing track's exact tempo) and short synthesized SFX for hits.
 */

import { beatTime } from "../core/timing";
import type { Judgment } from "../core/timing";

export class AudioEngine {
  readonly ctx: AudioContext;
  private master: GainNode;
  private musicGain: GainNode;
  private clickGain: GainNode;
  private sfxGain: GainNode;

  private buffer: AudioBuffer | null = null;
  private source: AudioBufferSourceNode | null = null;

  /** ctx.currentTime at which song time 0 occurs. */
  private songStart = 0;
  private playing = false;

  /**
   * Audio output latency (seconds) between when a sample is *scheduled* on the
   * AudioContext clock and when it is actually *heard* through the speakers.
   * songTime() must subtract this, otherwise the note visuals and the judgment
   * clock run this far AHEAD of the sound — so tapping exactly on the beat you
   * hear reads as LATE by the same amount. This was the game-wide "feels off /
   * out of sync" delay. Measured once at start() from the real device.
   */
  private outputLatencySec = 0;
  /**
   * Extra manual calibration (seconds, +ve = treat audio as more delayed). Small
   * headroom on top of the measured latency; tune if a device still feels late.
   */
  private static readonly CALIBRATION_SEC = 0.0;

  // metronome scheduling
  private bpm = 90;
  private offset = 0;
  private nextBeatIndex = 0;
  private metronomeOn = true;

  constructor() {
    const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    this.ctx = new Ctx();
    this.master = this.ctx.createGain();
    this.master.gain.value = 0.9;
    this.master.connect(this.ctx.destination);

    this.musicGain = this.ctx.createGain();
    this.musicGain.gain.value = 0.85;
    this.musicGain.connect(this.master);

    this.clickGain = this.ctx.createGain();
    this.clickGain.gain.value = 0.16;
    this.clickGain.connect(this.master);

    this.sfxGain = this.ctx.createGain();
    this.sfxGain.gain.value = 0.5;
    this.sfxGain.connect(this.master);
  }

  /** Must be called from a user gesture before playback. */
  async unlock(): Promise<void> {
    if (this.ctx.state !== "running") await this.ctx.resume();
  }

  async decode(data: ArrayBuffer): Promise<void> {
    this.buffer = await this.ctx.decodeAudioData(data);
  }

  /** Track length in seconds (decoded buffer, else fallback). */
  get duration(): number {
    return this.buffer ? this.buffer.duration : 64;
  }

  setMetronome(on: boolean): void {
    this.metronomeOn = on;
  }

  /** raw AudioContext clock — fed to RunController as its source of truth. */
  now(): number {
    return this.ctx.currentTime;
  }

  /**
   * seconds since the song started AS HEARD (freezes while suspended). Subtracts
   * the output latency so note visuals + judgment line up with the sound reaching
   * the player's ears, not with when it was scheduled on the audio clock.
   */
  songTime(): number {
    if (!this.playing) return 0;
    return this.ctx.currentTime - this.songStart - this.latencyComp;
  }

  /** Total latency to compensate: measured device latency + manual calibration. */
  private get latencyComp(): number {
    return this.outputLatencySec + AudioEngine.CALIBRATION_SEC;
  }

  isPlaying(): boolean {
    return this.playing;
  }

  /** Start music + metronome. Anchors song time 0 to now. */
  start(bpm: number, offset: number): number {
    this.bpm = bpm;
    this.offset = offset;
    this.nextBeatIndex = 0;
    // Measure device output latency now (values only settle once the context is
    // running). Prefer outputLatency (hardware+buffer, what reaches the speaker);
    // fall back to baseLatency (processing only) when a browser reports 0.
    const out = (this.ctx as AudioContext & { outputLatency?: number }).outputLatency ?? 0;
    const base = (this.ctx as AudioContext & { baseLatency?: number }).baseLatency ?? 0;
    this.outputLatencySec = out > 0 ? out : base;
    const t0 = this.ctx.currentTime + 0.06; // tiny lead so scheduling is clean
    this.songStart = t0;
    if (this.buffer) {
      const src = this.ctx.createBufferSource();
      src.buffer = this.buffer;
      src.connect(this.musicGain);
      src.start(t0);
      this.source = src;
    }
    this.playing = true;
    return t0;
  }

  async pause(): Promise<void> {
    if (this.playing && this.ctx.state === "running") await this.ctx.suspend();
  }

  async resume(): Promise<void> {
    if (this.playing && this.ctx.state === "suspended") await this.ctx.resume();
  }

  stop(): void {
    if (this.source) {
      try {
        this.source.stop();
      } catch {
        /* already stopped */
      }
      this.source = null;
    }
    this.playing = false;
  }

  /**
   * Schedule any metronome clicks whose time is within the lookahead window.
   * Call every frame. No-op when metronome is off or not playing.
   */
  pumpMetronome(lookahead = 0.25): void {
    if (!this.playing || !this.metronomeOn) return;
    const horizon = this.ctx.currentTime + lookahead;
    // schedule beats until past the horizon
    for (let safety = 0; safety < 64; safety++) {
      const when = this.songStart + beatTime(this.nextBeatIndex, this.bpm, this.offset);
      if (when > horizon) break;
      if (when >= this.ctx.currentTime - 0.02) {
        this.click(when, this.nextBeatIndex % 4 === 0);
      }
      this.nextBeatIndex++;
    }
  }

  private click(when: number, downbeat: boolean): void {
    const osc = this.ctx.createOscillator();
    const g = this.ctx.createGain();
    osc.type = "square";
    osc.frequency.value = downbeat ? 1320 : 880;
    const peak = downbeat ? 0.5 : 0.28;
    g.gain.setValueAtTime(0.0001, when);
    g.gain.exponentialRampToValueAtTime(peak, when + 0.004);
    g.gain.exponentialRampToValueAtTime(0.0001, when + 0.06);
    osc.connect(g);
    g.connect(this.clickGain);
    osc.start(when);
    osc.stop(when + 0.08);
  }

  /** Short synthesized hit feedback. */
  sfx(kind: Judgment | "count"): void {
    const t = this.ctx.currentTime;
    if (kind === "Miss") {
      this.tone(t, 180, 110, "sawtooth", 0.18, 0.6);
      return;
    }
    if (kind === "count") {
      this.tone(t, 660, 660, "triangle", 0.1, 0.4);
      return;
    }
    const perfect = kind === "Perfect";
    this.tone(t, perfect ? 880 : 620, perfect ? 1760 : 880, "triangle", 0.16, 0.5);
    if (perfect) this.tone(t + 0.02, 1320, 2640, "sine", 0.14, 0.35);
  }

  private tone(when: number, f0: number, f1: number, type: OscillatorType, dur: number, vol: number): void {
    const osc = this.ctx.createOscillator();
    const g = this.ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(f0, when);
    osc.frequency.exponentialRampToValueAtTime(Math.max(1, f1), when + dur);
    g.gain.setValueAtTime(0.0001, when);
    g.gain.exponentialRampToValueAtTime(vol, when + 0.01);
    g.gain.exponentialRampToValueAtTime(0.0001, when + dur);
    osc.connect(g);
    g.connect(this.sfxGain);
    osc.start(when);
    osc.stop(when + dur + 0.02);
  }
}
