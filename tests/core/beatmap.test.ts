import { describe, it, expect } from "vitest";
import {
  parseBeatmap,
  spawnTime,
  BeatmapError,
} from "../../src/core/beatmap";

const validRaw = () => ({
  track: "sweetpapa_groove_01.mp3",
  bpm: 92,
  offset: 0.3,
  events: [
    { beat: 4, type: "GAP" },
    { beat: 6, type: "NOTE" },
    { beat: 8, type: "BAR" },
  ],
});

describe("beatmap.ts", () => {
  // @req:REQ-MAP-01
  describe("REQ-MAP-01: schema validation", () => {
    it("REQ-MAP-01: a valid map parses to a Beatmap", () => {
      const map = parseBeatmap(validRaw());
      expect(map.track).toBe("sweetpapa_groove_01.mp3");
      expect(map.bpm).toBe(92);
      expect(map.offset).toBe(0.3);
      expect(map.events).toHaveLength(3);
    });

    it("REQ-MAP-01: bpm<=0 is rejected with BeatmapError", () => {
      expect(() => parseBeatmap({ ...validRaw(), bpm: 0 })).toThrow(BeatmapError);
      expect(() => parseBeatmap({ ...validRaw(), bpm: -120 })).toThrow(BeatmapError);
    });

    it("REQ-MAP-01: offset<0 is rejected with BeatmapError", () => {
      expect(() => parseBeatmap({ ...validRaw(), offset: -0.1 })).toThrow(BeatmapError);
    });

    it("REQ-MAP-01: a negative beat is rejected with BeatmapError", () => {
      expect(() =>
        parseBeatmap({ ...validRaw(), events: [{ beat: -1, type: "GAP" }] })
      ).toThrow(BeatmapError);
    });

    it("REQ-MAP-01: an unknown event type is rejected with BeatmapError", () => {
      expect(() =>
        parseBeatmap({ ...validRaw(), events: [{ beat: 1, type: "WIGGLE" }] })
      ).toThrow(BeatmapError);
    });

    it("REQ-MAP-01: missing required fields are rejected with BeatmapError", () => {
      const { track, ...noTrack } = validRaw();
      expect(() => parseBeatmap(noTrack)).toThrow(BeatmapError);

      const { bpm, ...noBpm } = validRaw();
      expect(() => parseBeatmap(noBpm)).toThrow(BeatmapError);

      const { events, ...noEvents } = validRaw();
      expect(() => parseBeatmap(noEvents)).toThrow(BeatmapError);

      expect(() =>
        parseBeatmap({ ...validRaw(), events: [{ beat: 1 }] })
      ).toThrow(BeatmapError);
      expect(() =>
        parseBeatmap({ ...validRaw(), events: [{ type: "GAP" }] })
      ).toThrow(BeatmapError);
    });

    it("REQ-MAP-01: non-object input is rejected with BeatmapError", () => {
      expect(() => parseBeatmap(null)).toThrow(BeatmapError);
      expect(() => parseBeatmap("nope")).toThrow(BeatmapError);
      expect(() => parseBeatmap(42)).toThrow(BeatmapError);
    });

    it("REQ-MAP-01: non-finite numeric fields are rejected with BeatmapError", () => {
      // NaN/Infinity are classic bad-JSON / coercion artifacts the schema must reject.
      expect(() => parseBeatmap({ ...validRaw(), bpm: NaN })).toThrow(BeatmapError);
      expect(() => parseBeatmap({ ...validRaw(), bpm: Infinity })).toThrow(BeatmapError);
      expect(() => parseBeatmap({ ...validRaw(), offset: NaN })).toThrow(BeatmapError);
      expect(() =>
        parseBeatmap({ ...validRaw(), events: [{ beat: Infinity, type: "GAP" }] })
      ).toThrow(BeatmapError);
    });
  });

  // @req:REQ-MAP-02
  describe("REQ-MAP-02: ordering and de-duplication", () => {
    it("REQ-MAP-02: unsorted events come back sorted ascending by beat", () => {
      const map = parseBeatmap({
        ...validRaw(),
        events: [
          { beat: 12, type: "GAP" },
          { beat: 4, type: "GAP" },
          { beat: 8, type: "BAR" },
        ],
      });
      expect(map.events.map((e) => e.beat)).toEqual([4, 8, 12]);
    });

    it("REQ-MAP-02: duplicate same (beat,type) collapses to a single event", () => {
      const map = parseBeatmap({
        ...validRaw(),
        events: [
          { beat: 4, type: "GAP" },
          { beat: 4, type: "GAP" },
        ],
      });
      expect(map.events).toHaveLength(1);
      expect(map.events[0]).toMatchObject({ beat: 4, type: "GAP" });
    });

    it("REQ-MAP-02: different types at the same beat are both kept", () => {
      const map = parseBeatmap({
        ...validRaw(),
        events: [
          { beat: 4, type: "GAP" },
          { beat: 4, type: "NOTE" },
        ],
      });
      expect(map.events).toHaveLength(2);
      const types = map.events.map((e) => e.type).sort();
      expect(types).toEqual(["GAP", "NOTE"]);
      expect(map.events.every((e) => e.beat === 4)).toBe(true);
    });
  });

  // @req:REQ-MAP-03
  describe("REQ-MAP-03: spawn lead", () => {
    it("REQ-MAP-03: leadTime=2.0, bpm=120, offset=0, beat=8 -> spawnTime 2.0", () => {
      // beatTime(8,120,0) = 4.0; 4.0 - 2.0 = 2.0
      expect(spawnTime(8, 120, 0, 2.0)).toBeCloseTo(2.0, 12);
    });

    it("REQ-MAP-03: a negative computed spawn time clamps to 0 (pre-spawn)", () => {
      // beatTime(1,120,0)=0.5; 0.5 - 2.0 = -1.5 -> clamp to 0
      expect(spawnTime(1, 120, 0, 2.0)).toBe(0);
    });

    it("REQ-MAP-03: offset is included via beatTime", () => {
      // beatTime(8,120,0.3)=4.3; 4.3 - 2.0 = 2.3
      expect(spawnTime(8, 120, 0.3, 2.0)).toBeCloseTo(2.3, 12);
    });
  });
});
