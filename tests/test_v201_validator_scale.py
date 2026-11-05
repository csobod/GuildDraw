"""The readiness check on a large drawing (BUILDPLAN, "The offset's cousins",
item 1): it runs on the GUI thread after every edit, and it compared every
piece, curve and contour of a layer with every other. An outline exploded
into 899 pieces with one deleted took 297 s a check, 2000 small closed
curves on OUTLINE 21 s, 1000 SCULPT lines 1.3 s. Each test counts the work
one rule does, not the time it takes, so a slow computer passes it too."""
import math
import time

import pytest
from shapely.geometry.base import BaseGeometry

import framedraft.export.validate as V
from framedraft.document import Layer
from framedraft.export.validate import validate
from helpers import circle, line, spline


def _ring(n, rx=60.0, ry=25.0, layer=Layer.OUTLINE):
    """An outline exploded into *n* straight pieces, end to end."""
    pts = [(rx * math.cos(2 * math.pi * i / n), ry * math.sin(2 * math.pi * i / n))
           for i in range(n)]
    return [line([pts[i], pts[(i + 1) % n]], layer=layer) for i in range(n)]


def _blob(x, y, r, layer=Layer.OUTLINE):
    return spline([(x + r * math.cos(math.pi * k / 4), y + r * math.sin(math.pi * k / 4))
                   for k in range(8)], closed=True, layer=layer)


def _blobs(n, layer=Layer.OUTLINE, pitch=1.0, r=0.3, grow=0.0):
    side = math.ceil(math.sqrt(n))
    return [_blob((i % side) * pitch, (i // side) * pitch, r + grow * i, layer)
            for i in range(n)]


def _strokes(n, layer=Layer.SCULPT):
    """Short lines on a grid right of the axis, as a DXF of hatch or section
    lines brings in."""
    return [line([(5 + (i % 20) * 2.0, -15 + (i // 20) * 1.0),
                  (6.3 + (i % 20) * 2.0, -14.6 + (i // 20) * 1.0)], layer=layer)
            for i in range(n)]


def _front():
    pts = [(70 * math.cos(2 * math.pi * i / 40), 25 * math.sin(2 * math.pi * i / 40))
           for i in range(40)]
    return [spline(pts, closed=True), circle(-30, 0, 18), circle(30, 0, 18)]


class _Count:
    """Wraps a function and counts its calls."""
    def __init__(self, fn):
        self.fn, self.n = fn, 0

    def __call__(self, *args, **kwargs):
        self.n += 1
        return self.fn(*args, **kwargs)


class _CountingMath:
    """The math module, with math.hypot counted: each end measured against
    another."""
    def __init__(self):
        self.hypot = _Count(math.hypot)

    def __getattr__(self, name):
        return getattr(math, name)


# ── Pieces that meet end to end (_closed_chains) ──────────────────────────

def test_an_exploded_outline_with_a_gap_measures_each_end_a_few_times(monkeypatch):
    # Every piece started a walk to the gap, and each step measured the tip
    # against every end: 0.9 s at 179 pieces, 297 s at 899.
    pieces = _ring(150)
    del pieces[75]
    m = _CountingMath()
    monkeypatch.setattr(V, "math", m)
    assert V._closed_chains(pieces) == []
    assert m.hypot.n < 5 * len(pieces)        # 714 249 before


def test_an_exploded_outline_closes_into_one_ring_in_order(monkeypatch):
    pieces = _ring(150)
    for p in pieces[::3]:
        p.nodes.reverse()                     # pieces drawn either way
    shuffled = pieces[1::2] + pieces[::2]
    m = _CountingMath()
    monkeypatch.setattr(V, "math", m)
    chains = V._closed_chains(shuffled)
    assert m.hypot.n < 5 * len(pieces)
    assert len(chains) == 1 and len(chains[0]) == 150
    start = pieces.index(shuffled[0])
    order = [pieces.index(c) for c in chains[0]]
    step = order[1] - order[0]
    assert order == [(start + step * k) % 150 for k in range(150)]


def test_a_ring_with_a_spur_still_closes():
    # The walk goes to the lowest-numbered piece at a fork, as it always has;
    # a spur that ends nowhere is no ring.
    ring = _ring(40)
    spur = line([(60, 0), (80, 0)], layer=Layer.OUTLINE)
    chains = V._closed_chains([spur] + ring)
    assert len(chains) == 1 and set(map(id, chains[0])) == set(map(id, ring))


def test_a_check_on_an_exploded_outline_with_a_gap_names_each_piece():
    pieces = _ring(300)
    del pieces[100]
    errors, _ = validate(_front()[1:] + pieces, True)
    assert sum("OUTLINE contour is not closed" in e for e in errors) == 299


# ── Curves that lie one on another (_copy_checks) ─────────────────────────

def test_copies_are_sought_only_among_curves_of_the_same_size_and_place(monkeypatch):
    # Every SCULPT line was compared with every other: 1.3 s an edit at 1000.
    strokes = _strokes(400)
    copies = [line([(n.x, n.y) for n in reversed(s.nodes)], layer=Layer.SCULPT)
              for s in strokes[::100]]
    seen = _Count(V._traces_coincide)
    monkeypatch.setattr(V, "_traces_coincide", seen)
    errors, _ = validate(_front() + strokes + copies, False)
    assert errors == ["4 SCULPT curves lie on top of another SCULPT curve, and "
                      "GuildModel reads each: delete the copies."]
    assert seen.n < len(strokes) // 4          # 80 405 pairs before


# ── The Ghost's twins (_ghost_checks) ─────────────────────────────────────

def test_a_twin_is_compared_only_with_the_curves_within_its_reach(monkeypatch):
    strokes = _strokes(400)
    meets = _Count(V._meet)
    monkeypatch.setattr(V, "_meet", meets)
    errors, _ = validate(_front() + strokes, True)
    assert any(e.startswith("400 SCULPT curves have a twin") for e in errors)
    assert meets.n < 3 * len(strokes)          # 160 403 before


# ── OUTLINE contours inside one another (_outline_bodies) ─────────────────

@pytest.fixture()
def shapely_calls(monkeypatch):
    """Counts of the area and containment tests shapely is asked for."""
    calls = {"area": 0, "contains": 0, "intersection": 0}
    area, contains, intersection = (BaseGeometry.area, BaseGeometry.contains,
                                    BaseGeometry.intersection)

    def counted_area(self):
        calls["area"] += 1
        return area.fget(self)

    def counted(name, fn):
        def wrapper(self, *args, **kwargs):
            calls[name] += 1
            return fn(self, *args, **kwargs)
        return wrapper

    monkeypatch.setattr(BaseGeometry, "area", property(counted_area))
    monkeypatch.setattr(BaseGeometry, "contains", counted("contains", contains))
    monkeypatch.setattr(BaseGeometry, "intersection",
                        counted("intersection", intersection))
    return calls


def test_outline_contours_are_tested_only_where_their_bounds_meet(shapely_calls):
    # Each contour was tested against every other, its area recomputed each
    # time: 2000 small closed curves on OUTLINE took 21 s a check.
    polys = V._area_polys(_blobs(600, grow=1e-4))
    shapely_calls.update(area=0, contains=0)
    bodies, holes, strays = V._outline_bodies(polys)
    assert len(bodies) == 1 and bodies[0] is polys[-1]
    assert holes == [] and len(strays) == 599
    assert shapely_calls["contains"] < 10      # 180 299 before
    assert shapely_calls["area"] < 2 * len(polys)


def test_openings_inside_a_profile_are_still_found(shapely_calls):
    profile = spline([(-5, -5), (40, -5), (40, 40), (-5, 40)], closed=True)
    polys = V._area_polys([profile] + _blobs(400, grow=1e-4))
    bodies, holes, strays = V._outline_bodies(polys)
    assert bodies == [polys[0]] and len(holes) == 400 and strays == []


# ── INLAY seats (_inlay_checks) ───────────────────────────────────────────

def test_seats_are_tested_only_against_what_they_can_meet(shapely_calls):
    seats = [circle(-9 + (i % 10) * 2.0, -20 + (i // 10) * 2.0, 0.8, layer=Layer.INLAY)
             for i in range(120)]           # in the bridge, clear of the lenses
    errors, _ = validate(_front() + seats, False)
    assert not any("INLAY" in e for e in errors)
    # one test against the body for each seat, a few more where a seat
    # nears a lens
    assert shapely_calls["intersection"] < 2 * len(seats)   # 7504 before


def test_overlapping_seats_are_still_named_in_order():
    seats = [circle(-8 + i * 1.5, -10, 1.0, layer=Layer.INLAY) for i in range(6)]
    errors, _ = validate(_front() + seats, False)
    pairs = [e for e in errors if "overlap without nesting" in e]
    assert pairs == [f"INLAY {i} and INLAY {i + 1} overlap without nesting; nest "
                     "one inside the other for a step, or move them apart."
                     for i in range(1, 6)]


# ── One check on a whole drawing ──────────────────────────────────────────

def test_two_thousand_small_closed_outline_curves_check_in_good_time():
    # 21 s before; the aim is half a second, and the bound is ten times that
    # for a slow computer.
    curves = _blobs(2000)
    start = time.perf_counter()
    validate(curves, True)
    assert time.perf_counter() - start < 5.0
