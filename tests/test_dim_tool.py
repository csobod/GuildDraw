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


def test_first_point_hover_shows_then_clears_marker():
    """Pick-A phase gets a live crosshair (its own feedback, since there is no
    rubber-band yet); placing the first point removes it."""
    snap = _RecordingSnap()
    tool = DimTool()
    scene = FrameScene()
    tool.activate(scene, None, snap=snap)

    assert tool._hover_marker is None
    tool.handle_move(QPointF(5.0, 5.0))
    assert tool._hover_marker is not None
    assert tool._hover_marker.scene() is scene

    tool.handle_press(QPointF(5.0, 5.0))          # place point A
    assert tool._hover_marker is None             # marker gone once A is set


def test_hover_marker_cleared_on_deactivate():
    snap = _RecordingSnap()
    tool = DimTool()
    tool.activate(FrameScene(), None, snap=snap)
    tool.handle_move(QPointF(3.0, 3.0))
    assert tool._hover_marker is not None
    tool.deactivate()
    assert tool._hover_marker is None


def test_scene_uses_noindex_for_dim_delete_crash_safety():
    """Regression for the 'delete a dimension → app closes' segfault.

    DimItem's Python boundingRect() changes with zoom (its screen-sized label),
    which mutates the item's geometry without the prepareGeometryChange() a BSP
    item index needs to stay consistent — so removing it left a dangling
    pointer that faulted on the next index query. FrameScene uses NoIndex so
    that whole class of crash can't happen."""
    import gc

    from PySide6.QtWidgets import QGraphicsScene
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtCore import QRectF
    from framedraft.canvas.dim import DimItem
    from framedraft.document import DimLine

    scene = FrameScene()
    assert scene.itemIndexMethod() == QGraphicsScene.ItemIndexMethod.NoIndex

    dim = DimLine(x0=-20, y0=5, x1=20, y1=5, offset=8)
    item = scene.add_dim(dim)
    # paint at several scales so the DimItem's cached bound-scale keeps changing
    for s in (0.3, 3.0, 0.1, 5.0):
        img = QImage(200, 150, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        p.scale(s, s)
        scene.render(p, QRectF(0, 0, 200, 150), QRectF(-40, -30, 80, 60))
        p.end()

    scene.remove_dim(dim)
    del item
    gc.collect()
    # querying the index + a full re-render after removal must not touch a
    # dangling pointer (this is what crashed with a BSP index)
    hits = scene.items(QRectF(-100, -100, 200, 200))
    assert all(not isinstance(i, DimItem) for i in hits)
    img = QImage(200, 150, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    scene.render(p, QRectF(0, 0, 200, 150), QRectF(-40, -30, 80, 60))
    p.end()


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
