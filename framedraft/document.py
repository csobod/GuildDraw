from dataclasses import dataclass
from typing import Optional, List
from enum import Enum


# Layer names a drawing may carry for a layer read under another name. HINGE
# became COMPONENT in 2.0, and every drawing, library entry and DXF made
# before says HINGE, so the alias is permanent; only COMPONENT is written.
# GuildModel's core/layers.py keeps the same table.
LAYER_ALIASES: dict[str, str] = {"HINGE": "COMPONENT"}


class Layer(str, Enum):
    OUTLINE   = "OUTLINE"
    LENS      = "LENS"
    BRIDGE    = "BRIDGE"
    COMPONENT = "COMPONENT"  # a pocket for what mounts on the posterior: hinges,
                             # bridges, endpieces, bridge bars (HINGE before 2.0)
    DRILL     = "DRILL"      # drill-mount holes (Frame Front; circles → DXF/OMA)
    REF       = "REF"
    SCULPT    = "SCULPT"     # back-surface scallop lines (Frame Front → GuildModel)
    ENGRAVING = "ENGRAVING"  # engraving marks (Temple)
    INLAY     = "INLAY"      # a seat for a plaque, a laminate or a plate (2.0; front
                             # and temples). GuildModel owns its depth and face.

    @classmethod
    def _missing_(cls, value):
        """An alias reads as its layer: Layer("HINGE") is COMPONENT, in every
        reader (the .gdraw, the library, an imported DXF or SVG)."""
        if isinstance(value, str) and value in LAYER_ALIASES:
            return cls(LAYER_ALIASES[value])
        return None


MACHINED_LAYERS = {Layer.OUTLINE, Layer.LENS, Layer.BRIDGE, Layer.COMPONENT, Layer.DRILL,
                   Layer.INLAY}
# Every name a reader recognizes, the aliases included.
ALL_LAYER_NAMES = {l.value for l in Layer} | set(LAYER_ALIASES)

# Layers the Ghost previews across the mirror axis, on the canvas and while
# drawing. OUTLINE is handled separately: it spans the full frame, so only an
# OPEN half ghosts (or, on a front, a closed rim beside the axis). One set for
# both users, the scene and the draw tool. The Ghost is a drawing aid: since
# 2.0 nothing exports it, as GuildModel never applies it; the validator names
# each twin no drawn curve stands for, and the OMA trace pairs lenses and
# holes on its own.
MIRRORED_LAYERS = {Layer.LENS, Layer.COMPONENT, Layer.SCULPT, Layer.DRILL}

# Layers available per workspace (strict — layer combo filtered to these).
# BRIDGE exists in the enum for future GuildModel bridge-path tooling (deferred).
# INLAY is never mirrored: a seat is drawn where it is cut, and a pair comes
# from Mirror (bake), the way OUTLINE and ENGRAVING work.
WORKSPACE_LAYERS: dict[str, list[Layer]] = {
    "front":     [Layer.OUTLINE, Layer.LENS, Layer.DRILL, Layer.SCULPT, Layer.INLAY,
                  Layer.COMPONENT, Layer.REF],
    "temple_r":  [Layer.OUTLINE, Layer.ENGRAVING, Layer.INLAY, Layer.SCULPT,
                  Layer.COMPONENT, Layer.REF],
    "temple_l":  [Layer.OUTLINE, Layer.ENGRAVING, Layer.INLAY, Layer.SCULPT,
                  Layer.COMPONENT, Layer.REF],
    # The Component tab, where a component is drawn for the library; the
    # Hinge Pocket tab ("hinge") before 2.0.
    "component": [Layer.COMPONENT, Layer.REF],
}

# Workspace names a file may carry for a workspace read under another name:
# the Component tab was "hinge" (hinge.svg) before 2.0.
WORKSPACE_ALIASES: dict[str, str] = {"hinge": "component"}


@dataclass
class FaceImage:
    path: str = ""
    tx: float = 0.0
    ty: float = 0.0
    rotation: float = 0.0
    opacity: float = 0.7
    # The photo's own calibration, image px per mm (2.0); None for a photo
    # never calibrated, or from a file that kept one for the whole design.
    px_per_mm: Optional[float] = None
    # Shown on the canvas; fixed in place, turn and scale (2.0).
    visible: bool = True
    locked: bool = True
    # Stored in the design (2.0): the photo goes into the .gdraw and shows on
    # any computer. Not stored, the file names it by link_id alone, a random
    # id this computer's image_links table maps to the photo's file, so a
    # patient's photo never leaves the machine in a design. A file from
    # before 2.0 stored every photo, and reads so.
    stored: bool = False
    link_id: str = ""


@dataclass
class Calibration:
    px_per_mm: Optional[float] = None

    @property
    def is_set(self) -> bool:
        return self.px_per_mm is not None and self.px_per_mm > 0


@dataclass
class MirrorAxis:
    enabled: bool = True
    x: float = 0.0


@dataclass
class FormingMetadata:
    bridge_angle_deg: float = 0.0
    apical_radius_mm: float = 0.0


# Bevel-offset presets: preset key -> outward offset depth (mm) of the finished
# (beveled) lens edge beyond the bare lens-material shape.  Drives the boxing
# guide's finished-measurement outline and the A/B/DBL the boxing system reports.
BEVEL_PRESETS: dict[str, float] = {
    "flat":       0.0,   # flat / rimless (drill-mount lenses — no bevel)
    "horn_metal": 0.5,
    "acetate":    1.0,
}


@dataclass
class BevelSpec:
    """Lens bevel model.

    *depth_mm* is how far the finished (beveled) lens sits proud of the bare
    lens-material shape on every edge.  ``preset == "custom"`` keeps a
    user-entered depth; the other presets derive their depth from
    ``BEVEL_PRESETS``.  ``depth_mm == 0`` (flat/rimless) means no bevel outline
    is drawn and the lens is drill-mount eligible.
    """
    preset:   str   = "acetate"
    depth_mm: float = 1.0

    @classmethod
    def from_preset(cls, preset: str) -> "BevelSpec":
        if preset in BEVEL_PRESETS:
            return cls(preset=preset, depth_mm=BEVEL_PRESETS[preset])
        return cls(preset=preset, depth_mm=0.0)


@dataclass
class MachinedBridge:
    depth_mm: float = 4.0
    width_mm: float = 5.0


@dataclass
class ControlPoint:
    x: float
    y: float


@dataclass
class SplineNode:
    x: float
    y: float
    cp_in: Optional[ControlPoint] = None
    cp_out: Optional[ControlPoint] = None


@dataclass
class Curve:
    kind: str        # "line" | "spline" | "circle" | "arc"
    layer: Layer
    nodes: List      # List[SplineNode]; for circle/arc, nodes[0] = center
    closed: bool = False
    mirrored: bool = False   # legacy: nothing sets this anymore (mirror copies
                             # are plain geometry since M-era Mirror rework);
                             # kept because old saved files may still carry it
    line_weight: float = 1.5
    radius: Optional[float] = None       # circle / arc radius (mm)
    start_angle: Optional[float] = None  # arc start angle (degrees; 0=right, 90=down-screen)
    end_angle: Optional[float] = None    # arc end angle (degrees, same convention)
    group_id: Optional[str] = None       # curves sharing a group_id select/move as
                                         # a rigid unit and expose no node editing
    component_kind: Optional[str] = None # on a COMPONENT curve: the top-level
                                         # library folder it was placed from
                                         # ("Hinges", "Bridges"); None when drawn
                                         # by hand. Saved as "component_kind",
                                         # since "kind" is the curve's type.


@dataclass
class TextObject:
    """Re-editable text insertion (ENGRAVING workflow, M8).

    Rendered as font outline paths on canvas and converted to closed
    spline Curves at DXF-export time — the TextObject itself is never
    exported, so the string/font/size stay editable in the document.
    """
    text:        str
    family:      str
    size_mm:     float            # cap height in mm
    rotation:    float = 0.0      # degrees; positive = CCW as displayed
    anchor_x:    float = 0.0      # baseline-left origin, scene mm
    anchor_y:    float = 0.0
    layer:       Layer = Layer.ENGRAVING
    line_weight: float = 1.0


@dataclass
class DimLine:
    x0: float
    y0: float
    x1: float
    y1: float
    offset: float = 0.0   # perpendicular displacement of the dim line (mm)


# NOTE: the old aggregate `Document` / `WorkspaceDocument` dataclasses were
# never adopted and were removed in M4 (v0.9.4). The live per-workspace state
# is `framedraft.app.WorkspaceState`, whose document-mutation primitives are
# the single source of truth for the curves/dims lists and undo snapshots.
