"""
OMA / Vision Council DCS lens-trace interchange (TRCFMT format 1, ASCII).

The Data Communication Standard (DCS, colloquially "the OMA format") is the
ASCII record format spoken by frame tracers, lens edgers, and labs:

    LABEL=value;value;...          one record per line (CRLF or LF)

A lens trace is announced by a TRCFMT record and carried by R records:

    TRCFMT=1;400;E;R;F             format 1 (ASCII), 400 points, Equally
                                   spaced angles, side R (right lens / OD),
                                   F = frame trace
    R=2550;2548;...                radii in 1/100 mm, signed ASCII integers,
                                   conventionally 10 per line; point i sits at
                                   angle 360*i/n degrees CCW from the +x axis,
                                   measured from the boxing center

Frame-box records (HBOX, VBOX, DBL, FED, CRIB, ...) carry per-side values
separated by ';' in R;L order. Records this module doesn't understand are
preserved verbatim through a parse -> build round trip.

Coordinate conventions:
  * The OMA polar frame is y-UP (mathematical), point 0 at 3 o'clock, CCW.
  * GuildDraw scene coordinates are y-DOWN mm, so y is negated on import and
    export (same convention as the DXF exporter).
  * Negative / zero radii mark invalid tracer points and are skipped on
    import (their angles are skipped with them).

Only TRCFMT format 1 with E (equal) spacing is supported — the same baseline
as the eeng/lens_protocol reference implementation. Format 4 (packed binary)
raises a clear error.

Qt-free on purpose — everything here is unit-testable without a GUI.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..document import Curve, Layer, SplineNode
from ..fitting import fit_curve
from ..geometry import compute_catmull_handles, sample_curve

import re

_R_VALUE         = re.compile(r"[+-]?[0-9]+")   # an R record's field, 1/100 mm
_R_PER_LINE      = 10     # radii per R record when building (DCS convention)
_DEFAULT_NODES   = 32     # a trace this sparse keeps each point as a node
_TRACE_TOL_MM    = 0.02   # the import's largest miss of a traced point (mm)
_TRACE_FIT_TOL_MM = 0.015 # the fit's first tolerance: its own measure runs
                          # up to 0.008 mm under _worst_miss's
_TRACE_NOISE_MM  = 0.005  # noisier than this, a trace is smoothed before the fit
_MAX_TRACE_NODES = 256    # the fit stops adding nodes here
_MIN_TRACE_PTS   = 8      # fewer valid points than this is not a lens shape
_SAMPLES_PER_SEG = 32     # contour sampling density for curve_to_trace
_EXPORT_OUTLINE_TOL_MM = 0.001  # the bevel outline's chords, for points_to_trace:
                          # boxing's 0.01 put each export up to 0.01 mm inside,
                          # B -0.18 mm over ten round trips


# ---------------------------------------------------------------------------
# Job model
# ---------------------------------------------------------------------------

@dataclass
class OmaTrace:
    side:     str                  # "R" (OD) | "L" (OS)
    radii_mm: List[float] = field(default_factory=list)  # CCW from 0°, y-up
    npts:     Optional[int] = None # point count declared in TRCFMT (if any)
    ttype:    str = "F"            # trace type field (F=frame, P=pattern, L=lens)


#: How far past its lens's box a hole must land, read by the standard, for
#: the file to be taken for a GuildDraw export from before 2.3 (`place_drills`).
_DRILL_FAR_MM = 5.0
#: A hole's diameter when the file gives none: the standard leaves it to the
#: device (its drill's own), and 1.4 mm is the common mount's.
DEFAULT_DRILL_DIA_MM = 1.4


@dataclass
class OmaDrill:
    """One DRILLE feature, as DCS 3.14 §5.5.2 defines it. `eye` is R, L or B:
    B is "both", the data describing the RIGHT lens and mirrored by the
    device for the left. `ftype` is the reference specifier, C for Center
    Reference: x and y from the box center of that lens's own trace, x to
    the right as the front is seen and y UP, mm.

    Until 2.3 GuildDraw read and wrote the position from the midpoint
    between the two lenses, every hole tagged B (the 2.3 sweep): a lab's
    edger would have drilled each lens a lens-width off, and a mount's file
    came in with its holes heaped at the lens centers. `place_drills` reads
    both; the export writes the standard's."""
    x:     float
    y:     float
    dia:   float
    eye:   str = "B"               # R | L | B (both: right-lens data, mirrored)
    ftype: str = "C"               # the reference specifier (C, EN, ET, BN, BT…)
    raw:   Optional[List[str]] = None  # original fields, for faithful rebuild

    @property
    def is_slot(self) -> bool:
        """A slot or a rectangular region: end coordinates off the start, or
        feature type 2. GuildDraw's DRILL layer holds round holes only."""
        raw = self.raw or []
        if len(raw) > 8 and raw[8].strip() == "2":
            return True
        try:
            return (len(raw) > 6 and raw[5] != "" and raw[6] != ""
                    and (abs(float(raw[5]) - self.x) > 1e-6
                         or abs(float(raw[6]) - self.y) > 1e-6))
        except ValueError:
            return False


@dataclass
class DrillLayout:
    """Where a file's holes go on the canvas (`place_drills`)."""
    holes: List[Tuple[float, float, float]] = field(default_factory=list)  # x, y, dia; y down
    legacy: bool = False        # read as a GuildDraw export from before 2.3
    unread: int = 0             # edge- or box-referenced: not placed
    slots: int = 0              # slots and rectangles, placed as a hole at their start
    no_lens: int = 0            # for a lens the file has no trace of


def place_drills(drills: List[OmaDrill], centers: Dict[str, Tuple[float, float]],
                 outlines: Optional[Dict[str, list]] = None) -> DrillLayout:
    """The scene positions of a file's DRILLE holes (y down), given where
    each traced lens's box center was placed (*centers*, by side).

    A hole is placed from its own lens's center; a B record lands on both
    lenses, mirrored on the left (DCS 3.14 §5.5.2.1–3). A GuildDraw export
    from before 2.3 has every hole tagged B and measured from the midpoint
    between the lenses instead: it is told apart by where the holes fall
    (*outlines*, each placed lens as a closed point list), since the
    standard's reading puts such a file's temple-side holes off the lens,
    and is read the old way."""
    out = DrillLayout()
    placed: list = []           # (side, x, y, dia)
    for d in drills:
        if not d.ftype.upper().startswith("C") and d.ftype != "":
            out.unread += 1
            continue
        sides = []
        if d.eye in ("R", "B"):
            sides.append(("R", 1.0))
        if d.eye in ("L", "B"):
            sides.append(("L", -1.0 if d.eye == "B" else 1.0))
        hit = False
        for side, sx in sides:
            if side in centers:
                cx, cy = centers[side]
                placed.append((side, cx + sx * d.x, cy - d.y, d.dia))
                hit = True
        if not hit:
            out.no_lens += 1
            continue
        out.slots += d.is_slot

    # The old way's mark: every hole tagged B from the frame's center, so
    # read by the standard a temple-side hole lands a lens-width off its
    # lens (30 mm past its box, where a mount's edge notch is a millimeter
    # or two), while read from the frame's center every hole is in a lens.
    if (len(centers) == 2 and outlines and len(outlines) == 2 and drills
            and all(d.eye == "B" and d.ftype.upper() in ("C", "") for d in drills)):
        from shapely.geometry import Point, Polygon
        polys = {}
        for side, pts in outlines.items():
            poly = Polygon(pts) if len(pts) >= 3 else None
            if poly is not None and not poly.is_valid:
                poly = poly.buffer(0)
            if poly is None or poly.is_empty:
                polys = {}
                break
            polys[side] = poly
        far_off = False
        for side, x, y, _ in placed:
            if side in polys:
                x0, y0, x1, y1 = polys[side].bounds
                far_off |= (x < x0 - _DRILL_FAR_MM or x > x1 + _DRILL_FAR_MM
                            or y < y0 - _DRILL_FAR_MM or y > y1 + _DRILL_FAR_MM)
        if polys and far_off:
            ox = 0.5 * (centers["R"][0] + centers["L"][0])
            oy = 0.5 * (centers["R"][1] + centers["L"][1])
            frame = [(ox + d.x, oy - d.y, d.dia) for d in drills]
            grown = [poly.buffer(1.0) for poly in polys.values()]
            if all(any(g.contains(Point(x, y)) for g in grown) for x, y, _ in frame):
                return DrillLayout(holes=frame, legacy=True,
                                   slots=sum(d.is_slot for d in drills))
    out.holes = [(x, y, dia) for _, x, y, dia in placed]
    return out


@dataclass
class OmaJob:
    """All records of a DCS file: traces decoded, everything else preserved."""
    records: List[Tuple[str, str]]  = field(default_factory=list)  # (LABEL, raw value)
    traces:  Dict[str, OmaTrace]    = field(default_factory=dict)  # side -> trace
    drills:  List[OmaDrill]         = field(default_factory=list)  # DRILLE features

    def values(self, label: str) -> Optional[List[str]]:
        """Fields of the first record with this label, split on ';'."""
        label = label.upper()
        for lab, val in self.records:
            if lab == label:
                return [v.strip() for v in val.split(";")]
        return None

    def floats(self, label: str) -> Optional[List[float]]:
        """Numeric fields of the first record with this label (None if absent
        or nothing parses)."""
        vals = self.values(label)
        if vals is None:
            return None
        out: List[float] = []
        for v in vals:
            try:
                f = float(v)
            except ValueError:
                continue
            if math.isfinite(f):         # "nan" and "inf" parse as floats
                out.append(f)
        return out or None

    def set_record(self, label: str, value: str) -> None:
        """Replace the first record with this label, or append a new one."""
        label = label.upper()
        for i, (lab, _) in enumerate(self.records):
            if lab == label:
                self.records[i] = (label, value)
                return
        self.records.append((label, value))


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_oma(text: str) -> OmaJob:
    """Parse a DCS/OMA file. Raises ValueError with a specific message on
    anything malformed or unsupported; unknown records are kept in order."""
    job = OmaJob()
    cur: Optional[OmaTrace] = None

    # A byte-order mark an editor put first (read as ASCII it is three
    # replacement characters), and the NUL or Ctrl-Z padding some DOS-era
    # hosts end a file with: neither is a record, and each refused the file.
    text = text.lstrip("\ufeff\ufffd")
    for raw in text.splitlines():
        line = raw.strip().strip("\x00\x1a").strip()
        if not line:
            continue
        if "=" not in line:
            raise ValueError(f"Malformed OMA record (no '='): {line!r}")
        label, _, value = line.partition("=")
        label = label.strip().upper()
        value = value.strip()

        if label == "TRCFMT":
            vals = [v.strip() for v in value.split(";")]
            try:
                fmt = int(vals[0])
            except (ValueError, IndexError):
                raise ValueError(
                    f"TRCFMT has no parseable format number: {value!r}"
                ) from None
            if fmt == 0:
                # The standard's "no trace available": a record, not a trace
                # (it read "format 0 is not supported, ask for format 1").
                cur = None
                job.records.append((label, value))
                continue
            if fmt != 1:
                raise ValueError(
                    f"TRCFMT format {fmt} is not supported — only format 1 "
                    "(ASCII radii) is. Ask the tracer/lab for a format-1 file."
                )
            npts = None
            if len(vals) > 1 and vals[1]:
                try:
                    npts = int(vals[1])
                except ValueError:
                    npts = None    # request files use '?' — tolerate
            spacing = vals[2].upper() if len(vals) > 2 and vals[2] else "E"
            if spacing != "E":
                raise ValueError(
                    f"Only equally-spaced (E) traces are supported, got {spacing!r}."
                )
            side = vals[3].upper() if len(vals) > 3 and vals[3] else "R"
            if side not in ("R", "L"):
                raise ValueError(f"Unknown trace side {side!r} (expected R or L).")
            ttype = vals[4].upper() if len(vals) > 4 and vals[4] else "F"
            cur = OmaTrace(side=side, npts=npts, ttype=ttype)
            job.traces[side] = cur

        elif label == "R":
            if cur is None:
                raise ValueError("R record found before any TRCFMT record.")
            for v in value.split(";"):
                v = v.strip()
                if not v:
                    continue
                # A plain signed decimal integer only: int() also takes
                # "1_000" and non-ASCII digits (the 2.3 hunt).
                if not _R_VALUE.fullmatch(v):
                    raise ValueError(f"Bad radius value in R record: {v!r}")
                try:
                    cur.radii_mm.append(int(v) / 100.0)
                except ValueError:
                    raise ValueError(
                        f"Bad radius value in R record: {v!r}"
                    ) from None

        elif label == "DRILLE":
            # A feature has at least eye;reference;x;y (the standard's own
            # minimal example, which was dropped unsaid); the diameter may be
            # empty, absent or "?", the device's to choose. A bare "DRILLE=0"
            # (no holes) or "R;0" is preserved verbatim instead.
            vals = [v.strip() for v in value.split(";")]
            if len(vals) >= 4:
                try:
                    x, y = float(vals[2]), float(vals[3])
                    dia_txt = vals[4] if len(vals) > 4 else ""
                    dia = DEFAULT_DRILL_DIA_MM if dia_txt in ("", "?") else float(dia_txt)
                    if not all(math.isfinite(v) for v in (x, y, dia)):
                        raise ValueError("a value is not a finite number")
                    job.drills.append(OmaDrill(
                        x=x, y=y, dia=dia,
                        eye=(vals[0] or "B").upper(), ftype=vals[1] or "C", raw=vals))
                except ValueError as e:
                    raise ValueError(f"Bad DRILLE record {value!r}: {e}") from None
            else:
                job.records.append((label, value))

        else:
            job.records.append((label, value))

    for side, tr in list(job.traces.items()):
        if tr.npts and len(tr.radii_mm) != tr.npts:
            raise ValueError(
                f"Side {side}: TRCFMT declares {tr.npts} points but "
                f"{len(tr.radii_mm)} radii were found."
            )
        if not tr.radii_mm:
            if tr.npts is None:
                # A lab REQUEST record (TRCFMT=1;?;E;R;F) announces a trace
                # that is not in the file. Tolerated: drop it, keep the rest.
                del job.traces[side]
                continue
            raise ValueError(f"Side {side}: TRCFMT record has no R data.")

    return job


_TRACE_KINDS = {"F": "a frame trace", "P": "a pattern trace", "D": "a demo lens trace"}
_FRAME_KINDS = {1: "plastic", 2: "metal", 3: "rimless"}


def trace_origin(job: OmaJob) -> str:
    """What the file declares its trace to be, in words for the import
    dialog: TRCFMT's type (F frame, P pattern, D demo lens) and FTYP's frame
    type. Empty when it declares neither. GuildDraw draws no conclusion from
    it: an eyewire's bevel, a demo lens and a drill-mount shape each trace
    differently, and whether the shape wants shrinking is the user's call."""
    kinds = sorted({tr.ttype for tr in job.traces.values()})
    if len(kinds) == 1:
        k = kinds[0]
        what = f"{_TRACE_KINDS[k]} ({k})" if k in _TRACE_KINDS else f"a trace of type {k}"
    elif kinds:
        what = "traces of types " + " and ".join(kinds)
    else:
        what = ""
    ftyp = job.floats("FTYP")
    n = int(ftyp[0]) if ftyp and float(ftyp[0]).is_integer() else 0
    if not n:                       # absent, fractional, or 0 = not stated
        return what
    if not what:
        return f"frame type {n} (FTYP)"
    if n in _FRAME_KINDS:
        return f"{what} of a {_FRAME_KINDS[n]} frame (FTYP {n})"
    return f"{what}, frame type {n} (FTYP)"


# ---------------------------------------------------------------------------
# Trace -> Curve
# ---------------------------------------------------------------------------

def trace_to_curve(radii_mm: List[float],
                   layer: Layer = Layer.LENS,
                   target_nodes: int = _DEFAULT_NODES) -> Curve:
    """Equal-angle polar trace -> closed spline in scene coords.

    Point i sits at angle 360*i/n CCW (y-up OMA frame); scene y is negated.
    Non-positive radii (invalid tracer points) are skipped. No traced point
    lies over _TRACE_TOL_MM from the result: a fixed 32 nodes put a
    tight-cornered rectangle 0.2 mm off, and a re-export to the lab carried
    the error. The boxing center of the trace lands at the scene origin
    (callers translate to place it).

    A trace of more than target_nodes points is fitted by the cubic engine
    (2.0.1), which brought a practice's 412 tracer files in at 20 to 54
    nodes a lens (median 35). The Catmull-Rom decimation it replaced needed
    72 to 256 for the same 0.02 mm, too many to edit by hand; it remains the
    fallback, and a sparser trace keeps each point as a node.

    A trace noisier than its 0.01 mm rounding is smoothed first (2.0.1): no
    curve comes within 0.02 mm of every noisy point, so the fit took one node
    a point, wiggling at each, and the bevel shrink of a 2000-point trace
    folded at every wiggle and failed after 15 s.
    """
    n = len(radii_mm)
    if n < _MIN_TRACE_PTS:
        raise ValueError(f"Trace has only {n} points — not a usable lens shape.")
    noise = trace_noise_mm(radii_mm)
    if noise > _TRACE_NOISE_MM:
        radii_mm = _smoothed(radii_mm, noise)

    pts: List[Tuple[float, float]] = []
    for i, r in enumerate(radii_mm):
        if r is None or r <= 0:
            continue
        a = 2.0 * math.pi * i / n
        pts.append((r * math.cos(a), -r * math.sin(a)))   # scene y-down
    if len(pts) < _MIN_TRACE_PTS:
        raise ValueError(
            f"Trace has only {len(pts)} valid (positive-radius) points."
        )

    if len(pts) > target_nodes:
        fitted = _fitted_trace(pts, layer)
        if fitted is not None:
            return fitted
    most = min(len(pts), _MAX_TRACE_NODES)
    k = min(target_nodes, most)
    while True:
        idxs = sorted({int(round(j * len(pts) / k)) % len(pts) for j in range(k)})
        nodes = [SplineNode(x=pts[i][0], y=pts[i][1]) for i in idxs]
        compute_catmull_handles(nodes, closed=True)
        curve = Curve(kind="spline", layer=layer, nodes=nodes, closed=True)
        if k >= most or _worst_miss(curve, pts) <= _TRACE_TOL_MM:
            return curve
        k = min(most, k + max(8, k // 2))


def _fitted_trace(pts: List[Tuple[float, float]], layer: Layer) -> Optional[Curve]:
    """The traced points fitted by the cubic engine, the tolerance tightened
    until no point lies over _TRACE_TOL_MM from the curve; None if three
    tries miss or the fit needs over _MAX_TRACE_NODES nodes. A fit that
    doubles back in angle is a miss too: the deviation cannot see a loop,
    and the lens would not export (11 of a practice's 824 traces, before
    the fitter refused crossed handles)."""
    tol = _TRACE_FIT_TOL_MM
    for _ in range(3):
        curve = fit_curve(pts, tol_mm=tol, closed=True, layer=layer).curve
        if len(curve.nodes) > _MAX_TRACE_NODES:
            return None
        if _worst_miss(curve, pts) <= _TRACE_TOL_MM:
            try:
                curve_to_trace(curve, n=_MIN_TRACE_PTS)
                return curve
            except ValueError:
                pass
        tol *= 0.7
    return None


def trace_noise_mm(radii_mm: List[float]) -> float:
    """The tracer's noise in a trace, from the third differences of
    neighboring radii (their median, so a corner does not count; a second
    difference still carries a tight corner's curvature). A clean trace shows
    only its 0.01 mm rounding: 0.0033 mm for every lens in the library."""
    import statistics

    n = len(radii_mm)
    d3 = []
    for i in range(n):
        w = [radii_mm[(i + k) % n] for k in (-1, 0, 1, 2)]
        if all(r is not None and r > 0 for r in w):
            d3.append(-w[0] + 3.0 * w[1] - 3.0 * w[2] + w[3])
    if len(d3) < _MIN_TRACE_PTS:
        return 0.0
    return statistics.median(abs(v) for v in d3) / 0.6745 / math.sqrt(20.0)


def _smoothed(radii_mm: List[float], noise: float) -> List[float]:
    """*radii_mm* smoothed down to the rounding's noise by a quadratic
    Savitzky–Golay filter around the trace, which keeps a corner's curvature
    where a plain average would round it; the window is held to a fortieth of
    the trace. A window over an invalid radius leaves its point as it was."""
    n = len(radii_mm)

    def gain(m):                  # the filter's noise variance factor
        return 3.0 * (3 * m * m + 3 * m - 1) / ((2 * m - 1) * (2 * m + 1) * (2 * m + 3))

    m = 2
    while noise * math.sqrt(gain(m)) > 0.003 and 2 * (m + 1) + 1 <= max(5, n // 40):
        m += 1
    norm = (2 * m - 1) * (2 * m + 1) * (2 * m + 3)
    c = [3.0 * (3 * m * m + 3 * m - 1 - 5 * k * k) / norm for k in range(-m, m + 1)]
    out = list(radii_mm)
    for i in range(n):
        window = [radii_mm[(i + k) % n] for k in range(-m, m + 1)]
        if all(r is not None and r > 0 for r in window):
            out[i] = sum(w * r for w, r in zip(c, window, strict=True))
    return out


def _worst_miss(curve: Curve, pts: list) -> float:
    """The largest distance from a traced point to *curve*."""
    import shapely
    from shapely.geometry import LineString
    line = LineString([(x, y) for x, y, _t in sample_curve(curve, 24)])
    return float(shapely.distance(shapely.points(pts), line).max())


# ---------------------------------------------------------------------------
# Curve -> trace
# ---------------------------------------------------------------------------

def boxing_center(curve: Curve) -> Tuple[float, float]:
    """Bbox center of the sampled contour (scene coords) — the radial origin
    used by curve_to_trace."""
    pts = sample_curve(curve, n_per_seg=_SAMPLES_PER_SEG)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0


def curve_to_trace(curve: Curve, n: int = 400) -> List[float]:
    """Sample a closed contour at n equal angles about its boxing center.

    Returns radii in mm, point i at angle 360*i/n CCW in the y-up OMA frame.
    Raises ValueError if the contour is not star-shaped about its boxing
    center — radial sampling cannot represent such a shape.
    """
    samples = sample_curve(curve, n_per_seg=_SAMPLES_PER_SEG)
    return points_to_trace([(x, y) for x, y, _t in samples], n=n)


def points_to_trace(points: List[Tuple[float, float]], n: int = 400) -> List[float]:
    """Radially resample a closed contour polyline (scene coords, y-down) at
    n equal angles about its bbox center — the core of curve_to_trace, split
    out so a *finished* (bevel-offset) outline can be traced directly.

    Same contract as curve_to_trace: radii in mm, point i at angle 360*i/n CCW
    in the y-up OMA frame; raises ValueError on non-star-shaped contours.
    """
    if len(points) < 3:
        raise ValueError("Contour has too few points to trace.")
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0

    # Scene (y-down) -> OMA frame (y-up) about the boxing center, deduped.
    pp: List[Tuple[float, float]] = []
    for x, y in points:
        dx, dy = x - cx, -(y - cy)
        if pp and abs(dx - pp[-1][0]) < 1e-9 and abs(dy - pp[-1][1]) < 1e-9:
            continue
        pp.append((dx, dy))
    if len(pp) > 1 and abs(pp[0][0] - pp[-1][0]) < 1e-9 \
            and abs(pp[0][1] - pp[-1][1]) < 1e-9:
        pp.pop()   # closing sample duplicates the first point

    def unwrap(points):
        """(unwrapped theta, r) per point + the wrap-around closing step."""
        thetas: List[float] = []
        rs:     List[float] = []
        prev_raw = th = 0.0
        for dx, dy in points:
            r = math.hypot(dx, dy)
            if r < 1e-9:
                raise ValueError(
                    "Contour passes through its boxing center — cannot trace."
                )
            a = math.atan2(dy, dx)
            if not thetas:
                th = a
            else:
                th += (a - prev_raw + math.pi) % (2.0 * math.pi) - math.pi
            prev_raw = a
            thetas.append(th)
            rs.append(r)
        a0 = math.atan2(points[0][1], points[0][0])
        d_close = (a0 - prev_raw + math.pi) % (2.0 * math.pi) - math.pi
        return thetas, rs, d_close

    thetas, rs, d_close = unwrap(pp)
    total = thetas[-1] + d_close - thetas[0]
    if abs(abs(total) - 2.0 * math.pi) > 0.1:
        raise ValueError(
            "Contour does not wind once around its boxing center — it is not "
            "star-shaped and cannot be represented as an OMA radial trace."
        )
    if total < 0:               # normalize to CCW in the OMA frame
        pp.reverse()
        thetas, rs, d_close = unwrap(pp)

    _BACK_TOL = 1e-6   # radians — tolerate sampling jitter only
    steps = [thetas[i + 1] - thetas[i] for i in range(len(thetas) - 1)]
    steps.append(d_close)
    if min(steps) < -_BACK_TOL:
        raise ValueError(
            "Contour doubles back in angle about its boxing center — it is "
            "not star-shaped and cannot be represented as an OMA radial trace."
        )

    # Close the (theta, r) loop and resample at n equal angles, each ray
    # meeting its segment exactly. A radius interpolated linearly in angle
    # bows a straight segment outward by r·Δθ²/8: 0.09 mm on a bevel-grown
    # lens, whose outline 2.0.1 flattens into chords up to 4 mm long.
    pp.append(pp[0])
    thetas.append(thetas[0] + 2.0 * math.pi)
    rs.append(rs[0])
    th0 = thetas[0]
    radii: List[float] = []
    for k in range(n):
        a = th0 + ((2.0 * math.pi * k / n - th0) % (2.0 * math.pi))
        j = bisect_right(thetas, a)
        j = max(1, min(j, len(thetas) - 1))
        t0, t1 = thetas[j - 1], thetas[j]
        f = 0.0 if t1 <= t0 else (a - t0) / (t1 - t0)
        r = rs[j - 1] + f * (rs[j] - rs[j - 1])
        (x0, y0), (x1, y1) = pp[j - 1], pp[j]
        dx, dy = x1 - x0, y1 - y0
        den = math.cos(a) * dy - math.sin(a) * dx    # 0: the segment is radial
        if abs(den) > 1e-12:
            s = (x0 * dy - y0 * dx) / den
            if 0.0 < s <= max(rs[j - 1], rs[j]) + 1e-9:
                r = s
        radii.append(r)
    return radii


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def _drill_line(d: OmaDrill) -> str:
    """DRILLE record for one hole. Rebuilds the original fields verbatim when
    available (faithful round trip); otherwise emits a simple round through-hole:
    eye;type;x;y;dia;x;y;0;1;F (point 2 = point 1 for a round hole)."""
    if d.raw is not None:
        return "DRILLE=" + ";".join(d.raw)
    return (f"DRILLE={d.eye};{d.ftype};{d.x:.2f};{d.y:.2f};{d.dia:.2f};"
            f"{d.x:.2f};{d.y:.2f};0;1;F")


def build_oma(job: OmaJob) -> str:
    """Serialize an OmaJob to DCS text (CRLF, TRCFMT format 1, R records in
    chunks of 10). Non-trace records are emitted first, in their stored order;
    traces follow in R, L order; DRILLE drill features come last."""
    lines = [f"{label}={value}" for label, value in job.records]
    for side in ("R", "L"):
        tr = job.traces.get(side)
        if tr is None:
            continue
        ints = [str(int(round(r * 100.0))) for r in tr.radii_mm]
        lines.append(f"TRCFMT=1;{len(ints)};E;{side};{tr.ttype}")
        for i in range(0, len(ints), _R_PER_LINE):
            lines.append("R=" + ";".join(ints[i:i + _R_PER_LINE]))
    for d in job.drills:
        lines.append(_drill_line(d))
    return "\r\n".join(lines) + "\r\n"
