"""
SVG native save / load.

Format:
  Standard SVG 1.1 with path elements for each curve.
  A <metadata> child of the root <svg> holds a JSON blob with all app state
  (calibration, mirror axis, forming metadata, layer assignments, face image).

Coordinate system: scene units = mm (1 scene unit = 1 mm).
viewBox and width/height are always emitted in mm so the SVG renders at
true physical scale in Inkscape and other viewers.

The calibration.px_per_mm value stored in metadata is the face-image
calibration (image pixels per real-world mm).  It is NOT applied to
geometry coordinates, which are already in mm.
"""

import json
import os
from xml.etree import ElementTree as ET

from PySide6.QtGui import QPainterPath

from ..document import (
    Curve, Layer, SplineNode, ControlPoint,
    FaceImage, Calibration, MirrorAxis, FormingMetadata, MachinedBridge, DimLine,
    TextObject, BevelSpec,
)
from ..canvas.items import build_path


_NS  = "http://www.w3.org/2000/svg"
_XNS = "http://www.w3.org/XML/1998/namespace"


# ---------- path-data helpers ----------

def _path_d(curve: Curve) -> str:
    path = build_path(curve)
    d    = []
    n    = path.elementCount()
    i    = 0
    while i < n:
        el = path.elementAt(i)
        kind = el.type
        if kind == QPainterPath.ElementType.MoveToElement:
            d.append(f"M {el.x:.4f},{el.y:.4f}")
            i += 1
        elif kind == QPainterPath.ElementType.LineToElement:
            d.append(f"L {el.x:.4f},{el.y:.4f}")
            i += 1
        elif kind == QPainterPath.ElementType.CurveToElement:
            c1 = path.elementAt(i)
            c2 = path.elementAt(i + 1)
            c3 = path.elementAt(i + 2)
            d.append(f"C {c1.x:.4f},{c1.y:.4f} "
                     f"{c2.x:.4f},{c2.y:.4f} "
                     f"{c3.x:.4f},{c3.y:.4f}")
            i += 3
        else:
            i += 1
    if curve.closed:
        d.append("Z")
    return " ".join(d)


def _content_bbox(curves: list) -> tuple[float, float, float, float]:
    """Return (min_x, min_y, max_x, max_y) bounding box over all curve nodes."""
    from ..geometry import arc_bbox
    xs, ys = [], []
    for c in curves:
        if (c.kind == "arc" and c.radius and c.nodes
                and c.start_angle is not None and c.end_angle is not None):
            bx0, by0, bx1, by1 = arc_bbox(c.nodes[0].x, c.nodes[0].y, c.radius,
                                          c.start_angle, c.end_angle)
            xs.extend([bx0, bx1])
            ys.extend([by0, by1])
        elif c.kind in ("circle", "arc") and c.radius and c.nodes:
            cx, cy, r = c.nodes[0].x, c.nodes[0].y, c.radius
            xs.extend([cx - r, cx + r])
            ys.extend([cy - r, cy + r])
        else:
            for n in c.nodes:
                xs.append(n.x); ys.append(n.y)
                if n.cp_in:  xs.append(n.cp_in.x);  ys.append(n.cp_in.y)
                if n.cp_out: xs.append(n.cp_out.x); ys.append(n.cp_out.y)
    if not xs:
        return -100.0, -100.0, 100.0, 100.0
    pad = max((max(xs) - min(xs)) * 0.05, 20.0)
    return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad


# ---------- save ----------

def _curve_to_dict(curve: Curve) -> dict:
    nodes = []
    for n in curve.nodes:
        nd: dict = {"x": n.x, "y": n.y}
        if n.cp_in:
            nd["cp_in"]  = {"x": n.cp_in.x,  "y": n.cp_in.y}
        if n.cp_out:
            nd["cp_out"] = {"x": n.cp_out.x, "y": n.cp_out.y}
        nodes.append(nd)
    d = {
        "kind":        curve.kind,
        "layer":       curve.layer.value,
        "closed":      curve.closed,
        "mirrored":    curve.mirrored,
        "line_weight": curve.line_weight,
        "nodes":       nodes,
    }
    if curve.radius is not None:
        d["radius"] = curve.radius
    if curve.start_angle is not None:
        d["start_angle"] = curve.start_angle
    if curve.end_angle is not None:
        d["end_angle"] = curve.end_angle
    if curve.group_id:
        d["group"] = curve.group_id
    return d


def _dim_to_dict(d: DimLine) -> dict:
    return {"x0": d.x0, "y0": d.y0, "x1": d.x1, "y1": d.y1, "offset": d.offset}


def _dim_from_dict(d: dict) -> DimLine:
    return DimLine(x0=d["x0"], y0=d["y0"], x1=d["x1"], y1=d["y1"],
                   offset=d.get("offset", 0.0))


def _text_to_dict(t: TextObject) -> dict:
    return {"text": t.text, "family": t.family, "size_mm": t.size_mm,
            "rotation": t.rotation, "anchor_x": t.anchor_x,
            "anchor_y": t.anchor_y, "layer": t.layer.value,
            "line_weight": t.line_weight}


def _text_from_dict(t: dict) -> TextObject:
    return TextObject(
        text        = t["text"],
        family      = t.get("family", "Arial"),
        size_mm     = t.get("size_mm", 5.0),
        rotation    = t.get("rotation", 0.0),
        anchor_x    = t.get("anchor_x", 0.0),
        anchor_y    = t.get("anchor_y", 0.0),
        layer       = Layer(t.get("layer", "ENGRAVING")),
        line_weight = t.get("line_weight", 1.0),
    )


def save_svg(
    curves:           list,
    path:             str,
    calibration:      Calibration,
    mirror:           MirrorAxis,
    forming:          FormingMetadata,
    machined_bridge:  MachinedBridge,
    face_images:      list[FaceImage] | None = None,
    bookmarks:        list | None = None,
    dims:             list | None = None,
    layers:           dict | None = None,   # {layer name: {"visible","locked"}}
    fill:             dict | None = None,   # {"visible","color","opacity"}
    texts:            list | None = None,   # list[TextObject]
    bevel:            BevelSpec | None = None,
) -> None:
    ET.register_namespace("", _NS)
    root = ET.Element(f"{{{_NS}}}svg")
    root.set("version", "1.1")

    # Scene units are mm, so the bounding box IS in mm.
    # Always emit viewBox + physical width/height for correct rendering in
    # external viewers (Inkscape, browsers, etc.).
    non_mirrored = [c for c in curves if not c.mirrored]
    if non_mirrored:
        vx, vy, vx2, vy2 = _content_bbox(non_mirrored)
        vw = vx2 - vx
        vh = vy2 - vy
        root.set("viewBox", f"{vx:.4f} {vy:.4f} {vw:.4f} {vh:.4f}")
        root.set("width",   f"{vw:.4f}mm")
        root.set("height",  f"{vh:.4f}mm")

    meta_el = ET.SubElement(root, f"{{{_NS}}}metadata")
    state = {
        "calibration": {"px_per_mm": calibration.px_per_mm},
        "mirror":      {"x": mirror.x, "enabled": mirror.enabled},
        "forming":     {
            "bridge_angle_deg":  forming.bridge_angle_deg,
            "apical_radius_mm":  forming.apical_radius_mm,
        },
        "machined_bridge": {
            "depth_mm": machined_bridge.depth_mm,
            "width_mm": machined_bridge.width_mm,
        },
        "face_images": [
            {"path": fi.path, "tx": fi.tx, "ty": fi.ty,
             "rotation": fi.rotation, "opacity": fi.opacity}
            for fi in (face_images or [])
        ],
        "curves": [_curve_to_dict(c) for c in curves if not c.mirrored],
    }
    if bookmarks:
        state["bookmarks"] = [
            {
                "name":      bm["name"],
                "timestamp": bm["timestamp"],
                "curves":    [_curve_to_dict(c) for c in bm["snapshot"]["curves"]],
                # dims/texts are part of the snapshot too — dropping them here
                # silently truncated bookmarks on a save/reload round trip.
                "dims":      [_dim_to_dict(d)
                              for d in bm["snapshot"].get("dims", [])],
                "texts":     [_text_to_dict(t)
                              for t in bm["snapshot"].get("texts", [])],
            }
            for bm in bookmarks
        ]
    if dims:
        state["dims"] = [_dim_to_dict(d) for d in dims]
    if layers:
        state["layers"] = layers
    if fill:
        state["fill"] = fill
    if bevel:
        state["bevel"] = {"preset": bevel.preset, "depth_mm": bevel.depth_mm}
    if texts:
        state["texts"] = [_text_to_dict(t) for t in texts]
    meta_el.text = json.dumps(state, indent=2)

    for curve in non_mirrored:
        pe = ET.SubElement(root, f"{{{_NS}}}path")
        pe.set("d", _path_d(curve))
        pe.set("data-layer", curve.layer.value)
        pe.set("data-kind",  curve.kind)
        pe.set("fill",       "none")
        pe.set("stroke",     "#1f1f1f")
        pe.set("stroke-width", str(curve.line_weight))

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(path, xml_declaration=True, encoding="utf-8")


# ---------- load ----------

# No legitimate GuildDraw SVG comes anywhere near this; the cap keeps a hostile
# multi-gigabyte file from being read into memory just to be rejected below.
_MAX_SVG_BYTES = 64 * 1024 * 1024   # 64 MB


def _read_checked_svg(path: str) -> bytes:
    """Read an SVG file, refusing inputs that could be used for a parser DoS.

    GuildDraw opens .svg/.gdraw files that are freely shared between makers, so
    they are untrusted input. Python's stdlib ``xml.etree.ElementTree`` expands
    internal entities, which makes it vulnerable to the "billion laughs" /
    quadratic-blowup attack (a few hundred bytes inflating to gigabytes in
    memory). We never want a third-party parser here (defusedxml) — the bundle
    is deliberately minimal — so we close the hole with a dependency-free guard:

      * cap the on-disk size (no legitimate GuildDraw file is this large), and
      * reject any DTD/entity declaration. GuildDraw-native SVGs never declare a
        DOCTYPE or ENTITY, and ``load_svg`` only accepts GuildDraw-native files
        (it requires the metadata block), so this rejects nothing valid.

    ElementTree does not resolve *external* entities, so entity-expansion is the
    only vector and the DOCTYPE/ENTITY scan fully covers it.
    """
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise ValueError(str(exc)) from exc
    if size > _MAX_SVG_BYTES:
        raise ValueError(
            f"Refusing to open: file is {size / 1_048_576:.0f} MB, larger than "
            f"the {_MAX_SVG_BYTES // 1_048_576} MB limit for a GuildDraw SVG.")
    with open(path, "rb") as f:
        data = f.read()
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError(
            "Refusing to open: the file declares an XML DTD or entities, which "
            "GuildDraw never writes and which can be abused for a "
            "denial-of-service (entity-expansion) attack.")
    return data


def _curve_from_dict(d: dict) -> Curve:
    nodes = []
    for nd in d["nodes"]:
        n = SplineNode(x=nd["x"], y=nd["y"])
        if "cp_in" in nd:
            n.cp_in  = ControlPoint(nd["cp_in"]["x"],  nd["cp_in"]["y"])
        if "cp_out" in nd:
            n.cp_out = ControlPoint(nd["cp_out"]["x"], nd["cp_out"]["y"])
        nodes.append(n)
    return Curve(
        kind        = d["kind"],
        layer       = Layer(d["layer"]),
        nodes       = nodes,
        closed      = d.get("closed",      False),
        mirrored    = d.get("mirrored",    False),
        line_weight = d.get("line_weight", 1.5),
        radius      = d.get("radius"),
        start_angle = d.get("start_angle"),
        end_angle   = d.get("end_angle"),
        group_id    = d.get("group"),
    )


def _load_face_images(state: dict) -> list[FaceImage]:
    """Parse face_images list, falling back to legacy face_image single-object."""
    if "face_images" in state:
        return [
            FaceImage(
                path    =fi.get("path",     ""),
                tx      =fi.get("tx",        0.0),
                ty      =fi.get("ty",        0.0),
                rotation=fi.get("rotation",  0.0),
                opacity =fi.get("opacity",   0.7),
            )
            for fi in state["face_images"]
        ]
    # Legacy single-object key
    fi = state.get("face_image", {})
    if fi.get("path"):
        return [FaceImage(
            path    =fi.get("path",     ""),
            tx      =fi.get("tx",        0.0),
            ty      =fi.get("ty",        0.0),
            rotation=fi.get("rotation",  0.0),
            opacity =fi.get("opacity",   0.7),
        )]
    return []


def load_svg(path: str) -> dict:
    """
    Return a dict with keys: curves, calibration, mirror, forming,
    machined_bridge, face_image.  Raises on parse error.
    """
    root = ET.fromstring(_read_checked_svg(path))

    meta_el = root.find(f"{{{_NS}}}metadata")
    if meta_el is None or not meta_el.text:
        raise ValueError("SVG has no GuildDraw metadata block.")

    state = json.loads(meta_el.text)

    cal_d  = state.get("calibration", {})
    mir_d  = state.get("mirror",      {})
    frm_d  = state.get("forming",     {})
    mb_d   = state.get("machined_bridge", {})

    bookmarks = [
        {
            "name":      bm.get("name", ""),
            "timestamp": bm.get("timestamp", ""),
            "snapshot":  {
                "curves": [_curve_from_dict(c) for c in bm.get("curves", [])],
                "dims":   [_dim_from_dict(d) for d in bm.get("dims", [])],
                "texts":  [_text_from_dict(t) for t in bm.get("texts", [])],
            },
        }
        for bm in state.get("bookmarks", [])
    ]

    dims = [_dim_from_dict(d) for d in state.get("dims", [])]

    return {
        "curves": [_curve_from_dict(c) for c in state.get("curves", [])],
        "dims":   dims,
        "calibration": Calibration(px_per_mm=cal_d.get("px_per_mm")),
        "mirror": MirrorAxis(
            enabled=mir_d.get("enabled", True),
            x=mir_d.get("x", 0.0),
        ),
        "forming": FormingMetadata(
            bridge_angle_deg=frm_d.get("bridge_angle_deg", 0.0),
            apical_radius_mm=frm_d.get("apical_radius_mm", 0.0),
        ),
        "machined_bridge": MachinedBridge(
            depth_mm=mb_d.get("depth_mm", 4.0),
            width_mm=mb_d.get("width_mm", 5.0),
        ),
        "face_images": _load_face_images(state),
        "bookmarks": bookmarks,
        "layers": state.get("layers", {}),
        "fill": state.get("fill"),   # None when absent (pre-0.9.8 files)
        "bevel": (
            BevelSpec(preset=state["bevel"].get("preset", "acetate"),
                      depth_mm=state["bevel"].get("depth_mm", 1.0))
            if isinstance(state.get("bevel"), dict) else None
        ),   # None when absent (pre-rc2 files)
        "texts": [_text_from_dict(t) for t in state.get("texts", [])],
    }
