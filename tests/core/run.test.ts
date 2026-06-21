import { describe, it, expect } from "vitest";
import { nextState, RunController, RunError } from "../../src/core/run";

describe("run.ts", () => {
  // @req:REQ-RUN-01
  describe("REQ-RUN-01: state machine", () => {
    it("REQ-RUN-01: legal forward transitions return the target phase", () => {
      expect(nextState("Loading", "Countdown")).toBe("Countdown");
      expect(nextState("Countdown", "Playing")).toBe("Playing");
      expect(nextState("Playing", "Results")).toBe("Results");
    });

    it("REQ-RUN-01: Results->Loading (retry) is legal", () => {
      expect(nextState("Results", "Loading")).toBe("Loading");
    });

    it("REQ-RUN-01: skipping states is illegal and throws RunError", () => {
      expect(() => nextState("Loading", "Playing")).toThrow(RunError);
      expect(() => nextState("Loading", "Results")).toThrow(RunError);
      expect(() => nextState("Countdown", "Results")).toThrow(RunError);
    });

    it("REQ-RUN-01: backward transitions are illegal and throw RunError", () => {
      expect(() => nextState("Playing", "Loading")).toThrow(RunError);
      expect(() => nextState("Playing", "Countdown")).toThrow(RunError);
      expect(() => nextState("Results", "Playing")).toThrow(RunError);
    });

    it("REQ-RUN-01: RunController starts in Loading", () => {
      const ctrl = new RunController({ clock: () => 0, trackDuration: 30 });
      expect(ctrl.state).toBe("Loading");
    });
  });

  // @req:REQ-RUN-02
  describe("REQ-RUN-02: pause/resume sync (drift-free elapsed)", () => {
    it("REQ-RUN-02: paused span is excluded from elapsed()", () => {
      let now = 0;
      const ctrl = new RunController({ clock: () => now, trackDuration: 30 });
      ctrl.start();
      ctrl.beginPlay(); // anchors origin at now=0
      now = 10;
      ctrl.pause();
      now = 25; // 15s spent paused
      ctrl.resume();
      now = 27; // +2s playing
      // 10s before pause + 2s after resume = 12s, NOT 27s
      expect(ctrl.elapsed()).toBeCloseTo(12, 6);
    });

    it("REQ-RUN-02: isPaused reflects pause/resume state", () => {
      let now = 0;
      const ctrl = new RunController({ clock: () => now, trackDuration: 30 });
      ctrl.start();
      ctrl.beginPlay();
      expect(ctrl.isPaused()).toBe(false);
      ctrl.pause();
      expect(ctrl.isPaused()).toBe(true);
      ctrl.resume();
      expect(ctrl.isPaused()).toBe(false);
    });

    it("REQ-RUN-02: elapsed advances with the clock while not paused", () => {
      let now = 0;
      const ctrl = new RunController({ clock: () => now, trackDuration: 30 });
      ctrl.start();
      ctrl.beginPlay();
      now = 5;
      expect(ctrl.elapsed()).toBeCloseTo(5, 6);
      now = 8.5;
      expect(ctrl.elapsed()).toBeCloseTo(8.5, 6);
    });

    it("REQ-RUN-02: multiple pause/resume cycles do not accumulate drift", () => {
      let now = 0;
      const ctrl = new RunController({ clock: () => now, trackDuration: 100 });
      ctrl.start();
      ctrl.beginPlay();
      now = 3;
      ctrl.pause();
      now = 13; // +10 paused
      ctrl.resume();
      now = 16; // +3 playing  (total play 6)
      ctrl.pause();
      now = 26; // +10 paused
      ctrl.resume();
      now = 30; // +4 playing  (total play 10)
      expect(ctrl.elapsed()).toBeCloseTo(10, 6);
    });
  });

  // @req:REQ-RUN-03
  describe("REQ-RUN-03: end condition", () => {
    it("REQ-RUN-03: tick stays Playing before the track ends", () => {
      let now = 0;
      const ctrl = new RunController({ clock: () => now, trackDuration: 30 });
      ctrl.start();
      ctrl.beginPlay();
      now = 29.9;
      expect(ctrl.tick()).toBe("Playing");
      expect(ctrl.isEnded()).toBe(false);
    });

    it("REQ-RUN-03: tick transitions to Results once at track end", () => {
      let now = 0;
      const ctrl = new RunController({ clock: () => now, trackDuration: 30 });
      ctrl.start();
      ctrl.beginPlay();
      now = 30;
      expect(ctrl.tick()).toBe("Results");
      expect(ctrl.isEnded()).toBe(true);
      expect(ctrl.state).toBe("Results");
    });

    it("REQ-RUN-03: calling tick again after end stays Results and does not re-fire", () => {
      let now = 0;
      const ctrl = new RunController({ clock: () => now, trackDuration: 30 });
      ctrl.start();
      ctrl.beginPlay();
      now = 35;
      expect(ctrl.tick()).toBe("Results");
      now = 40;
      // idempotent: still Results, no throw, no second transition
      expect(ctrl.tick()).toBe("Results");
      expect(ctrl.tick()).toBe("Results");
      expect(ctrl.state).toBe("Results");
      expect(ctrl.isEnded()).toBe(true);
    });

    it("REQ-RUN-03: pause near the end — real time past trackDuration while paused does NOT end the run (also REQ-RUN-02)", () => {
      let now = 0;
      const ctrl = new RunController({ clock: () => now, trackDuration: 30 });
      ctrl.start();
      ctrl.beginPlay();
      now = 29;
      ctrl.pause();
      now = 100; // lots of real time passes, but paused -> elapsed frozen at ~29
      expect(ctrl.tick()).toBe("Playing");
      expect(ctrl.isEnded()).toBe(false);
      ctrl.resume(); // elapsed is still ~29
      now = 101.5; // +1.5 playing -> elapsed ~30.5 >= 30
      expect(ctrl.tick()).toBe("Results");
      expect(ctrl.isEnded()).toBe(true);
    });
  });
});
