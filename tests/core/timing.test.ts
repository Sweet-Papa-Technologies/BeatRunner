import { describe, it, expect } from "vitest";
import {
  beatTime,
  judge,
  nearestBeat,
  createClock,
  DEFAULT_WINDOWS,
} from "../../src/core/timing";

describe("timing.ts", () => {
  // @req:REQ-TIME-01
  describe("REQ-TIME-01: beat time", () => {
    it("REQ-TIME-01: beatTime(0) at 120bpm offset 0 is 0", () => {
      expect(beatTime(0, 120, 0)).toBeCloseTo(0, 12);
    });

    it("REQ-TIME-01: beatTime(4) at 120bpm offset 0 is 2.0", () => {
      expect(beatTime(4, 120, 0)).toBeCloseTo(2.0, 12);
    });

    it("REQ-TIME-01: offset is added to the beat position", () => {
      expect(beatTime(0, 120, 0.3)).toBeCloseTo(0.3, 12);
      expect(beatTime(4, 120, 0.3)).toBeCloseTo(2.3, 12);
    });

    it("REQ-TIME-01: offset defaults to 0 when omitted", () => {
      expect(beatTime(4, 120)).toBeCloseTo(2.0, 12);
    });

    it("REQ-TIME-01: fractional bpm computes within float epsilon", () => {
      // beatTime(1, 93.5, 0) = (1/93.5)*60 = 0.6417112299...
      expect(beatTime(1, 93.5, 0)).toBeCloseTo((1 / 93.5) * 60, 12);
      expect(beatTime(8, 93.5, 0.25)).toBeCloseTo(0.25 + (8 / 93.5) * 60, 12);
    });
  });

  // @req:REQ-TIME-02
  describe("REQ-TIME-02: judgment windows", () => {
    it("REQ-TIME-02: exact hit (d=0) is Perfect", () => {
      expect(judge(2.0, 2.0)).toBe("Perfect");
    });

    it("REQ-TIME-02: d=0.050 is Perfect (inclusive boundary)", () => {
      expect(judge(2.05, 2.0)).toBe("Perfect");
    });

    it("REQ-TIME-02: d=0.051 is Good (just past Perfect)", () => {
      expect(judge(2.051, 2.0)).toBe("Good");
    });

    it("REQ-TIME-02: d=0.120 is Good (inclusive boundary)", () => {
      expect(judge(2.12, 2.0)).toBe("Good");
    });

    it("REQ-TIME-02: d=0.121 is Miss (just past Good)", () => {
      expect(judge(2.121, 2.0)).toBe("Miss");
    });

    it("REQ-TIME-02: windows are symmetric around the target (early == late)", () => {
      expect(judge(2.0 - 0.05, 2.0)).toBe("Perfect");
      expect(judge(2.0 - 0.051, 2.0)).toBe("Good");
      expect(judge(2.0 - 0.12, 2.0)).toBe("Good");
      expect(judge(2.0 - 0.121, 2.0)).toBe("Miss");
    });

    it("REQ-TIME-02: DEFAULT_WINDOWS constant matches the spec values", () => {
      expect(DEFAULT_WINDOWS.perfect).toBe(0.05);
      expect(DEFAULT_WINDOWS.good).toBe(0.12);
    });

    it("REQ-TIME-02: custom windows override the defaults", () => {
      const tight = { perfect: 0.01, good: 0.02 };
      // d=0.03 would be Perfect under defaults but Miss under the tight config
      expect(judge(2.03, 2.0, tight)).toBe("Miss");
      expect(judge(2.005, 2.0, tight)).toBe("Perfect");
      expect(judge(2.015, 2.0, tight)).toBe("Good");
    });
  });

  // @req:REQ-TIME-03
  describe("REQ-TIME-03: nearest-beat selection", () => {
    it("REQ-TIME-03: input 1.25 between 1.00 and 1.50 picks 1.00", () => {
      expect(nearestBeat(1.25, [1.0, 1.5])).toBeCloseTo(1.0, 12);
    });

    it("REQ-TIME-03: picks genuinely nearest, not merely the next beat", () => {
      expect(nearestBeat(1.4, [1.0, 1.5])).toBeCloseTo(1.5, 12);
    });

    it("REQ-TIME-03: exact equidistant tie resolves to the earlier (smaller) beat", () => {
      // input exactly midway between 2.0 and 3.0 -> earlier = 2.0
      expect(nearestBeat(2.5, [2.0, 3.0])).toBeCloseTo(2.0, 12);
    });

    it("REQ-TIME-03: tie resolves by VALUE not array position (larger beat listed first)", () => {
      // Larger candidate appears first; rule must still pick the earlier (smaller) beat.
      expect(nearestBeat(2.5, [3.0, 2.0])).toBeCloseTo(2.0, 12);
      expect(nearestBeat(1.25, [1.5, 1.0])).toBeCloseTo(1.0, 12);
    });

    it("REQ-TIME-03: unsorted candidate list still yields the nearest", () => {
      expect(nearestBeat(1.4, [3.0, 1.5, 0.2, 1.0])).toBeCloseTo(1.5, 12);
    });

    it("REQ-TIME-03: empty candidate array throws", () => {
      expect(() => nearestBeat(1.0, [])).toThrow();
    });
  });

  // @req:REQ-TIME-04
  describe("REQ-TIME-04: audio-clock source of truth (injectable)", () => {
    it("REQ-TIME-04: clock returns the value produced by injected now()", () => {
      const clock = createClock(() => 7.5);
      expect(clock()).toBeCloseTo(7.5, 12);
    });

    it("REQ-TIME-04: clock re-reads injected source, reflecting changes deterministically", () => {
      let now = 0;
      const clock = createClock(() => now);
      expect(clock()).toBeCloseTo(0, 12);
      now = 12.34;
      expect(clock()).toBeCloseTo(12.34, 12);
    });
  });
});
