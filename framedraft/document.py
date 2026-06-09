from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum


class Layer(str, Enum):
    OUTLINE   = "OUTLINE"
    LENS      = "LENS"
    BRIDGE    = "BRIDGE"
    HINGE     = "HINGE"
    REF       = "REF"
    SCULPT    = "SCULPT"     # back-surface scallop lines (Frame Front → GuildCAM)
    ENGRAVING = "ENGRAVING"  # engraving marks (Temple)


MACHINED_LAYERS = {Layer.OUTLINE, Layer.LENS, Layer.BRIDGE, Layer.HINGE}
ALL_LAYER_NAMES = {l.value for l in Layer}

# Layers available per workspace (strict — layer combo filtered to these).
# BRIDGE exists in the enum for future GuildCAM bridge-path tooling (deferred).
WORKSPACE_LAYERS: dict[str, list[Layer]] = {
    "front":    [Layer.OUTLINE, Layer.LENS,      Layer.SCULPT, Layer.HINGE, Layer.REF],
    "temple_r": [Layer.OUTLINE, Layer.ENGRAVING, Layer.SCULPT, Layer.HINGE, Layer.REF],
    "temple_l": [Layer.OUTLINE, Layer.ENGRAVING, Layer.SCULPT, Layer.HINGE, Layer.REF],
    "hinge":    [Layer.HINGE,   Layer.REF],
}


@dataclass
class FaceImage:
    path: str = ""
    tx: float = 0.0
    ty: float = 0.0
    rotation: float = 0.0
    opacity: float = 0.7


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
    mirrored: bool = False
    line_weight: float = 1.5
    radius: Optional[float] = None       # circle / arc radius (mm)
    start_angle: Optional[float] = None  # arc start angle (degrees; 0=right, 90=down-screen)
    end_angle: Optional[float] = None    # arc end angle (degrees, same convention)


@dataclass
class DimLine:
    x0: float
    y0: float
    x1: float
    y1: float
    offset: float = 0.0   # perpendicular displacement of the dim line (mm)


@dataclass
class Document:
    face_image: FaceImage = field(default_factory=FaceImage)
    calibration: Calibration = field(default_factory=Calibration)
    units: str = "mm"
    mirror_axis: MirrorAxis = field(default_factory=MirrorAxis)
    forming_metadata: FormingMetadata = field(default_factory=FormingMetadata)
    machined_bridge: MachinedBridge = field(default_factory=MachinedBridge)
    curves: List[Curve] = field(default_factory=list)


@dataclass
class WorkspaceDocument:
    """All serialisable state for one workspace tab (front / temple / hinge)."""
    workspace_type: str                                # "front" | "temple" | "hinge"
    curves:         List[Curve]        = field(default_factory=list)
    dims:           List[DimLine]      = field(default_factory=list)
    calibration:    Calibration        = field(default_factory=Calibration)
    mirror:         MirrorAxis         = field(default_factory=MirrorAxis)
    forming:        FormingMetadata    = field(default_factory=FormingMetadata)
    face_images:    List[FaceImage]    = field(default_factory=list)
    bookmarks:      list               = field(default_factory=list)
