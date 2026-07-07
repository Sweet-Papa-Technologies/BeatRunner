"""quantize.py — snap onset-derived beats to legal rows and convert realized
placements into simfile Note objects (STEPFORGE spec §4, REQ-SM-01).

Row/measure encoding is delegated to `simfile.notes.NoteData.from_notes` — we
never hand-format the note grammar (REQ-SM-07). Our job is only to put each note
on a legal subdivision for its difficulty and pair holds with their tails.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from simfile.notes import Note, NoteData, NoteType
from simfile.timing import Beat

from .grammar import LEGAL_ROWS


@dataclass
class Placement:
    """A realized note: concrete panel(s), kind and optional hold length."""
    beat: float
    panels: tuple[int, ...]        # 1 = tap, 2 = a jump
    kind: str = "tap"              # tap|hold|roll|mine
    hold_beats: float | None = None
    meta: dict = field(default_factory=dict)


def snap_beat(beat: float, finest_subdiv: float) -> Fraction:
    """Snap a beat to the coarsest exact fraction on the difficulty's finest
    subdivision grid (e.g. 0.25 -> quarters of a beat)."""
    steps = round(beat / finest_subdiv)
    return Fraction(steps) * Fraction(finest_subdiv).limit_denominator(192)


def measure_resolution_ok(beats: list[Fraction]) -> bool:
    """True iff every beat lands on a legal per-measure subdivision (each measure
    = 4 beats, rows in LEGAL_ROWS). A beat's within-measure position must be an
    integer number of rows for some legal row count."""
    for b in beats:
        pos = b % 4                                   # position within the measure
        ok = any(((pos / 4) * q).denominator == 1 for q in LEGAL_ROWS)
        if not ok:
            return False
    return True


_KIND_HEAD = {"tap": NoteType.TAP, "hold": NoteType.HOLD_HEAD,
              "roll": NoteType.ROLL_HEAD, "mine": NoteType.MINE}


def to_simfile_notes(placements: list[Placement], finest_subdiv: float) -> NoteData:
    """Convert placements into a simfile NoteData (4 columns). Holds/rolls emit a
    head + a matching tail on the same column."""
    notes: list[Note] = []
    for p in placements:
        b = snap_beat(p.beat, finest_subdiv)
        head = _KIND_HEAD.get(p.kind, NoteType.TAP)
        for col in p.panels:
            if p.kind in ("hold", "roll") and p.hold_beats:
                notes.append(Note(beat=Beat(b), column=col, note_type=head))
                tail = snap_beat(p.beat + p.hold_beats, finest_subdiv)
                notes.append(Note(beat=Beat(tail), column=col, note_type=NoteType.TAIL))
            else:
                notes.append(Note(beat=Beat(b), column=col, note_type=head))
    notes.sort(key=lambda n: (n.beat, n.column))
    return NoteData.from_notes(notes, columns=4)
