import Phaser from "phaser";
import { AudioEngine } from "../audio/AudioEngine";
import { parseBeatmap } from "../core/beatmap";
import type { Beatmap, EventType } from "../core/beatmap";
import { beatTime, judge, nearestBeat } from "../core/timing";
import type { Judgment } from "../core/timing";
import { applyHit, accuracy, gradeFor, initialScore, multiplier } from "../core/scoring";
import type { ScoreState } from "../core/scoring";
import { RunController } from "../core/run";
import { trackById } from "../game/tracks";
import type { RunResult, TrackDef } from "../game/tracks";
import {
  COLORS, LEAD_TIME, STAGE, TYPE_FOR_ACTION, VIEW, tierColor,
  type ActionName,
} from "../game/config";
import { shockwave, sparkleBurst, starfield, spawnStreak, ambientSparkles } from "../game/fx";

interface LiveEvent {
  beat: number;
  type: EventType;
  targetTime: number;
  spawned: boolean;
  judged: boolean;
  sprite?: Phaser.GameObjects.Container;
  glow?: Phaser.GameObjects.Image;
}

const MISS_GRACE = 0.12;
const OB_COLOR: Record<EventType, number> = { GAP: COLORS.gap, BAR: COLORS.bar, NOTE: COLORS.note };
const OB_TEX: Record<EventType, string> = { GAP: "ob_gap", BAR: "ob_bar", NOTE: "ob_note" };
const POSE: Record<ActionName, string> = { Jump: "hero_jump", Duck: "hero_duck", Strike: "hero_strike" };
const Y_FOR_TYPE: Record<EventType, number> = {
  GAP: STAGE.groundY - 8,
  BAR: STAGE.groundY - 110,
  NOTE: STAGE.groundY - 150,
};

export class PlayScene extends Phaser.Scene {
  private audio!: AudioEngine;
  private track!: TrackDef;
  private beatmap!: Beatmap;
  private liveEvents: LiveEvent[] = [];
  private run!: RunController;
  private score: ScoreState = initialScore();
  private maxCombo = 0;
  private prevMult = 1;
  private started = false;
  private ended = false;
  private paused = false;

  // visuals
  private layers: Phaser.GameObjects.TileSprite[] = [];
  private hero!: Phaser.GameObjects.Sprite;
  private heroAura!: Phaser.GameObjects.Image;
  private beatGlow!: Phaser.GameObjects.Image;
  private horizon!: Phaser.GameObjects.Graphics;
  private heroBaseY = STAGE.groundY;
  private heroBusy = false;
  private ghostTimer = 0;
  private particles!: Phaser.GameObjects.Particles.ParticleEmitter;
  private lastBeatPulsed = -1;

  // hud
  private scoreText!: Phaser.GameObjects.Text;
  private comboText!: Phaser.GameObjects.Text;
  private multText!: Phaser.GameObjects.Text;
  private judgeText!: Phaser.GameObjects.Text;
  private progress!: Phaser.GameObjects.Graphics;
  private pauseOverlay?: Phaser.GameObjects.Container;

  constructor() {
    super("Play");
  }

  init(data: { trackId: string }): void {
    this.track = trackById(data?.trackId ?? "groove");
    this.liveEvents = [];
    this.score = initialScore();
    this.maxCombo = 0;
    this.prevMult = 1;
    this.started = false;
    this.ended = false;
    this.paused = false;
    this.lastBeatPulsed = -1;
    this.layers = [];
    this.heroBusy = false;
    this.ghostTimer = 0;
  }

  async create(): Promise<void> {
    this.audio = this.registry.get("audio") as AudioEngine;
    this.cameras.main.fadeIn(280, 0, 0, 0);
    this.buildWorld();
    this.buildHud();
    this.bindInput();

    const loading = this.add.text(VIEW.width / 2, VIEW.height / 2, "loading the groove…", {
      fontFamily: "system-ui, sans-serif", fontSize: "28px", color: "#ffffff",
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

    this.liveEvents = this.beatmap.events.map((ev) => ({
      beat: ev.beat,
      type: ev.type,
      targetTime: beatTime(ev.beat, this.beatmap.bpm, this.beatmap.offset),
      spawned: false,
      judged: false,
    }));

    this.run = new RunController({ clock: () => this.audio.now(), trackDuration: this.audio.duration });
    this.run.start();
    loading.destroy();
    this.countIn();
  }

  // ---------- world ----------
  private buildWorld(): void {
    starfield(this, VIEW.width, VIEW.height, 100);

    this.layers = [
      this.add.tileSprite(0, 0, VIEW.width, VIEW.height, "bg_sky").setOrigin(0).setDepth(1),
      this.add.tileSprite(0, 0, VIEW.width, VIEW.height, "bg_city").setOrigin(0).setAlpha(0.85).setDepth(1),
      this.add.tileSprite(0, VIEW.height - 230, VIEW.width, 230, "bg_near").setOrigin(0, 0).setDepth(2),
    ];

    ambientSparkles(this, VIEW.width, VIEW.height);

    // neon horizon + ground reflection (re-drawn each beat for the flash)
    this.horizon = this.add.graphics().setDepth(2);
    this.drawHorizon(0.8);

    // pocket marker
    const pocket = this.add.graphics().setDepth(2);
    pocket.lineStyle(2, 0xffffff, 0.18);
    pocket.lineBetween(STAGE.actionX, 130, STAGE.actionX, STAGE.groundY + 64);
    const pmGlow = this.add.image(STAGE.actionX, STAGE.groundY - 70, "glow")
      .setBlendMode(Phaser.BlendModes.ADD).setTint(0xffffff).setAlpha(0.10).setScale(2, 5).setDepth(2);
    this.tweens.add({ targets: pmGlow, alpha: 0.22, duration: 900, yoyo: true, repeat: -1, ease: "Sine.inOut" });

    // beat glow behind hero
    this.beatGlow = this.add.image(STAGE.actionX, STAGE.groundY - 70, "glow")
      .setBlendMode(Phaser.BlendModes.ADD).setTint(this.track.color).setAlpha(0.5).setScale(4.5).setDepth(4);

    // hero aura + sprite
    this.heroAura = this.add.image(STAGE.actionX, STAGE.groundY - 60, "glow")
      .setBlendMode(Phaser.BlendModes.ADD).setTint(COLORS.hero).setAlpha(0.5).setScale(3).setDepth(5);
    this.hero = this.add.sprite(STAGE.actionX, this.heroBaseY, "hero_run1").setDepth(6).setOrigin(0.5, 1).setScale(0.46);
    if (this.anims.exists("hero-run")) this.hero.play("hero-run");

    this.particles = this.add.particles(0, 0, "spark", {
      lifespan: 560, speed: { min: 90, max: 360 }, scale: { start: 0.8, end: 0 },
      rotate: { start: 0, end: 360 }, gravityY: 300,
      blendMode: Phaser.BlendModes.ADD, emitting: false,
    }).setDepth(9);
  }

  private drawHorizon(intensity: number): void {
    const y = STAGE.groundY + 64;
    this.horizon.clear();
    this.horizon.fillStyle(0x05030d, 0.85);
    this.horizon.fillRect(0, y, VIEW.width, VIEW.height - y);
    this.horizon.lineStyle(4, this.track.color, intensity);
    this.horizon.lineBetween(0, y, VIEW.width, y);
    this.horizon.lineStyle(2, 0xffffff, intensity * 0.6);
    this.horizon.lineBetween(0, y + 3, VIEW.width, y + 3);
  }

  private buildHud(): void {
    const f = (size: number) => ({ fontFamily: "system-ui, sans-serif", fontSize: `${size}px`, color: "#ffffff" });
    this.scoreText = this.add.text(28, 22, "0", { ...f(46), fontStyle: "bold" }).setDepth(20);
    this.scoreText.setShadow(0, 0, "#9b8cff", 12, true, true);
    this.add.text(30, 74, "SCORE", { ...f(16), color: "#9b8cff" }).setDepth(20);

    this.comboText = this.add.text(VIEW.width - 28, 18, "", { ...f(58), fontStyle: "bold" })
      .setOrigin(1, 0).setDepth(20);
    this.multText = this.add.text(VIEW.width - 30, 86, "", { ...f(24), fontStyle: "bold" }).setOrigin(1, 0).setDepth(20);

    this.judgeText = this.add.text(STAGE.actionX, 250, "", { ...f(46), fontStyle: "bold" })
      .setOrigin(0.5).setDepth(20).setAlpha(0);

    this.progress = this.add.graphics().setDepth(20);

    const hint = "SPACE/↑ Jump · ↓ Duck · F Strike · P pause";
    this.add.text(VIEW.width / 2, VIEW.height - 24, hint, { ...f(17), color: "#ffffff" })
      .setOrigin(0.5).setDepth(20).setAlpha(0.55);
  }

  // ---------- input ----------
  private bindInput(): void {
    const kb = this.input.keyboard;
    if (!kb) return;
    kb.on("keydown-SPACE", () => this.act("Jump"));
    kb.on("keydown-UP", () => this.act("Jump"));
    kb.on("keydown-W", () => this.act("Jump"));
    kb.on("keydown-DOWN", () => this.act("Duck"));
    kb.on("keydown-S", () => this.act("Duck"));
    kb.on("keydown-F", () => this.act("Strike"));
    kb.on("keydown-J", () => this.act("Strike"));
    kb.on("keydown-P", () => this.togglePause());
    kb.on("keydown-ESC", () => this.togglePause());
    kb.on("keydown-M", () => this.audio.setMetronome(false));

    this.input.on("pointerdown", (p: Phaser.Input.Pointer) => {
      if (this.paused) return;
      const third = p.x / VIEW.width;
      this.act(third < 0.34 ? "Jump" : third < 0.67 ? "Duck" : "Strike");
    });
  }

  // ---------- countdown ----------
  private countIn(): void {
    const beatMs = (60 / this.beatmap.bpm) * 1000;
    const big = this.add.text(VIEW.width / 2, VIEW.height / 2 - 40, "", {
      fontFamily: "system-ui, sans-serif", fontSize: "140px", color: "#ffffff", fontStyle: "bold",
    }).setOrigin(0.5).setDepth(30);
    big.setShadow(0, 0, "#ff5dcb", 30, true, true);
    const seq = ["3", "2", "1", "GO!"];
    seq.forEach((label, i) => {
      this.time.delayedCall(i * beatMs, () => {
        big.setText(label).setScale(0.3).setAlpha(1);
        big.setColor(label === "GO!" ? "#7af2c4" : "#ffffff");
        this.audio.sfx("count");
        shockwave(this, VIEW.width / 2, VIEW.height / 2 - 40, label === "GO!" ? 0x7af2c4 : 0xffffff, { scale: 3.2 });
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
    this.layers[0].tilePositionX += delta * 0.012;
    this.layers[1].tilePositionX += delta * 0.06;
    this.layers[2].tilePositionX += delta * 0.26;

    if (!this.started || this.ended || this.paused) return;

    this.audio.pumpMetronome();
    const songTime = this.audio.songTime();

    this.updateBeatPulse(songTime);
    this.updateGhosts(delta);
    this.updateEvents(songTime);
    this.updateHud(songTime);

    if (this.run.tick() === "Results") this.finish();
  }

  private updateGhosts(delta: number): void {
    this.ghostTimer -= delta;
    if (this.ghostTimer > 0) return;
    this.ghostTimer = 55;
    const g = this.add.image(this.hero.x, this.hero.y, this.hero.texture.key)
      .setOrigin(0.5, 1).setScale(this.hero.scaleX, this.hero.scaleY)
      .setTint(tierColor(this.score.combo)).setAlpha(0.35).setBlendMode(Phaser.BlendModes.ADD).setDepth(5);
    this.tweens.add({ targets: g, alpha: 0, x: g.x - 40, duration: 320, onComplete: () => g.destroy() });
  }

  private updateBeatPulse(songTime: number): void {
    const beat = Math.floor((songTime - this.beatmap.offset) / (60 / this.beatmap.bpm));
    if (beat === this.lastBeatPulsed || beat < 0) return;
    this.lastBeatPulsed = beat;
    const accent = beat % 4 === 0;

    this.tweens.add({ targets: this.cameras.main, zoom: accent ? 1.018 : 1.009, duration: 95, yoyo: true, ease: "Sine.inOut" });

    this.beatGlow.setScale(accent ? 6 : 5).setAlpha(accent ? 0.8 : 0.6);
    this.tweens.add({ targets: this.beatGlow, scale: 4.2, alpha: 0.4, duration: 260, ease: "Quad.out" });

    this.heroAura.setTint(tierColor(this.score.combo));
    this.drawHorizon(accent ? 1 : 0.8);

    if (accent) spawnStreak(this, VIEW.width, VIEW.height, this.track.color);
    if (beat % 2 === 0) spawnStreak(this, VIEW.width, VIEW.height, 0xffffff);
  }

  private updateEvents(songTime: number): void {
    const rightX = STAGE.spawnX;
    for (const e of this.liveEvents) {
      if (e.judged) continue;

      if (!e.spawned && songTime >= e.targetTime - LEAD_TIME) {
        e.spawned = true;
        this.spawnObstacle(e, rightX);
      }

      if (e.spawned && e.sprite) {
        const frac = Phaser.Math.Clamp((e.targetTime - songTime) / LEAD_TIME, -0.4, 1);
        e.sprite.x = STAGE.actionX + (rightX - STAGE.actionX) * frac;
        if (e.glow) e.glow.x = e.sprite.x;
        // proximity telegraph: brighten as it nears the pocket
        const near = 1 - Phaser.Math.Clamp(Math.abs(e.sprite.x - STAGE.actionX) / 300, 0, 1);
        if (e.glow) e.glow.setAlpha(0.25 + near * 0.5);
      }

      if (e.spawned && !e.judged && songTime > e.targetTime + MISS_GRACE) {
        this.resolve(e, "Miss", true);
      }
    }
  }

  private spawnObstacle(e: LiveEvent, x: number): void {
    const color = OB_COLOR[e.type];
    const y = Y_FOR_TYPE[e.type];
    e.glow = this.add.image(x, y, "glow").setBlendMode(Phaser.BlendModes.ADD).setTint(color)
      .setAlpha(0.4).setScale(2.4).setDepth(4);

    const img = this.add.image(0, 0, OB_TEX[e.type]).setOrigin(0.5, e.type === "GAP" ? 1 : 0.5);
    img.setScale(e.type === "BAR" ? 0.62 : 0.44);
    const halo = this.add.image(0, 0, "ring").setBlendMode(Phaser.BlendModes.ADD).setTint(color).setAlpha(0.5).setScale(0.6);
    const cont = this.add.container(x, y, [halo, img]).setDepth(5);
    e.sprite = cont;

    // spawn pop
    cont.setScale(0.2);
    this.tweens.add({ targets: cont, scale: 1, duration: 240, ease: "Back.out" });
    // idle life
    this.tweens.add({ targets: halo, angle: 360, duration: 4000, repeat: -1 });
    if (e.type === "NOTE") {
      this.tweens.add({ targets: img, angle: { from: -8, to: 8 }, duration: 500, yoyo: true, repeat: -1, ease: "Sine.inOut" });
      this.tweens.add({ targets: cont, y: y - 14, duration: 600, yoyo: true, repeat: -1, ease: "Sine.inOut" });
    } else {
      this.tweens.add({ targets: halo, scale: 0.75, duration: 420, yoyo: true, repeat: -1, ease: "Sine.inOut" });
    }
  }

  private updateHud(songTime: number): void {
    this.scoreText.setText(`${this.score.score}`);
    if (this.score.combo > 1) {
      this.comboText.setText(`${this.score.combo}`);
      const col = Phaser.Display.Color.IntegerToColor(tierColor(this.score.combo)).rgba;
      this.comboText.setColor(col);
      const m = multiplier(this.score.combo);
      this.multText.setText(m > 1 ? `×${m}` : "");
      this.multText.setColor(col);
    } else {
      this.comboText.setText("");
      this.multText.setText("");
    }

    const p = Phaser.Math.Clamp(songTime / this.audio.duration, 0, 1);
    this.progress.clear();
    this.progress.fillStyle(0xffffff, 0.12); this.progress.fillRect(0, 0, VIEW.width, 6);
    this.progress.fillStyle(this.track.color, 1); this.progress.fillRect(0, 0, VIEW.width * p, 6);
    this.progress.fillStyle(0xffffff, 0.9); this.progress.fillCircle(VIEW.width * p, 3, 5);
  }

  // ---------- actions & judgment ----------
  private act(action: ActionName): void {
    if (!this.started || this.ended || this.paused) return;
    const wantType = TYPE_FOR_ACTION[action];
    const songTime = this.audio.songTime();
    const candidates = this.liveEvents.filter(
      (e) => !e.judged && e.type === wantType && Math.abs(e.targetTime - songTime) <= 0.26,
    );
    this.animateHero(action);
    if (candidates.length === 0) return;

    const target = nearestBeat(songTime, candidates.map((c) => c.targetTime));
    const ev = candidates.find((c) => c.targetTime === target)!;
    this.resolve(ev, judge(songTime, ev.targetTime), false);
  }

  private resolve(e: LiveEvent, result: Judgment, auto: boolean): void {
    e.judged = true;
    this.score = applyHit(this.score, result);
    this.maxCombo = Math.max(this.maxCombo, this.score.combo);
    this.audio.sfx(result);
    this.flashJudge(result);

    const sprite = e.sprite;
    const glow = e.glow;
    if (glow) this.tweens.add({ targets: glow, alpha: 0, duration: 220, onComplete: () => glow.destroy() });
    if (sprite) {
      this.tweens.killTweensOf(sprite);
      if (result === "Miss") {
        this.tweens.add({ targets: sprite, alpha: 0, y: sprite.y + 36, angle: 20, duration: 280, onComplete: () => sprite.destroy() });
      } else {
        shockwave(this, sprite.x, sprite.y, OB_COLOR[e.type], { scale: 2.2 });
        sparkleBurst(this, sprite.x, sprite.y, result === "Perfect" ? COLORS.perfect : COLORS.good, result === "Perfect" ? 22 : 12);
        this.particles.setParticleTint(result === "Perfect" ? COLORS.perfect : COLORS.good);
        this.particles.emitParticleAt(sprite.x, sprite.y, result === "Perfect" ? 18 : 8);
        this.tweens.add({ targets: sprite, alpha: 0, scale: sprite.scale * 1.9, duration: 220, onComplete: () => sprite.destroy() });
      }
    }

    if (result !== "Miss") this.checkComboMilestone();
    if (result === "Miss" && !auto) return;
    if (result === "Miss") this.stumble();
  }

  private checkComboMilestone(): void {
    const m = multiplier(this.score.combo);
    if (m > this.prevMult) {
      this.prevMult = m;
      const col = tierColor(this.score.combo);
      shockwave(this, this.hero.x, this.hero.y - 80, col, { scale: 4 });
      sparkleBurst(this, this.hero.x, this.hero.y - 80, col, 30);
      this.cameras.main.flash(160, 60, 40, 90);
      const t = this.add.text(VIEW.width / 2, 360, `×${m} COMBO!`, {
        fontFamily: "system-ui, sans-serif", fontSize: "52px", color: Phaser.Display.Color.IntegerToColor(col).rgba, fontStyle: "bold",
      }).setOrigin(0.5).setDepth(25).setScale(0.5);
      this.tweens.add({ targets: t, scale: 1.2, duration: 220, ease: "Back.out" });
      this.tweens.add({ targets: t, alpha: 0, y: 320, delay: 500, duration: 400, onComplete: () => t.destroy() });
    } else if (this.score.combo === 0) {
      this.prevMult = 1;
    }
  }

  private animateHero(action: ActionName): void {
    if (this.heroBusy) return;
    this.heroBusy = true;
    const poseKey = POSE[action];
    const hadAnim = this.anims.exists("hero-run");
    if (this.textures.exists(poseKey)) { this.hero.anims.stop(); this.hero.setTexture(poseKey); }
    const restore = () => {
      this.heroBusy = false;
      if (hadAnim) this.hero.play("hero-run");
    };

    if (action === "Jump") {
      this.tweens.add({ targets: this.hero, y: this.heroBaseY - 180, duration: 280, yoyo: true, ease: "Quad.out", onComplete: restore });
      this.tweens.add({ targets: this.heroAura, y: this.heroBaseY - 240, duration: 280, yoyo: true, ease: "Quad.out" });
    } else if (action === "Duck") {
      this.tweens.add({ targets: this.hero, scaleY: 0.3, duration: 130, yoyo: true, hold: 140, ease: "Quad.out", onComplete: restore });
    } else {
      this.tweens.add({ targets: this.hero, scaleX: 0.56, duration: 90, yoyo: true, ease: "Quad.out", onComplete: restore });
      const fx = this.add.image(STAGE.actionX + 80, Y_FOR_TYPE.NOTE, "ring").setBlendMode(Phaser.BlendModes.ADD)
        .setTint(COLORS.note).setDepth(7).setScale(0.3);
      this.tweens.add({ targets: fx, scale: 1.6, alpha: 0, duration: 240, onComplete: () => fx.destroy() });
    }
  }

  // ---------- juice ----------
  private flashJudge(result: Judgment): void {
    const colors: Record<Judgment, number> = { Perfect: COLORS.perfect, Good: COLORS.good, Miss: COLORS.miss };
    const label: Record<Judgment, string> = { Perfect: "PERFECT", Good: "GOOD", Miss: "MISS" };
    this.judgeText.setText(label[result]);
    this.judgeText.setColor(Phaser.Display.Color.IntegerToColor(colors[result]).rgba);
    this.judgeText.setShadow(0, 0, Phaser.Display.Color.IntegerToColor(colors[result]).rgba, 18, true, true);
    this.judgeText.setAlpha(1).setScale(0.6).setY(250);
    this.tweens.add({ targets: this.judgeText, scale: 1.15, y: 230, duration: 180, ease: "Back.out" });
    this.tweens.add({ targets: this.judgeText, alpha: 0, delay: 260, duration: 240 });

    if (result === "Perfect") {
      this.cameras.main.flash(120, 80, 60, 30);
      this.cameras.main.shake(140, 0.006);
    } else if (result === "Good") {
      this.cameras.main.flash(80, 30, 70, 50);
    }
  }

  private stumble(): void {
    this.cameras.main.shake(190, 0.009);
    this.tweens.add({ targets: this.hero, angle: { from: -12, to: 0 }, duration: 320, ease: "Elastic.out" });
    const v = this.add.rectangle(0, 0, VIEW.width, VIEW.height, COLORS.miss, 0.2).setOrigin(0).setDepth(15);
    this.tweens.add({ targets: v, alpha: 0, duration: 260, onComplete: () => v.destroy() });
  }

  // ---------- pause ----------
  private togglePause(): void {
    if (!this.started || this.ended) return;
    this.paused = !this.paused;
    if (this.paused) {
      this.run.pause();
      this.audio.pause();
      const bg = this.add.rectangle(0, 0, VIEW.width, VIEW.height, 0x05030d, 0.72).setOrigin(0);
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
      total: this.liveEvents.length,
      accuracy: acc,
      grade: gradeFor(acc),
    };
    this.cameras.main.fadeOut(420, 0, 0, 0);
    this.cameras.main.once("camerafadeoutcomplete", () => this.scene.start("Results", result));
  }
}
