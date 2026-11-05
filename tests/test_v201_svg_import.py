"""SVG import in 2.0.1, from the files-in-and-out review of 2026-10-29: the
hairline rule (cumulative, after the import's scale, and said), the
document's aspect ratio, a curve cap like DXF's, and groups nested deeper
than Python's recursion limit. Each test names the finding it pins."""
import math
import random
import re

import pytest

from framedraft.document import Layer
from framedraft.export import svg_import
from framedraft.export.svg_import import content_bbox, import_svg, place_curves, read_svg

_SVG = '<svg xmlns="http://www.w3.org/2000/svg" {attrs}>{body}</svg>'


def _write(tmp_path, body, attrs='width="60mm" height="50mm" viewBox="0 0 60 50"',
           name="in.svg"):
    p = tmp_path / name
    p.write_text(_SVG.format(attrs=attrs, body=body), encoding="utf-8")
    return str(p)


def _read(tmp_path, body, attrs='width="60mm" height="50mm" viewBox="0 0 60 50"'):
    return read_svg(_write(tmp_path, body, attrs), Layer.REF, "front")


def _ellipse(step, rx=5.0, ry=4.0, cx=30.0, cy=25.0):
    """Points round an ellipse, each *step()* mm of arc after the last."""
    pts, a = [], 0.0
    while a < 2 * math.pi:
        pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
        a += step() / math.hypot(rx * math.sin(a), ry * math.cos(a))
    return pts


def _polygon(pts):
    return '<polygon points="' + " ".join(f"{x:.6f},{y:.6f}" for x, y in pts) + '"/>'


def _path(pts, close=True):
    return ('<path d="M ' + " L ".join(f"{x:.6f} {y:.6f}" for x, y in pts)
            + (' Z"/>' if close else '"/>'))


def _gaps(c, closed=None):
    ns = c.nodes
    out = [math.hypot(ns[i].x - ns[i - 1].x, ns[i].y - ns[i - 1].y) for i in range(1, len(ns))]
    if c.closed if closed is None else closed:
        out.append(math.hypot(ns[0].x - ns[-1].x, ns[0].y - ns[-1].y))
    return out


def _merge_note(notes):
    return [n for n in notes if "within 0.01 mm" in n]


# ── The hairline rule ──────────────────────────────────────────────────────

@pytest.mark.parametrize("form", [_polygon, _path])
@pytest.mark.parametrize("step", [0.005, 0.009])
def test_an_outline_sampled_finer_than_the_hairline_imports_and_says_so(tmp_path, form, step):
    # Each segment was shorter than 0.01 mm, so each was dropped: the outline
    # came in as nothing, and the window blamed the file.
    pts = _ellipse(lambda: step)
    doc = _read(tmp_path, form(pts))
    assert len(doc.curves) == 1
    c = doc.curves[0]
    assert c.closed and c.kind == "line"
    gaps = _gaps(c)
    assert min(gaps) > svg_import._HAIRLINE_MM
    assert max(gaps) < 2 * svg_import._HAIRLINE_MM + 1e-9
    assert doc.width_mm == pytest.approx(10.0, abs=0.01)
    assert doc.height_mm == pytest.approx(8.0, abs=0.01)
    [note] = _merge_note(doc.notes)
    merged = int(re.match(r"(\d+) point", note).group(1))
    # the seam's own fold, at most a node or two, goes unsaid
    assert len(pts) - len(c.nodes) - 2 <= merged <= len(pts) - len(c.nodes)


def test_mixed_spacing_keeps_no_gap_wider_than_two_hairlines(tmp_path):
    # Per segment, three quarters of the nodes went and left gaps to 0.22 mm.
    rnd = random.Random(7)
    pts = _ellipse(lambda: rnd.uniform(0.004, 0.012))
    c = _read(tmp_path, _polygon(pts)).curves[0]
    gaps = _gaps(c)
    assert min(gaps) > svg_import._HAIRLINE_MM
    assert max(gaps) < 0.025


def test_a_spline_keeps_its_handles_through_a_cumulative_merge(tmp_path):
    # Three anchors 4 µm apart, then a real cubic: the first two merge into
    # the start, the cubic leaves from it with its own handle.
    d = "M 0 0 L 0.004 0 L 0.008 0 C 3 5 7 5 10 0"
    c = _read(tmp_path, f'<path d="{d}"/>').curves[0]
    assert c.kind == "spline" and len(c.nodes) == 2
    assert (c.nodes[0].x, c.nodes[0].y) == (0, 0)
    assert (c.nodes[0].cp_out.x, c.nodes[0].cp_out.y) == (3, 5)
    assert (c.nodes[1].cp_in.x, c.nodes[1].cp_in.y) == (7, 5)


def test_a_curve_no_larger_than_the_hairline_is_left_out_with_a_note(tmp_path):
    doc = _read(tmp_path, '<path d="M 1 1 L 1.004 1 L 1.004 1.004"/>')
    assert doc.curves == []
    assert any("no larger than 0.01 mm" in n for n in doc.notes)


def test_a_seam_and_repeated_points_merge_without_a_note(tmp_path):
    # The rule's first purpose: a converter's closing gap of a few microns,
    # and points written twice. Neither is worth a word.
    d = ("M 0 0 L 0 0 C 0 10 10 10 10 0 L 10 0 "
         "C 10 -10 0.004 -10 0.004 -0.002 Z")
    doc = _read(tmp_path, f'<path d="{d}"/><rect x="20" y="20" width="5" height="5"/>')
    c = doc.curves[0]
    assert c.closed and len(c.nodes) == 2 and c.nodes[0].cp_in is not None
    assert doc.notes == []


def test_the_hairline_is_measured_after_the_imports_scale(tmp_path):
    # Points 0.04 mm apart in the file, imported at a tenth of its size: 4 µm
    # apart, a node on its neighbor. The merge ran before the scale.
    pts = [(i * 0.04, 0.0) for i in range(251)]                # 10 mm, 0.04 mm steps
    path = _write(tmp_path, _path(pts, close=False))
    doc = read_svg(path, Layer.REF, "front")
    assert len(doc.curves[0].nodes) == 251 and not _merge_note(doc.notes)
    notes: list[str] = []
    [c] = place_curves(doc.curves, scale=0.1, center=(0.0, 0.0), notes=notes)
    assert min(_gaps(c)) > svg_import._HAIRLINE_MM
    # the open curve's ends stay where they were; a node inside gives way
    assert (c.nodes[0].x, c.nodes[-1].x) == pytest.approx((-0.5, 0.5), abs=1e-12)
    [note] = _merge_note(notes)
    assert f"{251 - len(c.nodes)} point(s)" in note and "at the chosen size" in note
    # import_svg knows its scale, so it says so too
    curves, notes = import_svg(path, Layer.REF, "front", scale=0.1)
    assert len(curves[0].nodes) == len(c.nodes) and _merge_note(notes)
    # and an enlargement merges nothing more
    big = place_curves(doc.curves, scale=10.0)
    assert len(big[0].nodes) == 251


def test_a_seam_that_a_reduction_closes_folds(tmp_path):
    # Ends 0.05 mm short of the start: a node of its own at full size, on the
    # start at a tenth.
    d = "M 0 0 L 10 0 L 10 10 L 0.05 0 Z"
    doc = _read(tmp_path, f'<path d="{d}"/>')
    assert len(doc.curves[0].nodes) == 4
    [c] = place_curves(doc.curves, scale=0.1)
    assert c.closed and len(c.nodes) == 3
    assert min(_gaps(c)) > svg_import._HAIRLINE_MM


# ── The aspect ratio ───────────────────────────────────────────────────────

_SQUARE = '<rect x="0" y="0" width="100" height="100"/>'


@pytest.mark.parametrize("par, size", [
    (None, (50.0, 50.0)),                       # xMidYMid meet, the default
    ("xMinYMin meet", (50.0, 50.0)),
    ("none", (100.0, 50.0)),
    ("xMidYMid slice", (100.0, 100.0)),
    ("defer xMaxYMax", (50.0, 50.0)),
])
def test_a_size_unlike_the_viewbox_follows_preserve_aspect_ratio(tmp_path, par, size):
    # The scale came from the width alone: 100 mm wide where a browser and
    # Inkscape draw it 50.
    attrs = 'width="100mm" height="50mm" viewBox="0 0 100 100"'
    if par is not None:
        attrs += f' preserveAspectRatio="{par}"'
    doc = _read(tmp_path, _SQUARE, attrs)
    assert doc.physical
    assert (doc.width_mm, doc.height_mm) == pytest.approx(size)


def test_a_circle_stretched_by_none_comes_in_as_an_ellipse(tmp_path):
    attrs = 'width="100mm" height="50mm" viewBox="0 0 100 100" preserveAspectRatio="none"'
    c = _read(tmp_path, '<circle cx="50" cy="50" r="20"/>', attrs).curves[0]
    assert c.kind == "spline" and c.closed
    bb = content_bbox([c])
    assert (bb[2] - bb[0], bb[3] - bb[1]) == pytest.approx((40.0, 20.0), abs=1e-3)
    meet = _read(tmp_path, '<circle cx="50" cy="50" r="20"/>',
                 'width="100mm" height="50mm" viewBox="0 0 100 100"').curves[0]
    assert meet.kind == "circle" and meet.radius == pytest.approx(10.0)


@pytest.mark.parametrize("par, box", [
    (None, (5.0, 0.0, 15.0, 10.0)),             # xMidYMid meet: centered across
    ("xMinYMin meet", (0.0, 0.0, 10.0, 10.0)),
    ("xMaxYMid", (10.0, 0.0, 20.0, 10.0)),
    ("xMidYMid slice", (0.0, -5.0, 20.0, 15.0)),
    ("none", (0.0, 0.0, 20.0, 10.0)),
])
def test_a_nested_svg_aligns_and_slices_as_it_says(tmp_path, par, box):
    # Only xMidYMid meet and none were read; every other alignment was centered.
    nested = ('<svg x="0" y="0" width="20" height="10" viewBox="0 0 10 10"'
              + (f' preserveAspectRatio="{par}"' if par else "")
              + '><rect x="0" y="0" width="10" height="10"/></svg>')
    doc = _read(tmp_path, nested, 'width="100mm" height="100mm" viewBox="0 0 100 100"')
    assert doc.bbox == pytest.approx(box)


def test_the_governing_side_decides_whether_the_size_is_physical(tmp_path):
    # meet takes the height's scale here, and the height is in px
    attrs = 'width="100mm" height="50px" viewBox="0 0 100 100"'
    doc = _read(tmp_path, _SQUARE, attrs)
    assert not doc.physical
    assert doc.width_mm == pytest.approx(50 * 25.4 / 96)


# ── A curve cap ────────────────────────────────────────────────────────────

def test_the_import_stops_at_the_curve_cap_with_a_note(tmp_path):
    n = svg_import._MAX_CURVES + 50
    d = " ".join(f"M {i % 200} {i // 200} h 0.5" for i in range(n))
    doc = _read(tmp_path, f'<path d="{d}"/><rect x="0" y="0" width="5" height="5"/>',
                'width="200mm" height="200mm" viewBox="0 0 200 200"')
    assert len(doc.curves) == svg_import._MAX_CURVES
    assert any(f"stopped at {svg_import._MAX_CURVES} curves" in n for n in doc.notes)


# ── Deep nesting ───────────────────────────────────────────────────────────

def test_groups_nested_thousands_deep_import(tmp_path):
    # A RecursionError, shown as "maximum recursion depth exceeded".
    depth = 5000
    body = ('<g transform="translate(0.001 0)">' * depth
            + '<rect x="0" y="0" width="10" height="5"/>' + "</g>" * depth
            + '<rect x="20" y="0" width="1" height="1"/>')
    doc = _read(tmp_path, body, 'width="100mm" height="100mm" viewBox="0 0 100 100"')
    assert len(doc.curves) == 2
    assert content_bbox([doc.curves[0]]) == pytest.approx((5.0, 0.0, 15.0, 5.0))
