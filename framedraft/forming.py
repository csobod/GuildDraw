"""Forming, on the drawing side (BUILDPLAN *Road to 2.3*): the frame front
head-on as it will look after the press, and the temple with its tip bend.

The front is cut flat and then formed: the base curve is pressed into each
rim, the face form is the angle between the two lens planes at the bridge,
and the bridge may be projected forward. Seen from the front, forming narrows
the lens: a little in the lens's own plane, more head-on. GuildModel models
this with one smooth map (its ``core/forming/thermoform.py``, M18 there);
``ThermoformMap`` below is that map, ported verbatim but for the constant 530
in place of the schema import, so that the two apps show the same formed
front. ``tests/test_forming_parity.py`` runs GuildModel's own module when its
tree is on disk and holds the two to 0.01 mm.

Conventions, in one place:

* GuildDraw's scene is y-down millimeters. GuildModel's map takes the
  drawing after one flip, (x, y) → (−x, −y), with z = 0 the anterior face
  and +z toward the wearer. `FrontForming` flips in, maps, and flips back,
  so everything a caller sees is in scene coordinates.
* The map keeps its z = 0 surface at its length. Which surface of the sheet
  keeps its length in the press is the research's largest unknown (§2.6):
  GuildModel assumes the front face, the textbook says mid-thickness. The
  `neutral_fraction` k puts that surface k·t behind the anterior face, so a
  point at depth d maps with z = d − k·t; 0 is GuildModel's answer.
* "A" has three values: as cut (the flat drawing), in the lens plane (what
  ISO 8624 measures and what a drawing carries), and head-on (what the
  maker asked to see). The readouts give all three and say which is which.
* A temple is a side elevation, its core on y = 0 and its hinge end at the
  smallest x. Both temple tabs show the skin side with the hinge at the
  left, so the left temple is drawn as the right's mirror about the core
  line: "down" is +y on the right temple's tab and −y on the left's
  (`TipBend.down`). ISO 8624 measures the length to bend from the dowel
  point, the screw's axis; the drawing has no screw, so the hinge end of
  the outline stands in.

Qt-free on purpose: numpy and shapely only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from .document import Curve, Layer
from .geometry import (_cubics_curve, _curve_cubics, arc_to_spline, circle_to_spline,
                       flatten_curve, split_bezier_at_t)

__all__ = [
    "DIOPTER_MM", "GROOVE_APEX_MM", "ISO_A_TOL_MM",
    "NEUTRAL_RANGE", "SHEET_THICKNESS_RANGE_MM", "TOOLING_INDEX_RANGE",
    "BridgeGeometry", "FormingSetup", "FrontForming", "FrontReadout", "LensReadout",
    "PressRow", "PRESS_ROWS", "ThermoformMap", "ThermoformParams",
    "TipBend", "TipBendParams", "DEFAULT_DROP_MM", "UNFORM_TOL_MM", "UnformDiverged",
    "bridge_from_lenses", "densify", "front_readout", "lens_readout", "press_row",
    "radius_for", "rule_for_index", "unform_curve", "unform_points",
]

#: The optical convention's constant: base curve in diopters is this over the
#: radius in millimeters, the 1.53-index tool-maker's sphere. GuildModel's
#: `DIOPTER_MM`; the lab data standard presumes the same index.
DIOPTER_MM = 530.0
#: The tooling index Preferences may set: the radius a base curve names is
#: (index − 1) × 1000 / D. 1.53, the historical standard, is `DIOPTER_MM`'s
#: 530; the older European lens clocks' 1.523 moves a 50 mm lens by at most
#: 0.04 mm.
TOOLING_INDEX_DEFAULT = 1.53
TOOLING_INDEX_RANGE = (1.4, 2.0)
#: The sheet Preferences may set, mm, and the depth of the surface that keeps
#: its length, as a fraction of it (research §2.6).
SHEET_THICKNESS_RANGE_MM = (1.0, 12.0)
NEUTRAL_RANGE = (0.0, 1.0)
#: Where the lens groove's apex sits behind the anterior face, mm:
#: GuildModel's `LensGrooveParams.anterior_offset_mm` default. The outline
#: that a lens must fit is the groove line, so the readouts measure there.
GROOVE_APEX_MM = 1.5
#: ISO 12870's tolerance on the lens size A, mm, either way.
ISO_A_TOL_MM = 0.5

# --------------------------------------------------------------- the press rows


@dataclass(frozen=True)
class PressRow:
    """One die of a base-curve press: the base curve it is tagged with, its
    own radius (which is what the sheet bends to on that row, and is not
    530 / D on the SBT dies), and the face form the frame comes off it with
    (included, 180 flat)."""
    label: str
    base_curve: float
    radius_mm: float
    face_form_deg: float


#: The maker's SBT base-curve press, read off its drawing (GuildModel's
#: `config/presses.yaml`, 2026-09-24). GuildDraw's own copy: the apps never
#: read each other's files (research Q4c).
PRESS_ROWS: tuple[PressRow, ...] = (
    PressRow("SBT base 2 / lens 4", 2.0, 259.0, 174.69),
    PressRow("SBT base 3 / lens 4", 3.0, 181.0, 169.24),
    PressRow("SBT base 4 / lens 4", 4.0, 144.0, 163.97),
    PressRow("SBT base 2 / lens 2", 2.0, 262.0, 170.11),
)


def press_row(label: str) -> PressRow | None:
    for row in PRESS_ROWS:
        if row.label == label:
            return row
    return None


def radius_for(base_curve: float, rule_mm: float = DIOPTER_MM) -> float:
    """The radius a base curve names under a radius rule; 0 for flat."""
    d = float(base_curve)
    return float(rule_mm) / d if d > 0.0 else 0.0


# -------------------------------------------------------------- the shop's setup


def rule_for_index(tooling_index: float) -> float:
    """The constant over D a tooling index names: 530 at 1.53."""
    return round((float(tooling_index) - 1.0) * 1000.0, 6)


@dataclass(frozen=True)
class FormingSetup:
    """The values Preferences ▸ General ▸ Forming holds. They describe the
    shop's press and sheet, not one design, and no design has a field for
    them, so every design uses them: a pressed coupon that settles the
    neutral surface reaches the designs already saved. A design stores a copy
    (`ThermoformParams`) for GuildModel's reader."""
    tooling_index: float = TOOLING_INDEX_DEFAULT
    sheet_thickness_mm: float = 6.0
    neutral_fraction: float = 0.0

    @property
    def radius_rule(self) -> float:
        return rule_for_index(self.tooling_index)

    @classmethod
    def from_prefs(cls, d) -> "FormingSetup":
        """The setup in a prefs dict, held to the fields' bounds; a hand-edited
        file's kinds were checked when prefs.py read it."""
        out = cls()
        if not isinstance(d, dict):
            return out

        def held(key, bounds):
            return min(max(float(d.get(key, getattr(out, key))), bounds[0]), bounds[1])

        return cls(held("tooling_index", TOOLING_INDEX_RANGE),
                   held("sheet_thickness_mm", SHEET_THICKNESS_RANGE_MM),
                   held("neutral_fraction", NEUTRAL_RANGE))


# ------------------------------------------------------------- the stored block


@dataclass
class ThermoformParams:
    """The front's forming, as the ``.gdraw`` stores it under ``thermoform``.

    The first four keys are named after GuildModel's `FormingMetadata`, so
    its reader can take them as the default for its own forming (research
    Q3): `base_curve` in diopters (0 = flat), `base_radius_mm` the radius in
    use (a press row's die, else the rule's constant over D; 0 = flat),
    `face_form_wrap_deg` = 180 − the included face form (0 = flat), and the
    bridge projection. The rest is GuildDraw's: the press row the values
    came from ("" = custom), then the shop's setup as of the last save (the
    tooling index's constant, the sheet thickness and the length-keeping
    surface's depth as a fraction of it, research §2.6), which `with_setup`
    replaces with this computer's.
    """
    base_curve: float = 0.0
    base_radius_mm: float = 0.0
    face_form_wrap_deg: float = 0.0
    bridge_projection_mm: float = 0.0
    press_preset: str = ""
    radius_rule: float = DIOPTER_MM
    sheet_thickness_mm: float = 6.0
    neutral_fraction: float = 0.0

    KEYS = ("base_curve", "base_radius_mm", "face_form_wrap_deg",
            "bridge_projection_mm", "press_preset", "radius_rule",
            "sheet_thickness_mm", "neutral_fraction")

    @property
    def is_flat(self) -> bool:
        return (self.base_radius_mm <= 0.0 and self.face_form_wrap_deg == 0.0
                and self.bridge_projection_mm <= 0.0)

    @property
    def face_form_deg(self) -> float:
        """The included face form, 180 flat."""
        return 180.0 - self.face_form_wrap_deg

    @property
    def face_form_per_side_deg(self) -> float:
        """ISO 13666's face form: each lens plane's angle to the front's."""
        return 0.5 * self.face_form_wrap_deg

    def with_base_curve(self, base_curve: float) -> "ThermoformParams":
        """The same forming at another base curve, the radius kept in step:
        on a press row the die's radius, off one the rule's."""
        row = press_row(self.press_preset) if self.press_preset else None
        if row is not None and abs(row.base_curve - base_curve) < 1e-9:
            radius = row.radius_mm
        else:
            radius = radius_for(base_curve, self.radius_rule)
        return replace(self, base_curve=float(base_curve), base_radius_mm=radius)

    def with_setup(self, setup: FormingSetup) -> "ThermoformParams":
        """The same forming under the shop's *setup*: a base curve off a press
        row takes the radius the new tooling index names. A radius stored
        under this same index stands, so opening a file changes nothing else."""
        out = replace(self, radius_rule=setup.radius_rule,
                      sheet_thickness_mm=setup.sheet_thickness_mm,
                      neutral_fraction=setup.neutral_fraction)
        if abs(setup.radius_rule - self.radius_rule) > 1e-9:
            out = out.with_base_curve(out.base_curve)
        return out

    @classmethod
    def from_row(cls, row: PressRow, base: "ThermoformParams | None" = None
                 ) -> "ThermoformParams":
        """The forming a press row sets: its base curve, its radius and its
        face form; the rest from *base* (the projection, the sheet)."""
        base = base if base is not None else cls()
        return replace(base, base_curve=row.base_curve, base_radius_mm=row.radius_mm,
                       face_form_wrap_deg=180.0 - row.face_form_deg,
                       press_preset=row.label)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.KEYS}

    @classmethod
    def from_dict(cls, d) -> "ThermoformParams":
        """Tolerant: a key that is missing, or not a number, takes the
        default; a file from before 2.3 has no block and reads flat."""
        out = cls()
        if not isinstance(d, dict):
            return out

        def num(key, lo, hi):
            v = d.get(key)
            try:
                f = float(v)
            except (TypeError, ValueError):
                return getattr(out, key)
            if not math.isfinite(f):
                return getattr(out, key)
            return min(max(f, lo), hi)

        # The bounds are the Forming group's fields': a file past them
        # would sync into clamped fields and be stored clamped at the next
        # edit of any field (the 2.3 forming review).
        out.base_curve = num("base_curve", 0.0, 16.0)
        out.base_radius_mm = num("base_radius_mm", 0.0, 1e4)
        out.face_form_wrap_deg = num("face_form_wrap_deg", 0.0, 30.0)
        out.bridge_projection_mm = num("bridge_projection_mm", 0.0, 8.0)
        out.radius_rule = num("radius_rule", *map(rule_for_index, TOOLING_INDEX_RANGE))
        out.sheet_thickness_mm = num("sheet_thickness_mm", *SHEET_THICKNESS_RANGE_MM)
        out.neutral_fraction = num("neutral_fraction", *NEUTRAL_RANGE)
        preset = d.get("press_preset", "")
        out.press_preset = preset if isinstance(preset, str) and press_row(preset) else ""
        # A radius of 0 with a base curve set: the rule decides (a hand-
        # edited file, or one that stored the curve only).
        if out.base_curve > 0.0 and out.base_radius_mm <= 0.0:
            out = out.with_base_curve(out.base_curve)
        # …and a radius with no base curve is no radius: the field would
        # read Flat over a formed front, and GuildModel reads such a file flat.
        if out.base_curve <= 0.0:
            out.base_radius_mm = 0.0
        return out


# ------------------------------------------------- GuildModel's map, ported


def _smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


#: Half-width of the wrap band when the drawing gives no bridge zone, mm
#: (GuildModel's `DEFAULT_BAND_HALF_MM`).
DEFAULT_BAND_HALF_MM = 9.0
#: Distance between the two creases at the bridge's top edge when the drawing
#: gives none, mm (`DEFAULT_CREASE_GAP_MM`).
DEFAULT_CREASE_GAP_MM = 20.0
#: The V plate's included angle when none is given, degrees
#: (`DEFAULT_CREASE_ANGLE_DEG`).
DEFAULT_CREASE_ANGLE_DEG = 45.0


@dataclass(frozen=True)
class BridgeGeometry:
    """Where the drawing puts the bends: what the map needs from a front, in
    GuildModel's (flipped) frame. `apex_x` / `apex_y` are where the rims are
    apexed (mean |x| and mean y of the two lens centroids), `band_half` the
    half-width of the wrap band, `top_y` the bridge's edge away from the
    nose where the creases start, `top_width` its width there, `nose_dir`
    which way along y the nose lies, `projects` whether there is a bridge
    to set forward, `wraps` whether there is a second eye to wrap toward."""
    apex_x: float = 30.0
    apex_y: float = 0.0
    band_half: float = DEFAULT_BAND_HALF_MM
    top_y: float = 12.0
    center_y: float = 7.0
    top_width: float = DEFAULT_CREASE_GAP_MM
    nose_dir: float = -1.0
    projects: bool = True
    wraps: bool = True


def _die_profile(u, h, R: float, p: float, blend: float = 0.0):
    """The bump's section across the gap (GuildModel's `_die_profile`,
    verbatim): a cylinder of radius R pressed p into the sheet while the V
    plate holds it flat outside ±h."""
    u = np.asarray(u, dtype=np.float64)
    h = np.asarray(h, dtype=np.float64)
    if R <= 0.0 or p <= 0.0:
        return np.zeros(np.broadcast(u, h).shape, dtype=np.float64)
    tiny = 1e-12
    p_eff = min(p, R)
    a = np.minimum(p_eff, R - np.sqrt(np.clip(R * R - h * h, 0.0, None)))
    c = a - R
    D2 = h * h + c * c
    L = np.sqrt(np.clip(D2 - R * R, 0.0, None))
    Tu = R * (h * R + c * L) / np.maximum(D2, tiny)
    Td = c + R * (h * L - c * R) / np.maximum(D2, tiny)
    arc = c + np.sqrt(np.clip(R * R - u * u, 0.0, None))
    run = np.maximum(h - Tu, tiny)
    flank = Td * (h - u) / run
    if blend <= 0.0:
        d = np.where(u <= Tu, arc, np.where(u <= h, flank, 0.0))
        return np.where(h > 0.0, np.clip(d, 0.0, None), 0.0)

    rf = float(blend)
    tan_phi = np.where(h - Tu > 1e-9, Td / run, h / np.maximum(-c, tiny))
    phi = np.arctan(tan_phi)
    s_len = rf * np.tan(0.5 * phi)
    flank_len = np.sqrt((h - Tu) ** 2 + Td ** 2)
    on_flank = s_len <= flank_len
    uc_flank = h + s_len
    uc_arc = np.sqrt(np.clip(a * (R + 2.0 * rf - c), 0.0, None))
    uc = np.where(on_flank, uc_flank, uc_arc)
    fillet = rf - np.sqrt(np.clip(rf * rf - (u - uc) ** 2, 0.0, None))
    arc_end = np.where(on_flank, Tu, R * uc / (R + rf))
    flank_end = uc - rf * np.sin(phi)
    d = np.where(u <= arc_end, arc,
                 np.where(on_flank & (u <= flank_end), flank,
                          np.where(u <= uc, fillet, 0.0)))
    return np.where(h > 0.0, np.clip(d, 0.0, None), 0.0)


class ThermoformMap:
    """Flat coordinates ``(N, 3)`` → formed coordinates ``(N, 3)``, in
    GuildModel's frame (GuildModel's `ThermoformMap`, verbatim but for the
    mesh helpers it carries there).

    The tangent angle of the horizontal through the lens centers is
    ``theta(x) = (x − apex_x·s(x)) / R + (wrap / 2)·s(x)``, with ``s`` a
    smoothstep from −1 to +1 across the bridge band; it is tabulated once
    every 0.05 mm over ±150 mm. The vertical bend is the rim's radius about
    the lens-center height; the bridge bump is a z displacement before the
    bend. A pure function of its parameters.
    """

    def __init__(self, *, radius_mm: float = 0.0, face_form_deg: float = 180.0,
                 projection_mm: float = 0.0,
                 crease_gap_mm: float = DEFAULT_CREASE_GAP_MM,
                 crease_angle_deg: float = DEFAULT_CREASE_ANGLE_DEG,
                 bridge_offset_mm: float = 0.0,
                 die_radius_mm: float = 0.0,
                 crease_blend_mm: float = 0.0,
                 bridge: BridgeGeometry | None = None,
                 x_range=(-150.0, 150.0), grid_mm: float = 0.05) -> None:
        self.bridge = bridge if bridge is not None else BridgeGeometry()
        self.R = float(radius_mm) if radius_mm and radius_mm > 0 else float("inf")
        self.face_form_deg = float(face_form_deg) if self.bridge.wraps else 180.0
        self.wrap = np.radians(180.0 - self.face_form_deg)
        self.p = max(float(projection_mm), 0.0)
        self.gap = max(float(crease_gap_mm), 1e-3)
        self.crease_angle_deg = float(crease_angle_deg)
        self._half_tan = float(np.tan(np.radians(0.5 * self.crease_angle_deg)))
        self.offset = float(bridge_offset_mm)
        self.die = float(die_radius_mm) if die_radius_mm and die_radius_mm > 0 else 0.0
        self.blend = max(float(crease_blend_mm or 0.0), 0.0)
        self.apex_x, self.apex_y = float(self.bridge.apex_x), float(self.bridge.apex_y)
        self.b = max(float(self.bridge.band_half), 1e-3)
        self._grid = float(grid_mm)
        self._xs = np.arange(x_range[0], x_range[1] + grid_mm, grid_mm)
        self._tabulate()

    def _tabulate(self) -> None:
        xs, grid_mm = self._xs, self._grid
        s = 2.0 * _smoothstep((xs + self.b) / (2.0 * self.b)) - 1.0
        theta = np.zeros_like(xs)
        if np.isfinite(self.R):
            theta += (xs - self.apex_x * s) / self.R
        theta += 0.5 * self.wrap * s
        i0 = int(np.argmin(np.abs(xs)))
        cx, sx = np.cos(theta), np.sin(theta)
        X = np.concatenate(([0.0], np.cumsum(0.5 * (cx[1:] + cx[:-1]) * grid_mm)))
        Z = np.concatenate(([0.0], np.cumsum(0.5 * (sx[1:] + sx[:-1]) * grid_mm)))
        self._theta = theta
        self._X, self._Z = X - X[i0], Z - Z[i0]

    @property
    def is_flat(self) -> bool:
        """True when the map is the identity: no curve, no wrap, no projection."""
        return not np.isfinite(self.R) and self.wrap == 0.0 and self.p == 0.0

    def theta_at(self, x) -> np.ndarray:
        """The surface's tangent angle at ``x`` on the lens-center line,
        radians: a lens plane's tilt from the frontal plane (ZTILT)."""
        return np.interp(np.asarray(x, dtype=np.float64), self._xs, self._theta)

    def bend_radii_mm(self) -> tuple[float, float]:
        """``(thickness, projection)``: the radius the part's thickness has
        to stay under, and the reverse bend between the rims that bounds
        the bridge set (GuildModel's `bend_radii_mm`)."""
        d = np.gradient(self._theta, self._grid)
        k_thick = float(max(d.max(), 0.0))
        k_proj = float(max((-d).max(), 0.0))
        along = 1.0 / k_thick if k_thick > 0 else float("inf")
        thickness = float(min(along, self.R))
        projection = 1.0 / k_proj if k_proj > 0 else float("inf")
        return thickness, projection

    def fold_warning(self, thickness_mm: float) -> str | None:
        """Why this map folds a part this thick, or None when it does not."""
        thickness, projection = self.bend_radii_mm()
        if thickness_mm > thickness:
            return (f"bends tighter (R {thickness:.1f} mm) than the sheet is thick "
                    f"({thickness_mm:.1f} mm)")
        if self.p > 0.0 and abs(self.apex_mm()) > projection:
            return (f"the bridge set ({abs(self.apex_mm()):.1f} mm) is more than the "
                    f"reverse bend between the rims can carry (R {projection:.1f} mm)")
        return None

    def crease_half_width(self, y):
        y = np.asarray(y, dtype=np.float64)
        t = (y - self.bridge.top_y) * self.bridge.nose_dir
        h = 0.5 * self.gap - np.clip(t, 0.0, None) * self._half_tan
        return np.clip(h, 0.0, None)

    def bump(self, x, y):
        """Forward displacement of the bridge bump at ``(x, y)``, mm."""
        x = np.asarray(x, dtype=np.float64)
        if self.p == 0.0:
            return np.zeros_like(x)
        h = self.crease_half_width(y)
        u = np.abs(x - self.offset)
        return _die_profile(u, h, self.die_radius_mm(), self.p, self.blend)

    @staticmethod
    def auto_die_radius(gap_mm: float, projection_mm: float) -> float:
        h, p = 0.5 * abs(float(gap_mm)), abs(float(projection_mm))
        if p == 0.0:
            return float("inf")
        return (h * h + p * p) / (2.0 * p) if h >= p else h

    def die_radius_mm(self) -> float:
        if self.die > 0.0:
            return self.die
        return self.auto_die_radius(self.gap, self.p)

    def apex_mm(self) -> float:
        if self.p == 0.0:
            return 0.0
        return float(_die_profile(
            np.zeros(1), np.full(1, 0.5 * self.gap), self.die_radius_mm(),
            self.p, self.blend)[0])

    def in_band(self, x) -> np.ndarray:
        """True where ``x`` lies in the wrap band, where the face form bends
        the sheet: a lens edge there is bent with it."""
        return np.abs(np.asarray(x, dtype=np.float64)) < self.b

    def __call__(self, pts):
        pts = np.asarray(pts, dtype=np.float64)
        if self.is_flat:
            return pts.copy()
        x, y = pts[:, 0], pts[:, 1] - self.apex_y
        z = pts[:, 2] - self.bump(pts[:, 0], pts[:, 1])
        th = np.interp(x, self._xs, self._theta)
        M = np.stack([np.interp(x, self._xs, self._X),
                      np.full_like(x, self.apex_y),
                      np.interp(x, self._xs, self._Z)], axis=1)
        n = np.stack([-np.sin(th), np.zeros_like(th), np.cos(th)], axis=1)
        yhat = np.array([0.0, 1.0, 0.0])
        if np.isfinite(self.R):
            phi = y / self.R
            arc = ((self.R * np.sin(phi))[:, None] * yhat
                   + (self.R * (1 - np.cos(phi)))[:, None] * n)
            n2 = np.cos(phi)[:, None] * n - np.sin(phi)[:, None] * yhat
        else:
            arc, n2 = y[:, None] * yhat, n
        return M + arc + z[:, None] * n2

    def bridge_set_mm(self) -> float:
        """z of the bridge's center line relative to the rims at the same
        height; negative means the bridge sits forward of them."""
        ty = float(self.bridge.top_y)
        apex = self(np.array([[self.apex_x, ty, 0.0]]))[0, 2]
        return float(self(np.array([[self.offset, ty, 0.0]]))[0, 2] - apex)

    @classmethod
    def from_params(cls, params: ThermoformParams, bridge: BridgeGeometry | None = None
                    ) -> "ThermoformMap":
        """The map a front's `ThermoformParams` describes: the crease layout
        at GuildModel's defaults, the gap the drawing's own bridge width."""
        bridge = bridge if bridge is not None else BridgeGeometry()
        return cls(radius_mm=float(params.base_radius_mm),
                   face_form_deg=180.0 - float(params.face_form_wrap_deg),
                   projection_mm=(float(params.bridge_projection_mm)
                                  if bridge.projects else 0.0),
                   crease_gap_mm=float(bridge.top_width),
                   bridge=bridge)


# ------------------------------------------------------ the map of a drawing


def _flip(xy) -> np.ndarray:
    """Scene coordinates ↔ GuildModel's frame: (x, y) → (−x, −y), its own
    inverse."""
    return -np.asarray(xy, dtype=np.float64)[:, :2]


def _polygon_of(pts) -> "object | None":
    """A shapely polygon of a closed point list, or None when it has no
    area; a crossing one is repaired by the zero buffer."""
    from shapely.geometry import Polygon
    if len(pts) < 3:
        return None
    poly = Polygon(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly if not poly.is_empty and poly.area > 1e-9 else None


def bridge_from_lenses(lenses: list, outline_pts: list | None = None) -> BridgeGeometry:
    """The bridge geometry a drawing gives, GuildModel's fallback estimate
    (its `bridge_geometry` without a zone partition): the rims apexed at the
    lens centroids, the band half the gap between the lenses, the creases
    starting a band's width above the lens centers, the gap twice the band.

    *lenses* are closed point lists in scene coordinates, one per eye (a
    third or more is treated as the two outermost by x). A monocle (one
    lens) takes no face form and no projection, as GuildModel's does.
    """
    polys = [p for p in (_polygon_of(pts) for pts in lenses) if p is not None]
    if not polys:
        return BridgeGeometry()
    by_x = sorted(polys, key=lambda p: p.centroid.x)
    # GuildModel's frame. The rims are apexed at the two lenses the band is
    # measured between: a third curve on LENS between them (a mark, a slip)
    # pulled the apex toward the axis and tilted both lens planes.
    ends = by_x if len(by_x) < 3 else [by_x[0], by_x[-1]]
    cents = [(-p.centroid.x, -p.centroid.y) for p in ends]
    apex_x = float(np.mean([abs(cx) for cx, _ in cents]))
    apex_y = float(np.mean([cy for _, cy in cents]))
    if len(polys) < 2:
        x0, _, x1, _ = polys[0].bounds
        x0, x1 = -x1, -x0
        band = DEFAULT_BAND_HALF_MM
        if x0 < 0.0 < x1:
            apex_x = 0.0
        else:
            band = min(band, max(min(abs(x0), abs(x1)), 1e-3))
        return BridgeGeometry(apex_x, apex_y, band, apex_y + band, apex_y,
                              2.0 * band, -1.0, projects=False, wraps=False)
    od, os_ = by_x[0], by_x[-1]
    inner = sorted([od.bounds[0], od.bounds[2], os_.bounds[0], os_.bounds[2]])[1:3]
    gap = float(inner[1] - inner[0])
    band = 0.5 * gap if gap > 0 else DEFAULT_BAND_HALF_MM
    return BridgeGeometry(apex_x, apex_y, band, apex_y + band, apex_y,
                          2.0 * band, -1.0)


@dataclass
class FrontForming:
    """The forming of one drawn front: its parameters, the bridge geometry
    read off its lenses, and the map. Every method takes and gives scene
    coordinates; depths are from the anterior face."""
    params: ThermoformParams
    bridge: BridgeGeometry
    fmap: ThermoformMap = field(repr=False)

    @classmethod
    def build(cls, params: ThermoformParams, lenses: list,
              outline_pts: list | None = None) -> "FrontForming":
        bridge = bridge_from_lenses(lenses, outline_pts)
        return cls(params, bridge, ThermoformMap.from_params(params, bridge))

    @property
    def is_flat(self) -> bool:
        return self.fmap.is_flat

    def _z_in(self, depth_mm: float) -> float:
        return float(depth_mm) - self.params.neutral_fraction * self.params.sheet_thickness_mm

    def formed(self, xy, depth_mm: float = 0.0) -> np.ndarray:
        """The formed points, ``(N, 3)`` in GuildModel's frame: x and y
        flipped, +z toward the wearer."""
        xy = np.asarray(xy, dtype=np.float64)
        if len(xy) == 0:
            return np.zeros((0, 3))
        flat = np.column_stack([_flip(xy), np.full(len(xy), self._z_in(depth_mm))])
        return self.fmap(flat)

    def head_on(self, xy, depth_mm: float = 0.0) -> np.ndarray:
        """The points as seen from the front after forming, ``(N, 2)`` in
        scene coordinates: the formed x and y."""
        return _flip(self.formed(xy, depth_mm)[:, :2])

    def tilt_rad(self, center_x: float) -> float:
        """The lens plane's tilt at a lens center (scene x), radians, signed
        in GuildModel's frame."""
        return float(self.fmap.theta_at(-float(center_x)))

    def lens_plane(self, xy, center_x: float, depth_mm: float = 0.0) -> np.ndarray:
        """The points projected onto the lens plane, ``(N, 2)`` in scene-like
        coordinates (u across, v down): the plane tangent to the rim's
        sphere at the lens center, where ISO 8624 measures."""
        P = self.formed(xy, depth_mm)
        th = self.tilt_rad(center_x)
        u = P[:, 0] * math.cos(th) + P[:, 2] * math.sin(th)
        return _flip(np.column_stack([u, P[:, 1]]))

    def edge_sag(self, xy, center_x: float, center_y: float,
                 depth_mm: float = 0.0) -> float:
        """How far the lens edge sits behind the lens center along the lens
        plane's normal, mm: the sag of the formed lens, the research's
        ``R(1 − cos(A/2R))`` on a sphere."""
        P = self.formed(xy, depth_mm)
        if len(P) == 0:
            return 0.0
        th = self.tilt_rad(center_x)
        C = self.formed([[center_x, center_y]], depth_mm)[0]
        w = -P[:, 0] * math.sin(th) + P[:, 2] * math.cos(th)
        w0 = -C[0] * math.sin(th) + C[2] * math.cos(th)
        return float(np.abs(w - w0).max())

    def in_band(self, xy) -> np.ndarray:
        return self.fmap.in_band(_flip(xy)[:, 0])

    def fold_warning(self) -> str | None:
        return self.fmap.fold_warning(self.params.sheet_thickness_mm)


# ----------------------------------------------------------------- readouts


def _perimeter(pts) -> float:
    pts = np.asarray(pts, dtype=np.float64)
    if len(pts) < 2:
        return 0.0
    d = np.diff(np.vstack([pts, pts[:1]]), axis=0)
    return float(np.sqrt((d * d).sum(axis=1)).sum())


def _box(pts) -> tuple[float, float, float, float]:
    pts = np.asarray(pts, dtype=np.float64)
    return (float(pts[:, 0].min()), float(pts[:, 1].min()),
            float(pts[:, 0].max()), float(pts[:, 1].max()))


@dataclass
class LensReadout:
    """One eye's finished lens (the groove line), flat and formed."""
    a_flat: float
    b_flat: float
    a_lens_plane: float
    b_lens_plane: float
    a_head_on: float
    b_head_on: float
    circ_flat: float
    circ_lens_plane: float
    circ_3d: float
    edge_sag_mm: float
    tilt_deg: float                     # ZTILT: the lens plane's tilt, per eye
    box_flat: tuple
    box_head_on: tuple
    box_lens_plane: tuple
    in_band: bool                       # an edge inside the wrap band

    @property
    def a_off_iso(self) -> bool:
        """The lens-plane A more than ISO's tolerance off the flat A."""
        return abs(self.a_lens_plane - self.a_flat) > ISO_A_TOL_MM + 1e-9


#: How far a lens may reach into the bridge band unflagged, mm. The band
#: is half the gap between the drawn lenses, so a drawn lens sits on its
#: edge, a hair inside when the pair is a hair off the axis; the bend grows
#: from nothing at the band's edge, and half a millimeter in it is still
#: under a hundredth of the face form.
BAND_REACH_TOL_MM = 0.5


def lens_readout(ff: FrontForming, outline_pts: list,
                 depth_mm: float = GROOVE_APEX_MM,
                 outset_mm: float = 0.0) -> LensReadout | None:
    """The readout of one finished lens outline (a closed point list in
    scene coordinates), measured at the groove's depth. *outset_mm* is how
    far the outline was grown from the drawn lens (the bevel depth): the
    band is measured from the drawn lenses, so the finished outline always
    sits that far inside it."""
    pts = np.asarray(outline_pts, dtype=np.float64)
    if len(pts) < 3:
        return None
    # The map bends a straight side: a polygon lens formed from its corners
    # alone read up to a millimeter narrow (the 2.3 sweep).
    pts = densify(pts)
    bf = _box(pts)
    cx = 0.5 * (bf[0] + bf[2])
    head = ff.head_on(pts, depth_mm)
    plane = ff.lens_plane(pts, cx, depth_mm)
    P = ff.formed(pts, depth_mm)
    bh, bp = _box(head), _box(plane)
    return LensReadout(
        a_flat=bf[2] - bf[0], b_flat=bf[3] - bf[1],
        a_lens_plane=bp[2] - bp[0], b_lens_plane=bp[3] - bp[1],
        a_head_on=bh[2] - bh[0], b_head_on=bh[3] - bh[1],
        circ_flat=_perimeter(pts), circ_lens_plane=_perimeter(plane),
        circ_3d=_perimeter(P),
        edge_sag_mm=ff.edge_sag(pts, cx, 0.5 * (bf[1] + bf[3]), depth_mm),
        tilt_deg=abs(math.degrees(ff.tilt_rad(cx))),
        box_flat=bf, box_head_on=bh, box_lens_plane=bp,
        in_band=bool((np.abs(pts[:, 0]) < ff.bridge.band_half - max(outset_mm, 0.0)
                      - BAND_REACH_TOL_MM).any()),
    )


@dataclass
class FrontReadout:
    """The front's readouts, flat → formed. ``od`` is the lens with the
    smaller scene x (the wearer's right), ``os`` the other; one may be None."""
    od: LensReadout | None
    os: LensReadout | None
    dbl_flat: float | None
    dbl_head_on: float | None
    centers_flat: float | None          # boxed-center distance
    centers_head_on: float | None
    width_flat: float | None            # the outline's overall width
    width_head_on: float | None
    depth_mm: float | None              # the formed outline's z range
    endpiece_set_mm: float | None       # the endpieces' z past the bridge, toward the face
    bridge_set_mm: float
    flags: list = field(default_factory=list)


def front_readout(ff: FrontForming, od_pts: list | None, os_pts: list | None,
                  outlines: list | None = None,
                  depth_mm: float = GROOVE_APEX_MM,
                  outset_mm: float = 0.0) -> FrontReadout:
    """Everything the panel shows for a front: the two lenses (finished
    outlines, scene coordinates, grown *outset_mm* from the drawn lenses),
    the DBL and the boxed-center distance between them head-on, and the
    OUTLINE's width, depth and endpiece set (*outlines*: the outline
    curves' point lists, Ghost twins included)."""
    od = lens_readout(ff, od_pts, depth_mm, outset_mm) if od_pts else None
    os_ = lens_readout(ff, os_pts, depth_mm, outset_mm) if os_pts else None
    dbl_f = dbl_h = cf = ch = None
    if od is not None and os_ is not None:
        dbl_f = os_.box_flat[0] - od.box_flat[2]
        dbl_h = os_.box_head_on[0] - od.box_head_on[2]
        cf = (0.5 * (os_.box_flat[0] + os_.box_flat[2])
              - 0.5 * (od.box_flat[0] + od.box_flat[2]))
        ch = (0.5 * (os_.box_head_on[0] + os_.box_head_on[2])
              - 0.5 * (od.box_head_on[0] + od.box_head_on[2]))
    wf = wh = depth = endpiece = None
    pts = [p for o in (outlines or []) for p in o]
    if len(pts) >= 2:
        arr = np.asarray(pts, dtype=np.float64)
        wf = float(arr[:, 0].max() - arr[:, 0].min())
        P = ff.formed(arr, 0.0)
        wh = float(P[:, 0].max() - P[:, 0].min())
        depth = float(P[:, 2].max() - P[:, 2].min())
        # The bridge's z at the outline's center line against the endpieces':
        # the outermost point each side, averaged.
        i_lo, i_hi = int(np.argmin(P[:, 0])), int(np.argmax(P[:, 0]))
        center = ff.fmap(np.array([[0.0, -float(arr[:, 1].mean()), 0.0]]))[0, 2]
        endpiece = float(0.5 * (P[i_lo, 2] + P[i_hi, 2]) - center)
    flags = []
    for side, r in (("OD", od), ("OS", os_)):
        if r is None:
            continue
        if r.a_off_iso:
            flags.append(f"{side}: A in the lens plane is {r.a_lens_plane - r.a_flat:+.2f} mm "
                         f"off the flat A, past ISO's ±{ISO_A_TOL_MM:.1f} mm; draw the lens "
                         "larger, or use Flatten Lens Shape.")
        if r.in_band:
            flags.append(f"{side}: the lens reaches into the bridge band "
                         f"(±{ff.bridge.band_half:.1f} mm of the axis), where the face "
                         "form bends the sheet; it forms bent.")
    fold = ff.fold_warning()
    if fold:
        flags.append("The sheet folds: " + fold + ".")
    return FrontReadout(od, os_, dbl_f, dbl_h, cf, ch, wf, wh, depth, endpiece,
                        ff.fmap.bridge_set_mm(), flags)


# ------------------------------------------------------------------- unform
# Flatten Lens Shape, on the panel.


#: How near the flattened lens, formed again, lies to the drawn one, mm:
#: the fitter's own tolerance (`fitting.fit_curve` on an imported trace).
#: A span that misses it gets a node at its middle; the drawn nodes stay.
UNFORM_TOL_MM = 0.015
#: Samples a span, how often a span may be halved, and the step along a
#: tangent that finds the flat curve's own.
_UNFORM_SAMPLES = 24
_UNFORM_ROUNDS = 5
_UNFORM_STEP_MM = 0.01


class UnformDiverged(ValueError):
    """The flat shape could not be found: the forming is too deep for the
    search to settle (past base 10 or so with a deep face form)."""


def unform_points(ff: FrontForming, target_xy, center_x: float,
                  depth_mm: float = GROOVE_APEX_MM, iters: int = 12,
                  stop_mm: float = 1e-6) -> np.ndarray:
    """The flat points that form to *target_xy* in the lens plane (research
    §4.4): a fixed-point iteration, ``q ← q + (p − plane(q))``, which
    converges in a few steps because the map is smooth and close to the
    identity across a lens. ``(N, 2)`` in scene coordinates."""
    p = np.asarray(target_xy, dtype=np.float64)[:, :2]
    if len(p) == 0 or ff.is_flat:
        return p.copy()
    q = p.copy()
    for _ in range(iters):
        err = p - ff.lens_plane(q, center_x, depth_mm)
        q += err
        if float(np.abs(err).max()) < stop_mm:
            break
    return q


def _unform_settled(ff: FrontForming, pts, center_x: float, depth_mm: float) -> np.ndarray:
    """`unform_points` run to the end, or `UnformDiverged`: the iteration
    returned its last guess whatever it missed by (48 mm at base 16)."""
    q = unform_points(ff, pts, center_x, depth_mm, iters=60, stop_mm=1e-10)
    if len(q) and not ff.is_flat:
        miss = float(np.abs(np.asarray(pts, dtype=np.float64)[:, :2]
                            - ff.lens_plane(q, center_x, depth_mm)).max())
        if not miss < 1e-6:
            raise UnformDiverged(
                f"the flat shape was not found (off by {miss:.2g} mm): the base "
                "curve and the face form are too deep for this lens")
    return q


def _bezier_points(c, t: np.ndarray) -> np.ndarray:
    c = np.asarray(c, dtype=np.float64)
    u = 1.0 - t
    return (np.outer(u ** 3, c[0]) + np.outer(3.0 * u * u * t, c[1])
            + np.outer(3.0 * u * t * t, c[2]) + np.outer(t ** 3, c[3]))


def _cubics_center_x(spans: list) -> float:
    """The middle of the cubics' own x extent (their turning points, not a
    sampling): the lens center the readouts take, where the lens plane is."""
    xs = []
    for c in spans:
        x0, x1, x2, x3 = (float(p[0]) for p in c)
        xs += [x0, x3]
        # x'(t) / 3 = a t² + b t + c0
        a, b, c0 = (x3 - 3.0 * x2 + 3.0 * x1 - x0), 2.0 * (x2 - 2.0 * x1 + x0), (x1 - x0)
        if abs(a) < 1e-12:
            roots = [-c0 / b] if abs(b) > 1e-12 else []
        else:
            disc = b * b - 4.0 * a * c0
            roots = ([(-b + sg * math.sqrt(disc)) / (2.0 * a) for sg in (1.0, -1.0)]
                     if disc >= 0.0 else [])
        for r in roots:
            if 0.0 < r < 1.0:
                u = 1.0 - r
                xs.append(u ** 3 * x0 + 3 * u * u * r * x1 + 3 * u * r * r * x2 + r ** 3 * x3)
    return 0.5 * (min(xs) + max(xs))


def _even_cubic(c) -> list:
    """A straight run (both handles retracted) as a cubic of even speed, so
    its unformed bow has handles to be fitted with."""
    p0, p1, p2, p3 = (tuple(map(float, p)) for p in c)
    if p1 == p0 and p2 == p3:
        dx, dy = (p3[0] - p0[0]) / 3.0, (p3[1] - p0[1]) / 3.0
        return [p0, (p0[0] + dx, p0[1] + dy), (p3[0] - dx, p3[1] - dy), p3]
    return [p0, p1, p2, p3]


def _end_dir(a, *others):
    """The unit direction from *a* to the first of *others* not on it."""
    for b in others:
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy)
        if n > 1e-12:
            return dx / n, dy / n
    return None


def _smooth_joints(spans: list, closed: bool) -> list:
    """``(j, k, tangent)`` for each joint of consecutive spans the drawn
    curve passes through without a corner: its tangents there in line."""
    out = []
    for k in range(len(spans)):
        j = k - 1 if k else (len(spans) - 1 if closed else None)
        if j is None or (j == k):
            continue
        a = _end_dir(spans[j][2], spans[j][3]) or _end_dir(spans[j][1], spans[j][3]) \
            or _end_dir(spans[j][0], spans[j][3])
        b = _end_dir(spans[k][0], spans[k][1], spans[k][2], spans[k][3])
        if a is None or b is None:
            continue
        if a[0] * b[0] + a[1] * b[1] > 0.0 and abs(a[0] * b[1] - a[1] * b[0]) < 1e-4:
            n = math.hypot(a[0] + b[0], a[1] + b[1])
            out.append((j, k, ((a[0] + b[0]) / n, (a[1] + b[1]) / n)))
    return out


def unform_curve(curve: Curve, ff: FrontForming,
                 depth_mm: float = GROOVE_APEX_MM,
                 tol_mm: float = UNFORM_TOL_MM) -> Curve:
    """A copy of *curve* that is the flat shape forming to the drawn one in
    the lens plane, within *tol_mm* all along it.

    Each span's samples are unformed and a cubic is fitted through them:
    the nodes land exactly, the handles are solved by least squares at the
    samples' own parameters, and the two handles at a node the drawn curve
    runs smoothly through are turned into one line. A span that still
    misses the tolerance gets a node at its middle, so the drawn nodes are
    kept and no more are added than the forming asks for. (2.3 shipped to
    the maker with the handles sent through the map as if they lay on the
    lens: 0.03 to 0.26 mm off between the nodes at base 4, the library's
    two-node lens 0.4 mm wide.) A circle, an arc or a polygon becomes a
    spline: formed, its sides are arcs and straights no more.
    `UnformDiverged` when the forming is too deep for a flat shape to be
    found."""
    import copy
    if curve.kind == "circle":
        src = circle_to_spline(curve)
    elif curve.kind == "arc":
        src = arc_to_spline(curve)
    else:
        src = copy.deepcopy(curve)
    if ff.is_flat or len(src.nodes) < 2:
        return src
    spans = [_even_cubic(c) for c in _curve_cubics(src)]
    if not spans:
        return src
    closed = bool(src.closed)
    t = np.linspace(0.0, 1.0, _UNFORM_SAMPLES + 1)
    u = 1.0 - t
    b0, b1, b2, b3 = u ** 3, 3.0 * u * u * t, 3.0 * u * t * t, t ** 3
    # The two handles of a span, free: [x1, y1, x2, y2] offsets from its ends.
    A = np.zeros((2 * len(t), 4))
    A[0::2, 0] = A[1::2, 1] = b1
    A[0::2, 2] = A[1::2, 3] = b2

    def solve(q, d1=None, d2=None):
        """The span through the samples *q*: each handle free, or held to a
        line through its node (*d1* at the start, *d2* at the end)."""
        q0, q3 = q[0], q[-1]
        rest = (q - np.outer(b0 + b1, q0) - np.outer(b2 + b3, q3)).reshape(-1)
        cols = [A[:, 0:2] if d1 is None else (A[:, 0:2] @ d1)[:, None],
                A[:, 2:4] if d2 is None else (A[:, 2:4] @ d2)[:, None]]
        x = np.linalg.lstsq(np.hstack(cols), rest, rcond=None)[0]
        n1 = cols[0].shape[1]
        h1 = x[:n1] if d1 is None else x[0] * d1
        h2 = x[n1:] if d2 is None else x[n1] * d2
        return [q0, q0 + h1, q3 + h2, q3]

    def misses(fits, flat):
        return [float(np.sqrt(((_bezier_points(f, t) - q) ** 2).sum(axis=1)).max())
                for f, q in zip(fits, flat, strict=True)]

    center_x = _cubics_center_x(spans)   # the lens's own, as the readouts take it
    fitted: list = []
    for rnd in range(_UNFORM_ROUNDS + 1):
        joints = _smooth_joints(spans, closed)
        # Each span's samples, and a step along the drawn tangent at each
        # smooth node: where that lands is the flat curve's own tangent.
        probes = [(spans[k][0][0] + _UNFORM_STEP_MM * d[0], spans[k][0][1] + _UNFORM_STEP_MM * d[1])
                  for _, k, d in joints]
        drawn = np.vstack([_bezier_points(c, t) for c in spans] + [np.reshape(probes, (-1, 2))])
        settled = _unform_settled(ff, drawn, center_x, depth_mm)
        flat = settled[:len(spans) * len(t)].reshape(len(spans), len(t), 2)
        free = [solve(q) for q in flat]
        # A node the drawn curve runs smoothly through keeps one line for its
        # two handles (left free, the two fits met there up to a degree off
        # line, a corner to the Offset tool). Two lines are tried, the flat
        # curve's own tangent and the mean of the two free fits', and the
        # spans solved again along each; the better set stands.
        tangent, mean = {}, {}
        for (j, k, _), probe in zip(joints, settled[len(spans) * len(t):], strict=True):
            node = free[k][0]
            d = probe - node
            n = float(np.hypot(*d))
            if n > 1e-12:
                tangent[(k, 0)] = tangent[(j, 1)] = d / n
            vin, vout = free[j][2] - node, free[k][1] - node
            lin, lout = float(np.hypot(*vin)), float(np.hypot(*vout))
            if lin > 1e-9 and lout > 1e-9:
                d = vout / lout - vin / lin
                n = float(np.hypot(*d))
                if n > 1e-9:
                    mean[(k, 0)] = mean[(j, 1)] = d / n
        best = None
        for held in (tangent, {**tangent, **mean}):
            fits = [solve(q, held.get((k, 0)), held.get((k, 1))) for k, q in enumerate(flat)]
            miss = misses(fits, flat)
            score = (sum(m > tol_mm for m in miss), max(miss))
            if best is None or score < best[0]:
                best = (score, fits, miss)
        _, fitted, miss = best
        if rnd == _UNFORM_ROUNDS or max(miss) <= tol_mm:
            break
        halved = []
        for c, m in zip(spans, miss, strict=True):
            halved += list(split_bezier_at_t(*c, 0.5)) if m > tol_mm else [c]
        spans = halved
    out = _cubics_curve([[tuple(map(float, pt)) for pt in f] for f in fitted], src)
    out.kind = "spline"
    return out


# --------------------------------------------------------- the temple's bend

#: The drop a temple is given when the file names no length to bend, mm:
#: the research's default (§5.2), from the 35–40 mm the trade bends.
DEFAULT_DROP_MM = 37.0


@dataclass
class TipBendParams:
    """A temple tab's tip bend, as the ``.gdraw`` stores it under
    ``tip_bend``: the length to bend from the hinge end (0 = the drawn
    length less `DEFAULT_DROP_MM`), the downward angle of the drop (0 is a
    library temple, straight) and the bend's radius, which nothing in the
    trade publishes and so is a field."""
    length_to_bend_mm: float = 0.0
    drop_angle_deg: float = 50.0
    bend_radius_mm: float = 15.0

    KEYS = ("length_to_bend_mm", "drop_angle_deg", "bend_radius_mm")

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.KEYS}

    @classmethod
    def from_dict(cls, d) -> "TipBendParams":
        out = cls()
        if not isinstance(d, dict):
            return out

        def num(key, lo, hi):
            try:
                f = float(d.get(key))
            except (TypeError, ValueError):
                return getattr(out, key)
            return min(max(f, lo), hi) if math.isfinite(f) else getattr(out, key)

        out.length_to_bend_mm = num("length_to_bend_mm", 0.0, 300.0)
        out.drop_angle_deg = num("drop_angle_deg", 0.0, 90.0)
        out.bend_radius_mm = num("bend_radius_mm", 0.5, 100.0)
        return out


@dataclass
class TipBend:
    """The bend resolved against a drawn temple: the core keeps its length
    (the wire's), and the ear point sits at the middle of the arc, so the
    straight run is ``length to bend − r·δ/2``, the arc ``r·δ`` and the
    tail the rest. Points move by their (arc length along the core, offset
    from the core) coordinates. `down` is the sign of scene y the drop goes
    toward: +1 on the right temple's tab, −1 on the left's, whose drawing is
    the right's mirror about the core line (GuildModel's `temple_axes` reads
    the same two signs after its intake's flip)."""
    x_hinge: float
    overall_mm: float
    length_to_bend_mm: float
    drop_angle_deg: float
    bend_radius_mm: float
    core_y: float = 0.0
    down: float = 1.0

    @classmethod
    def resolve(cls, params: TipBendParams, x_hinge: float, overall_mm: float,
                core_y: float = 0.0, down: float = 1.0) -> "TipBend":
        ltb = params.length_to_bend_mm
        if ltb <= 0.0:
            ltb = max(overall_mm - DEFAULT_DROP_MM, 0.0)
        return cls(float(x_hinge), float(overall_mm), float(ltb),
                   float(params.drop_angle_deg), float(params.bend_radius_mm),
                   float(core_y), 1.0 if down >= 0 else -1.0)

    @property
    def angle_rad(self) -> float:
        return math.radians(self.drop_angle_deg)

    @property
    def arc_mm(self) -> float:
        return self.bend_radius_mm * self.angle_rad

    @property
    def straight_mm(self) -> float:
        """The straight run from the hinge end to the arc's start."""
        return self.length_to_bend_mm - 0.5 * self.arc_mm

    @property
    def tail_mm(self) -> float:
        """The straight run from the arc's end to the tip."""
        return self.overall_mm - self.length_to_bend_mm - 0.5 * self.arc_mm

    @property
    def drop_mm(self) -> float:
        """ISO's length of drop: from the ear point to the tip, straightened."""
        return self.overall_mm - self.length_to_bend_mm

    @property
    def is_straight(self) -> bool:
        return self.drop_angle_deg <= 0.0 or self.overall_mm <= 0.0

    def out_of_range(self) -> str | None:
        """Why the bend does not fit this temple, or None when it does."""
        if self.overall_mm <= 0.0:
            return None
        if self.length_to_bend_mm >= self.overall_mm:
            return (f"the length to bend ({self.length_to_bend_mm:.1f} mm) is the whole "
                    f"temple ({self.overall_mm:.1f} mm): nothing is left to drop")
        if self.straight_mm < 0.0:
            return (f"the bend (R {self.bend_radius_mm:.1f} mm over {self.drop_angle_deg:.0f}°) "
                    f"starts before the hinge: {0.5 * self.arc_mm:.1f} mm of arc each side "
                    f"of the ear point, with {self.length_to_bend_mm:.1f} mm to bend")
        if self.tail_mm < 0.0:
            return (f"the bend (R {self.bend_radius_mm:.1f} mm over {self.drop_angle_deg:.0f}°) "
                    f"runs past the tip: {0.5 * self.arc_mm:.1f} mm of arc each side of the "
                    f"ear point, with {self.drop_mm:.1f} mm to drop")
        return None

    def map_points(self, xy) -> np.ndarray:
        """Bend the points, ``(N, 2)`` scene coordinates; the identity when
        the bend is straight or out of range."""
        P = np.asarray(xy, dtype=np.float64)[:, :2].copy()
        if len(P) == 0 or self.is_straight or self.out_of_range():
            return P
        s = P[:, 0] - self.x_hinge                  # along the core
        d = (P[:, 1] - self.core_y) * self.down     # off the core, down +
        s1, r, delta = self.straight_mm, self.bend_radius_mm, self.angle_rad
        xs, ds = s.copy(), d.copy()                 # bent, in the same frame
        on_arc = (s > s1) & (s <= s1 + self.arc_mm)
        past = s > s1 + self.arc_mm
        # the arc: its center r below the core at the arc's start
        a = (s[on_arc] - s1) / r
        xs[on_arc] = s1 + (r - d[on_arc]) * np.sin(a)
        ds[on_arc] = r - (r - d[on_arc]) * np.cos(a)
        # the tail: from the arc's end, along its direction
        ex, ey = s1 + r * math.sin(delta), r - r * math.cos(delta)
        t = s[past] - s1 - self.arc_mm
        xs[past] = ex + t * math.cos(delta) - d[past] * math.sin(delta)
        ds[past] = ey + t * math.sin(delta) + d[past] * math.cos(delta)
        return np.column_stack([self.x_hinge + xs, self.core_y + self.down * ds])

    def tip(self) -> tuple[float, float]:
        """Where the core's end lands, scene coordinates."""
        p = self.map_points([[self.x_hinge + self.overall_mm, self.core_y]])[0]
        return float(p[0]), float(p[1])

    @property
    def reach_mm(self) -> float:
        """The bent temple's projected length, hinge end to tip along x."""
        return self.tip()[0] - self.x_hinge

    @property
    def tip_drop_mm(self) -> float:
        """How far the tip sits below the core, mm: toward `down`."""
        return (self.tip()[1] - self.core_y) * self.down


#: The longest chord a formed polyline may have, mm. A straight run is its
#: two ends when flat, and the press and the bend move its middle too.
MAX_CHORD_MM = 1.0


def densify(pts, max_chord_mm: float = MAX_CHORD_MM) -> np.ndarray:
    """*pts* with every chord longer than *max_chord_mm* cut into equal
    parts, ``(N, 2)``. A closed list (last point on the first) stays so; an
    open one is not closed."""
    P = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
    if len(P) < 2:
        return P.copy()
    d = np.hypot(*(P[1:] - P[:-1]).T)
    k = np.maximum(np.ceil(d / max(float(max_chord_mm), 1e-6)), 1.0).astype(int)
    if int(k.max()) == 1:
        return P.copy()
    start = np.repeat(np.arange(len(k)), k)
    step = np.concatenate([np.arange(n) for n in k]) / np.repeat(k, k)
    out = P[start] + (P[start + 1] - P[start]) * step[:, None]
    return np.vstack([out, P[-1:]])


def flatten_for_view(curve: Curve, tol_mm: float = 0.02) -> list:
    """A curve as a point list for the formed views, closed curves closed
    and no chord past `MAX_CHORD_MM`: the view bends polylines, which keeps
    the geometry questions (how a handle bends) out of a view-only feature.
    A straight side was its two ends, and a temple drawn with the Line tool
    showed bent as a skewed quadrilateral, 22 mm off (the 2.3 sweep)."""
    pts = flatten_curve(curve, tol_mm)
    if curve.closed and len(pts) > 2 and (abs(pts[0][0] - pts[-1][0]) > 1e-9
                                          or abs(pts[0][1] - pts[-1][1]) > 1e-9):
        pts = list(pts) + [pts[0]]
    if len(pts) < 2:
        return list(pts)
    return [(float(x), float(y)) for x, y in densify(pts)]


def is_lens(curve: Curve) -> bool:
    return curve.layer == Layer.LENS and bool(curve.nodes)


def is_lens_shape(curve: Curve) -> bool:
    """A LENS curve that bounds a shape: closed, or open with its ends met
    within the 0.1 mm the OMA export takes for closed. A stray line or a
    half-drawn lens on LENS is no lens: closed as a polygon, it moved the
    rims' apex, and Flatten Lens Shape "flattened" it."""
    if not is_lens(curve):
        return False
    if curve.closed or curve.kind == "circle":
        return True
    if curve.kind == "arc" or len(curve.nodes) < 2:
        return False
    a, b = curve.nodes[0], curve.nodes[-1]
    return (math.hypot(b.x - a.x, b.y - a.y) <= 0.1
            and (len(curve.nodes) > 2 or a.cp_out is not None or b.cp_in is not None))
