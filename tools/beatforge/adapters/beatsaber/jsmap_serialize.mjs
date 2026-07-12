// jsmap_serialize.mjs — SABERFORGE serializer (REQ-BS-06). Builds Info.dat (v2,
// broadest CustomLevels/ChroMapper support) + one v3 beatmap .dat per difficulty
// via KivalEvan's BeatSaber-JSMap (`bsmap`). We NEVER hand-format the JSON — this
// helper owns the grammar; Python owns the note objects + metadata. Invoked as a
// subprocess (mirrors tools/beatforge/check_maps_node.mjs):
//     node jsmap_serialize.mjs <payload.json>
// The payload declares the song folder, per-difficulty objects and lighting; the
// helper writes the files, runs a JSMap round-trip byte-stability check, and
// prints a JSON result to stdout.
import { writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { readFileSync } from "node:fs";
import * as bsmap from "bsmap";

const {
  createBeatmap, createInfo, createInfoBeatmap, createColorNote, createBombNote,
  createObstacle, createArc, createChain, createBasicEvent, saveDifficulty,
  saveInfo, loadDifficulty,
} = bsmap;

const SAVE_OPTS = { validate: { enabled: false }, sort: true };

function buildDifficulty(d) {
  const bm = createBeatmap({ version: 3 });
  const df = bm.difficulty;
  for (const n of d.colorNotes ?? [])
    df.colorNotes.push(createColorNote({ time: n.b, posX: n.x, posY: n.y, color: n.c, direction: n.d, angleOffset: n.a ?? 0 }));
  for (const n of d.bombNotes ?? [])
    df.bombNotes.push(createBombNote({ time: n.b, posX: n.x, posY: n.y }));
  for (const o of d.obstacles ?? [])
    df.obstacles.push(createObstacle({ time: o.b, posX: o.x, posY: o.y, width: o.w, height: o.h, duration: o.d }));
  for (const a of d.arcs ?? [])
    df.arcs.push(createArc({ time: a.b, posX: a.x, posY: a.y, color: a.c, direction: a.d,
      tailTime: a.tb, tailPosX: a.tx, tailPosY: a.ty, tailDirection: a.td,
      lengthMultiplier: a.mu ?? 1, tailLengthMultiplier: a.tmu ?? 1, midAnchor: a.m ?? 0 }));
  for (const c of d.chains ?? [])
    df.chains.push(createChain({ time: c.b, posX: c.x, posY: c.y, color: c.c, direction: c.d,
      tailTime: c.tb, tailPosX: c.tx, tailPosY: c.ty, sliceCount: c.sc, squish: c.s ?? 1 }));
  for (const e of d.basicEvents ?? [])
    bm.lightshow.basicEvents.push(createBasicEvent({ time: e.b, type: e.et, value: e.i, floatValue: e.f ?? 1 }));
  return bm;
}

function main() {
  const payload = JSON.parse(readFileSync(process.argv[2], "utf8"));
  mkdirSync(payload.outDir, { recursive: true });

  const info = createInfo({ version: 4 });
  info.song.title = payload.info.title ?? "Untitled";
  info.song.author = payload.info.artist ?? "unknown";
  info.audio.filename = payload.info.songFilename ?? "song.ogg";
  info.audio.bpm = payload.info.bpm ?? 120;
  info.coverImageFilename = payload.info.coverImageFilename ?? "cover.jpg";
  info.songPreviewFilename = payload.info.songFilename ?? "song.ogg";
  info.audio.previewStartTime = payload.info.previewStart ?? 0;
  info.audio.previewDuration = payload.info.previewDuration ?? 10;
  // REQ-POS-01: AI-assisted marker + credit lives in Info customData.
  info.customData = { ...(info.customData ?? {}), _contributors: [],
    _saberforge: payload.info.marker ?? "SABERFORGE (AI-assisted draft)" };

  const files = {};
  const roundtrip = {};
  for (const d of payload.difficulties) {
    const bm = buildDifficulty(d);
    const json = saveDifficulty(bm, 3, SAVE_OPTS);
    const text = JSON.stringify(json);
    const path = join(payload.outDir, d.filename);
    writeFileSync(path, text);
    files[d.key] = path;
    // REQ-BS-06 round-trip byte-stability: reload through JSMap, re-save, compare.
    const reloaded = loadDifficulty(JSON.parse(text), 3, { validate: { enabled: false } });
    const text2 = JSON.stringify(saveDifficulty(reloaded, 3, SAVE_OPTS));
    roundtrip[d.key] = text2 === text;

    info.difficulties.push(createInfoBeatmap({
      characteristic: "Standard", difficulty: d.difficulty, filename: d.filename,
      njs: d.njs, njsOffset: d.offset ?? 0,
      customData: { _difficultyLabel: d.label ?? d.difficulty,
        _information: [payload.info.marker ?? "SABERFORGE (AI-assisted draft)"] },
    }));
  }

  // Info.dat as v2 (classic _difficultyBeatmapSets — broadest support).
  const infoJson = saveInfo(info, 2, { validate: { enabled: false } });
  const infoPath = join(payload.outDir, "Info.dat");
  writeFileSync(infoPath, JSON.stringify(infoJson));
  files.info = infoPath;

  process.stdout.write(JSON.stringify({
    ok: true, files, roundtrip,
    roundtrip_ok: Object.values(roundtrip).every(Boolean),
  }));
}

try {
  main();
} catch (e) {
  process.stdout.write(JSON.stringify({ ok: false, error: String(e && e.stack || e) }));
  process.exit(1);
}
