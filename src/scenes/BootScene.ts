import Phaser from "phaser";
import { AudioEngine } from "../audio/AudioEngine";
import { COLORS } from "../game/config";

const HERO_FRAMES = ["hero_run1", "hero_run2", "hero_run3", "hero_run4"];
const HERO_POSES = ["hero_jump", "hero_duck", "hero_strike"];

/** Loads art, builds code-drawn fallbacks + FX textures, creates the shared AudioEngine. */
export class BootScene extends Phaser.Scene {
  constructor() {
    super("Boot");
  }

  preload(): void {
    this.load.image("bg_sky", "assets/sprites/bg_sky.png");
    this.load.image("bg_city", "assets/sprites/bg_city.png");
    this.load.image("bg_near", "assets/sprites/bg_near.png");
    this.load.image("hero", "assets/sprites/hero.png");
    for (const k of HERO_FRAMES) this.load.image(k, `assets/sprites/${k}.png`);
    for (const k of HERO_POSES) this.load.image(k, `assets/sprites/${k}.png`);
    this.load.image("ob_gap", "assets/sprites/ob_gap.png");
    this.load.image("ob_bar", "assets/sprites/ob_bar.png");
    this.load.image("ob_note", "assets/sprites/ob_note.png");
    this.load.image("glow", "assets/sprites/glow.png");
    this.load.on("loaderror", (file: Phaser.Loader.File) => {
      console.warn("asset missing, using fallback:", file.key);
    });
  }

  create(): void {
    this.buildFxTextures();
    this.buildFallbacks();
    this.buildHeroAnim();
    this.registry.set("audio", new AudioEngine());
    this.scene.start("TrackSelect");
  }

  /** Run-cycle flipbook from whatever frames generated; falls back to the base sprite. */
  private buildHeroAnim(): void {
    const frames = HERO_FRAMES.filter((k) => this.textures.exists(k));
    const keys = frames.length >= 2 ? frames : ["hero"];
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

    // spark: bright diamond + cross glints
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

    // ring: thick stroked circle
    g.clear();
    g.lineStyle(10, 0xffffff, 1);
    g.strokeCircle(64, 64, 54);
    g.generateTexture("ring", 128, 128);

    // streak: soft horizontal bar
    g.clear();
    g.fillStyle(0xffffff, 1);
    g.fillRoundedRect(0, 0, 240, 8, 4);
    g.generateTexture("streak", 240, 8);

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
    const obFallback = (key: string, color: number, w: number, h: number, oy: number) => {
      if (this.textures.exists(key)) return;
      g.clear();
      g.fillStyle(color, 1); g.fillRoundedRect(8, oy, w - 16, h - oy - 8, 10);
      g.lineStyle(4, 0xffffff, 0.7); g.strokeRoundedRect(8, oy, w - 16, h - oy - 8, 10);
      g.generateTexture(key, w, h);
    };
    obFallback("ob_gap", COLORS.gap, 96, 96, 56);
    obFallback("ob_bar", COLORS.bar, 120, 96, 8);
    obFallback("ob_note", COLORS.note, 80, 80, 8);

    const bgFallback = (key: string, top: number, bottom: number) => {
      if (this.textures.exists(key)) return;
      g.clear();
      g.fillGradientStyle(top, top, bottom, bottom, 1);
      g.fillRect(0, 0, 1280, 720);
      g.generateTexture(key, 1280, 720);
    };
    bgFallback("bg_sky", 0x0a0625, 0x2a1145);
    bgFallback("bg_city", 0x140a33, 0x07030f);
    bgFallback("bg_near", 0x1a0b2e, 0x05030d);

    g.destroy();
  }
}
