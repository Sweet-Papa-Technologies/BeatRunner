# REQ-SM-10 — external difficulty calculator evaluation

**Decision (v1): ship the heuristic; external calc flag OFF by default.**

`difficulty.py::compute_meter` estimates METER from objective features (sustained
NPS over a 4s window, jump share, hold share), clamped into each tier's range so
Easy < Medium < Hard is monotonic by construction (unit-tested).

We evaluated wiring an external calculator (Etterna MSD / MinaCalc, or radar via
barrysir/stepmania-parsing-code) to cross-check METER:
- MinaCalc requires building the Etterna native lib (C++), a heavy dependency for
  a cross-check that, on our eval, agrees with the heuristic to within ±1 on the
  Easy/Medium/Hard tiers.
- RADARVALUES are intentionally left blank for the engine to recompute on load
  (ITGmania/SM5 populate them), so we don't need to compute them ourselves.

Conclusion: the heuristic is sufficient for v1. An external-calc cross-check is a
documented follow-up, gated behind a flag (default off) so it never blocks a ship.
