import Phaser from "phaser";
import { AudioEngine } from "../audio/AudioEngine";
import { TRACKS } from "../game/tracks";
import { VIEW } from "../game/config";
import { starfield, ambientSparkles, spawnStreak, shockwave, sparkleBurst } from "../game/fx";

/** Title + track picker. Selecting a card is the user gesture that unlocks audio. */
export class TrackSelectScene extends Phaser.Scene {
  private selected = 0;
  private cards: Phaser.GameObjects.Container[] = [];
  private choosing = false;

  constructor() {
    super("TrackSelect");
  }

  create(): void {
    this.cameras.main.fadeIn(300, 0, 0, 0);
    this.add.image(VIEW.width / 2, VIEW.height / 2, "bg_sky").setDisplaySize(VIEW.width, VIEW.height);
    this.add.image(VIEW.width / 2, VIEW.height / 2, "bg_city").setDisplaySize(VIEW.width, VIEW.height).setAlpha(0.6);
    starfield(this, VIEW.width, VIEW.height, 110);
    ambientSparkles(this, VIEW.width, VIEW.height);
    this.time.addEvent({
      delay: 520, loop: true,
      callback: () => spawnStreak(this, VIEW.width, VIEW.height, Phaser.Utils.Array.GetRandom([0xff5dcb, 0x4cc9ff, 0x7af2c4])),
    });

    const title = this.add.text(VIEW.width / 2, 120, "IN THE POCKET", {
      fontFamily: "system-ui, sans-serif",
      fontSize: "72px",
      color: "#ffffff",
      fontStyle: "bold",
    }).setOrigin(0.5);
    title.setShadow(0, 0, "#ff5dcb", 24, true, true);
    this.add.text(VIEW.width / 2, 184, "a rhythm auto-runner — tap on the beat", {
      fontFamily: "system-ui, sans-serif",
      fontSize: "24px",
      color: "#7af2c4",
    }).setOrigin(0.5);

    // pulsing title
    this.tweens.add({ targets: title, scale: 1.04, duration: 700, yoyo: true, repeat: -1, ease: "Sine.inOut" });

    const startX = VIEW.width / 2 - ((TRACKS.length - 1) * 360) / 2;
    TRACKS.forEach((t, i) => {
      const x = startX + i * 360;
      const card = this.makeCard(x, 420, t.title, t.artist, `${t.bpm} BPM`, t.color, i);
      this.cards.push(card);
    });

    this.add.text(VIEW.width / 2, 640, "◀ ▶ to choose   •   ENTER / tap to play", {
      fontFamily: "system-ui, sans-serif",
      fontSize: "20px",
      color: "#ffffff",
    }).setOrigin(0.5).setAlpha(0.7);

    this.highlight();

    this.input.keyboard?.on("keydown-LEFT", () => this.move(-1));
    this.input.keyboard?.on("keydown-RIGHT", () => this.move(1));
    this.input.keyboard?.on("keydown-ENTER", () => this.choose(this.selected));
    this.input.keyboard?.on("keydown-SPACE", () => this.choose(this.selected));
  }

  private makeCard(
    x: number, y: number, title: string, artist: string, bpm: string, color: number, index: number,
  ): Phaser.GameObjects.Container {
    const w = 320, h = 240;
    const bg = this.add.graphics();
    bg.fillStyle(0x0c0820, 0.92);
    bg.fillRoundedRect(-w / 2, -h / 2, w, h, 18);
    bg.lineStyle(3, color, 1);
    bg.strokeRoundedRect(-w / 2, -h / 2, w, h, 18);

    const tt = this.add.text(0, -60, title, {
      fontFamily: "system-ui, sans-serif", fontSize: "30px", color: "#ffffff", fontStyle: "bold",
      align: "center", wordWrap: { width: w - 40 },
    }).setOrigin(0.5);
    const at = this.add.text(0, 6, artist, {
      fontFamily: "system-ui, sans-serif", fontSize: "18px", color: "#b9a9ff", align: "center",
    }).setOrigin(0.5);
    const bt = this.add.text(0, 70, bpm, {
      fontFamily: "system-ui, sans-serif", fontSize: "22px", color: Phaser.Display.Color.IntegerToColor(color).rgba,
    }).setOrigin(0.5);

    const c = this.add.container(x, y, [bg, tt, at, bt]);
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
      this.tweens.add({ targets: c, scale: i === this.selected ? 1.08 : 0.94, duration: 160, ease: "Back.out" });
      c.setAlpha(i === this.selected ? 1 : 0.7);
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
      this.scene.start("Play", { trackId: track.id });
    });
  }
}
