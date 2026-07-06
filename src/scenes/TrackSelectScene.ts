import Phaser from "phaser";
import { AudioEngine } from "../audio/AudioEngine";
import { TRACKS } from "../game/tracks";
import type { Difficulty } from "../game/tracks";
import { VIEW } from "../game/config";
import { ambientSparkles, spawnStreak, shockwave, sparkleBurst } from "../game/fx";

const DIFFICULTIES: { key: Difficulty; label: string; color: number }[] = [
  { key: "casual", label: "CASUAL", color: 0x2de2e6 },
  { key: "standard", label: "STANDARD", color: 0xffd23c },
  { key: "overdrive", label: "OVERDRIVE", color: 0xff2d95 },
];

/** Title + track picker. Selecting a card is the user gesture that unlocks audio. */
export class TrackSelectScene extends Phaser.Scene {
  private selected = 0;
  private cards: Phaser.GameObjects.Container[] = [];
  private choosing = false;
  private difficulty = 1; // index into DIFFICULTIES; default Standard
  private diffChips: Phaser.GameObjects.Container[] = [];

  constructor() {
    super("TrackSelect");
  }

  create(): void {
    // Phaser reuses the scene instance across scene.start(), so instance fields
    // keep their previous values. Returning from Results left `choosing===true`
    // (all input dead — "menu gets stuck / buttons don't work") and grew the
    // cards/chips arrays with destroyed objects. Reset everything on entry, and
    // clear any keyboard handlers from a prior visit so keys don't double-fire.
    this.cards = [];
    this.diffChips = [];
    this.choosing = false;
    this.selected = Phaser.Math.Clamp(this.selected, 0, TRACKS.length - 1);
    this.input.keyboard?.removeAllListeners();

    this.cameras.main.fadeIn(300, 0, 0, 0);
    this.add.image(VIEW.width / 2, VIEW.height / 2, "od_sky").setDisplaySize(VIEW.width, VIEW.height);
    this.add.image(VIEW.width / 2, VIEW.height - 150, "od_ridge").setDisplaySize(VIEW.width, 320).setAlpha(0.8);
    this.add.image(VIEW.width / 2, VIEW.height - 120, "od_city").setDisplaySize(VIEW.width, 280).setAlpha(0.4);
    ambientSparkles(this, VIEW.width, VIEW.height);
    this.time.addEvent({
      delay: 480, loop: true,
      callback: () => spawnStreak(this, VIEW.width, VIEW.height, Phaser.Utils.Array.GetRandom([0xff2d95, 0x2de2e6, 0xffd23c])),
    });

    const title = this.add.text(VIEW.width / 2, 96, "OVERDRIVE", {
      fontFamily: "system-ui, sans-serif", fontSize: "84px", color: "#ffffff", fontStyle: "bold",
    }).setOrigin(0.5);
    title.setShadow(0, 0, "#ff2d95", 28, true, true);
    this.add.text(VIEW.width / 2, 158, "a synthwave rhythm highway  —  hit the lanes on the beat", {
      fontFamily: "system-ui, sans-serif", fontSize: "22px", color: "#2de2e6",
    }).setOrigin(0.5);
    this.tweens.add({ targets: title, scale: 1.035, duration: 720, yoyo: true, repeat: -1, ease: "Sine.inOut" });

    const gap = 296;
    const startX = VIEW.width / 2 - ((TRACKS.length - 1) * gap) / 2;
    TRACKS.forEach((t, i) => {
      const card = this.makeCard(startX + i * gap, 408, t.title, t.artist, `${t.bpm} BPM`, t.color, i);
      this.cards.push(card);
    });

    this.buildDifficultyPicker(596);

    this.add.text(VIEW.width / 2, 664, "◀ ▶ choose track   •   1 / 2 / 3 or ▲ ▼ difficulty   •   ENTER / tap to play", {
      fontFamily: "system-ui, sans-serif", fontSize: "20px", color: "#ffffff",
    }).setOrigin(0.5).setAlpha(0.7);

    this.highlight();

    this.input.keyboard?.on("keydown-LEFT", () => this.move(-1));
    this.input.keyboard?.on("keydown-RIGHT", () => this.move(1));
    this.input.keyboard?.on("keydown-UP", () => this.setDifficulty(this.difficulty - 1));
    this.input.keyboard?.on("keydown-DOWN", () => this.setDifficulty(this.difficulty + 1));
    this.input.keyboard?.on("keydown-ONE", () => this.setDifficulty(0));
    this.input.keyboard?.on("keydown-TWO", () => this.setDifficulty(1));
    this.input.keyboard?.on("keydown-THREE", () => this.setDifficulty(2));
    this.input.keyboard?.on("keydown-ENTER", () => this.choose(this.selected));
    this.input.keyboard?.on("keydown-SPACE", () => this.choose(this.selected));
  }

  private buildDifficultyPicker(y: number): void {
    const chipW = 190, gap = 210;
    const startX = VIEW.width / 2 - gap;
    DIFFICULTIES.forEach((d, i) => {
      const bg = this.add.graphics();
      const draw = (active: boolean) => {
        bg.clear();
        bg.fillStyle(active ? d.color : 0x0c0824, active ? 0.28 : 0.85);
        bg.fillRoundedRect(-chipW / 2, -20, chipW, 40, 12);
        bg.lineStyle(active ? 3 : 2, d.color, active ? 1 : 0.55);
        bg.strokeRoundedRect(-chipW / 2, -20, chipW, 40, 12);
      };
      draw(i === this.difficulty);
      const label = this.add.text(0, 0, d.label, {
        fontFamily: "system-ui, sans-serif", fontSize: "18px",
        color: i === this.difficulty ? "#ffffff" : "#b9a9ff", fontStyle: "bold",
      }).setOrigin(0.5);
      const chip = this.add.container(startX + i * gap, y, [bg, label]);
      chip.setSize(chipW, 40);
      chip.setInteractive(new Phaser.Geom.Rectangle(-chipW / 2, -20, chipW, 40), Phaser.Geom.Rectangle.Contains);
      chip.on("pointerdown", () => this.setDifficulty(i));
      chip.setData("draw", draw);
      chip.setData("label", label);
      this.diffChips.push(chip);
    });
  }

  private setDifficulty(idx: number): void {
    this.difficulty = Phaser.Math.Wrap(idx, 0, DIFFICULTIES.length);
    this.diffChips.forEach((chip, i) => {
      const active = i === this.difficulty;
      (chip.getData("draw") as (a: boolean) => void)(active);
      (chip.getData("label") as Phaser.GameObjects.Text)
        .setColor(active ? "#ffffff" : "#b9a9ff");
      this.tweens.add({ targets: chip, scale: active ? 1.08 : 1, duration: 140, ease: "Back.out" });
    });
  }

  private makeCard(
    x: number, y: number, title: string, artist: string, bpm: string, color: number, index: number,
  ): Phaser.GameObjects.Container {
    const w = 268, h = 268;
    const bg = this.add.graphics();
    bg.fillStyle(0x0c0824, 0.92);
    bg.fillRoundedRect(-w / 2, -h / 2, w, h, 18);
    bg.lineStyle(3, color, 1);
    bg.strokeRoundedRect(-w / 2, -h / 2, w, h, 18);

    const best = Number(localStorage.getItem(`od_best_${TRACKS[index].id}`) ?? 0);

    const disc = this.add.image(0, -64, "pad").setTint(color).setScale(0.66).setAlpha(0.9);
    this.tweens.add({ targets: disc, angle: 360, duration: 8000, repeat: -1 });
    const tt = this.add.text(0, 12, title, {
      fontFamily: "system-ui, sans-serif", fontSize: "26px", color: "#ffffff", fontStyle: "bold",
      align: "center", wordWrap: { width: w - 40 },
    }).setOrigin(0.5);
    const at = this.add.text(0, 58, artist, {
      fontFamily: "system-ui, sans-serif", fontSize: "15px", color: "#b9a9ff", align: "center",
    }).setOrigin(0.5);
    const bt = this.add.text(0, 90, bpm, {
      fontFamily: "system-ui, sans-serif", fontSize: "20px", color: Phaser.Display.Color.IntegerToColor(color).rgba, fontStyle: "bold",
    }).setOrigin(0.5);
    const children: Phaser.GameObjects.GameObject[] = [bg, disc, tt, at, bt];
    if (best > 0) {
      children.push(this.add.text(0, 116, `best ${best}`, {
        fontFamily: "system-ui, sans-serif", fontSize: "14px", color: "#fff27a",
      }).setOrigin(0.5));
    }

    const c = this.add.container(x, y, children);
    c.setSize(w, h);
    c.setInteractive(new Phaser.Geom.Rectangle(-w / 2, -h / 2, w, h), Phaser.Geom.Rectangle.Contains);
    c.on("pointerover", () => { this.selected = index; this.highlight(); });
    c.on("pointerdown", () => this.choose(index));
    return c;
  }

  private move(dir: number): void {
    this.selected = Phaser.Math.Wrap(this.selected + dir, 0, this.cards.length);
    this.highlight();
  }

  private highlight(): void {
    this.cards.forEach((c, i) => {
      this.tweens.add({ targets: c, scale: i === this.selected ? 1.07 : 0.9, duration: 160, ease: "Back.out" });
      c.setAlpha(i === this.selected ? 1 : 0.66);
    });
  }

  private async choose(index: number): Promise<void> {
    const track = TRACKS[index];
    const card = this.cards[index];
    if (this.choosing || !track || !card) return;
    this.choosing = true;
    const audio = this.registry.get("audio") as AudioEngine;
    await audio.unlock();
    shockwave(this, card.x, card.y, track.color, { scale: 5, duration: 500 });
    sparkleBurst(this, card.x, card.y, track.color, 28);
    this.cameras.main.flash(160, 40, 20, 60);
    this.cameras.main.fadeOut(260, 0, 0, 0);
    this.cameras.main.once("camerafadeoutcomplete", () => {
      this.scene.start("Play", { trackId: track.id, difficulty: DIFFICULTIES[this.difficulty].key });
    });
  }
}
