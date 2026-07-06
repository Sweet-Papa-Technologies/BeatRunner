"""QA metric + gate tests (REQ-QA-01/02)."""
from beatforge import config, qa
from beatforge.resolve import resolve_events
from beatforge.validate import validate_and_repair


def _chart(a, difficulty, refs):
    design = {"events": refs}
    vr = validate_and_repair(resolve_events(design, a), a, difficulty)
    return vr, qa.compute_metrics(vr, a, difficulty)


def test_metrics_basic_shape(make_analysis):
    a = make_analysis()
    refs = [{"ref": f"p{i:03d}", "lane": ["GAP", "BAR", "NOTE"][i % 3]}
            for i in range(0, 30, 2)]
    vr, m = _chart(a, "standard", refs)
    assert m["onset_alignment"] == 1.0  # all onset refs sit on detected onsets
    assert set(m["lane_share"]) == {"GAP", "BAR", "NOTE"}
    assert "spearman" in m["density_energy"]


def test_onset_alignment_counts_only_onset_events(make_analysis):
    a = make_analysis()
    refs = [{"ref": "grid:8", "lane": "BAR"}, {"ref": "grid:16", "lane": "GAP"}]
    vr, m = _chart(a, "casual", refs)
    assert m["onset_events"] == 0 and m["grid_events"] == 2


def test_flat_track_exempts_density_shape_gates(make_analysis):
    """Uniform loops (low energy CV) are exempt from density-shape gates but
    still enforce alignment/lane/nps/hold (config note)."""
    a = make_analysis(energy_cv=0.03)  # below DENSITY_GATE_MIN_CV
    refs = [{"ref": f"p{i:03d}", "lane": ["GAP", "BAR", "NOTE"][i % 3]}
            for i in range(0, 30, 2)]
    vr, m = _chart(a, "standard", refs)
    assert m["flat_track_exempt"] is True
    assert m["gates"]["density_spearman"] and m["gates"]["density_peak"]


def test_structured_track_enforces_density(make_analysis):
    a = make_analysis(energy_cv=0.3)  # above threshold -> full gate applies
    refs = [{"ref": f"p{i:03d}", "lane": ["GAP", "BAR", "NOTE"][i % 3]}
            for i in range(0, 30, 2)]
    vr, m = _chart(a, "standard", refs)
    assert m["flat_track_exempt"] is False


def test_violation_report_is_machine_readable(make_analysis):
    a = make_analysis(energy_cv=0.3)
    # alternate only two lanes (2-beat spaced, no jacks) -> NOTE share 0 -> the
    # lane_balance gate fails and the machine-readable report must name it.
    refs = [{"ref": f"p{i:03d}", "lane": ["BAR", "GAP"][k % 2]}
            for k, i in enumerate(range(0, 24, 2))]
    vr, m = _chart(a, "standard", refs)
    assert not m["gates"]["lane_balance"]
    rep = qa.violation_report(m, "standard")
    assert "lane" in rep.lower()
