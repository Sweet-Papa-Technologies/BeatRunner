/** Reusable neon juice effects. Kept framework-thin so scenes stay readable. */
import Phaser from "phaser";

/** Expanding neon shockwave ring. */
export function shockwave(
  scene: Phaser.Scene, x: number, y: number, color: number,
  opts: { scale?: number; duration?: number; thickness?: number } = {},
): void {
  const ring = scene.add.image(x, y, "ring").setBlendMode(Phaser.BlendModes.ADD)
    .setTint(color).setDepth(9).setScale(0.15).setAlpha(0.95);
  scene.tweens.add({
    targets: ring,
    scale: opts.scale ?? 2.6,
    alpha: 0,
    duration: opts.duration ?? 420,
    ease: "Cubic.out",
    onComplete: () => ring.destroy(),
  });
}

/** One-shot sparkle explosion at a point. */
export function sparkleBurst(
  scene: Phaser.Scene, x: number, y: number, color: number, count = 16,
): void {
  const e = scene.add.particles(x, y, "spark", {
    lifespan: { min: 280, max: 720 },
    speed: { min: 120, max: 460 },
    angle: { min: 0, max: 360 },
    scale: { start: 0.95, end: 0 },
    rotate: { start: 0, end: 360 },
    gravityY: 420,
    blendMode: Phaser.BlendModes.ADD,
    tint: color,
    emitting: false,
  }).setDepth(10);
  e.explode(count);
  scene.time.delayedCall(900, () => e.destroy());
}

/** Twinkling starfield drifting slowly; returns the container for parallax control. */
export function starfield(scene: Phaser.Scene, w: number, h: number, count = 90): Phaser.GameObjects.Container {
  const c = scene.add.container(0, 0).setDepth(0);
  for (let i = 0; i < count; i++) {
    const x = Phaser.Math.Between(0, w);
    const y = Phaser.Math.Between(0, h * 0.7);
    const s = Phaser.Math.FloatBetween(0.1, 0.4);
    const star = scene.add.image(x, y, "spark").setBlendMode(Phaser.BlendModes.ADD).setScale(s)
      .setTint(Phaser.Utils.Array.GetRandom([0xffffff, 0x9bd0ff, 0xffb6f0]));
    scene.tweens.add({
      targets: star, alpha: { from: 0.2, to: 1 }, duration: Phaser.Math.Between(700, 2200),
      yoyo: true, repeat: -1, delay: Phaser.Math.Between(0, 1500),
    });
    c.add(star);
  }
  return c;
}

/** Periodically-spawned diagonal light streaks for motion energy. */
export function spawnStreak(scene: Phaser.Scene, w: number, h: number, color: number): void {
  const y = Phaser.Math.Between(60, h - 200);
  const streak = scene.add.image(w + 80, y, "streak").setBlendMode(Phaser.BlendModes.ADD)
    .setTint(color).setAlpha(0).setScale(Phaser.Math.FloatBetween(0.6, 1.4), 0.5).setDepth(1);
  scene.tweens.add({ targets: streak, alpha: 0.5, duration: 120, yoyo: true, hold: 60 });
  scene.tweens.add({
    targets: streak, x: -200, duration: Phaser.Math.Between(500, 900),
    ease: "Sine.in", onComplete: () => streak.destroy(),
  });
}

/** Floating drifting embers/sparkles for ambient life. */
export function ambientSparkles(scene: Phaser.Scene, w: number, h: number): Phaser.GameObjects.Particles.ParticleEmitter {
  return scene.add.particles(0, 0, "spark", {
    x: { min: 0, max: w },
    y: h + 10,
    lifespan: { min: 3000, max: 6000 },
    speedY: { min: -50, max: -16 },
    speedX: { min: -14, max: 14 },
    scale: { start: 0.3, end: 0 },
    alpha: { start: 0.7, end: 0 },
    blendMode: Phaser.BlendModes.ADD,
    tint: [0xff5dcb, 0x4cc9ff, 0x7af2c4, 0xfff27a],
    frequency: 160,
    emitting: true,
  }).setDepth(3);
}
