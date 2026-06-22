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
                                   measured from the boxing centre

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
from ..geometry import compute_catmull_handles, sample_curve

_R_PER_LINE      = 10     # radii per R record when building (DCS convention)
_DEFAULT_NODES   = 32     # decimation target — hand-editable node count
_MIN_TRACE_PTS   = 8      # fewer valid points than this is not a lens shape
_SAMPLES_PER_SEG = 32     # contour sampling density for curve_to_trace


# ---------------------------------------------------------------------------
# Job model
# ---------------------------------------------------------------------------

@dataclass
class OmaTrace:
    side:     str                  # "R" (OD) | "L" (OS)
    radii_mm: List[float] = field(default_factory=list)  # CCW from 0°, y-up
    npts:     Optional[int] = None # point count declared in TRCFMT (if any)
    ttype:    str = "F"            # trace type field (F=frame, P=pattern, L=lens)


@dataclass
class OmaDrill:
    """One DRILLE drill-hole feature. Position is mm from the binocular frame
    centre (origin between the lenses), y-UP (OMA convention)."""
    x:     float
    y:     float
    dia:   float
    eye:   str = "B"               # B=binocular | R | L
    ftype: str = "C"              # feature type (C = simple round hole)
    raw:   Optional[List[str]] = None  # original fields, for faithful rebuild


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
                out.append(float(v))
            except ValueError:
                continue
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

    for raw in text.splitlines():
        line = raw.strip()
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
                try:
                    cur.radii_mm.append(int(v) / 100.0)
                except ValueError:
                    raise ValueError(
                        f"Bad radius value in R record: {v!r}"
                    ) from None

        elif label == "DRILLE":
            # A populated DRILLE has >=5 fields (eye;type;x;y;dia;...). A bare
            # count like "DRILLE=0" (no holes) is preserved verbatim instead.
            vals = [v.strip() for v in value.split(";")]
            if len(vals) >= 5:
                try:
                    job.drills.append(OmaDrill(
                        x=float(vals[2]), y=float(vals[3]), dia=float(vals[4]),
                        eye=vals[0] or "B", ftype=vals[1] or "C", raw=vals))
                except ValueError as e:
                    raise ValueError(f"Bad DRILLE record {value!r}: {e}") from None
            else:
                job.records.append((label, value))

        else:
            job.records.append((label, value))

    for side, tr in job.traces.items():
        if tr.npts and len(tr.radii_mm) != tr.npts:
            raise ValueError(
                f"Side {side}: TRCFMT declares {tr.npts} points but "
                f"{len(tr.radii_mm)} radii were found."
            )
        if not tr.radii_mm:
            raise ValueError(f"Side {side}: TRCFMT record has no R data.")

    return job


# ---------------------------------------------------------------------------
# Trace -> Curve
# ---------------------------------------------------------------------------

def trace_to_curve(radii_mm: List[float],
                   layer: Layer = Layer.LENS,
                   target_nodes: int = _DEFAULT_NODES) -> Curve:
    """Equal-angle polar trace -> closed Catmull-Rom spline in scene coords.

    Point i sits at angle 360*i/n CCW (y-up OMA frame); scene y is negated.
    Non-positive radii (invalid tracer points) are skipped. The result is
    decimated to ~target_nodes so it stays hand-editable; the boxing centre
    of the trace lands at the scene origin (callers translate to place it).
    """
    n = len(radii_mm)
    if n < _MIN_TRACE_PTS:
        raise ValueError(f"Trace has only {n} points — not a usable lens shape.")

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

    k = min(target_nodes, len(pts))
    idxs = sorted({int(round(j * len(pts) / k)) % len(pts) for j in range(k)})
    nodes = [SplineNode(x=pts[i][0], y=pts[i][1]) for i in idxs]
    compute_catmull_handles(nodes, closed=True)
    return Curve(kind="spline", layer=layer, nodes=nodes, closed=True)


# ---------------------------------------------------------------------------
# Curve -> trace
# ---------------------------------------------------------------------------

def boxing_center(curve: Curve) -> Tuple[float, float]:
    """Bbox centre of the sampled contour (scene coords) — the radial origin
    used by curve_to_trace."""
    pts = sample_curve(curve, n_per_seg=_SAMPLES_PER_SEG)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0


def curve_to_trace(curve: Curve, n: int = 400) -> List[float]:
    """Sample a closed contour at n equal angles about its boxing centre.

    Returns radii in mm, point i at angle 360*i/n CCW in the y-up OMA frame.
    Raises ValueError if the contour is not star-shaped about its boxing
    centre — radial sampling cannot represent such a shape.
    """
    samples = sample_curve(curve, n_per_seg=_SAMPLES_PER_SEG)
    if len(samples) < 3:
        raise ValueError("Contour has too few points to trace.")
    cx, cy = boxing_center(curve)

    # Scene (y-down) -> OMA frame (y-up) about the boxing centre, deduped.
    pp: List[Tuple[float, float]] = []
    for x, y, _t in samples:
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
                    "Contour passes through its boxing centre — cannot trace."
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
            "Contour does not wind once around its boxing centre — it is not "
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
            "Contour doubles back in angle about its boxing centre — it is "
            "not star-shaped and cannot be represented as an OMA radial trace."
        )

    # Close the (theta, r) loop and resample at n equal angles.
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
        radii.append(rs[j - 1] + f * (rs[j] - rs[j - 1]))
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
