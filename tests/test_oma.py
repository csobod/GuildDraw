"""OMA / DCS lens-trace interchange (M7) — parser, conversions, round-trip."""
import math

import pytest

from framedraft.document import Layer
from framedraft.export.oma import (
    OmaJob, OmaTrace, parse_oma, build_oma, trace_to_curve, curve_to_trace,
    boxing_center,
)
from helpers import circle, line


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

GOLDEN = (
    "JOB=12345\r\n"
    "CLIENT=Guild Optical\r\n"
    "DBL=18.50\r\n"
    "HBOX=46.00;46.00\r\n"
    "VBOX=38.00;38.00\r\n"
    "TRCFMT=1;16;E;R;F\r\n"
    "R=2000;2100;2000;1900;2000;2100;2000;1900;2000;2100\r\n"
    "R=2000;1900;2000;2100;2000;1900\r\n"
    "TRCFMT=1;16;E;L;F\r\n"
    "R=2000;2000;2000;2000;2000;2000;2000;2000;2000;2000\r\n"
    "R=2000;2000;2000;2000;2000;2000\r\n"
)


import pathlib

from framedraft.export.oma import OmaDrill

_DRILLED = (
    "TRCFMT=1;8;E;R;F\r\n"
    "R=2000;2000;2000;2000;2000;2000;2000;2000\r\n"
    "DRILLE=B;C;-25.00;9.00;1.40;-25.00;9.00;0;1;F\r\n"
    "DRILLE=B;C;21.67;6.20;1.40;21.67;6.20;0;1;F\r\n"
)


def test_parse_drille_holes():
    job = parse_oma(_DRILLED)
    assert len(job.drills) == 2
    d0 = job.drills[0]
    assert (d0.x, d0.y, d0.dia) == pytest.approx((-25.0, 9.0, 1.4))
    assert d0.eye == "B" and d0.ftype == "C"


def test_drille_round_trips_verbatim():
    # A parsed DRILLE keeps its raw fields → build re-emits it byte-for-byte.
    job = parse_oma(_DRILLED)
    out = build_oma(job)
    assert "DRILLE=B;C;-25.00;9.00;1.40;-25.00;9.00;0;1;F" in out
    assert "DRILLE=B;C;21.67;6.20;1.40;21.67;6.20;0;1;F" in out
    assert parse_oma(out).drills[0].x == pytest.approx(-25.0)


def test_drille_built_from_scratch_uses_canonical_format():
    job = OmaJob()
    job.traces["R"] = OmaTrace(side="R", radii_mm=[20.0] * 8)
    job.drills.append(OmaDrill(x=-25.0, y=9.0, dia=1.4))
    assert "DRILLE=B;C;-25.00;9.00;1.40;-25.00;9.00;0;1;F" in build_oma(job)


def test_bare_drille_count_is_preserved():
    # "DRILLE=0" (no holes) is not a feature — keep it verbatim, no drills.
    job = parse_oma("TRCFMT=1;3;E;R;F\r\nR=2000;2000;2000\r\nDRILLE=0\r\n")
    assert job.drills == []
    assert "DRILLE=0" in build_oma(job)


def test_golden_silhouette_sample_if_present():
    sample = pathlib.Path(__file__).resolve().parents[1] / "HEART_54_0.OMA"
    if not sample.exists():
        pytest.skip("HEART_54_0.OMA sample not present")
    job = parse_oma(sample.read_text(encoding="ascii", errors="replace"))
    assert len(job.drills) == 4
    xs = sorted(round(d.x, 2) for d in job.drills)
    assert xs == [-25.0, -22.0, 21.67, 24.67]
    assert all(d.dia == pytest.approx(1.4) for d in job.drills)
    # full round trip preserves all four DRILLE lines verbatim
    rebuilt = build_oma(job)
    for raw_line in sample.read_text(encoding="ascii").splitlines():
        if raw_line.startswith("DRILLE=B"):
            assert raw_line in rebuilt


def test_parse_golden_file():
    job = parse_oma(GOLDEN)
    assert set(job.traces) == {"R", "L"}
    assert len(job.traces["R"].radii_mm) == 16
    assert len(job.traces["L"].radii_mm) == 16
    assert job.traces["R"].radii_mm[0] == pytest.approx(20.0)   # 2000 -> mm
    assert job.traces["R"].radii_mm[1] == pytest.approx(21.0)
    assert job.values("DBL") == ["18.50"]
    assert job.floats("DBL") == [18.5]
    assert job.floats("HBOX") == [46.0, 46.0]
    # unknown records preserved, in order
    assert ("JOB", "12345") in job.records
    assert ("CLIENT", "Guild Optical") in job.records


def test_parse_tolerates_lf_blank_lines_and_trailing_semicolons():
    text = "dbl=17\n\nTRCFMT=1;8;E;L;F\nR=1000;1000;1000;1000;\nR=1000;1000;1000;1000\n"
    job = parse_oma(text)
    assert job.floats("DBL") == [17.0]
    assert len(job.traces["L"].radii_mm) == 8


def test_parse_format_4_raises():
    with pytest.raises(ValueError, match="format 4"):
        parse_oma("TRCFMT=4;400;E;R;F\nR=1;2\n")


def test_parse_uneven_spacing_raises():
    with pytest.raises(ValueError, match="equally-spaced"):
        parse_oma("TRCFMT=1;8;U;R;F\nR=1;2;3;4;5;6;7;8\n")


def test_parse_r_before_trcfmt_raises():
    with pytest.raises(ValueError, match="before any TRCFMT"):
        parse_oma("R=1000;1000\n")


def test_parse_point_count_mismatch_raises():
    with pytest.raises(ValueError, match="declares 10"):
        parse_oma("TRCFMT=1;10;E;R;F\nR=1000;1000;1000\n")


def test_parse_malformed_line_raises():
    with pytest.raises(ValueError, match="no '='"):
        parse_oma("THIS IS NOT A RECORD\n")


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def test_build_chunks_r_records_and_preserves_unknown_records():
    job = OmaJob()
    job.records.append(("CLIENT", "Guild Optical"))
    job.set_record("DBL", "18.50")
    job.traces["R"] = OmaTrace(side="R", radii_mm=[20.0] * 25)
    text = build_oma(job)
    lines = text.strip().split("\r\n")
    assert "CLIENT=Guild Optical" in lines
    assert "DBL=18.50" in lines
    assert "TRCFMT=1;25;E;R;F" in lines
    r_lines = [ln for ln in lines if ln.startswith("R=")]
    assert [len(ln[2:].split(";")) for ln in r_lines] == [10, 10, 5]


def test_build_parse_round_trip_is_exact():
    job = parse_oma(GOLDEN)
    job2 = parse_oma(build_oma(job))
    assert job2.records == job.records
    for side in ("R", "L"):
        assert job2.traces[side].radii_mm == job.traces[side].radii_mm


# ---------------------------------------------------------------------------
# trace -> Curve
# ---------------------------------------------------------------------------

def test_trace_to_curve_circle():
    radii = [25.0] * 400
    c = trace_to_curve(radii)
    assert c.kind == "spline" and c.closed and c.layer == Layer.LENS
    assert 4 <= len(c.nodes) <= 16      # the cubic fit (Catmull-Rom took 32)
    for nd in c.nodes:
        assert math.hypot(nd.x, nd.y) == pytest.approx(25.0, abs=1e-9)
    # between-node fidelity: evaluate densely, radius stays ~25 mm
    from framedraft.geometry import sample_curve
    for x, y, _t in sample_curve(c):
        assert math.hypot(x, y) == pytest.approx(25.0, abs=0.01)


def test_trace_to_curve_skips_invalid_points_keeping_angles():
    # invalid (negative) radii must be skipped without rotating the shape
    radii = [25.0] * 16
    radii[3] = -100.0
    c = trace_to_curve(radii)
    angles = sorted(math.atan2(-nd.y, nd.x) % (2 * math.pi) for nd in c.nodes)
    expected = sorted(2 * math.pi * i / 16 for i in range(16) if i != 3)
    assert angles == pytest.approx(expected)


def test_trace_to_curve_too_few_points_raises():
    with pytest.raises(ValueError, match="points"):
        trace_to_curve([25.0] * 4)
    with pytest.raises(ValueError, match="valid"):
        trace_to_curve([25.0] * 6 + [-1.0] * 10)


# ---------------------------------------------------------------------------
# Curve -> trace
# ---------------------------------------------------------------------------

def test_curve_to_trace_offset_circle():
    c = circle(10.0, -5.0, 24.0)
    assert boxing_center(c) == pytest.approx((10.0, -5.0), abs=1e-6)
    radii = curve_to_trace(c, n=360)
    assert len(radii) == 360
    for r in radii:
        assert r == pytest.approx(24.0, abs=0.01)


def test_curve_to_trace_non_star_shaped_raises():
    # L-shaped contour: its bbox center (5, 5) lies outside the region
    l_shape = line([(0, 0), (10, 0), (10, 2), (2, 2), (2, 10), (0, 10)],
                   closed=True, layer=Layer.LENS)
    with pytest.raises(ValueError, match="star-shaped"):
        curve_to_trace(l_shape)


# ---------------------------------------------------------------------------
# Full round-trip (1.0 release criterion: < 0.05 mm)
# ---------------------------------------------------------------------------

def _lens_like_radii(n=400):
    """Smooth lens-ish shape, symmetric in x and y so its bbox center
    coincides with the polar origin (keeps the comparison center-consistent)."""
    out = []
    for i in range(n):
        a = 2 * math.pi * i / n
        r = 24.0 + 2.5 * math.cos(2 * a) + 0.8 * math.cos(4 * a)
        out.append(round(r * 100) / 100.0)   # quantize like a real R record
    return out


def test_import_export_round_trip_within_005mm():
    src = _lens_like_radii()
    curve = trace_to_curve(src)
    back = curve_to_trace(curve, n=len(src))
    worst = max(abs(a - b) for a, b in zip(src, back, strict=True))
    assert worst < 0.05, f"max radius deviation {worst:.4f} mm"


def test_full_file_round_trip_within_005mm():
    job = OmaJob()
    job.set_record("DBL", "18.00")
    job.traces["R"] = OmaTrace(side="R", radii_mm=_lens_like_radii())
    job.traces["L"] = OmaTrace(side="L", radii_mm=_lens_like_radii())

    reparsed = parse_oma(build_oma(job))                      # file -> job
    curve = trace_to_curve(reparsed.traces["R"].radii_mm)     # import
    job2 = OmaJob()
    job2.traces["R"] = OmaTrace(side="R", radii_mm=curve_to_trace(curve))
    reparsed2 = parse_oma(build_oma(job2))                    # export -> file

    a = job.traces["R"].radii_mm
    b = reparsed2.traces["R"].radii_mm
    worst = max(abs(x - y) for x, y in zip(a, b, strict=True))
    assert worst < 0.05, f"max radius deviation {worst:.4f} mm"


def test_a_tight_cornered_trace_comes_back_within_two_hundredths():
    """A fixed 32 nodes put a rectangle with 2 mm corners 0.2 mm off."""
    import shapely
    from shapely.geometry import LineString
    from framedraft.geometry import sample_curve
    n, a, b, rc = 1000, 25.0, 16.0, 2.0
    radii = []
    for i in range(n):
        t = 2 * math.pi * i / n
        dx, dy = math.cos(t), math.sin(t)
        lo, hi = 0.0, 40.0                        # the rounded rectangle's edge
        for _ in range(60):
            mid = (lo + hi) / 2
            x, y = abs(mid * dx), abs(mid * dy)
            qx, qy = max(x - (a - rc), 0.0), max(y - (b - rc), 0.0)
            inside = (x <= a and y <= b and math.hypot(qx, qy) <= rc)
            lo, hi = (mid, hi) if inside else (lo, mid)
        radii.append(lo)
    c = trace_to_curve(radii)
    pts = [(r * math.cos(2 * math.pi * i / n), -r * math.sin(2 * math.pi * i / n))
           for i, r in enumerate(radii)]
    line = LineString([(x, y) for x, y, _t in sample_curve(c, 24)])
    assert float(shapely.distance(shapely.points(pts), line).max()) <= 0.02


def test_a_radius_field_is_a_plain_integer():
    """int() took "1_000" as 1000 and non-ASCII digits (the 2.3 hunt)."""
    import pytest
    from framedraft.export.oma import parse_oma
    good = parse_oma("TRCFMT=1;3;E;R;F\nR=2550;-10;+2548\n")
    assert good.traces["R"].radii_mm == [25.5, -0.1, 25.48]
    for bad in ("R=1_000;2550;2550\n", "R=٢٥٥٠;2550;2550\n", "R=25.50;2550;2550\n"):
        with pytest.raises(ValueError):
            parse_oma("TRCFMT=1;3;E;R;F\n" + bad)


# ── DRILLE as the standard defines it (the 2.3 sweep; DCS 3.14 §5.5.2) ──────

def _ring(cx, cy, a, b, n=120):
    return [(cx + a * math.cos(2 * math.pi * i / n), cy + b * math.sin(2 * math.pi * i / n))
            for i in range(n)]


#: A rimless mount's four holes, as its maker's own file gives them: 2 and 5
#: mm inside each edge of a 54 mm lens, the right lens's, "B" for both.
_MOUNT = (
    "DRILLE=B;C;-25.00;9.00;1.40;-25.00;9.00;0;1;F\r\n"
    "DRILLE=B;C;-22.00;9.16;1.40;-22.00;9.16;0;1;F\r\n"
    "DRILLE=B;C;21.67;6.20;1.40;21.67;6.20;0;1;F\r\n"
    "DRILLE=B;C;24.67;6.20;1.40;24.67;6.20;0;1;F\r\n"
)


def test_a_b_record_is_the_right_lens_s_hole_mirrored_onto_the_left():
    """It was read from the midpoint between the lenses: the mount's eight
    holes came in as four, heaped at the two lens centers."""
    from framedraft.export.oma import place_drills
    job = parse_oma("TRCFMT=1;4;E;R;P\r\nR=2700;2000;2700;2000\r\n" + _MOUNT)
    centers = {"R": (-36.0, 0.0), "L": (36.0, 0.0)}
    outlines = {"R": _ring(-36, 0, 27, 20), "L": _ring(36, 0, 27, 20)}
    lay = place_drills(job.drills, centers, outlines)
    assert not lay.legacy and (lay.unread, lay.slots, lay.no_lens) == (0, 0, 0)
    got = sorted((round(x, 2), round(y, 2)) for x, y, _ in lay.holes)
    assert got == sorted([(-61.0, -9.0), (-58.0, -9.16), (-14.33, -6.2), (-11.33, -6.2),
                          (61.0, -9.0), (58.0, -9.16), (14.33, -6.2), (11.33, -6.2)])
    assert all(dia == pytest.approx(1.4) for _, _, dia in lay.holes)
    # Every hole is in its lens, 2 to 5.4 mm inside an edge of its box.
    for x, _y, _ in lay.holes:
        assert 2.0 <= 27.0 - abs(abs(x) - 36.0) <= 5.4
    # One lens traced: its holes only (the Ghost shows the twin's).
    one = place_drills(job.drills, {"R": (-36.0, 0.0)}, {"R": outlines["R"]})
    assert len(one.holes) == 4 and all(x < 0 for x, _, _ in one.holes)


def test_r_and_l_records_go_to_their_own_lens_unmirrored():
    from framedraft.export.oma import place_drills
    job = parse_oma("DRILLE=R;C;21.00;6.00;1.40\r\nDRILLE=L;C;-21.00;6.00;2.00\r\n")
    lay = place_drills(job.drills, {"R": (-36.0, 1.0), "L": (36.0, 1.0)})
    assert sorted(lay.holes) == [(-15.0, -5.0, 1.4), (15.0, -5.0, 2.0)]
    # A hole for a lens the file has no trace of is counted, not guessed.
    alone = place_drills(job.drills, {"R": (-36.0, 1.0)})
    assert alone.holes == [(-15.0, -5.0, 1.4)] and alone.no_lens == 1


def test_a_guilddraw_export_from_before_2_3_is_read_as_it_was_written():
    """Every hole tagged B and measured from the frame's center: the
    standard's reading puts its temple-side holes off the lens."""
    from framedraft.export.oma import place_drills
    old = parse_oma("".join(
        f"DRILLE=B;C;{x:.2f};{y:.2f};1.40;{x:.2f};{y:.2f};0;1;F\r\n"
        for x, y in ((-56.0, 8.0), (-12.0, 6.0), (12.0, 6.0), (56.0, 8.0))))
    centers = {"R": (-34.0, 0.0), "L": (34.0, 0.0)}
    outlines = {"R": _ring(-34, 0, 25, 20), "L": _ring(34, 0, 25, 20)}
    lay = place_drills(old.drills, centers, outlines)
    assert lay.legacy
    assert sorted(lay.holes) == [(-56.0, -8.0, 1.4), (-12.0, -6.0, 1.4),
                                 (12.0, -6.0, 1.4), (56.0, -8.0, 1.4)]
    # The mount's file is not taken for one: its holes are in the lens as the
    # standard reads them.
    mount = parse_oma(_MOUNT)
    wide = {"R": _ring(-36, 0, 27, 20), "L": _ring(36, 0, 27, 20)}
    assert not place_drills(mount.drills, {"R": (-36.0, 0.0), "L": (36.0, 0.0)}, wide).legacy


def test_the_standard_s_minimal_record_and_an_unknown_diameter_are_read():
    """`DRILLE=B;C;-17.0;10.32`, the standard's own example, was dropped
    unsaid, and a "?" diameter refused the whole file."""
    from framedraft.export.oma import DEFAULT_DRILL_DIA_MM
    job = parse_oma("DRILLE=B;C;-17.0;10.32\r\nDRILLE=r;C;3;4;?\r\nDRILLE=L;;5;6;\r\n"
                    "DRILLE=0\r\nDRILLE=R;0\r\n")
    assert [(d.eye, d.ftype, d.x, d.y, d.dia) for d in job.drills] == [
        ("B", "C", -17.0, 10.32, DEFAULT_DRILL_DIA_MM), ("R", "C", 3.0, 4.0, DEFAULT_DRILL_DIA_MM),
        ("L", "C", 5.0, 6.0, DEFAULT_DRILL_DIA_MM)]
    out = build_oma(job)
    assert "DRILLE=B;C;-17.0;10.32\r\n" in out and "DRILLE=0\r\n" in out and "DRILLE=R;0" in out
    with pytest.raises(ValueError, match="Bad DRILLE"):
        parse_oma("DRILLE=B;C;abc;1;1.4\r\n")


def test_edge_references_and_slots_are_counted_not_misplaced():
    """An edge-referenced hole was placed as if from the center, and a slot
    as a round hole, neither with a word."""
    from framedraft.export.oma import place_drills
    job = parse_oma("DRILLE=B;EN;3.0;5.0;1.4\r\nDRILLE=R;BT;2.5;0;1.4\r\n"
                    "DRILLE=R;C;-20.0;5.0;1.4;-17.0;5.0;0;1;F\r\n"
                    "DRILLE=R;CF;10.0;2.0;1.4;10.0;2.0;0;1;F\r\n")
    lay = place_drills(job.drills, {"R": (-36.0, 0.0), "L": (36.0, 0.0)})
    assert lay.unread == 2 and lay.slots == 1
    assert sorted(lay.holes) == [(-56.0, -5.0, 1.4), (-26.0, -2.0, 1.4)]


def test_a_hole_built_for_an_eye_names_it():
    job = OmaJob()
    job.drills.append(OmaDrill(x=-18.0, y=10.0, dia=1.4, eye="R"))
    job.drills.append(OmaDrill(x=18.0, y=10.0, dia=1.4, eye="L"))
    out = build_oma(job)
    assert "DRILLE=R;C;-18.00;10.00;1.40;-18.00;10.00;0;1;F\r\n" in out
    assert "DRILLE=L;C;18.00;10.00;1.40;18.00;10.00;0;1;F\r\n" in out


def test_a_byte_order_mark_padding_and_a_no_trace_format_do_not_refuse_the_file():
    """An editor's BOM (three replacement characters, read as ASCII), a DOS
    host's Ctrl-Z or NUL padding, and TRCFMT=0, the standard's "no trace
    available", each refused the whole file."""
    body = "TRCFMT=1;4;E;R;F\r\nR=2000;2000;2000;2000\r\n"
    for text in ("\ufffd\ufffd\ufffd" + body, "\ufeff" + body,
                 body + "\x1a\r\n", body + "\x00\x00\x00\r\n", body + "\x1a"):
        assert parse_oma(text).traces["R"].radii_mm == [20.0] * 4
    none = parse_oma("TRCFMT=0\r\nHBOX=50.00;50.00\r\n")
    assert none.traces == {} and ("TRCFMT", "0") in none.records
    assert "TRCFMT=0\r\n" in build_oma(none)
    with pytest.raises(ValueError, match="no '='"):
        parse_oma(body + "this is not a record\r\n")
    with pytest.raises(ValueError, match="format 4"):
        parse_oma("TRCFMT=4;400;E;R;F\r\n")
