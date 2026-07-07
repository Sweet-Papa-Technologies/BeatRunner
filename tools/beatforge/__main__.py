"""beatforge CLI — `python -m beatforge {generate|analyze|chart|validate|qa|all}`.

Run from anywhere with `tools/` on PYTHONPATH, or `cd tools && python -m beatforge`.
Idempotent: stages skip work whose output exists unless --force.
"""
from __future__ import annotations

import argparse
import json
import sys

from . import config
from .analyze import analyze_track, load_cached
from .compute import make_backend
from .validate import BeatmapError, parse_beatmap_py


def _opts(a) -> config.RunOptions:
    tracks = (a.track,) if getattr(a, "track", None) else tuple(config.TRACK_CATALOGUE)
    diffs = (a.difficulty,) if getattr(a, "difficulty", None) else config.DIFFICULTIES
    return config.RunOptions(
        backend=getattr(a, "backend", config.DEFAULT_BACKEND),
        force=getattr(a, "force", False),
        skip_gen=getattr(a, "skip_gen", True),
        allow_local_fallback=getattr(a, "allow_local_fallback", False),
        tracks=tracks, difficulties=diffs, gpu=getattr(a, "gpu", config.COLAB_GPU),
        offline=getattr(a, "offline", False),
    )


def cmd_analyze(a):
    opts = _opts(a)
    backend = make_backend(opts, run_id="cli")
    try:
        for tid in opts.tracks:
            an = analyze_track(tid, opts, backend=backend)
            print(f"[analyze] {tid}: bpm={an['bpm']} offset={an['offset']} "
                  f"onsets={len(an['onsets'])} holds={an.get('sustain_available')} "
                  f"backend={an['beat_backend']} stems={an['stem_source']}")
    finally:
        backend.close()


def cmd_chart(a):
    from .pipeline import chart_track
    from .llm import make_llm_client
    opts = _opts(a)
    client = make_llm_client()
    backend = make_backend(opts, run_id="cli")
    try:
        for tid in opts.tracks:
            summary = chart_track(tid, opts, client, backend=backend)
            for diff, info in summary["charts"].items():
                if "error" in info:
                    print(f"[chart] {tid}/{diff}: FAILED — {info['error'][:120]}")
                    continue
                print(f"[chart] {tid}/{diff}: {info['events']} events, "
                      f"{info['attempts']} attempt(s), critic={info['critic_score']}, "
                      f"gates_pass={info['gates_pass']} -> {info['map']}")
    finally:
        backend.close()


def cmd_validate(a):
    """Re-parse emitted maps with the schema-parity validator (REQ-VAL-01)."""
    opts = _opts(a)
    ok = True
    for tid in opts.tracks:
        base = config.TRACK_CATALOGUE.get(tid, tid)
        for diff in opts.difficulties:
            p = config.MAPS_PUB / f"{base}.{diff}.beatmap.json"
            if not p.exists():
                continue
            try:
                bm = parse_beatmap_py(json.loads(p.read_text()))
                print(f"[validate] {p.name}: OK ({len(bm['events'])} events)")
            except BeatmapError as e:
                ok = False
                print(f"[validate] {p.name}: FAIL {e}")
    sys.exit(0 if ok else 1)


def cmd_qa(a):
    opts = _opts(a)
    for tid in opts.tracks:
        base = config.TRACK_CATALOGUE.get(tid, tid)
        for diff in opts.difficulties:
            p = config.BUILD_DIR / f"{base}.{diff}.qa.json"
            if p.exists():
                r = json.loads(p.read_text())
                m = r["metrics"]
                print(f"[qa] {tid}/{diff}: align={m['onset_alignment']:.2f} "
                      f"nps={m['peak_nps_4s']:.1f} critic={(r.get('critic') or {}).get('score')} "
                      f"gates={all(m['gates'].values())}")


def cmd_generate(a):
    from .gen import generate_track
    from .vertex import VertexClient
    opts = _opts(a)
    client = VertexClient()
    for tid in opts.tracks:
        res = generate_track(tid, opts, client)
        print(f"[generate] {tid}: winner score={res['winner_score']:.1f} "
              f"rounds={res['rounds']} -> {res['audio']}")


def cmd_compare(a):
    """Benchmark the OpenAI-compatible model (e.g. local Gemma 4 12B) against
    Gemini 3.5 Flash on the audio-understanding probe + designer/critic. With
    --track it runs one track; without, it sweeps the whole catalogue."""
    from .compare import compare_track, format_report
    opts = _opts(a)
    tracks = (a.track,) if a.track else tuple(config.TRACK_CATALOGUE)
    diff = a.difficulty or "standard"
    reachable = _openai_reachable()
    if not reachable:
        print("[compare] WARNING: OpenAI-compatible server "
              f"{config.OPENAI_BASE_URL} is not reachable; the Gemma column will "
              "show errors. Gemini baseline still runs.")
    for tid in tracks:
        report = compare_track(tid, diff, opts, probe_only=a.probe_only)
        print(format_report(report))
        out = config.BUILD_DIR / f"compare.{config.TRACK_CATALOGUE.get(tid, tid)}.{diff}.json"
        out.write_text(json.dumps(report, indent=2))
    print(f"\nreports -> {config.BUILD_DIR.relative_to(config.REPO_ROOT)}/compare.*.json")


def _openai_reachable() -> bool:
    from .llm import OpenAICompatClient
    try:
        OpenAICompatClient().list_models(timeout=6)
        return True
    except Exception:
        return False


def cmd_all(a):
    from .pipeline import chart_track
    from .llm import make_llm_client
    opts = _opts(a)
    client = make_llm_client()          # charting: swappable (Gemini or Gemma)
    if not opts.skip_gen:
        # Generation (Lyria + A&R) is Vertex-only, independent of the chart backend.
        from .gen import generate_track
        from .vertex import VertexClient
        gen_client = VertexClient()
        for tid in opts.tracks:
            generate_track(tid, opts, gen_client)
    # ONE backend/session for the whole batch (REQ-COMPUTE-03)
    backend = make_backend(opts, run_id="batch")
    try:
        for tid in opts.tracks:
            summary = chart_track(tid, opts, client, backend=backend)
            print(f"[all] {tid}: " + ", ".join(
                f"{d}={i['events']}ev/critic{i['critic_score']}"
                for d, i in summary["charts"].items()))
    finally:
        backend.close()


def build_parser():
    p = argparse.ArgumentParser(prog="beatforge",
                                description="Music-aware track & chart pipeline for OVERDRIVE.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, difficulty=True):
        sp.add_argument("--track", help="single track id (default: all)")
        if difficulty:
            sp.add_argument("--difficulty", choices=config.DIFFICULTIES)
        sp.add_argument("--backend", choices=["local", "colab"], default=config.DEFAULT_BACKEND)
        sp.add_argument("--gpu", default=config.COLAB_GPU)
        sp.add_argument("--force", action="store_true")
        sp.add_argument("--allow-local-fallback", action="store_true", dest="allow_local_fallback")
        sp.add_argument("--offline", action="store_true", help="skip Vertex calls")

    common(sub.add_parser("analyze", help="Workstream B: DSP ground truth"), difficulty=False)
    common(sub.add_parser("chart", help="Workstreams C/D: design + validate + QA"))
    common(sub.add_parser("validate", help="re-parse emitted maps (schema parity)"))
    common(sub.add_parser("qa", help="print QA metrics for emitted charts"))
    g = sub.add_parser("generate", help="Workstream A: Lyria x Gemini A&R loop")
    common(g, difficulty=False)
    av = sub.add_parser("all", help="generate?(skip) -> analyze -> chart everything")
    common(av)
    av.add_argument("--skip-gen", action="store_true", default=True, dest="skip_gen",
                    help="keep existing audio (default)")
    av.add_argument("--with-gen", action="store_false", dest="skip_gen",
                    help="run the generation loop first")

    cmp = sub.add_parser("compare", help="benchmark OpenAI-compatible model vs Gemini 3.5 Flash")
    common(cmp)
    cmp.add_argument("--probe-only", action="store_true", dest="probe_only",
                     help="only run the audio-understanding probe (skip full chart design)")

    for name, fn in {"analyze": cmd_analyze, "chart": cmd_chart, "validate": cmd_validate,
                     "qa": cmd_qa, "generate": cmd_generate, "all": cmd_all,
                     "compare": cmd_compare}.items():
        sub.choices[name].set_defaults(fn=fn)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
