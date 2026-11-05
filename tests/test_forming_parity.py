"""GuildDraw's forming map against GuildModel's own (research §7.1): the two
apps must show the same formed front. GuildModel's module runs in its own
venv when its tree sits beside this one (or where ``GUILDMODEL_TREE``
points); skipped otherwise, as on CI."""
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from framedraft.forming import BridgeGeometry, ThermoformMap

_TREE = Path(os.environ.get("GUILDMODEL_TREE")
             or Path(__file__).resolve().parents[2] / "GuildModel")
_PY = _TREE / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

pytestmark = pytest.mark.skipif(
    not (_TREE / "src" / "guildmodel").is_dir() or not _PY.exists(),
    reason=f"GuildModel's tree and venv not found at {_TREE}")

_SCRIPT = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import numpy as np
from guildmodel.core.forming.thermoform import BridgeGeometry, ThermoformMap
job = json.load(sys.stdin)
out = []
for case in job:
    b = BridgeGeometry(**case["bridge"])
    m = ThermoformMap(bridge=b, **case["map"])
    out.append(m(np.asarray(case["pts"])).tolist())
json.dump(out, sys.stdout)
"""


def _guildmodel_forms(cases):
    proc = subprocess.run([str(_PY), "-I", "-c", _SCRIPT, str(_TREE / "src")],
                          input=json.dumps(cases), capture_output=True, text=True,
                          check=True, timeout=120)
    return [np.asarray(o) for o in json.loads(proc.stdout)]


def _grid():
    xs, ys = np.meshgrid(np.linspace(-70.0, 70.0, 57), np.linspace(-25.0, 25.0, 21))
    zs = np.zeros_like(xs)
    return np.column_stack([xs.ravel(), ys.ravel(), zs.ravel()]).tolist()


_CASES = [
    {"bridge": dict(apex_x=34.0, apex_y=0.0, band_half=9.0, top_y=9.0, center_y=0.0,
                    top_width=18.0, nose_dir=-1.0),
     "map": dict(radius_mm=132.5, face_form_deg=170.0)},
    {"bridge": dict(apex_x=33.5, apex_y=-4.0, band_half=10.0, top_y=12.0, center_y=6.0,
                    top_width=20.3, nose_dir=-1.0),
     "map": dict(radius_mm=144.0, face_form_deg=163.97, projection_mm=4.0)},
    {"bridge": dict(apex_x=36.0, apex_y=2.0, band_half=8.0, top_y=10.0, center_y=4.0,
                    top_width=16.0, nose_dir=1.0),
     "map": dict(radius_mm=66.25, face_form_deg=160.0, projection_mm=2.5,
                 crease_gap_mm=14.0, crease_angle_deg=30.0, bridge_offset_mm=1.0,
                 die_radius_mm=8.0, crease_blend_mm=1.0)},
    {"bridge": dict(apex_x=0.0, apex_y=0.0, band_half=9.0, top_y=9.0, center_y=0.0,
                    top_width=18.0, nose_dir=-1.0, projects=False, wraps=False),
     "map": dict(radius_mm=132.5, face_form_deg=160.0, projection_mm=3.0)},
]


def test_the_ported_map_agrees_with_guildmodel_to_a_micron():
    cases = [dict(c, pts=_grid()) for c in _CASES]
    theirs = _guildmodel_forms(cases)
    for case, ref in zip(cases, theirs, strict=True):
        ours = ThermoformMap(bridge=BridgeGeometry(**case["bridge"]), **case["map"])(
            np.asarray(case["pts"]))
        assert np.abs(ours - ref).max() < 1e-6, case["map"]
