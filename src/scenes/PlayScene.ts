import Phaser from "phaser";
import { AudioEngine } from "../audio/AudioEngine";
import { parseBeatmap } from "../core/beatmap";
import type { Beatmap, EventType } from "../core/beatmap";
import { beatTime, judge } from "../core/timing";
import type { Judgment } from "../core/timing";
import { applyHit, accuracy, gradeFor, initialScore, multiplier } from "../core/scoring";
import type { ScoreState } from "../core/scoring";
import { RunController } from "../core/run";
import { trackById } from "../game/tracks";
import type { RunResult, TrackDef } from "../game/tracks";
import {
  COLORS, HIGHWAY, LANE_COLORS, LANE_COUNT, LANE_FOR_TYPE, LEAD_TIME, MISS_GRACE,
  VIEW, tierColor,
} from "../game/config";
import { project, laneX } from "../game/highway";
import { shockwave, sparkleBurst, laneBeam, ambientSparkles } from "../game/fx";

interface LiveNote {
  lane: number;
  type: EventType;
  beat: number;
  targetTime: number;
  /** sustain seconds (0 for a tap). */
  dur: number;
  endTime: number;
  spawned: boolean;
  /** head has been judged (hit or auto-missed). */
  judged: boolean;
  /** currently holding a sustain. */
  holding: boolean;
  holdDone: boolean;
  lastTick: number;
  head?: Phaser.GameObjects.Container;
  core?: Phaser.GameObjects.Image;
  ringImg?: Phaser.GameObjects.Image;
  glow?: Phaser.GameObjects.Image;
  tail?: Phaser.GameObjects.Graphics;
}

const HIT_WINDOW = 0.14;     // a press only consumes a note within this of its target
const SUSTAIN_TICK = 0.1;    // seconds between sustain bonus ticks
const SUSTAIN_POINTS = 8;
const HOLD_BONUS = 120;

const LANE_KEYS: Record<string, number> = {
  LEFT: 0, A: 0, J: 0,
  DOWN: 1, S: 1, K: 1, SPACE: 1,
  RIGHT: 2, D: 2, L: 2,
};

export class PlayScene extends Phaser.Scene {
  private audio!: AudioEngine;
  private track!: TrackDef;
  private beatmap!: Beatmap;
  private notes: LiveNote[] = [];
  private run!: RunController;
  private score: ScoreState = initialScore();
  private maxCombo = 0;
  private prevMult = 1;
  private started = false;
  private ended = false;
  private paused = false;
  private laneDown: boolean[] = [false, false, false];

  // world
  private sky!: Phaser.GameObjects.TileSprite;
  private ridge!: Phaser.GameObjects.TileSprite;
  private city!: Phaser.GameObjects.TileSprite;
  private sunGlow!: Phaser.GameObjects.Image;
  private grid!: Phaser.GameObjects.Graphics;
  private laneGlows: Phaser.GameObjects.Rectangle[] = [];
  private pads: Phaser.GameObjects.Image[] = [];
  private padGlows: Phaser.GameObjects.Image[] = [];
  private hero!: Phaser.GameObjects.Sprite;
  private heroAura!: Phaser.GameObjects.Image;
  private heroBaseY = 0;
  private heroBusy = false;
  private particles!: Phaser.GameObjects.Particles.ParticleEmitter;
  private gridPhase = 0;
  private lastBeatPulsed = -1;

  // hud
  private scoreText!: Phaser.GameObjects.Text;
  private comboText!: Phaser.GameObjects.Text;
  private comboLabel!: Phaser.GameObjects.Text;
  private multText!: Phaser.GameObjects.Text;
  private judgeText!: Phaser.GameObjects.Text;
  private progress!: Phaser.GameObjects.Graphics;
  private pauseOverlay?: Phaser.GameObjects.Container;

  constructor() {
    super("Play");
  }

  init(data: { trackId: string }): void {
    this.track = trackById(data?.trackId ?? "overdrive");
    this.notes = [];
    this.score = initialScore();
    this.maxCombo = 0;
    this.prevMult = 1;
    this.started = false;
    this.ended = false;
    this.paused = false;
    this.lastBeatPulsed = -1;
    this.gridPhase = 0;
    this.heroBusy = false;
    this.laneDown = [false, false, false];
    this.pads = [];
    this.padGlows = [];
    this.laneGlows = [];
  }

  async create(): Promise<void> {
    this.audio = this.registry.get("audio") as AudioEngine;
    this.cameras.main.fadeIn(300, 0, 0, 0);
    this.buildWorld();
    this.buildHud();
    this.bindInput();

    const loading = this.add.text(VIEW.width / 2, VIEW.height / 2, "syncing the highway…", {
      fontFamily: "system-ui, sans-serif", fontSize: "26px", color: "#ffffff",
    }).setOrigin(0.5).setDepth(100);

    try {
      const mapRaw = await (await fetch(this.track.map)).json();
      this.beatmap = parseBeatmap(mapRaw);
      const audioBuf = await (await fetch(this.track.audio)).arrayBuffer();
      await this.audio.decode(audioBuf);
    } catch (e) {
      console.error("load failed", e);
      loading.setText("could not load track");
      return;
    }

    this.notes = this.beatmap.events.map((ev) => {
      const targetTime = beatTime(ev.beat, this.beatmap.bpm, this.beatmap.offset);
      const dur = ev.dur ? (ev.dur / this.beatmap.bpm) * 60 : 0;
      return {
        lane: LANE_FOR_TYPE[ev.type], type: ev.type, beat: ev.beat,
        targetTime, dur, endTime: targetTime + dur,
        spawned: false, judged: false, holding: false, holdDone: false, lastTick: 0,
      };
    });

    this.run = new RunController({ clock: () => this.audio.now(), trackDuration: this.audio.duration });
    this.run.start();
    loading.destroy();
    this.audio.setMetronome(true);
    this.countIn();
  }

  // ---------- world ----------
  private buildWorld(): void {
    this.sky = this.add.tileSprite(0, 0, VIEW.width, VIEW.height, "od_sky").setOrigin(0).setDepth(0);
    this.fitTile(this.sky, "od_sky");
    this.ridge = this.add.tileSprite(0, 0, VIEW.width, VIEW.height, "od_ridge").setOrigin(0).setDepth(1).setAlpha(0.6);
    this.fitTile(this.ridge, "od_ridge");
    // distant skyline sits as a thin band right on the horizon, behind the road
    this.city = this.add.tileSprite(0, HIGHWAY.vpY - 64, VIEW.width, 150, "od_city").setOrigin(0).setDepth(1).setAlpha(0.5);

    // soft pulsing sun bloom anchored on the horizon
    this.sunGlow = this.add.image(HIGHWAY.vpX, HIGHWAY.vpY + 6, "glow")
      .setBlendMode(Phaser.BlendModes.ADD).setTint(COLORS.sun).setAlpha(0.5).setScale(9).setDepth(1);

    // darken the foreground so the road + notes read cleanly: gentle fade at the
    // horizon, deep solid black over the near road.
    const veil = this.add.graphics().setDepth(2);
    const fadeTop = HIGHWAY.vpY + 4, fadeH = 220;
    veil.fillGradientStyle(0x0a0420, 0x0a0420, 0x0a0420, 0x0a0420, 0, 0, 0.9, 0.9);
    veil.fillRect(0, fadeTop, VIEW.width, fadeH);
    veil.fillStyle(0x0a0420, 0.9);
    veil.fillRect(0, fadeTop + fadeH, VIEW.width, VIEW.height - fadeTop - fadeH);

    // animated perspective road grid
    this.grid = this.add.graphics().setDepth(2);

    // lane glow strips (brighten as notes approach / on hit)
    for (let i = 0; i < LANE_COUNT; i++) {
      const x = laneX(i);
      const strip = this.add.rectangle(x, (HIGHWAY.vpY + HIGHWAY.hitY) / 2, 90, HIGHWAY.hitY - HIGHWAY.vpY, LANE_COLORS[i], 0.0)
        .setBlendMode(Phaser.BlendModes.ADD).setDepth(3);
      this.laneGlows.push(strip);
    }

    // hit-line + three lane pads
    const hitGfx = this.add.graphics().setDepth(3);
    const lx = laneX(0) - 70, rx = laneX(2) + 70;
    hitGfx.lineStyle(3, 0xffffff, 0.5);
    hitGfx.lineBetween(lx, HIGHWAY.hitY, rx, HIGHWAY.hitY);
    hitGfx.lineStyle(8, 0xffffff, 0.12);
    hitGfx.lineBetween(lx, HIGHWAY.hitY + 4, rx, HIGHWAY.hitY + 4);

    for (let i = 0; i < LANE_COUNT; i++) {
      const x = laneX(i);
      const padGlow = this.add.image(x, HIGHWAY.hitY, "glow")
        .setBlendMode(Phaser.BlendModes.ADD).setTint(LANE_COLORS[i]).setAlpha(0.32).setScale(2.6).setDepth(3);
      const pad = this.add.image(x, HIGHWAY.hitY, "pad").setTint(LANE_COLORS[i]).setAlpha(0.85).setScale(0.92).setDepth(4);
      this.tweens.add({ targets: pad, angle: 360, duration: 9000, repeat: -1 });
      this.padGlows.push(padGlow);
      this.pads.push(pad);
    }

    ambientSparkles(this, VIEW.width, VIEW.height);

    // reacting mascot in the foreground corner
    this.heroBaseY = HIGHWAY.hitY + 86;
    this.heroAura = this.add.image(150, this.heroBaseY - 54, "glow")
      .setBlendMode(Phaser.BlendModes.ADD).setTint(COLORS.hero).setAlpha(0.45).setScale(3.4).setDepth(5);
    this.hero = this.add.sprite(150, this.heroBaseY, this.textures.exists("hero_run1") ? "hero_run1" : "hero")
      .setOrigin(0.5, 1).setScale(0.62).setDepth(6);
    if (this.anims.exists("hero-run")) this.hero.play("hero-run");
    this.tweens.add({ targets: this.hero, y: this.heroBaseY - 8, duration: 320, yoyo: true, repeat: -1, ease: "Sine.inOut" });

    this.particles = this.add.particles(0, 0, "spark", {
      lifespan: 560, speed: { min: 90, max: 360 }, scale: { start: 0.8, end: 0 },
      rotate: { start: 0, end: 360 }, gravityY: 260,
      blendMode: Phaser.BlendModes.ADD, emitting: false,
    }).setDepth(9);
  }

  private fitTile(t: Phaser.GameObjects.TileSprite, key: string): void {
    const src = this.textures.get(key).getSourceImage();
    if (src && src.width) t.setTileScale(VIEW.width / src.width);
  }

  private drawGrid(intensity: number): void {
    const g = this.grid;
    g.clear();
    const vpX = HIGHWAY.vpX, vpY = HIGHWAY.vpY, hitY = HIGHWAY.hitY;
    const edgeU = 1.9; // road half-width in lane-spread units
    const gpx = (u: number, d: number) => vpX + u * HIGHWAY.spread * d;
    const gpy = (d: number) => vpY + (hitY - vpY) * d;

    // longitudinal lane lines (road edges + lane boundaries)
    const cols = [-edgeU, -1.5, -0.5, 0.5, 1.5, edgeU];
    for (const u of cols) {
      const edge = Math.abs(u) > 1.6;
      g.lineStyle(edge ? 3 : 2, edge ? 0x6cf2ff : 0xff7adf, (edge ? 0.5 : 0.28) * intensity);
      g.lineBetween(gpx(u, 0.02), gpy(0.02), gpx(u, 1.25), gpy(1.25));
    }

    // transverse rungs, denser near the horizon, scrolling toward the camera
    const N = 16;
    for (let i = 0; i < N; i++) {
      const frac = ((i + (this.gridPhase % 1)) / N);
      const d = Math.pow(frac, 2.0) * 1.25;
      if (d < 0.02) continue;
      const a = (0.12 + 0.5 * d) * intensity;
      g.lineStyle(d > 0.7 ? 3 : 2, 0x9b6cff, Math.min(0.6, a));
      g.lineBetween(gpx(-edgeU, d), gpy(d), gpx(edgeU, d), gpy(d));
    }
  }

  private buildHud(): void {
    const f = (size: number) => ({ fontFamily: "system-ui, sans-serif", fontSize: `${size}px`, color: "#ffffff" });
    this.scoreText = this.add.text(30, 22, "0", { ...f(50), fontStyle: "bold" }).setDepth(20);
    this.scoreText.setShadow(0, 0, "#2de2e6", 14, true, true);
    this.add.text(32, 78, "SCORE", { ...f(15), color: "#6cf2c4" }).setDepth(20);

    this.comboText = this.add.text(VIEW.width / 2, 150, "", { ...f(80), fontStyle: "bold" }).setOrigin(0.5).setDepth(19).setAlpha(0);
    this.comboLabel = this.add.text(VIEW.width / 2, 198, "", { ...f(18), color: "#cfc6ff", fontStyle: "bold" }).setOrigin(0.5).setDepth(19).setAlpha(0);
    this.multText = this.add.text(VIEW.width - 30, 22, "", { ...f(46), fontStyle: "bold" }).setOrigin(1, 0).setDepth(20);

    this.judgeText = this.add.text(HIGHWAY.vpX, HIGHWAY.hitY - 120, "", { ...f(44), fontStyle: "bold" })
      .setOrigin(0.5).setDepth(20).setAlpha(0);

    this.progress = this.add.graphics().setDepth(20);

    const hint = "◄ ▼ ►  /  A S D  /  J K L   —   hit the lanes on the beat   ·   P pause";
    this.add.text(VIEW.width / 2, VIEW.height - 22, hint, { ...f(16), color: "#ffffff" })
      .setOrigin(0.5).setDepth(20).setAlpha(0.5);
  }

  // ---------- input ----------
  private bindInput(): void {
    const kb = this.input.keyboard;
    if (!kb) return;
    for (const key of Object.keys(LANE_KEYS)) {
      kb.on(`keydown-${key}`, () => this.pressLane(LANE_KEYS[key]));
      kb.on(`keyup-${key}`, () => this.releaseLane(LANE_KEYS[key]));
    }
    kb.on("keydown-P", () => this.togglePause());
    kb.on("keydown-ESC", () => this.togglePause());
    kb.on("keydown-M", () => this.audio.setMetronome(false));

    this.input.on("pointerdown", (p: Phaser.Input.Pointer) => {
      if (this.paused) return;
      const lane = p.x < VIEW.width / 3 ? 0 : p.x < (VIEW.width * 2) / 3 ? 1 : 2;
      this.pressLane(lane);
    });
    this.input.on("pointerup", (p: Phaser.Input.Pointer) => {
      const lane = p.x < VIEW.width / 3 ? 0 : p.x < (VIEW.width * 2) / 3 ? 1 : 2;
      this.releaseLane(lane);
    });
  }

  // ---------- countdown ----------
  private countIn(): void {
    const beatMs = (60 / this.beatmap.bpm) * 1000;
    const big = this.add.text(VIEW.width / 2, VIEW.height / 2 - 30, "", {
      fontFamily: "system-ui, sans-serif", fontSize: "150px", color: "#ffffff", fontStyle: "bold",
    }).setOrigin(0.5).setDepth(30);
    big.setShadow(0, 0, "#ff2d95", 30, true, true);
    const seq = ["3", "2", "1", "GO!"];
    seq.forEach((label, i) => {
      this.time.delayedCall(i * beatMs, () => {
        big.setText(label).setScale(0.3).setAlpha(1);
        big.setColor(label === "GO!" ? "#6cf2c4" : "#ffffff");
        this.audio.sfx("count");
        shockwave(this, VIEW.width / 2, VIEW.height / 2 - 30, label === "GO!" ? 0x6cf2c4 : 0xffffff, { scale: 3.4 });
        this.tweens.add({ targets: big, scale: 1.25, duration: beatMs * 0.6, ease: "Back.out" });
        this.tweens.add({ targets: big, alpha: 0, delay: beatMs * 0.55, duration: beatMs * 0.4 });
      });
    });
    this.time.delayedCall(seq.length * beatMs, () => { big.destroy(); this.beginPlay(); });
  }

  private beginPlay(): void {
    if (this.started || this.run.state !== "Countdown") return;
    this.run.beginPlay();
    this.audio.start(this.beatmap.bpm, this.beatmap.offset);
    this.started = true;
  }

  // ---------- main loop ----------
  update(_t: number, delta: number): void {
    this.sky.tilePositionX += delta * 0.004;
    this.ridge.tilePositionX += delta * 0.012;
    this.city.tilePositionX += delta * 0.03;

    if (!this.started || this.ended || this.paused) {
      if (!this.started) this.drawGrid(0.7);
      return;
    }

    this.audio.pumpMetronome();
    const songTime = this.audio.songTime();
    this.gridPhase += delta * 0.0011 * (this.beatmap.bpm / 100);

    this.updateBeatPulse(songTime);
    this.drawGrid(0.85);
    this.updateNotes(songTime);
    this.updateHud(songTime);

    if (this.run.tick() === "Results") this.finish();
  }

  private updateBeatPulse(songTime: number): void {
    const beat = Math.floor((songTime - this.beatmap.offset) / (60 / this.beatmap.bpm));
    if (beat === this.lastBeatPulsed || beat < 0) return;
    this.lastBeatPulsed = beat;
    const accent = beat % 4 === 0;

    this.tweens.add({ targets: this.cameras.main, zoom: accent ? 1.02 : 1.01, duration: 90, yoyo: true, ease: "Sine.inOut" });
    this.sunGlow.setScale(accent ? 10.5 : 9.6).setAlpha(accent ? 0.7 : 0.55);
    this.tweens.add({ targets: this.sunGlow, scale: 9, alpha: 0.45, duration: 280, ease: "Quad.out" });
    this.heroAura.setTint(tierColor(this.score.combo));
    // mascot bob accent
    if (accent && !this.heroBusy) {
      this.tweens.add({ targets: this.hero, scaleY: 0.66, duration: 90, yoyo: true, ease: "Quad.out" });
    }
  }

  private updateNotes(songTime: number): void {
    // decay lane glows; proximity/hit re-energize them below
    for (const lg of this.laneGlows) lg.fillAlpha *= 0.82;

    for (const n of this.notes) {
      if (n.holdDone) continue;

      if (!n.spawned && songTime >= n.targetTime - LEAD_TIME) {
        n.spawned = true;
        this.spawnNote(n);
      }
      if (!n.spawned) continue;

      const pHead = 1 - (n.targetTime - songTime) / LEAD_TIME;

      // sustain handling
      if (n.holding) {
        this.updateHold(n, songTime);
      }

      // position the head (clamp at the hit-line while holding)
      const dispP = n.holding ? Math.min(pHead, 1.0) : pHead;
      const pr = project(n.lane, dispP);
      if (n.head) {
        n.head.setPosition(pr.x, pr.y).setScale(pr.scale).setAlpha(n.holding ? 1 : pr.alpha);
      }
      // lane proximity glow
      if (!n.judged) {
        const near = Phaser.Math.Clamp(pHead, 0, 1);
        const cur = this.laneGlows[n.lane];
        cur.fillAlpha = Math.max(cur.fillAlpha, 0.04 + near * near * 0.16);
      }

      // hold tail
      if (n.dur > 0 && n.tail) this.drawTail(n, songTime, dispP);

      // auto-miss the head
      if (!n.judged && songTime > n.targetTime + MISS_GRACE) {
        this.resolve(n, "Miss", true);
      }
      // a missed tap flies off the bottom — clean it up
      if (n.judged && !n.holding && n.dur === 0 && pHead > 1.4) {
        this.killNote(n);
      }
    }
  }

  private spawnNote(n: LiveNote): void {
    const color = LANE_COLORS[n.lane];
    const pr = project(n.lane, 0);
    const glow = this.add.image(0, 0, "glow").setBlendMode(Phaser.BlendModes.ADD).setTint(color).setAlpha(0.55).setScale(1.6);
    const ringImg = this.add.image(0, 0, "ring").setBlendMode(Phaser.BlendModes.ADD).setTint(0xffffff).setAlpha(0.6).setScale(0.62);
    const core = this.add.image(0, 0, "note").setTint(color).setScale(0.5);
    const sheen = this.add.image(0, -14, "sheen").setTint(0xffffff).setAlpha(0.5).setScale(0.42).setBlendMode(Phaser.BlendModes.ADD);
    const head = this.add.container(pr.x, pr.y, [glow, ringImg, core, sheen]).setDepth(5).setScale(pr.scale);
    n.head = head; n.core = core; n.ringImg = ringImg; n.glow = glow;
    this.tweens.add({ targets: ringImg, angle: 360, duration: 3200, repeat: -1 });

    if (n.dur > 0) {
      n.tail = this.add.graphics().setDepth(4).setBlendMode(Phaser.BlendModes.ADD);
    }
  }

  private drawTail(n: LiveNote, songTime: number, headDispP: number): void {
    const g = n.tail!;
    g.clear();
    const pBottom = headDispP;                                   // head end (nearer camera)
    const pTop = 1 - (n.endTime - songTime) / LEAD_TIME;         // sustain end (further up)
    if (pTop >= pBottom) return;
    const top = project(n.lane, Math.max(0, pTop));
    const bot = project(n.lane, Math.min(pBottom, 1.0));
    const wTop = 26 * top.scale, wBot = 26 * bot.scale;
    g.fillStyle(LANE_COLORS[n.lane], n.holding ? 0.6 : 0.34);
    g.fillPoints([
      new Phaser.Geom.Point(top.x - wTop, top.y),
      new Phaser.Geom.Point(top.x + wTop, top.y),
      new Phaser.Geom.Point(bot.x + wBot, bot.y),
      new Phaser.Geom.Point(bot.x - wBot, bot.y),
    ], true);
  }

  private updateHold(n: LiveNote, songTime: number): void {
    if (!this.laneDown[n.lane]) { this.endHold(n, false); return; }
    if (songTime >= n.endTime) { this.endHold(n, true); return; }
    if (songTime - n.lastTick >= SUSTAIN_TICK) {
      n.lastTick = songTime;
      this.score = { ...this.score, score: this.score.score + SUSTAIN_POINTS };
      this.particles.setParticleTint(LANE_COLORS[n.lane]);
      this.particles.emitParticleAt(laneX(n.lane), HIGHWAY.hitY, 2);
    }
  }

  private endHold(n: LiveNote, complete: boolean): void {
    n.holding = false;
    n.holdDone = true;
    if (complete) {
      this.score = { ...this.score, score: this.score.score + HOLD_BONUS };
      shockwave(this, laneX(n.lane), HIGHWAY.hitY, LANE_COLORS[n.lane], { scale: 2.6 });
      sparkleBurst(this, laneX(n.lane), HIGHWAY.hitY, LANE_COLORS[n.lane], 18);
      this.flashPad(n.lane, 1);
    }
    this.killNote(n);
  }

  private killNote(n: LiveNote): void {
    n.head?.destroy(); n.head = undefined;
    if (n.tail) { n.tail.destroy(); n.tail = undefined; }
  }

  private updateHud(songTime: number): void {
    this.scoreText.setText(`${this.score.score}`);
    const m = multiplier(this.score.combo);
    if (m > 1) {
      this.multText.setText(`×${m}`);
      this.multText.setColor(Phaser.Display.Color.IntegerToColor(tierColor(this.score.combo)).rgba);
    } else this.multText.setText("");

    const p = Phaser.Math.Clamp(songTime / this.audio.duration, 0, 1);
    this.progress.clear();
    this.progress.fillStyle(0xffffff, 0.12); this.progress.fillRect(0, VIEW.height - 6, VIEW.width, 6);
    this.progress.fillStyle(this.track.color, 1); this.progress.fillRect(0, VIEW.height - 6, VIEW.width * p, 6);
    this.progress.fillStyle(0xffffff, 0.9); this.progress.fillCircle(VIEW.width * p, VIEW.height - 3, 5);
  }

  // ---------- actions & judgment ----------
  private pressLane(lane: number): void {
    if (!this.started || this.ended || this.paused) return;
    this.laneDown[lane] = true;
    this.animateHit(lane);
    this.flashPad(lane, 0.6);

    const songTime = this.audio.songTime();
    let best: LiveNote | undefined;
    let bestDist = Infinity;
    for (const n of this.notes) {
      if (n.judged || n.lane !== lane) continue;
      const d = Math.abs(n.targetTime - songTime);
      if (d <= HIT_WINDOW && d < bestDist) { best = n; bestDist = d; }
    }
    if (!best) return; // harmless whiff
    this.resolve(best, judge(songTime, best.targetTime), false);
  }

  private releaseLane(lane: number): void {
    this.laneDown[lane] = false;
  }

  private resolve(n: LiveNote, result: Judgment, auto: boolean): void {
    n.judged = true;
    this.score = applyHit(this.score, result);
    this.maxCombo = Math.max(this.maxCombo, this.score.combo);
    this.audio.sfx(result);
    this.flashJudge(result, n.lane);

    if (result === "Miss") {
      if (n.head) {
        this.tweens.killTweensOf(n.head);
        this.tweens.add({ targets: n.head, alpha: 0, duration: 240, onComplete: () => this.killNote(n) });
      } else this.killNote(n);
      if (auto) this.stumble();
      this.prevMult = 1;
      return;
    }

    // hit!
    const color = LANE_COLORS[n.lane];
    const x = laneX(n.lane);
    this.flashPad(n.lane, 1);
    laneBeam(this, x, HIGHWAY.hitY, HIGHWAY.vpY, color);
    shockwave(this, x, HIGHWAY.hitY, color, { scale: result === "Perfect" ? 2.4 : 1.8 });
    sparkleBurst(this, x, HIGHWAY.hitY, result === "Perfect" ? COLORS.perfect : color, result === "Perfect" ? 22 : 12);
    this.particles.setParticleTint(result === "Perfect" ? COLORS.perfect : color);
    this.particles.emitParticleAt(x, HIGHWAY.hitY, result === "Perfect" ? 16 : 8);

    if (n.dur > 0 && this.laneDown[n.lane]) {
      // begin sustain — keep head pinned at the hit-line
      n.holding = true;
      n.lastTick = this.audio.songTime();
      this.tweens.killTweensOf(n.head!);
    } else if (n.head) {
      this.tweens.killTweensOf(n.head);
      this.tweens.add({ targets: n.head, alpha: 0, scale: n.head.scale * 1.7, duration: 200, onComplete: () => this.killNote(n) });
    }

    this.checkComboMilestone();
  }

  private checkComboMilestone(): void {
    const m = multiplier(this.score.combo);
    if (m > this.prevMult) {
      this.prevMult = m;
      const col = tierColor(this.score.combo);
      shockwave(this, VIEW.width / 2, 170, col, { scale: 4 });
      sparkleBurst(this, VIEW.width / 2, 170, col, 30);
      this.cameras.main.flash(150, 50, 30, 80);
    }
  }

  private animateHit(lane: number): void {
    // mascot reacts on every press
    const poses = ["hero_jump", "hero_strike", "hero_duck"];
    const pose = poses[lane];
    if (!this.heroBusy && this.textures.exists(pose)) {
      this.heroBusy = true;
      this.hero.anims.stop();
      this.hero.setTexture(pose);
      this.tweens.add({ targets: this.hero, y: this.heroBaseY - 26, duration: 130, yoyo: true, ease: "Quad.out",
        onComplete: () => {
          this.heroBusy = false;
          if (this.anims.exists("hero-run")) this.hero.play("hero-run");
        } });
    }
  }

  private flashPad(lane: number, strength: number): void {
    const pad = this.pads[lane], glow = this.padGlows[lane];
    pad.setScale(0.92 + 0.3 * strength).setAlpha(1);
    this.tweens.add({ targets: pad, scale: 0.92, alpha: 0.85, duration: 220, ease: "Quad.out" });
    glow.setAlpha(0.32 + 0.5 * strength).setScale(2.6 + strength);
    this.tweens.add({ targets: glow, alpha: 0.32, scale: 2.6, duration: 240, ease: "Quad.out" });
    this.laneGlows[lane].fillAlpha = 0.3 * strength;
  }

  // ---------- juice ----------
  private flashJudge(result: Judgment, lane: number): void {
    const colors: Record<Judgment, number> = { Perfect: COLORS.perfect, Good: COLORS.good, Miss: COLORS.miss };
    const label: Record<Judgment, string> = { Perfect: "PERFECT", Good: "GOOD", Miss: "MISS" };
    const col = Phaser.Display.Color.IntegerToColor(colors[result]).rgba;
    this.judgeText.setText(label[result]).setColor(col).setX(laneX(lane));
    this.judgeText.setShadow(0, 0, col, 16, true, true);
    this.judgeText.setAlpha(1).setScale(0.6).setY(HIGHWAY.hitY - 110);
    this.tweens.add({ targets: this.judgeText, scale: 1.1, y: HIGHWAY.hitY - 130, duration: 160, ease: "Back.out" });
    this.tweens.add({ targets: this.judgeText, alpha: 0, delay: 240, duration: 240 });

    // combo readout
    if (this.score.combo > 1 && result !== "Miss") {
      this.comboText.setText(`${this.score.combo}`);
      this.comboLabel.setText("COMBO");
      const ccol = Phaser.Display.Color.IntegerToColor(tierColor(this.score.combo)).rgba;
      this.comboText.setColor(ccol); this.comboLabel.setColor(ccol);
      this.comboText.setAlpha(1).setScale(0.8); this.comboLabel.setAlpha(0.85);
      this.tweens.add({ targets: this.comboText, scale: 1, duration: 140, ease: "Back.out" });
    } else if (result === "Miss") {
      this.tweens.add({ targets: [this.comboText, this.comboLabel], alpha: 0, duration: 220 });
    }

    if (result === "Perfect") { this.cameras.main.flash(110, 70, 50, 30); this.cameras.main.shake(120, 0.005); }
    else if (result === "Good") this.cameras.main.flash(70, 20, 60, 50);
  }

  private stumble(): void {
    this.cameras.main.shake(180, 0.008);
    const v = this.add.rectangle(0, 0, VIEW.width, VIEW.height, COLORS.miss, 0.18).setOrigin(0).setDepth(15);
    this.tweens.add({ targets: v, alpha: 0, duration: 260, onComplete: () => v.destroy() });
  }

  // ---------- pause ----------
  private togglePause(): void {
    if (!this.started || this.ended) return;
    this.paused = !this.paused;
    if (this.paused) {
      this.run.pause();
      this.audio.pause();
      const bg = this.add.rectangle(0, 0, VIEW.width, VIEW.height, 0x0a0420, 0.74).setOrigin(0);
      const t = this.add.text(VIEW.width / 2, VIEW.height / 2, "PAUSED\n\nP / ESC to resume", {
        fontFamily: "system-ui, sans-serif", fontSize: "42px", color: "#ffffff", align: "center",
      }).setOrigin(0.5);
      this.pauseOverlay = this.add.container(0, 0, [bg, t]).setDepth(40);
    } else {
      this.run.resume();
      this.audio.resume();
      this.pauseOverlay?.destroy();
      this.pauseOverlay = undefined;
    }
  }

  // ---------- end ----------
  private finish(): void {
    if (this.ended) return;
    this.ended = true;
    this.audio.stop();
    const acc = accuracy(this.score);
    const result: RunResult = {
      trackId: this.track.id,
      score: this.score.score,
      maxCombo: this.maxCombo,
      perfects: this.score.perfects,
      goods: this.score.goods,
      misses: this.score.misses,
      total: this.notes.length,
      accuracy: acc,
      grade: gradeFor(acc),
    };
    this.cameras.main.fadeOut(440, 0, 0, 0);
    this.cameras.main.once("camerafadeoutcomplete", () => this.scene.start("Results", result));
  }
}
