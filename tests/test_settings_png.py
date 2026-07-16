"""Settings-apply workspace scoping (GitHub issue #4) + PNG export (issue #7).

These build the real MainWindow (never shown) against a prefs file redirected
to tmp_path, so the user's ~/.guilddraw/prefs.json is never read or written.
"""
import copy

import pytest
from PySide6.QtWidgets import QApplication

import framedraft.prefs as prefs_mod


@pytest.fixture()
def win(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    from framedraft.app import MainWindow
    w = MainWindow()
    QApplication.processEvents()
    yield w
    # Never leave the dirty flag set at close — on macOS even a never-shown
    # window gets a real closeEvent, and the unsaved-changes QMessageBox
    # would block CI teardown forever.
    w._dirty = False
    w.close()
    w.deleteLater()
    QApplication.processEvents()


def _tweaked_prefs(w) -> dict:
    p = copy.deepcopy(w._prefs)
    p["stock_width_mm"]  = 200.0
    p["stock_height_mm"] = 90.0
    p["pad_on_startup"]  = True
    p["pad_width_mm"]    = 50.0
    return p


# --------------------------------------------------------------- issue #4

def test_settings_apply_in_temple_leaves_temple_guides_alone(win):
    """Saving Settings while a Temple workspace is active must not re-draw
    the temple stock as the frame-front stock or strand a pad guide there."""
    win._ws_tab_widget.setCurrentIndex(1)          # temple_r
    QApplication.processEvents()
    temple = win._active_ws
    assert temple.workspace_type == "temple_r"
    assert win._stock_w_spin.value() == 160.0      # temple stock default

    win._apply_settings(_tweaked_prefs(win))

    # Temple sidebar + session + guide objects untouched
    assert win._stock_w_spin.value() == 160.0
    assert win._stock_h_spin.value() == 30.0
    assert temple.stock_w == 160.0 and temple.stock_h == 30.0
    assert temple.stock_guide._width_mm == 160.0
    assert temple.pad_visible is False
    assert temple.pad_guide._visible is False

    # The front workspace's session state received the new defaults
    front = win._workspaces[0]
    assert front.stock_w == 200.0 and front.stock_h == 90.0
    assert front.pad_visible is True and front.pad_w == 50.0

    # Switching to the front tab surfaces them in the sidebar + guides
    win._ws_tab_widget.setCurrentIndex(0)
    QApplication.processEvents()
    assert win._stock_w_spin.value() == 200.0
    assert front.stock_guide._width_mm == 200.0

    # And switching back, the temple is still intact (issue #4 symptom was
    # the corruption surviving until an app restart)
    win._ws_tab_widget.setCurrentIndex(1)
    QApplication.processEvents()
    assert win._stock_w_spin.value() == 160.0
    assert temple.stock_guide._width_mm == 160.0
    assert temple.pad_guide._visible is False


def test_settings_apply_in_front_updates_live_widgets(win):
    """On the front tab the new defaults still apply immediately (old behavior)."""
    assert win._active_ws.workspace_type == "front"
    win._apply_settings(_tweaked_prefs(win))
    assert win._stock_w_spin.value() == 200.0
    assert win._active_ws.stock_guide._width_mm == 200.0
    assert win._act_pad.isChecked() is True


# --------------------------------------------------------------- issue #7

def test_render_png_true_print_scale(tmp_path):
    """pixels = mm · dpi / 25.4 — a 100 mm rect at 300 dpi is ~1181 px wide."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPen, QColor
    from PySide6.QtWidgets import QGraphicsScene
    from framedraft.export.png import render_png

    scene = QGraphicsScene()
    pen = QPen(QColor("#112233"))
    pen.setWidthF(1.0)
    scene.addRect(0, 0, 100, 50, pen)

    out = tmp_path / "export.png"
    render_png(scene, str(out), dpi=300, rect=QRectF(0, 0, 100, 50),
               background="#faf6ee")
    img = QImage(str(out))
    assert abs(img.width() - round(100 * 300 / 25.4)) <= 1    # ≈ 1181
    assert abs(img.height() - round(50 * 300 / 25.4)) <= 1    # ≈ 591

    # geometry actually drawn (corner pixel of the rect is non-background)
    assert img.pixelColor(1, 1).name() != "#faf6ee"


def test_render_png_caps_giant_rasters(tmp_path):
    """An absurd dpi request degrades resolution instead of allocating GBs."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QGraphicsScene
    from framedraft.export.png import render_png

    scene = QGraphicsScene()
    scene.addRect(0, 0, 400, 200)
    out = tmp_path / "big.png"
    render_png(scene, str(out), dpi=10000, rect=QRectF(0, 0, 400, 200))
    img = QImage(str(out))
    assert max(img.width(), img.height()) <= 8192
    assert img.width() > 0 and img.height() > 0


def test_png_content_rect_covers_mirror_ghost(win):
    """The export crop must include the mirrored half of the frame when the
    ghost display is on — half a frame in the PNG would be a new bug."""
    from framedraft.document import Curve, SplineNode, Layer
    c = Curve(kind="line", layer=Layer.LENS,
              nodes=[SplineNode(x=10, y=-10), SplineNode(x=40, y=-10),
                     SplineNode(x=40, y=10), SplineNode(x=10, y=10)],
              closed=True)
    win._active_ws.add_curve(c)
    win._act_mirror.setChecked(True)
    rect = win._png_content_rect()
    assert rect is not None
    assert rect.left() < -35 and rect.right() > 35    # both halves framed
