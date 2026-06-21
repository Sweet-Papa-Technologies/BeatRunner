import Phaser from "phaser";
import { AudioEngine } from "../audio/AudioEngine";
import { COLORS } from "../game/config";

const HERO_FRAMES = ["hero_run1", "hero_run2", "hero_run3", "hero_run4"];
const HERO_POSES = ["hero_jump", "hero_duck", "hero_strike"];

/** Loads art, builds code-drawn FX + note textures, creates the shared AudioEngine. */
export class BootScene extends Phaser.Scene {
  constructor() {
    super("Boot");
  }

  preload(): void {
    // OVERDRIVE backgrounds (Imagen). Procedural fallbacks below if any are missing.
    this.load.image("od_sky", "assets/sprites/od_sky.png");
    this.load.image("od_ridge", "assets/sprites/od_ridge.png");
    this.load.image("od_city", "assets/sprites/od_city.png");
    this.load.image("glow", "assets/sprites/glow.png");

    for (const k of HERO_FRAMES) this.load.image(k, `assets/sprites/${k}.png`);
    for (const k of HERO_POSES) this.load.image(k, `assets/sprites/${k}.png`);
    this.load.image("hero", "assets/sprites/hero.png");

    this.load.on("loaderror", (file: Phaser.Loader.File) => {
      console.warn("asset missing, using fallback:", file.key);
    });
  }

  create(): void {
    this.buildFxTextures();
    this.buildNoteTextures();
    this.buildFallbacks();
    this.buildHeroAnim();
    this.registry.set("audio", new AudioEngine());
    this.scene.start("TrackSelect");
  }

  /** Run-cycle flipbook from whatever frames generated; falls back to the base sprite. */
  private buildHeroAnim(): void {
    const frames = HERO_FRAMES.filter((k) => this.textures.exists(k));
    const keys = frames.length >= 2 ? frames : this.textures.exists("hero") ? ["hero"] : [];
    if (keys.length === 0) return;
    this.anims.create({
      key: "hero-run",
      frames: keys.map((key) => ({ key })),
      frameRate: 12,
      repeat: -1,
    });
  }

  /** Additive FX primitives: spark, ring, streak. */
  private buildFxTextures(): void {
    const g = this.add.graphics();

    g.clear();
    g.fillStyle(0xffffff, 1);
    g.fillPoints([
      new Phaser.Geom.Point(16, 2), new Phaser.Geom.Point(22, 16),
      new Phaser.Geom.Point(16, 30), new Phaser.Geom.Point(10, 16),
    ], true);
    g.fillStyle(0xffffff, 0.7);
    g.fillRect(15, 0, 2, 32);
    g.fillRect(0, 15, 32, 2);
    g.generateTexture("spark", 32, 32);

    g.clear();
    g.lineStyle(10, 0xffffff, 1);
    g.strokeCircle(64, 64, 54);
    g.generateTexture("ring", 128, 128);

    g.clear();
    g.fillStyle(0xffffff, 1);
    g.fillRoundedRect(0, 0, 240, 8, 4);
    g.generateTexture("streak", 240, 8);

    g.destroy();
  }

  /** White, tint-ready note + lane-pad textures. */
  private buildNoteTextures(): void {
    const g = this.add.graphics();

    // note: a glossy rounded gem — bright core, softer rim. Tinted per lane in-scene.
    const s = 120;
    g.clear();
    g.fillStyle(0xffffff, 0.22); g.fillRoundedRect(6, 6, s - 12, s - 12, 26);
    g.fillStyle(0xffffff, 0.55); g.fillRoundedRect(18, 18, s - 36, s - 36, 20);
    g.fillStyle(0xffffff, 1.0); g.fillRoundedRect(30, 30, s - 60, s - 60, 14);
    g.generateTexture("note", s, s);

    // glossy highlight blob for the note's top sheen
    g.clear();
    g.fillStyle(0xffffff, 1);
    g.fillEllipse(60, 44, 56, 26);
    g.generateTexture("sheen", 120, 120);

    // hit-pad: a hexagon ring drawn as a stroked polygon.
    g.clear();
    const r = 58, cx = 64, cy = 64;
    const pts: Phaser.Geom.Point[] = [];
    for (let i = 0; i < 6; i++) {
      const a = (Math.PI / 3) * i - Math.PI / 2;
      pts.push(new Phaser.Geom.Point(cx + Math.cos(a) * r, cy + Math.sin(a) * r));
    }
    g.lineStyle(8, 0xffffff, 1);
    g.strokePoints(pts, true, true);
    g.generateTexture("pad", 128, 128);

    g.destroy();
  }

  /** Procedural neon textures used when a generated asset is absent. */
  private buildFallbacks(): void {
    const g = this.add.graphics();

    if (!this.textures.exists("glow")) {
      g.clear();
      g.fillStyle(0xffffff, 1); g.fillCircle(32, 32, 10);
      g.fillStyle(0xffffff, 0.35); g.fillCircle(32, 32, 24);
      g.generateTexture("glow", 64, 64);
    }
    if (!this.textures.exists("hero")) {
      g.clear();
      g.fillStyle(COLORS.hero, 1); g.fillRoundedRect(28, 18, 56, 84, 14);
      g.fillStyle(COLORS.heroAccent, 1); g.fillRoundedRect(36, 30, 40, 16, 6);
      g.generateTexture("hero", 112, 120);
    }

    // Synthwave sky fallback: indigo→magenta with a banded retro sun.
    if (!this.textures.exists("od_sky")) {
      g.clear();
      g.fillGradientStyle(0x150a35, 0x150a35, 0x4a1350, 0x4a1350, 1);
      g.fillRect(0, 0, 1280, 720);
      g.fillStyle(COLORS.sun, 1);
      g.fillCircle(640, 320, 150);
      g.fillStyle(0x150a35, 1);
      for (let i = 0; i < 7; i++) g.fillRect(490, 250 + i * 22, 300, 10);
      g.generateTexture("od_sky", 1280, 720);
    }
    const flat = (key: string, top: number, bottom: number) => {
      if (this.textures.exists(key)) return;
      g.clear();
      g.fillGradientStyle(top, top, bottom, bottom, 1);
      g.fillRect(0, 0, 1280, 720);
      g.generateTexture(key, 1280, 720);
    };
    flat("od_ridge", 0x1a0b3a, 0x0a0420);
    flat("od_city", 0x140a33, 0x0a0420);

    g.destroy();
  }
}
