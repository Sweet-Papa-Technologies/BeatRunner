/// <reference types="vite/client" />
import Phaser from "phaser";
import { VIEW, COLORS } from "./game/config";
import { BootScene } from "./scenes/BootScene";
import { TrackSelectScene } from "./scenes/TrackSelectScene";
import { PlayScene } from "./scenes/PlayScene";
import { ResultsScene } from "./scenes/ResultsScene";

const game = new Phaser.Game({
  type: Phaser.AUTO,
  parent: "game",
  width: VIEW.width,
  height: VIEW.height,
  backgroundColor: COLORS.bg0,
  scale: {
    mode: Phaser.Scale.FIT,
    autoCenter: Phaser.Scale.CENTER_BOTH,
  },
  render: { antialias: true, roundPixels: false },
  scene: [BootScene, TrackSelectScene, PlayScene, ResultsScene],
});

// Exposed for debugging / automated verification only.
(window as unknown as { __game: Phaser.Game }).__game = game;

// Dev only: tear down the running game before an HMR update re-runs this module,
// so we never end up with two Phaser.Game instances (duplicate scenes/listeners).
if (import.meta.hot) {
  import.meta.hot.accept();
  import.meta.hot.dispose(() => game.destroy(true));
}
