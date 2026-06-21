import Phaser from "phaser";
import { trackById } from "../game/tracks";
import type { RunResult } from "../game/tracks";
import { COLORS, VIEW } from "../game/config";
import { starfield, ambientSparkles, shockwave, sparkleBurst, spawnStreak } from "../game/fx";

const GRADE_COLORS: Record<string, number> = {
  S: 0xfff27a, A: 0x7af2c4, B: 0x4cc9ff, C: 0x9b8cff, D: 0xff5d7a,
};

export class ResultsScene extends Phaser.Scene {
  private result!: RunResult;

  constructor() {
    super("Results");
  }

  init(data: RunResult): void {
    this.result = data;
  }

  create(): void {
    const r = this.result;
    const track = trackById(r.trackId);
    this.cameras.main.fadeIn(360, 0, 0, 0);

    this.add.image(VIEW.width / 2, VIEW.height / 2, "bg_sky").setDisplaySize(VIEW.width, VIEW.height);
    this.add.image(VIEW.width / 2, VIEW.height / 2, "bg_city").setDisplaySize(VIEW.width, VIEW.height).setAlpha(0.5);
    starfield(this, VIEW.width, VIEW.height, 90);
    ambientSparkles(this, VIEW.width, VIEW.height);

    const bestKey = `itp_best_${r.trackId}`;
    const prevBest = Number(localStorage.getItem(bestKey) ?? 0);
    const isBest = r.score > prevBest;
    if (isBest) localStorage.setItem(bestKey, String(r.score));

    this.add.text(VIEW.width / 2, 80, track.title, {
      fontFamily: "system-ui, sans-serif", fontSize: "40px", color: "#ffffff", fontStyle: "bold",
    }).setOrigin(0.5);
    this.add.text(VIEW.width / 2, 124, "RESULTS", {
      fontFamily: "system-ui, sans-serif", fontSize: "22px", color: "#9b8cff",
    }).setOrigin(0.5);

    // Grade — big, pops in
    const gradeColor = GRADE_COLORS[r.grade] ?? 0xffffff;
    const grade = this.add.text(VIEW.width / 2, 280, r.grade, {
      fontFamily: "system-ui, sans-serif", fontSize: "200px", color: Phaser.Display.Color.IntegerToColor(gradeColor).rgba, fontStyle: "bold",
    }).setOrigin(0.5).setScale(0);
    grade.setShadow(0, 0, Phaser.Display.Color.IntegerToColor(gradeColor).rgba, 40, true, true);
    this.tweens.add({ targets: grade, scale: 1, duration: 600, ease: "Back.out", delay: 250 });
    this.tweens.add({ targets: grade, scale: 1.04, duration: 900, yoyo: true, repeat: -1, ease: "Sine.inOut", delay: 850 });
    this.time.delayedCall(450, () => {
      shockwave(this, VIEW.width / 2, 280, gradeColor, { scale: 6, duration: 600 });
      sparkleBurst(this, VIEW.width / 2, 280, gradeColor, 36);
      this.cameras.main.flash(220, 40, 30, 60);
    });

    // Animated climbing score
    const scoreText = this.add.text(VIEW.width / 2, 430, "0", {
      fontFamily: "system-ui, sans-serif", fontSize: "64px", color: "#ffffff", fontStyle: "bold",
    }).setOrigin(0.5);
    const counter = { v: 0 };
    this.tweens.add({
      targets: counter, v: r.score, duration: 1100, delay: 500, ease: "Cubic.out",
      onUpdate: () => scoreText.setText(`${Math.round(counter.v)}`),
    });

    // breakdown
    const rows = [
      [`Accuracy`, `${r.accuracy.toFixed(1)}%`, 0xffffff],
      [`Perfect`, `${r.perfects}`, COLORS.perfect],
      [`Good`, `${r.goods}`, COLORS.good],
      [`Miss`, `${r.misses}`, COLORS.miss],
      [`Max Combo`, `${r.maxCombo}`, 0x9b8cff],
    ] as const;
    rows.forEach(([label, val, color], i) => {
      const y = 500 + i * 34;
      this.add.text(VIEW.width / 2 - 160, y, label, {
        fontFamily: "system-ui, sans-serif", fontSize: "22px", color: "#cfc6ff",
      }).setOrigin(0, 0.5);
      this.add.text(VIEW.width / 2 + 160, y, val, {
        fontFamily: "system-ui, sans-serif", fontSize: "22px", color: Phaser.Display.Color.IntegerToColor(color).rgba, fontStyle: "bold",
      }).setOrigin(1, 0.5);
    });

    if (isBest) {
      const nb = this.add.text(VIEW.width / 2, 466, "★ NEW BEST ★", {
        fontFamily: "system-ui, sans-serif", fontSize: "24px", color: "#fff27a", fontStyle: "bold",
      }).setOrigin(0.5);
      this.tweens.add({ targets: nb, alpha: 0.3, duration: 500, yoyo: true, repeat: -1 });
      // celebratory confetti streaks
      this.time.addEvent({
        delay: 320, repeat: 8,
        callback: () => spawnStreak(this, VIEW.width, VIEW.height, Phaser.Utils.Array.GetRandom([0xfff27a, 0xff5dcb, 0x7af2c4])),
      });
    } else {
      this.add.text(VIEW.width / 2, 466, `Best: ${Math.max(prevBest, r.score)}`, {
        fontFamily: "system-ui, sans-serif", fontSize: "18px", color: "#8a7fc0",
      }).setOrigin(0.5);
    }

    this.button(VIEW.width / 2 - 130, 688, "RETRY", track.color, () => this.scene.start("Play", { trackId: r.trackId }));
    this.button(VIEW.width / 2 + 130, 688, "TRACKS", 0x9b8cff, () => this.scene.start("TrackSelect"));

    this.input.keyboard?.on("keydown-ENTER", () => this.scene.start("Play", { trackId: r.trackId }));
    this.input.keyboard?.on("keydown-ESC", () => this.scene.start("TrackSelect"));
  }

  private button(x: number, y: number, label: string, color: number, onClick: () => void): void {
    const w = 220, h = 56;
    const g = this.add.graphics();
    g.fillStyle(0x0c0820, 0.95);
    g.fillRoundedRect(-w / 2, -h / 2, w, h, 12);
    g.lineStyle(3, color, 1);
    g.strokeRoundedRect(-w / 2, -h / 2, w, h, 12);
    const t = this.add.text(0, 0, label, {
      fontFamily: "system-ui, sans-serif", fontSize: "26px", color: "#ffffff", fontStyle: "bold",
    }).setOrigin(0.5);
    const c = this.add.container(x, y, [g, t]).setSize(w, h);
    c.setInteractive(new Phaser.Geom.Rectangle(-w / 2, -h / 2, w, h), Phaser.Geom.Rectangle.Contains);
    c.on("pointerover", () => this.tweens.add({ targets: c, scale: 1.06, duration: 120 }));
    c.on("pointerout", () => this.tweens.add({ targets: c, scale: 1, duration: 120 }));
    c.on("pointerdown", onClick);
  }
}
