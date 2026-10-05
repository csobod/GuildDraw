"""
SVG import — bring foreign SVG geometry into a GuildDraw workspace.

The second door for other people's geometry, beside ``dxf_import``: a logo
for a temple engraving, a shape a colleague drew in Inkscape or Illustrator,
an outline traced in another editor. Every ``<path>`` comes in as the exact
cubic Béziers the file holds — one GuildDraw spline per subpath, a node per
segment, straight segments left straight — so nothing is flattened and
re-fitted. ``<rect>``, ``<circle>``, ``<ellipse>``, ``<line>``, ``<polyline>``
and ``<polygon>`` are read too; a circle that is still a circle after its
transforms stays a GuildDraw circle. Transforms (``matrix``, ``translate``,
``scale``, ``rotate``, ``skewX``, ``skewY``) are composed down through the
groups and applied to every point, which is exact for Béziers.

Coordinates: SVG is Y-down like the scene, so no flip. User units become
millimeters from the file's declared size (``width``/``height`` in mm, cm, in,
pt or pc against the ``viewBox``); a file that declares no physical size — a
plain ``viewBox``, or a width in px — is read at the CSS reference pixel, 96
per inch, and :attr:`SvgDocument.physical` says so, so the caller can offer a
size. GuildDraw's own saved ``.svg`` declares millimeters and a viewBox in
scene coordinates, so it comes back exactly where it was drawn.

Layer policy, as for DXF: a shape (or a ``<g>`` above it) labeled with a
GuildDraw layer name — Inkscape's ``inkscape:label``, GuildDraw's own
``data-layer``, or an ``id`` — that is *valid for the target workspace* keeps
that layer; everything else lands on ``active_layer``. Most SVGs carry no
layer names at all, and that is not reported; only a recognized name that is
not valid here (LENS on a temple) is.

Not rendered, so skipped: ``<defs>``, clip paths, masks, markers, patterns,
symbols, gradients, filters, metadata, and anything hidden with
``display:none``. Counted and reported, never silently dropped: ``<text>``
(convert it to paths in your editor), ``<use>`` clones (expand them), images,
and a malformed path.

Untrusted input: the file goes through the same DTD/entity guard GuildDraw's
own loader uses (``export.svg._read_checked_svg``).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from xml.etree import ElementTree as ET

from ..document import (
    ALL_LAYER_NAMES,
    ControlPoint,
    Curve,
    Layer,
    SplineNode,
    WORKSPACE_LAYERS,
)
from ..geometry import sample_curve
from .svg import _read_checked_svg

_SVG_NS = "http://www.w3.org/2000/svg"
_INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"

# The CSS reference pixel (SVG 1.1 §7.10): 96 per inch. What a unitless file is in.
_MM_PER_PX = 25.4 / 96.0
_UNIT_MM = {"mm": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72.0, "pc": 25.4 / 6.0,
            "px": _MM_PER_PX, "": _MM_PER_PX}
_PHYSICAL_UNITS = frozenset({"mm", "cm", "in", "pt", "pc"})

_EPS = 1e-6              # mm — two points this close are one point
# mm — a segment shorter than this is a hairline: a converter closing a path
# a few microns short of its start, two anchors dropped on one spot. It
# carries no shape and would import as a node sitting on its neighbor — a
# closed spline crossing itself at the seam (2026-10-05) — so it is merged.
_HAIRLINE_MM = 0.01
_QUARTER = math.pi / 2.0  # an arc is cut into cubics no wider than this

# Never rendered directly: definitions and metadata.
_SKIP = frozenset({
    "defs", "clipPath", "mask", "marker", "pattern", "symbol", "metadata", "title",
    "desc", "style", "script", "linearGradient", "radialGradient", "filter", "font",
    "font-face", "glyph", "missing-glyph", "view", "cursor",
})
_SHAPES = frozenset({"path", "rect", "circle", "ellipse", "line", "polyline", "polygon"})
_CONTAINERS = frozenset({"svg", "g", "a", "switch"})

_NUM_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_XFORM_RE = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)")
_LENGTH_RE = re.compile(r"\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([a-zA-Z%]*)\s*$")
_HIDDEN_RE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)

Point = tuple[float, float]
# SVG's matrix(a b c d e f): x' = a·x + c·y + e, y' = b·x + d·y + f
Affine = tuple[float, float, float, float, float, float]
_IDENTITY: Affine = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Affine transforms
# ---------------------------------------------------------------------------

def _mul(m: Affine, n: Affine) -> Affine:
    """``m·n`` — apply *n* first, then *m* (SVG lists transforms outermost first)."""
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + c * b2, b * a2 + d * b2,
            a * c2 + c * d2, b * c2 + d * d2,
            a * e2 + c * f2 + e, b * e2 + d * f2 + f)


def _apply(m: Affine, p: Point) -> Point:
    a, b, c, d, e, f = m
    x, y = p
    return (a * x + c * y + e, b * x + d * y + f)


def _translate(tx: float, ty: float) -> Affine:
    return (1.0, 0.0, 0.0, 1.0, tx, ty)


def _scale_m(sx: float, sy: float) -> Affine:
    return (sx, 0.0, 0.0, sy, 0.0, 0.0)


def _parse_transform(text: str | None) -> Affine:
    m = _IDENTITY
    for name, args in _XFORM_RE.findall(text or ""):
        v = [float(x) for x in _NUM_RE.findall(args)]
        if name == "matrix" and len(v) == 6:
            t: Affine = (v[0], v[1], v[2], v[3], v[4], v[5])
        elif name == "translate" and v:
            t = _translate(v[0], v[1] if len(v) > 1 else 0.0)
        elif name == "scale" and v:
            t = _scale_m(v[0], v[1] if len(v) > 1 else v[0])
        elif name == "rotate" and v:
            a = math.radians(v[0])
            ca, sa = math.cos(a), math.sin(a)
            t = (ca, sa, -sa, ca, 0.0, 0.0)
            if len(v) >= 3:                       # about a point: T(c) · R · T(-c)
                t = _mul(_translate(v[1], v[2]), _mul(t, _translate(-v[1], -v[2])))
        elif name == "skewX" and v:
            t = (1.0, 0.0, math.tan(math.radians(v[0])), 1.0, 0.0, 0.0)
        elif name == "skewY" and v:
            t = (1.0, math.tan(math.radians(v[0])), 0.0, 1.0, 0.0, 0.0)
        else:
            continue
        m = _mul(m, t)
    return m


def _similarity_scale(m: Affine) -> float | None:
    """The uniform scale of *m* when it is a similarity (rotation, uniform
    scale, translation — a circle stays a circle), else None."""
    a, b, c, d, _e, _f = m
    la, lc = math.hypot(a, b), math.hypot(c, d)
    if la < _EPS or lc < _EPS:
        return None
    if abs(a * c + b * d) > 1e-9 * la * lc or abs(la - lc) > 1e-9 * max(la, lc):
        return None
    return la


# ---------------------------------------------------------------------------
# Path data
# ---------------------------------------------------------------------------

# A segment is ("L", p0, p1) or ("C", p0, c1, c2, p1); a subpath is (segments, closed).
Segment = tuple
Subpath = tuple[list[Segment], bool]


class _PathLexer:
    """Cursor over path data. Arc flags are single characters that may be run
    together with the next number (``0 01 2 3``), so they get their own reader
    — a number regex would swallow ``01`` as one."""

    def __init__(self, d: str) -> None:
        self.s = d
        self.i = 0
        self.n = len(d)

    def _skip(self) -> None:
        s, n = self.s, self.n
        while self.i < n and s[self.i] in " \t\r\n,":
            self.i += 1

    def at_end(self) -> bool:
        self._skip()
        return self.i >= self.n

    def peek_command(self) -> str | None:
        self._skip()
        if self.i < self.n and self.s[self.i].isalpha():
            return self.s[self.i]
        return None

    def command(self) -> str:
        c = self.s[self.i]
        self.i += 1
        return c

    def number(self) -> float:
        self._skip()
        m = _NUM_RE.match(self.s, self.i)
        if not m:
            raise ValueError(f"expected a number at offset {self.i}")
        self.i = m.end()
        return float(m.group())

    def flag(self) -> bool:
        self._skip()
        if self.i >= self.n or self.s[self.i] not in "01":
            raise ValueError(f"expected an arc flag at offset {self.i}")
        self.i += 1
        return self.s[self.i - 1] == "1"


def _arc_segments(p0: Point, rx: float, ry: float, phi_deg: float,
                  large: bool, sweep: bool, p1: Point) -> list[Segment]:
    """An SVG elliptical arc (endpoint form, F.6.5) as cubic Béziers of at
    most a quarter turn each. Degenerate radii draw the chord, as the spec says."""
    x0, y0 = p0
    x1, y1 = p1
    if math.hypot(x1 - x0, y1 - y0) <= _EPS:
        return []
    rx, ry = abs(rx), abs(ry)
    if rx <= _EPS or ry <= _EPS:
        return [("L", p0, p1)]
    phi = math.radians(phi_deg)
    cp, sp = math.cos(phi), math.sin(phi)
    dx2, dy2 = (x0 - x1) / 2.0, (y0 - y1) / 2.0
    x1p = cp * dx2 + sp * dy2
    y1p = -sp * dx2 + cp * dy2
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1.0:                                   # radii too small: scale them up
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(0.0, num / den)) if den > 0 else 0.0
    if large == sweep:
        coef = -coef
    cxp = coef * (rx * y1p / ry)
    cyp = coef * (-ry * x1p / rx)
    cx = cp * cxp - sp * cyp + (x0 + x1) / 2.0
    cy = sp * cxp + cp * cyp + (y0 + y1) / 2.0

    def ang(ux: float, uy: float, vx: float, vy: float) -> float:
        return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)

    ux, uy = (x1p - cxp) / rx, (y1p - cyp) / ry
    vx, vy = (-x1p - cxp) / rx, (-y1p - cyp) / ry
    theta1 = ang(1.0, 0.0, ux, uy)
    dtheta = ang(ux, uy, vx, vy)
    if not sweep and dtheta > 0:
        dtheta -= 2.0 * math.pi
    elif sweep and dtheta < 0:
        dtheta += 2.0 * math.pi

    nseg = max(1, int(math.ceil(abs(dtheta) / _QUARTER - 1e-9)))
    delta = dtheta / nseg
    t = 4.0 / 3.0 * math.tan(delta / 4.0)

    def on(a: float) -> Point:
        ca, sa = math.cos(a), math.sin(a)
        return (cx + rx * ca * cp - ry * sa * sp, cy + rx * ca * sp + ry * sa * cp)

    def deriv(a: float) -> Point:
        ca, sa = math.cos(a), math.sin(a)
        return (-rx * sa * cp - ry * ca * sp, -rx * sa * sp + ry * ca * cp)

    segs: list[Segment] = []
    a1 = theta1
    e1 = p0
    for i in range(nseg):
        a2 = a1 + delta
        e2 = p1 if i == nseg - 1 else on(a2)
        d1, d2 = deriv(a1), deriv(a2)
        c1 = (e1[0] + t * d1[0], e1[1] + t * d1[1])
        c2 = (e2[0] - t * d2[0], e2[1] - t * d2[1])
        segs.append(("C", e1, c1, c2, e2))
        a1, e1 = a2, e2
    return segs


def _parse_path(d: str) -> list[Subpath]:
    """Path data → subpaths of line / cubic segments in user units.

    Quadratics are raised to cubics exactly; S/T reflect the previous control
    point per the spec; arcs become cubics; Z closes with a straight segment
    back to the subpath's start when the pen is not already there."""
    lx = _PathLexer(d)
    subpaths: list[Subpath] = []
    segs: list[Segment] = []
    cur: Point = (0.0, 0.0)
    start: Point = (0.0, 0.0)
    cmd: str | None = None
    prev_cubic_ctrl: Point | None = None
    prev_quad_ctrl: Point | None = None

    def pt(rel: bool) -> Point:
        x, y = lx.number(), lx.number()
        return (cur[0] + x, cur[1] + y) if rel else (x, y)

    while not lx.at_end():
        c = lx.peek_command()
        if c is not None:
            cmd = lx.command()
        else:
            if cmd is None:
                raise ValueError("path data does not start with a command")
            if cmd == "M":            # implicit repetition: pairs after M are L
                cmd = "L"
            elif cmd == "m":
                cmd = "l"
        rel = cmd.islower()
        u = cmd.upper()
        cubic_ctrl: Point | None = None
        quad_ctrl: Point | None = None

        if u == "Z":
            if segs:
                if math.hypot(cur[0] - start[0], cur[1] - start[1]) > _EPS:
                    segs.append(("L", cur, start))
                subpaths.append((segs, True))
                segs = []
            cur = start
        elif u == "M":
            p = pt(rel)
            if segs:
                subpaths.append((segs, False))
                segs = []
            cur = start = p
        elif u == "L":
            p = pt(rel)
            segs.append(("L", cur, p))
            cur = p
        elif u == "H":
            x = lx.number()
            p = (cur[0] + x if rel else x, cur[1])
            segs.append(("L", cur, p))
            cur = p
        elif u == "V":
            y = lx.number()
            p = (cur[0], cur[1] + y if rel else y)
            segs.append(("L", cur, p))
            cur = p
        elif u == "C":
            c1, c2, p = pt(rel), pt(rel), pt(rel)
            segs.append(("C", cur, c1, c2, p))
            cubic_ctrl, cur = c2, p
        elif u == "S":
            c2, p = pt(rel), pt(rel)
            c1 = ((2 * cur[0] - prev_cubic_ctrl[0], 2 * cur[1] - prev_cubic_ctrl[1])
                  if prev_cubic_ctrl else cur)
            segs.append(("C", cur, c1, c2, p))
            cubic_ctrl, cur = c2, p
        elif u in ("Q", "T"):
            if u == "Q":
                q, p = pt(rel), pt(rel)
            else:
                p = pt(rel)
                q = ((2 * cur[0] - prev_quad_ctrl[0], 2 * cur[1] - prev_quad_ctrl[1])
                     if prev_quad_ctrl else cur)
            c1 = (cur[0] + 2.0 / 3.0 * (q[0] - cur[0]), cur[1] + 2.0 / 3.0 * (q[1] - cur[1]))
            c2 = (p[0] + 2.0 / 3.0 * (q[0] - p[0]), p[1] + 2.0 / 3.0 * (q[1] - p[1]))
            segs.append(("C", cur, c1, c2, p))
            quad_ctrl, cur = q, p
        elif u == "A":
            rx, ry, phi = lx.number(), lx.number(), lx.number()
            large, sweep = lx.flag(), lx.flag()
            p = pt(rel)
            segs.extend(_arc_segments(cur, rx, ry, phi, large, sweep, p))
            cur = p
        else:
            raise ValueError(f"unknown path command {cmd!r}")

        prev_cubic_ctrl, prev_quad_ctrl = cubic_ctrl, quad_ctrl

    if segs:
        subpaths.append((segs, False))
    return subpaths


# ---------------------------------------------------------------------------
# Subpath → Curve
# ---------------------------------------------------------------------------

def _close(a: Point, b: Point, tol: float = _HAIRLINE_MM) -> bool:
    return math.hypot(a[0] - b[0], a[1] - b[1]) <= tol


def _curve_from_subpath(segs: list[Segment], closed: bool, ctm: Affine,
                        layer: Layer) -> Curve | None:
    """One subpath, transformed to millimeters, as a GuildDraw Curve: a
    polyline when every segment is straight, else a spline whose straight
    segments have no handles (GuildDraw draws a missing handle as straight).
    Hairline segments are merged into their neighbor; a closing segment
    that lands on the start folds into the first node, so a closed curve
    never carries a duplicate seam node."""
    placed: list[Segment] = []
    for s in segs:
        if s[0] == "L":
            a, b = _apply(ctm, s[1]), _apply(ctm, s[2])
            if _close(a, b):
                continue
            placed.append(("L", a, b))
        else:
            a, c1, c2, b = (_apply(ctm, q) for q in s[1:])
            if _close(a, b) and _close(a, c1) and _close(a, c2):
                continue
            placed.append(("C", a, c1, c2, b))
    if not placed:
        return None

    if all(s[0] == "L" for s in placed):
        pts = [placed[0][1]] + [s[2] for s in placed]
        if closed and len(pts) > 1 and _close(pts[0], pts[-1]):
            pts.pop()
        if len(pts) < 2:
            return None
        return Curve(kind="line", layer=layer,
                     nodes=[SplineNode(x=x, y=y) for x, y in pts],
                     closed=closed and len(pts) >= 3)

    def handle(node: SplineNode, p: Point) -> ControlPoint | None:
        return None if _close((node.x, node.y), p) else ControlPoint(p[0], p[1])

    nodes = [SplineNode(x=placed[0][1][0], y=placed[0][1][1])]
    for s in placed:
        node = nodes[-1]
        end = SplineNode(x=s[-1][0], y=s[-1][1])
        if s[0] == "C":
            node.cp_out = handle(node, s[2])
            end.cp_in = handle(end, s[3])
        nodes.append(end)
    if closed and len(nodes) > 2 and _close((nodes[0].x, nodes[0].y),
                                            (nodes[-1].x, nodes[-1].y)):
        nodes[0].cp_in = nodes[-1].cp_in
        nodes.pop()
    if len(nodes) < 2:
        return None
    return Curve(kind="spline", layer=layer, nodes=nodes, closed=closed)


# ---------------------------------------------------------------------------
# Basic shapes → path data (one code path for everything that is not a circle)
# ---------------------------------------------------------------------------

def _attr(elem, name: str, default: float = 0.0) -> float:
    v = elem.get(name)
    if v is None:
        return default
    m = _LENGTH_RE.match(v)
    if not m:
        return default
    val, unit = float(m.group(1)), m.group(2).lower()
    if unit == "%":
        return default
    return val * (_UNIT_MM[unit] / _MM_PER_PX) if unit in _UNIT_MM and unit else val


def _rect_d(e) -> str:
    x, y = _attr(e, "x"), _attr(e, "y")
    w, h = _attr(e, "width"), _attr(e, "height")
    if w <= 0 or h <= 0:
        return ""
    rx, ry = e.get("rx"), e.get("ry")
    rxv = _attr(e, "rx") if rx is not None else (_attr(e, "ry") if ry is not None else 0.0)
    ryv = _attr(e, "ry") if ry is not None else rxv
    rxv, ryv = min(max(rxv, 0.0), w / 2.0), min(max(ryv, 0.0), h / 2.0)
    if rxv <= _EPS or ryv <= _EPS:
        return f"M {x} {y} H {x + w} V {y + h} H {x} Z"
    return (f"M {x + rxv} {y} H {x + w - rxv} A {rxv} {ryv} 0 0 1 {x + w} {y + ryv} "
            f"V {y + h - ryv} A {rxv} {ryv} 0 0 1 {x + w - rxv} {y + h} H {x + rxv} "
            f"A {rxv} {ryv} 0 0 1 {x} {y + h - ryv} V {y + ryv} "
            f"A {rxv} {ryv} 0 0 1 {x + rxv} {y} Z")


def _ellipse_d(cx: float, cy: float, rx: float, ry: float) -> str:
    if rx <= 0 or ry <= 0:
        return ""
    return (f"M {cx + rx} {cy} A {rx} {ry} 0 0 1 {cx} {cy + ry} "
            f"A {rx} {ry} 0 0 1 {cx - rx} {cy} A {rx} {ry} 0 0 1 {cx} {cy - ry} "
            f"A {rx} {ry} 0 0 1 {cx + rx} {cy} Z")


def _points_d(e, closed: bool) -> str:
    v = [float(x) for x in _NUM_RE.findall(e.get("points") or "")]
    if len(v) < 4:
        return ""
    pairs = [f"{v[i]} {v[i + 1]}" for i in range(0, len(v) - 1, 2)]
    return "M " + " L ".join(pairs) + (" Z" if closed else "")


# ---------------------------------------------------------------------------
# Document walk
# ---------------------------------------------------------------------------

def _local(tag: str) -> tuple[str, str]:
    """(namespace, local name); a bare tag is in no namespace."""
    if tag.startswith("{"):
        ns, _, name = tag[1:].partition("}")
        return ns, name
    return "", tag


def _hidden(elem) -> bool:
    if (elem.get("display") or "").strip() == "none":
        return True
    if (elem.get("visibility") or "").strip() == "hidden":
        return True
    return bool(_HIDDEN_RE.search(elem.get("style") or ""))


def _layer_label(elem) -> str | None:
    for key in (f"{{{_INKSCAPE_NS}}}label", "data-layer", "id"):
        v = elem.get(key)
        if v and v.strip():
            return v.strip().upper()
    return None


def _parse_length(s: str | None) -> tuple[float, str] | None:
    m = _LENGTH_RE.match(s or "")
    return (float(m.group(1)), m.group(2).lower()) if m else None


def _document_scale(root) -> tuple[float, bool]:
    """``(mm per user unit, physical)`` from the root's size and viewBox.
    *physical* is True when the file states a real-world size."""
    vb = [float(x) for x in _NUM_RE.findall(root.get("viewBox") or "")]
    w, h = _parse_length(root.get("width")), _parse_length(root.get("height"))

    def known(ln) -> bool:
        return ln is not None and ln[0] > 0 and ln[1] in _UNIT_MM

    if len(vb) == 4 and vb[2] > 0 and vb[3] > 0:
        if known(w):
            return w[0] * _UNIT_MM[w[1]] / vb[2], w[1] in _PHYSICAL_UNITS
        if known(h):
            return h[0] * _UNIT_MM[h[1]] / vb[3], h[1] in _PHYSICAL_UNITS
        return _MM_PER_PX, False
    if known(w):
        return _UNIT_MM[w[1]], w[1] in _PHYSICAL_UNITS
    if known(h):
        return _UNIT_MM[h[1]], h[1] in _PHYSICAL_UNITS
    return _MM_PER_PX, False


@dataclass
class _Walk:
    allowed: set
    active: Layer
    curves: list[Curve] = field(default_factory=list)
    refiled: dict[str, int] = field(default_factory=dict)      # recognized name → count
    unsupported: dict[str, int] = field(default_factory=dict)  # tag → count

    def target(self, name: str | None) -> tuple[Layer, bool]:
        if name in ALL_LAYER_NAMES and Layer(name) in self.allowed:
            return Layer(name), True
        return self.active, False

    def shape(self, elem, tag: str, ctm: Affine, hint: str | None) -> None:
        own = _layer_label(elem)
        name = own if own in ALL_LAYER_NAMES else hint
        layer, kept = self.target(name)
        try:
            new = _shape_curves(elem, tag, ctm, layer)
        except (ValueError, IndexError):
            self.unsupported["malformed path"] = self.unsupported.get("malformed path", 0) + 1
            return
        if not new:
            return
        self.curves.extend(new)
        if not kept and name in ALL_LAYER_NAMES:
            self.refiled[name] = self.refiled.get(name, 0) + len(new)


def _shape_curves(elem, tag: str, ctm: Affine, layer: Layer) -> list[Curve]:
    if tag == "path":
        d = elem.get("d") or ""
    elif tag == "rect":
        d = _rect_d(elem)
    elif tag in ("circle", "ellipse"):
        cx, cy = _attr(elem, "cx"), _attr(elem, "cy")
        if tag == "circle":
            rx = ry = _attr(elem, "r")
        else:
            rx, ry = _attr(elem, "rx"), _attr(elem, "ry")
        s = _similarity_scale(ctm)
        if s is not None and rx > _EPS and abs(rx - ry) <= _EPS:
            c = _apply(ctm, (cx, cy))
            return [Curve(kind="circle", layer=layer, nodes=[SplineNode(x=c[0], y=c[1])],
                          radius=rx * s, closed=True)]
        d = _ellipse_d(cx, cy, rx, ry)
    elif tag == "line":
        d = (f"M {_attr(elem, 'x1')} {_attr(elem, 'y1')} "
             f"L {_attr(elem, 'x2')} {_attr(elem, 'y2')}")
    elif tag == "polyline":
        d = _points_d(elem, closed=False)
    else:                                   # polygon
        d = _points_d(elem, closed=True)
    if not d.strip():
        return []
    out: list[Curve] = []
    for segs, closed in _parse_path(d):
        c = _curve_from_subpath(segs, closed, ctm, layer)
        if c is not None:
            out.append(c)
    return out


def _walk(elem, ctm: Affine, hint: str | None, ctx: _Walk, *, is_root: bool) -> None:
    ns, tag = _local(elem.tag)
    if ns not in ("", _SVG_NS):            # sodipodi:namedview and friends
        return
    if tag in _SKIP or _hidden(elem):
        return
    ctm = _mul(ctm, _parse_transform(elem.get("transform")))
    if tag in _CONTAINERS:
        if tag == "svg" and not is_root:   # a nested <svg> places its content at x, y
            ctm = _mul(ctm, _translate(_attr(elem, "x"), _attr(elem, "y")))
        label = _layer_label(elem)
        if label in ALL_LAYER_NAMES:
            hint = label
        for child in elem:
            _walk(child, ctm, hint, ctx, is_root=False)
        return
    if tag in _SHAPES:
        ctx.shape(elem, tag, ctm, hint)
        return
    ctx.unsupported[tag] = ctx.unsupported.get(tag, 0) + 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class SvgDocument:
    """What an SVG holds, in millimeters, as GuildDraw curves.

    ``curves`` sit where the file places them (its origin at the scene origin,
    Y down); ``bbox`` is their extent, ``physical`` whether the file declared a
    real size or was read at 96 px/in, and ``notes`` what was re-filed or
    skipped — status-bar strings, like ``dxf_import``'s."""
    curves: list[Curve]
    notes: list[str]
    physical: bool
    bbox: tuple[float, float, float, float] | None
    guilddraw_native: bool = False

    @property
    def width_mm(self) -> float:
        return (self.bbox[2] - self.bbox[0]) if self.bbox else 0.0

    @property
    def height_mm(self) -> float:
        return (self.bbox[3] - self.bbox[1]) if self.bbox else 0.0


def content_bbox(curves: list[Curve]) -> tuple[float, float, float, float] | None:
    """Extent of the curves as drawn (sampled, not control-point extents)."""
    xs: list[float] = []
    ys: list[float] = []
    for c in curves:
        for x, y, _t in sample_curve(c, n_per_seg=12):
            xs.append(x)
            ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def read_svg(path: str, active_layer: Layer, workspace_type: str = "front") -> SvgDocument:
    """Read *path* into curves at the file's own scale.

    Recognized layer names valid for *workspace_type* are kept; everything else
    lands on *active_layer*. Raises ``ValueError`` on a file that is not SVG or
    that trips the DTD/entity guard."""
    data = _read_checked_svg(path)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"Not a valid SVG (XML) file: {exc}") from exc
    if _local(root.tag)[1] != "svg":
        raise ValueError("Not an SVG file: the document element is "
                         f"<{_local(root.tag)[1]}>, not <svg>.")

    mm_per_unit, physical = _document_scale(root)
    ctx = _Walk(allowed=set(WORKSPACE_LAYERS.get(workspace_type, list(Layer))),
                active=active_layer)
    _walk(root, _scale_m(mm_per_unit, mm_per_unit), None, ctx, is_root=True)

    meta = root.find(f"{{{_SVG_NS}}}metadata")
    native = bool(meta is not None and meta.text and meta.text.lstrip().startswith("{"))

    notes: list[str] = []
    if ctx.refiled:
        total = sum(ctx.refiled.values())
        names = ", ".join(sorted(ctx.refiled))
        notes.append(f"{total} curve(s) labeled {names} placed on {active_layer.value} "
                     f"— that layer is not used in this workspace; re-file via the "
                     f"Layers panel.")
    if ctx.unsupported:
        hints = {"text": "convert text to paths in your editor",
                 "use": "expand clones in your editor"}
        parts = []
        for k, v in sorted(ctx.unsupported.items()):
            parts.append(f"{k}×{v}" + (f" ({hints[k]})" if k in hints else ""))
        notes.append("Skipped: " + ", ".join(parts))
    if native:
        notes.append("This is a GuildDraw drawing — File ▸ Open keeps its full state.")
    return SvgDocument(curves=ctx.curves, notes=notes, physical=physical,
                       bbox=content_bbox(ctx.curves), guilddraw_native=native)


def _transform_curve(c: Curve, m: Affine, uniform: float) -> Curve:
    nodes = []
    for n in c.nodes:
        x, y = _apply(m, (n.x, n.y))
        nn = SplineNode(x=x, y=y)
        if n.cp_in is not None:
            cx, cy = _apply(m, (n.cp_in.x, n.cp_in.y))
            nn.cp_in = ControlPoint(cx, cy)
        if n.cp_out is not None:
            cx, cy = _apply(m, (n.cp_out.x, n.cp_out.y))
            nn.cp_out = ControlPoint(cx, cy)
        nodes.append(nn)
    return Curve(kind=c.kind, layer=c.layer, nodes=nodes, closed=c.closed,
                 line_weight=c.line_weight,
                 radius=(c.radius * uniform) if c.radius is not None else None,
                 start_angle=c.start_angle, end_angle=c.end_angle,
                 group_id=c.group_id)


def place_curves(curves: list[Curve], *, scale: float = 1.0,
                 center: Point | None = None) -> list[Curve]:
    """Copies of *curves* scaled uniformly about their own center and, when
    *center* is given, moved so that center lands there (the view's middle,
    for a logo that arrived at page size). ``scale=1`` with no center is the
    file's own placement."""
    bb = content_bbox(curves)
    if bb is None:
        return [_transform_curve(c, _IDENTITY, 1.0) for c in curves]
    cx, cy = (bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0
    tx, ty = center if center is not None else (cx, cy)
    m = _mul(_translate(tx, ty), _mul(_scale_m(scale, scale), _translate(-cx, -cy)))
    return [_transform_curve(c, m, abs(scale)) for c in curves]


def import_svg(
    path: str,
    active_layer: Layer,
    workspace_type: str = "front",
    *,
    scale: float = 1.0,
    center: Point | None = None,
) -> tuple[list[Curve], list[str]]:
    """Read *path* and return ``(curves, notes)`` placed with *scale* about the
    content's center and that center at *center* — :func:`read_svg` and
    :func:`place_curves` in one call, shaped like ``dxf_import.import_dxf``."""
    doc = read_svg(path, active_layer, workspace_type)
    return place_curves(doc.curves, scale=scale, center=center), doc.notes
