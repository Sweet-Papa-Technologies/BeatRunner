import { describe, it, expect } from "vitest";
import {
  BASE_POINTS,
  initialScore,
  basePoints,
  multiplier,
  applyHit,
  accuracy,
  gradeFor,
} from "../../src/core/scoring";
import type { Judgment } from "../../src/core/timing";

describe("scoring.ts", () => {
  // @req:REQ-SCORE-01
  describe("REQ-SCORE-01: base points", () => {
    it("REQ-SCORE-01: basePoints returns 100/50/0 for Perfect/Good/Miss", () => {
      expect(basePoints("Perfect")).toBe(100);
      expect(basePoints("Good")).toBe(50);
      expect(basePoints("Miss")).toBe(0);
    });

    it("REQ-SCORE-01: BASE_POINTS record matches the table exactly", () => {
      expect(BASE_POINTS.Perfect).toBe(100);
      expect(BASE_POINTS.Good).toBe(50);
      expect(BASE_POINTS.Miss).toBe(0);
    });
  });

  // @req:REQ-SCORE-02
  describe("REQ-SCORE-02: combo", () => {
    it("REQ-SCORE-02: sequence P,G,M,P yields combo 1,2,0,1", () => {
      let s = initialScore();
      s = applyHit(s, "Perfect");
      expect(s.combo).toBe(1);
      s = applyHit(s, "Good");
      expect(s.combo).toBe(2);
      s = applyHit(s, "Miss");
      expect(s.combo).toBe(0);
      s = applyHit(s, "Perfect");
      expect(s.combo).toBe(1);
    });

    it("REQ-SCORE-02: a Miss resets a large combo to 0", () => {
      let s = initialScore();
      for (let i = 0; i < 25; i++) s = applyHit(s, "Perfect");
      expect(s.combo).toBe(25);
      s = applyHit(s, "Miss");
      expect(s.combo).toBe(0);
    });

    it("REQ-SCORE-02: applyHit is pure and returns a new state object", () => {
      const s0 = initialScore();
      const s1 = applyHit(s0, "Perfect");
      expect(s1).not.toBe(s0);
      expect(s0.combo).toBe(0);
      expect(s0.score).toBe(0);
    });
  });

  // @req:REQ-SCORE-03
  describe("REQ-SCORE-03: multiplier tiers", () => {
    it("REQ-SCORE-03: multiplier tier boundaries are correct", () => {
      expect(multiplier(0)).toBe(1);
      expect(multiplier(9)).toBe(1);
      expect(multiplier(10)).toBe(2);
      expect(multiplier(19)).toBe(2);
      expect(multiplier(20)).toBe(3);
      expect(multiplier(29)).toBe(3);
      expect(multiplier(30)).toBe(4);
      expect(multiplier(100)).toBe(4);
    });

    it("REQ-SCORE-03: a Perfect while combo is 12 awards 100x2 = 200", () => {
      const s0 = { score: 0, combo: 12, perfects: 0, goods: 0, misses: 0 };
      const s1 = applyHit(s0, "Perfect");
      expect(s1.score - s0.score).toBe(200);
    });

    it("REQ-SCORE-03: a Good while combo is 20 awards 50x3 = 150", () => {
      const s0 = { score: 0, combo: 20, perfects: 0, goods: 0, misses: 0 };
      const s1 = applyHit(s0, "Good");
      expect(s1.score - s0.score).toBe(150);
    });
  });

  // @req:REQ-SCORE-04
  describe("REQ-SCORE-04: run total is non-decreasing", () => {
    it("REQ-SCORE-04: score never decreases across a deterministic event sequence", () => {
      // deterministic pseudo-random sequence (seeded LCG) of judgments
      const judgments: Judgment[] = ["Perfect", "Good", "Miss"];
      let seed = 1234567;
      const next = () => {
        seed = (seed * 1103515245 + 12345) & 0x7fffffff;
        return seed;
      };
      let s = initialScore();
      let prev = s.score;
      for (let i = 0; i < 500; i++) {
        const j = judgments[next() % 3];
        s = applyHit(s, j);
        expect(s.score).toBeGreaterThanOrEqual(prev);
        prev = s.score;
      }
      // Sanity: at least some points were awarded so the test is non-trivial.
      expect(s.score).toBeGreaterThan(0);
    });
  });

  // @req:REQ-SCORE-05
  describe("REQ-SCORE-05: grade and accuracy", () => {
    it("REQ-SCORE-05: gradeFor thresholds at 95/85/70/50", () => {
      expect(gradeFor(95)).toBe("S");
      expect(gradeFor(94.99)).toBe("A");
      expect(gradeFor(85)).toBe("A");
      expect(gradeFor(84.99)).toBe("B");
      expect(gradeFor(70)).toBe("B");
      expect(gradeFor(69.99)).toBe("C");
      expect(gradeFor(50)).toBe("C");
      expect(gradeFor(49.99)).toBe("D");
      expect(gradeFor(0)).toBe("D");
      expect(gradeFor(100)).toBe("S");
    });

    it("REQ-SCORE-05: accuracy is 0 when there are no events", () => {
      expect(accuracy(initialScore())).toBe(0);
    });

    it("REQ-SCORE-05: accuracy is (perfects+goods)/total*100", () => {
      const s = { score: 0, combo: 0, perfects: 8, goods: 1, misses: 1 };
      // (8+1)/10 * 100 = 90
      expect(accuracy(s)).toBeCloseTo(90, 9);
    });

    it("REQ-SCORE-05: applyHit tracks perfects/goods/misses counts used by accuracy", () => {
      let s = initialScore();
      s = applyHit(s, "Perfect");
      s = applyHit(s, "Perfect");
      s = applyHit(s, "Good");
      s = applyHit(s, "Miss");
      expect(s.perfects).toBe(2);
      expect(s.goods).toBe(1);
      expect(s.misses).toBe(1);
      // (2+1)/4 * 100 = 75
      expect(accuracy(s)).toBeCloseTo(75, 9);
      expect(gradeFor(accuracy(s))).toBe("B");
    });
  });
});
