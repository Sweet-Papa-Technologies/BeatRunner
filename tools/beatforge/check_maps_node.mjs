// REQ-VAL-01 cross-language contract: import the REAL src/core/beatmap.ts
// parseBeatmap and parse every emitted map. The TS core is the final referee of
// its own schema. Run: npx tsx tools/beatforge/check_maps_node.mjs
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const { parseBeatmap } = await import(join(root, "src", "core", "beatmap.ts"));

const mapsDir = join(root, "public", "maps");
const maps = readdirSync(mapsDir).filter((f) => f.endsWith(".beatmap.json"));
let fail = 0;
for (const m of maps) {
  try {
    const raw = JSON.parse(readFileSync(join(mapsDir, m), "utf8"));
    const bm = parseBeatmap(raw);
    console.log(`OK   ${m}  (${bm.events.length} events, bpm=${bm.bpm})`);
  } catch (e) {
    fail++;
    console.error(`FAIL ${m}: ${e.message}`);
  }
}
if (fail) { console.error(`${fail} map(s) failed the TS parser`); process.exit(1); }
console.log(`all ${maps.length} maps parse clean through src/core/beatmap.ts`);
