/** Track catalogue. Drop a new entry here (+ an .ogg and a .beatmap.json) to add a song. */

/** The three beatforge difficulty charts for a track (Workstream E, REQ-INT-02). */
export interface DifficultyMaps {
  casual: string;
  standard: string;
  overdrive: string;
}

export type Difficulty = keyof DifficultyMaps;

export interface TrackDef {
  id: string;
  title: string;
  artist: string;
  /**
   * Measured float BPM from beatforge Workstream B (REQ-INT-01). TrackSelect may
   * round for display; the beat-maps carry the same precise value.
   */
  bpm: number;
  /**
   * URL of the default (standard) beat-map JSON. Kept for backward compatibility:
   * a track without `maps` loads exactly as before (REQ-INT-02).
   */
  map: string;
  /**
   * Optional per-difficulty beat-maps emitted by beatforge. When present the
   * difficulty picker selects which one Play loads; absent falls back to `map`.
   */
  maps?: DifficultyMaps;
  /** URL of the audio file (served from public/). */
  audio: string;
  /** Accent color for the select card. */
  color: number;
}

export const TRACKS: TrackDef[] = [
  {
    id: "overdrive",
    title: "Overdrive Pulse",
    artist: "Sweet Papa & the Tones",
    bpm: 119.945,
    map: "maps/overdrive_pulse.standard.beatmap.json",
    maps: {
      casual: "maps/overdrive_pulse.casual.beatmap.json",
      standard: "maps/overdrive_pulse.standard.beatmap.json",
      overdrive: "maps/overdrive_pulse.overdrive.beatmap.json",
    },
    audio: "assets/tracks/overdrive_pulse.ogg",
    color: 0xff2d95,
  },
  {
    id: "midnight",
    title: "Midnight Run",
    artist: "Sweet Papa & the Tones",
    bpm: 129.07,
    map: "maps/midnight_run.standard.beatmap.json",
    maps: {
      casual: "maps/midnight_run.casual.beatmap.json",
      standard: "maps/midnight_run.standard.beatmap.json",
      overdrive: "maps/midnight_run.overdrive.beatmap.json",
    },
    audio: "assets/tracks/midnight_run.ogg",
    color: 0x2de2e6,
  },
  {
    id: "neon",
    title: "Neon Nights",
    artist: "Sweet Papa & the Tones",
    bpm: 137.95,
    map: "maps/neon_nights.standard.beatmap.json",
    maps: {
      casual: "maps/neon_nights.casual.beatmap.json",
      standard: "maps/neon_nights.standard.beatmap.json",
      overdrive: "maps/neon_nights.overdrive.beatmap.json",
    },
    audio: "assets/tracks/neon_nights.ogg",
    color: 0xb14cff,
  },
  {
    id: "groove",
    title: "Sweet Papa Groove",
    artist: "Sweet Papa & the Tones",
    bpm: 88.002,
    map: "maps/sweetpapa_groove.standard.beatmap.json",
    maps: {
      casual: "maps/sweetpapa_groove.casual.beatmap.json",
      standard: "maps/sweetpapa_groove.standard.beatmap.json",
      overdrive: "maps/sweetpapa_groove.overdrive.beatmap.json",
    },
    audio: "assets/tracks/sweetpapa_groove.ogg",
    color: 0xffd23c,
  },
];

/** Resolve the map URL for a track at a difficulty, falling back to `map`. */
export function mapForDifficulty(track: TrackDef, difficulty: Difficulty): string {
  return track.maps ? track.maps[difficulty] : track.map;
}

export function trackById(id: string): TrackDef {
  return TRACKS.find((t) => t.id === id) ?? TRACKS[0];
}

/** Data handed from Play -> Results via the scene start payload. */
export interface RunResult {
  trackId: string;
  /** Difficulty that was played, so Results' RETRY can replay the same chart. */
  difficulty: Difficulty;
  score: number;
  maxCombo: number;
  perfects: number;
  goods: number;
  misses: number;
  total: number;
  accuracy: number;
  grade: string;
}
