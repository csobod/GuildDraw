"""RC4 M26 — dimension tool: first-hover snap + arrowed rendering."""

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QGraphicsScene

from framedraft.canvas.dim import DimItem
from framedraft.canvas.scene import FrameScene
from framedraft.document import DimLine
from framedraft.tools.dim import DimTool


class _RecordingSnap:
    def __init__(self):
        self.calls = 0

    def snap(self, pos, nodes, view, use_snap=True):
        self.calls += 1
        return pos

    def hide(self):
        pass

    def set_doc_curves(self, curves):
        pass


def test_dim_snap_queried_while_hovering_for_first_point():
    """M26.1 — the snap indicator must track the cursor BEFORE point A is
    placed (it used to appear only after the first click)."""
    snap = _RecordingSnap()
    tool = DimTool()
    tool.activate(FrameScene(), None, snap=snap)

    tool.handle_move(QPointF(3.0, 4.0))
    assert snap.calls == 1, "snap engine not queried in the pick-A stage"


def test_dim_snap_still_queried_after_first_point():
    snap = _RecordingSnap()
    tool = DimTool()
    scene = FrameScene()
    tool.activate(scene, None, snap=snap)
    tool.handle_press(QPointF(0.0, 0.0))
    before = snap.calls
    tool.handle_move(QPointF(10.0, 0.0))
    assert snap.calls == before + 1


def test_dim_item_paints_arrows_and_label_without_artifacts():
    """Smoke: the arrowed/rotated-label paint path runs and draws ink."""
    scene = QGraphicsScene()
    dim = DimLine(x0=0.0, y0=0.0, x1=30.0, y1=0.0)
    dim.offset = 6.0
    item = DimItem(dim)
    scene.addItem(item)
    assert item.boundingRect().isValid()

    img = QImage(400, 300, QImage.Format.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    p = QPainter(img)
    scene.render(p, QRectF(0, 0, 400, 300), QRectF(-15, -25, 60, 45))
    p.end()

    inked = sum(
        1 for x in range(0, 400, 4) for y in range(0, 300, 4)
        if img.pixel(x, y) != 0xFFFFFFFF
    )
    assert inked > 20, "dimension rendered almost nothing"


def test_dim_item_bounds_cover_screen_sized_label():
    """The label is screen-sized; boundingRect must pad for it at the cached
    paint scale so panning can't leave text trails."""
    dim = DimLine(x0=0.0, y0=0.0, x1=30.0, y1=0.0)
    item = DimItem(dim)
    r = item.boundingRect()
    # deco pad (label half-width ≈ 45 px at scale 1) dominates the 6 mm base
    assert r.width() >= 30 + 2 * (item._label_w_px / 2.0)
