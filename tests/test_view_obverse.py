"""View Obverse (BUILDPLAN *Road to 2.0*, item 8): each tab's view turns to
show the drawing's other face, mirrored left to right on every tab, with a
corner badge naming the face toward the viewer. A view transform only: the
document, snapping, selection and every export are untouched."""
import zipfile

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QLabel

import framedraft.prefs as prefs_mod
from framedraft.document import Layer, TextObject
from helpers import circle, closed_diamond, line


@pytest.fixture()
def win(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    from framedraft.app import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    QApplication.processEvents()
    yield w
    w._dirty = False
    w.close()
    w.deleteLater()
    QApplication.processEvents()


def _front(win):
    ws = win._active_ws
    for c in (closed_diamond(0, 0, 45), circle(-17, 0, 11), circle(17, 0, 11),
              closed_diamond(30, -12, 5, layer=Layer.INLAY)):
        ws.add_curve(c)
    win._fit_view()
    QApplication.processEvents()
    return ws


def _center_scene(view) -> QPointF:
    vp = QRectF(view.viewport().rect())
    return view.viewportTransform().inverted()[0].map(vp.center())


def _tab(win, i):
    win._ws_tab_widget.setCurrentIndex(i)
    QApplication.processEvents()
    return win._active_ws


# ── The turn ───────────────────────────────────────────────────────────────

def test_the_turn_is_a_mirror_about_the_middle_of_the_view(win):
    _front(win)
    view = win.view
    before = view.transform()
    c0 = _center_scene(view)
    probe = QPointF(c0.x() + 20.0, c0.y() - 10.0)
    p0 = view.viewportTransform().map(probe)

    win._act_obverse.trigger()
    t = view.transform()
    assert (t.m11(), t.m12(), t.m21(), t.m22()) == pytest.approx(
        (-before.m11(), 0.0, 0.0, before.m22()))
    c1 = _center_scene(view)
    assert c1.x() == pytest.approx(c0.x(), abs=1.0 / view.zoom())
    assert c1.y() == pytest.approx(c0.y(), abs=1.0 / view.zoom())
    # The probe lands where its mirror twin about the center column was.
    twin = view.viewportTransform().map(QPointF(2 * c0.x() - probe.x(), probe.y()))
    p1 = view.viewportTransform().map(probe)
    vp_mid = QRectF(view.viewport().rect()).center().x()
    assert p1.x() - vp_mid == pytest.approx(-(p0.x() - vp_mid), abs=1.5)
    assert p1.y() == pytest.approx(p0.y(), abs=1.5)
    assert twin.x() == pytest.approx(p0.x(), abs=1.5)

    win._act_obverse.trigger()                    # and back, exactly
    t = view.transform()
    assert (t.m11(), t.m22()) == pytest.approx((before.m11(), before.m22()))
    assert not view.is_obverse()


def test_zoom_and_fit_keep_the_turn_and_read_a_positive_zoom(win):
    _front(win)
    view = win.view
    win._act_obverse.trigger()
    z = view.zoom()
    seen = []
    view.zoom_changed.connect(seen.append)
    view.zoom_by(2.0)
    assert view.is_obverse()
    assert view.zoom() == pytest.approx(2.0 * z)
    assert seen and seen[-1] > 0
    view.fit_view(QRectF(-50, -50, 100, 100))
    assert view.is_obverse() and view.zoom() > 0
    win._update_info_label()
    shown = win._info_label.text().split("Zoom:")[1].strip()
    assert shown.endswith(" px/mm")
    assert float(shown.split()[0]) == pytest.approx(view.zoom(), abs=0.05)
    assert float(shown.split()[0]) > 0


def test_the_wheel_zooms_about_the_cursor_in_the_turned_view(win):
    _front(win)
    view = win.view
    win._act_obverse.trigger()
    vp_pos = QPointF(300, 220)
    under = view.mapToScene(vp_pos.toPoint())
    ev = QWheelEvent(vp_pos, view.viewport().mapToGlobal(vp_pos), QPoint(0, 0),
                     QPoint(0, 120), Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase,
                     False)
    z = view.zoom()
    view.wheelEvent(ev)
    assert view.zoom() == pytest.approx(z * 1.15)
    assert view.is_obverse()
    after = view.mapToScene(vp_pos.toPoint())
    assert after.x() == pytest.approx(under.x(), abs=2.0 / view.zoom())
    assert after.y() == pytest.approx(under.y(), abs=2.0 / view.zoom())


def _mouse(view, kind, vp, buttons=Qt.MouseButton.LeftButton):
    button = (Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove
              else Qt.MouseButton.LeftButton)
    return QMouseEvent(kind, QPointF(vp), QPointF(view.viewport().mapToGlobal(vp)),
                       button, buttons, Qt.KeyboardModifier.NoModifier)


def test_a_box_drag_selects_what_it_covers_in_the_turned_view(win):
    ws = _front(win)
    view = win.view
    seat = closed_diamond(8, -30, 3, layer=Layer.INLAY)
    decoy = closed_diamond(-8, -30, 3, layer=Layer.INLAY)  # where an unturned
    ws.add_curve(seat)                                     # band would land
    ws.add_curve(decoy)
    win._act_obverse.trigger()
    # A band around the seat, in screen pixels, wherever the turn put it.
    a = view.mapFromScene(QPointF(8 - 5, -30 - 5))
    b = view.mapFromScene(QPointF(8 + 5, -30 + 5))
    start = QPoint(min(a.x(), b.x()), min(a.y(), b.y()))
    end = QPoint(max(a.x(), b.x()), max(a.y(), b.y()))
    view.mousePressEvent(_mouse(view, QEvent.Type.MouseButtonPress, start))
    view.mouseMoveEvent(_mouse(view, QEvent.Type.MouseMove, end,
                               Qt.MouseButton.LeftButton))
    view.mouseReleaseEvent(_mouse(view, QEvent.Type.MouseButtonRelease, end,
                                  Qt.MouseButton.NoButton))
    picked = [it.curve for it in ws.scene.selectedItems() if hasattr(it, "curve")]
    assert picked == [seat]


def test_a_line_drawn_in_the_turned_view_lands_under_the_clicks(win):
    _front(win)
    view = win.view
    win._act_obverse.trigger()
    win._act_snap.setChecked(False)
    win._act_line.trigger()
    ws = win._active_ws
    n0 = len(ws.doc_curves)
    for x, y in ((-30.0, 40.0), (30.0, 40.0)):
        vp = view.mapFromScene(QPointF(x, y))
        view.mousePressEvent(_mouse(view, QEvent.Type.MouseButtonPress, vp))
        view.mouseReleaseEvent(_mouse(view, QEvent.Type.MouseButtonRelease, vp,
                                      Qt.MouseButton.NoButton))
    win._draw_tool._finish(False)                  # what Enter does
    new = ws.doc_curves[n0:]
    assert len(new) == 1
    xs = sorted(round(n.x) for n in new[0].nodes)
    assert xs == [-30, 30]                         # the document is not mirrored


# ── Per tab, the badge, the component tab ──────────────────────────────────

def test_each_tab_keeps_its_own_turn_and_badge(win):
    _front(win)
    front_view = win.view
    win._act_obverse.trigger()
    assert front_view.obverse_badge.isVisible()
    assert front_view.obverse_badge.face() == "posterior"

    temple = _tab(win, 1)
    assert not win._act_obverse.isChecked()
    assert not temple.view.is_obverse()
    win._act_obverse.trigger()
    assert temple.view.obverse_badge.face() == "anterior"
    assert temple.view.is_obverse() and temple.obverse

    _tab(win, 0)
    assert win._act_obverse.isChecked()
    assert front_view.is_obverse() and front_view.obverse_badge.isVisible()
    win._act_obverse.trigger()
    assert not front_view.obverse_badge.isVisible()
    assert temple.view.is_obverse()                # the temple stays turned


def test_the_badge_never_turns_and_never_takes_a_click(win):
    _front(win)
    badge = win.view.obverse_badge
    assert badge.parent() is win.view               # not the scrolling viewport
    assert badge.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    win._act_obverse.trigger()
    vp = win.view.viewport().geometry()
    assert vp.left() < badge.x() < vp.left() + 12   # in the top-left corner
    assert vp.top() < badge.y() < vp.top() + 12


def test_the_badge_is_one_word_with_no_title_and_no_glyph(win):
    # The maker, 2026-10-17: the glyph and "Obverse" were a bit distracting.
    _front(win)
    win._act_obverse.trigger()
    badge = win.view.obverse_badge
    labels = badge.findChildren(QLabel)
    assert [lb.text() for lb in labels] == ["posterior"]
    assert not any(lb.pixmap() is not None and not lb.pixmap().isNull()
                   for lb in labels)
    assert "Obverse" not in " ".join(lb.text() for lb in labels)


def test_the_word_changes_in_place(win):
    # The quiet label's word and the chip's start within a pixel of each
    # other and are the same size, so the toggle swaps the word and adds the
    # box, and nothing jumps.
    _front(win)
    view = win.view
    quiet = view.face_label
    quiet_at = quiet.mapTo(view, QPoint(0, 0))
    quiet_size = (quiet.font().pixelSize(), quiet.sizeHint().height())
    win._act_obverse.trigger()
    QApplication.processEvents()
    word = view.obverse_badge.face_label()
    word_at = word.mapTo(view, QPoint(0, 0))
    assert abs(word_at.x() - quiet_at.x()) <= 1
    assert abs(word_at.y() - quiet_at.y()) <= 1
    assert (word.font().pixelSize(), word.sizeHint().height()) == quiet_size
    win._act_obverse.trigger()
    QApplication.processEvents()
    assert quiet.mapTo(view, QPoint(0, 0)) == quiet_at


def test_the_component_tab_has_no_obverse(win):
    assert win._act_obverse.isVisible()
    hinge = _tab(win, 3)
    assert not win._act_obverse.isVisible()
    win._hotkey_targets["obverse"]()                # V on the component tab
    assert not hinge.view.is_obverse() and not hinge.obverse
    assert not win._act_obverse.isChecked()
    _tab(win, 2)
    assert win._act_obverse.isVisible()


def test_the_hotkey_the_menu_and_the_toolbar_entry(win):
    assert prefs_mod.DEFAULTS["hotkeys"]["obverse"] == "V"
    assert prefs_mod.DEFAULTS["toolbar"]["obverse"] is True
    assert win._toolbar_actions["obverse"] is win._act_obverse
    win._hotkey_targets["obverse"]()
    assert win.view.is_obverse()
    proxy, act = win._view_menu_toggles["obverse"]
    assert act is win._act_obverse and proxy.text() == "View Obverse"
    win._sync_view_menu_toggles()                   # what opening the menu does
    assert proxy.isChecked()
    proxy.trigger()                                 # the menu turns it back
    assert not win.view.is_obverse()
    assert "(V)" in win._act_obverse.toolTip()


def test_new_and_open_return_every_tab_to_its_default_face(win, tmp_path):
    _front(win)
    win._act_obverse.trigger()
    temple = _tab(win, 1)
    win._act_obverse.trigger()
    _tab(win, 0)
    path = str(tmp_path / "frame.gdraw")
    win._do_save_gdraw(path)
    win._dirty = False
    win._new()
    assert not any(ws.obverse or ws.view.is_obverse() for ws in win._workspaces)
    assert not win._act_obverse.isChecked()
    win._act_obverse.trigger()
    win._open_gdraw(path, remember=False)
    assert not any(ws.view.is_obverse() for ws in win._workspaces)
    assert not temple.view.obverse_badge.isVisible()


# ── Nothing but the view ───────────────────────────────────────────────────

def test_the_file_and_the_dxf_are_the_same_whichever_face_is_shown(win, tmp_path,
                                                                    monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    ws = _front(win)
    temple = _tab(win, 1)
    temple.add_curve(line([(0, -6), (130, -5), (140, 2), (130, 6), (0, 6)],
                          closed=True, layer=Layer.OUTLINE))
    temple.add_text(TextObject(text="GUILD", family="DejaVu Sans", size_mm=4.0,
                               rotation=0.0, anchor_x=20.0, anchor_y=1.5,
                               layer=Layer.ENGRAVING))
    _tab(win, 0)

    def written(tag):
        gdraw = tmp_path / f"{tag}.gdraw"
        win._do_save_gdraw(str(gdraw))
        with zipfile.ZipFile(gdraw) as zf:
            members = {n: zf.read(n) for n in zf.namelist()}
        out = {}
        for i in (0, 1):
            _tab(win, i)
            dxf = tmp_path / f"{tag}-{i}.dxf"
            monkeypatch.setattr(QFileDialog, "getSaveFileName",
                                staticmethod(lambda *a, p=str(dxf), **k: (p, "")))
            win._export_dxf()
            out[i] = _dxf_entities(dxf)
        _tab(win, 0)
        return members, out

    plain = written("plain")
    win._act_obverse.trigger()
    _tab(win, 1)
    win._act_obverse.trigger()
    _tab(win, 0)
    turned = written("turned")
    win._dirty = False
    assert turned[0]["front.svg"] == plain[0]["front.svg"]
    assert turned[0]["temple_r.svg"] == plain[0]["temple_r.svg"]
    assert turned[1] == plain[1]
    assert ws.view.is_obverse()


def _dxf_entities(path):
    import ezdxf
    doc = ezdxf.readfile(str(path))
    out = []
    for e in doc.modelspace():
        pts = []
        if e.dxftype() == "SPLINE":
            pts = [tuple(round(v, 6) for v in p) for p in e.control_points]
        elif e.dxftype() in ("CIRCLE", "ARC"):
            pts = [tuple(round(v, 6) for v in e.dxf.center)]
        elif e.dxftype() == "LWPOLYLINE":
            pts = [tuple(round(v, 6) for v in p[:2]) for p in e.get_points()]
        elif e.dxftype() == "LINE":
            pts = [tuple(round(v, 6) for v in e.dxf.start),
                   tuple(round(v, 6) for v in e.dxf.end)]
        out.append((e.dxftype(), e.dxf.layer, tuple(pts)))
    return sorted(out)


# ── The PNG follows the view ───────────────────────────────────────────────

def test_a_mirrored_png_is_the_plain_one_reversed(win, tmp_path):
    from PySide6.QtGui import QImage
    from framedraft.export.png import render_png
    ws = _front(win)
    rect = QRectF(-50, -50, 100, 100)
    plain, turned = tmp_path / "plain.png", tmp_path / "turned.png"
    render_png(ws.scene, str(plain), dpi=40, rect=rect)
    render_png(ws.scene, str(turned), dpi=40, rect=rect, mirrored=True)
    a, b = QImage(str(plain)), QImage(str(turned))
    assert a.size() == b.size()
    w, h = a.width(), a.height()

    def near(p, q) -> bool:
        return max(abs(p.red() - q.red()), abs(p.green() - q.green()),
                   abs(p.blue() - q.blue())) <= 40

    def off(img, other):
        """Share of pixels where *other*, read right to left, is not *img*.
        A hairline may land a column over once reversed (sub-pixel rounding),
        so a pixel matches anything within one column of its mirror."""
        bad = 0
        for y in range(h):
            for x in range(w):
                p, m = img.pixelColor(x, y), w - 1 - x
                if not any(near(p, other.pixelColor(c, y))
                           for c in (m - 1, m, m + 1) if 0 <= c < w):
                    bad += 1
        return bad / (w * h)

    assert off(a, b) < 0.002              # the turned PNG is the plain one reversed
    assert off(a, a) > 0.002              # and the drawing is not symmetric itself


def test_the_png_export_follows_view_obverse(win, tmp_path, monkeypatch):
    import framedraft.export.png as png_mod
    from PySide6.QtWidgets import QFileDialog, QInputDialog
    _front(win)
    seen = []
    monkeypatch.setattr(png_mod, "render_png",
                        lambda *a, mirrored=False, **k: seen.append(mirrored))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / "f.png"), "")))
    monkeypatch.setattr(QInputDialog, "getItem",
                        staticmethod(lambda *a, **k: (a[3][2], True)))
    win._export_png()
    win._act_obverse.trigger()
    win._export_png()
    assert seen == [False, True]
    assert "as View Obverse shows it" in win._status.currentMessage()


def test_the_quiet_label_names_the_face_of_the_default_view(win):
    _front(win)
    label = win.view.face_label
    assert label.isVisible() and label.text() == "anterior"
    assert label.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    win._act_obverse.trigger()                     # the badge takes the corner
    assert not label.isVisible() and win.view.obverse_badge.isVisible()
    win._act_obverse.trigger()
    assert label.isVisible()
    temple = _tab(win, 1)
    assert temple.view.face_label.isVisible()
    assert temple.view.face_label.text() == "posterior"
    hinge = _tab(win, 3)
    assert not hinge.view.face_label.isVisible()   # no face to name
