"""check.py — triple-referee legality (SABERFORGE spec §9, REQ-BS-09).

The in-core validator (§5.2) and swing simulator (REQ-BS-04) are two referees;
the community's own tools are the third and final authority: GalaxyMaster Parity
Checker + Kival Evan Map Check, invoked here as external subprocesses. Their
availability is a DOCUMENTED PREREQUISITE — if a checker binary is absent the
build warns loudly and marks the map "unverified" rather than failing (so the
offline/CI path still runs behind fixtures, spec §11).

Configure the external commands via env vars (each receives the song folder path
as its final argument):
    SABERFORGE_PARITY_CHECKER_CMD   e.g. "galaxymaster-parity"
    SABERFORGE_MAPCHECK_CMD         e.g. "kival-mapcheck"
"""
from __future__ import annotations

import os
import shutil
import subprocess

_CHECKERS = {
    "galaxymaster_parity": "SABERFORGE_PARITY_CHECKER_CMD",
    "kival_evan_mapcheck": "SABERFORGE_MAPCHECK_CMD",
}


def _resolve(cmd: str | None):
    if not cmd:
        return None
    parts = cmd.split()
    exe = shutil.which(parts[0])
    return ([exe] + parts[1:]) if exe else None


def run_external_checkers(song_dir: str) -> dict:
    """Run each configured external checker on the song folder. Returns
    {name: {"available", "clean", "detail"}}. Missing checkers -> available
    False + a loud warning; never raises."""
    results = {}
    for name, env_var in _CHECKERS.items():
        argv = _resolve(os.environ.get(env_var))
        if argv is None:
            print(f"[saberforge] WARNING: external referee '{name}' not available "
                  f"(set ${env_var}); map marked UNVERIFIED by this checker.")
            results[name] = {"available": False, "clean": None,
                             "detail": f"{env_var} unset or binary not found"}
            continue
        try:
            proc = subprocess.run(argv + [song_dir], capture_output=True,
                                  text=True, timeout=180)
            clean = proc.returncode == 0
            results[name] = {"available": True, "clean": clean,
                             "detail": (proc.stdout or proc.stderr)[-1000:]}
            if not clean:
                print(f"[saberforge] {name}: FAIL — {(proc.stdout or proc.stderr)[:200]}")
        except Exception as e:                       # noqa: BLE001 — never abort the build
            results[name] = {"available": True, "clean": None, "detail": str(e)[:300]}
            print(f"[saberforge] WARNING: external referee '{name}' errored: {e}")
    return results


def referee_summary(in_core_ok: bool, sim_clean: bool, external: dict) -> dict:
    """Combine the three referees. `verified` is True only when the two in-core
    referees pass AND every AVAILABLE external checker is clean. If an external
    checker is unavailable the map is 'unverified' (not failed)."""
    ext_available = [v for v in external.values() if v.get("available")]
    ext_clean = all(v.get("clean") for v in ext_available) if ext_available else None
    any_unavailable = any(not v.get("available") for v in external.values())
    verified = in_core_ok and sim_clean and (ext_clean is True)
    return {
        "in_core_ok": in_core_ok,
        "simulator_clean": sim_clean,
        "external": external,
        "external_clean": ext_clean,
        "unverified": any_unavailable or ext_clean is None,
        "verified": verified,
    }
