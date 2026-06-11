"""
Batch DXF export (M9) — write every populated workspace's DXF in one go.

One frame = four files (`<name>_front.dxf`, `<name>_temple_r.dxf`,
`<name>_temple_l.dxf`, `<name>_hinge.dxf`); exporting them one tab at a
time invites mistakes, so this module validates all workspaces first and
writes nothing unless every populated workspace passes.

Qt-free: the caller (app.py) converts TextObjects to outline curves before
building the BatchWorkspace items, exactly as the single-file export does.
"""
from dataclasses import dataclass, field

from .dxf import export_dxf
from .validate import validate


# Workspace type → filename suffix, in export order.
WORKSPACE_SUFFIXES = {
    "front":    "front",
    "temple_r": "temple_r",
    "temple_l": "temple_l",
    "hinge":    "hinge",
}


@dataclass
class BatchWorkspace:
    workspace_type: str          # key of WORKSPACE_SUFFIXES
    curves:         list         # Curve objects in mm (text already converted)
    mirror_on:      bool = False
    axis_x:         float = 0.0  # mirror axis x in mm


@dataclass
class BatchReport:
    errors:   dict = field(default_factory=dict)   # ws_type -> [str]
    warnings: dict = field(default_factory=dict)   # ws_type -> [str]
    skipped:  list = field(default_factory=list)   # empty workspaces

    @property
    def ok(self) -> bool:
        return not self.errors


def base_from_path(path: str) -> str:
    """Strip a trailing .dxf (any case) so '<base>_front.dxf' etc. can be built."""
    if path.lower().endswith(".dxf"):
        return path[:-4]
    return path


def batch_paths(base: str, items: list) -> dict:
    """ws_type -> output path for every non-empty workspace, in export order."""
    populated = {it.workspace_type for it in items if it.curves}
    return {
        ws_type: f"{base}_{suffix}.dxf"
        for ws_type, suffix in WORKSPACE_SUFFIXES.items()
        if ws_type in populated
    }


def check_batch(items: list) -> BatchReport:
    """Run each populated workspace's validator; empty workspaces are skipped
    (an empty hinge tab is normal, not an export error)."""
    report = BatchReport()
    for item in items:
        if not item.curves:
            report.skipped.append(item.workspace_type)
            continue
        errors, warnings = validate(item.curves, item.mirror_on,
                                    item.workspace_type)
        if errors:
            report.errors[item.workspace_type] = errors
        if warnings:
            report.warnings[item.workspace_type] = warnings
    return report


def write_batch(items: list, base: str) -> list:
    """Write one DXF per populated workspace. Returns the paths written.
    Call check_batch first; this performs no validation of its own."""
    paths = batch_paths(base, items)
    written = []
    for item in items:
        path = paths.get(item.workspace_type)
        if path is None:
            continue
        export_dxf(
            curves     = item.curves,
            path       = path,
            mirror_on  = item.mirror_on,
            axis_x     = item.axis_x,
            horizontal = item.workspace_type in ("temple_r", "temple_l"),
        )
        written.append(path)
    return written
