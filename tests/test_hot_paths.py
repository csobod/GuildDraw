"""Qt hot paths must not import.

MainWindow.eventFilter is installed on the QApplication, so it runs for every
event the app delivers — a single Settings apply pushes ~12,000 through it. It
carried a `from PySide6.QtCore import QEvent` from v1.1.0, which ran shiboken's
`__feature__` import hook on every one of those events. On Linux that was only
throughput; on the macOS Intel runner it stalled the suite until the 120 s
per-test timeout fired, with the traceback parked in
`shibokensupport/signature/loader.py` underneath `setStyleSheet` re-polishing
every widget.

Painters, event handlers and boundingRect() are on the same footing: called per
frame or per event, so an import there is paid over and over. This walks the
source for that shape rather than trusting review to catch it again.
"""
import ast
import pathlib

PKG = pathlib.Path(__file__).resolve().parents[1] / "framedraft"

# Qt entry points called per event, per frame, or per paint.
_HOT = {
    "eventFilter", "paint", "paintEvent", "boundingRect", "shape", "itemChange",
    "drawBackground", "drawForeground", "mouseMoveEvent", "mousePressEvent",
    "mouseReleaseEvent", "mouseDoubleClickEvent", "hoverMoveEvent",
    "hoverEnterEvent", "hoverLeaveEvent", "wheelEvent", "keyPressEvent",
    "resizeEvent",
}

# Deliberate exceptions, with the reason they cost nothing in practice.
_ALLOWED = {
    # Fires only while a maker is recording a hotkey in Settings — one key
    # press at human speed, and after the Escape/bare-modifier early returns.
    ("KeyCaptureEdit", "keyPressEvent"),
}


def _offenders():
    out = []
    for path in sorted(PKG.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            for fn in cls.body:
                if not isinstance(fn, ast.FunctionDef) or fn.name not in _HOT:
                    continue
                if (cls.name, fn.name) in _ALLOWED:
                    continue
                for node in ast.walk(fn):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        mod = (getattr(node, "module", None)
                               or ",".join(a.name for a in node.names))
                        out.append(f"{path.name}:{node.lineno} "
                                   f"{cls.name}.{fn.name}() imports {mod}")
    return out


def test_no_hot_path_imports():
    found = _offenders()
    assert not found, (
        "import inside a Qt hot path — it is paid on every event or frame:\n  "
        + "\n  ".join(found)
        + "\nHoist it to module scope, or add it to _ALLOWED with the reason "
          "it is not actually hot.")


def test_the_app_wide_event_filter_is_clean():
    """Named explicitly: this is the one that actually hung a runner, and it is
    the hottest path in the app because it is installed on the QApplication."""
    tree = ast.parse((PKG / "app.py").read_text(encoding="utf-8"))
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == "MainWindow":
            for fn in cls.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == "eventFilter":
                    imports = [n for n in ast.walk(fn)
                               if isinstance(n, (ast.Import, ast.ImportFrom))]
                    assert not imports, "MainWindow.eventFilter imports again"
                    return
    raise AssertionError("MainWindow.eventFilter not found")
