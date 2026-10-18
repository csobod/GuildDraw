"""Sweep the maker's drawings, when some are on disk.

Copies of a few library designs, chosen for the limits they test (an
asymmetric front, the largest and the smallest eye, an outline with an opening,
four hinge lines, the one populated hinge-pocket tab, the most asymmetric
temple), sit in the gitignored ``tests/corpus/`` beside this file, or wherever
``GUILDDRAW_FRAME_CORPUS`` points; GuildModel's suite reads the same set.
Skipped, and silent, when neither exists (every CI run); set the variable to
"" to skip on purpose. Nothing here names a drawing: the names in a failure
come off the filesystem at the moment it fails.

What it checks is the handoff: every drawing loads without a tab error, every
populated workspace passes the export validator (the readiness dot would be
green), the batch DXF export writes one file per populated workspace, and a
save-and-reload round trip keeps every curve and text.
"""
import os
from pathlib import Path

import pytest

_CORPUS_ENV = "GUILDDRAW_FRAME_CORPUS"
_LOCAL_CORPUS = Path(__file__).parent / "corpus"
_TABS = ("front", "temple_r", "temple_l", "component")


def _drawings():
    root = os.environ.get(_CORPUS_ENV)
    if root is None and _LOCAL_CORPUS.is_dir():
        root = str(_LOCAL_CORPUS)
    if not root or not Path(root).is_dir():
        return []
    return [p for p in sorted(Path(root).rglob("*.gdraw"))
            if ".stversions" not in p.parts and not p.name.endswith(".bak")]


pytestmark = pytest.mark.skipif(
    not _drawings(),
    reason=f"no corpus: set {_CORPUS_ENV} to a folder of .gdraw drawings, or fill tests/corpus/")


@pytest.fixture(scope="module")
def loaded():
    from framedraft.export.gdraw import load_gdraw
    return [(p, load_gdraw(str(p))) for p in _drawings()]


def _mirror(ws) -> tuple[bool, float]:
    m = ws.get("mirror")
    if m is None:
        return False, 0.0
    if isinstance(m, dict):
        return bool(m.get("enabled", False)), float(m.get("x", 0.0))
    return bool(getattr(m, "enabled", False)), float(getattr(m, "x", 0.0))


def test_every_drawing_loads_clean(loaded):
    bad = [f"{p.name}: {d['errors']}" for p, d in loaded if d.get("errors")]
    assert not bad, "tabs that did not load:\n  " + "\n  ".join(bad)


def test_every_populated_workspace_is_ready_for_guildmodel(loaded):
    """The readiness dot would be green on every tab the maker drew on."""
    from framedraft.export.validate import validate

    bad = []
    for p, d in loaded:
        for tab in _TABS:
            curves = d[tab].get("curves") or []
            if not curves:
                continue
            on, _x = _mirror(d[tab])
            errors, _warnings = validate(curves, on, tab)
            if errors:
                bad.append(f"{p.name} [{tab}]: {errors[0]}")
    assert not bad, "workspaces the dot would show amber:\n  " + "\n  ".join(bad)


def test_batch_export_writes_one_dxf_per_populated_workspace(loaded, tmp_path):
    """Export All DXF, as the maker runs it. Texts are not outlined here (that
    needs the font machinery), and no corpus design carries any."""
    from framedraft.export.batch import BatchWorkspace, check_batch, write_batch

    for p, d in loaded:
        items = []
        for tab in _TABS:
            on, _x = _mirror(d[tab])
            items.append(BatchWorkspace(tab, d[tab].get("curves") or [], on))
        report = check_batch(items)
        assert report.ok, f"{p.name}: {report.errors}"
        written = write_batch(items, str(tmp_path / p.stem))
        assert len(written) == sum(1 for it in items if it.curves), p.name
        assert all(Path(w).stat().st_size > 0 for w in written), p.name


def test_save_and_reload_keeps_every_curve_and_text(loaded, tmp_path):
    from framedraft.export.gdraw import load_gdraw, save_gdraw

    for p, d in loaded:
        out = tmp_path / p.name
        save_gdraw({tab: d[tab] for tab in _TABS}, str(out), d["active_tab"])
        back = load_gdraw(str(out))
        assert not back.get("errors"), f"{p.name}: {back['errors']}"
        assert back["active_tab"] == d["active_tab"], p.name
        for tab in _TABS:
            for key in ("curves", "texts"):
                assert len(back[tab].get(key) or []) == len(d[tab].get(key) or []), (p.name, tab, key)
