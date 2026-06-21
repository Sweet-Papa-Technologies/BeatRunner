/** Track catalogue. Drop a new entry here (+ an .ogg and a .beatmap.json) to add a song. */

export interface TrackDef {
  id: string;
  title: string;
  artist: string;
  bpm: number;
  /** URL of the beat-map JSON (served from public/). */
  map: string;
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
    bpm: 120,
    map: "maps/overdrive_pulse.beatmap.json",
    audio: "assets/tracks/overdrive_pulse.ogg",
    color: 0xff2d95,
  },
  {
    id: "midnight",
    title: "Midnight Run",
    artist: "Sweet Papa & the Tones",
    bpm: 128,
    map: "maps/midnight_run.beatmap.json",
    audio: "assets/tracks/midnight_run.ogg",
    color: 0x2de2e6,
  },
  {
    id: "neon",
    title: "Neon Nights",
    artist: "Sweet Papa & the Tones",
    bpm: 92,
    map: "maps/neon_nights.beatmap.json",
    audio: "assets/tracks/neon_nights.ogg",
    color: 0xb14cff,
  },
  {
    id: "groove",
    title: "Sweet Papa Groove",
    artist: "Sweet Papa & the Tones",
    bpm: 88,
    map: "maps/sweetpapa_groove.beatmap.json",
    audio: "assets/tracks/sweetpapa_groove.ogg",
    color: 0xffd23c,
  },
];

export function trackById(id: string): TrackDef {
  return TRACKS.find((t) => t.id === id) ?? TRACKS[0];
}

/** Data handed from Play -> Results via the scene start payload. */
export interface RunResult {
  trackId: string;
  score: number;
  maxCombo: number;
  perfects: number;
  goods: number;
  misses: number;
  total: number;
  accuracy: number;
  grade: string;
}
