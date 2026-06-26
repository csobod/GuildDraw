"""Pinnable toolbar overflow pop-out.

Qt's native toolbar overflow ("⋯") shows the hidden actions in a transient
popup that auto-hides. PinnableToolBar turns the ⋯ into a toggle that pins those
actions out in a persistent panel until clicked again, and remembers the choice.

These run a real (offscreen) QApplication because the behaviour depends on
QToolBar's overflow layout.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget
from PySide6.QtGui import QAction

from framedraft.pinnable_toolbar import PinnableToolBar


def _make_overflowing_toolbar(n=30, height=160):
    win = QMainWindow()
    win.setCentralWidget(QWidget())
    tb = PinnableToolBar("Tools")
    win.addToolBar(Qt.ToolBarArea.LeftToolBarArea, tb)
    acts = [QAction(f"A{i}", win) for i in range(n)]
    for a in acts:
        tb.addAction(a)
    win.resize(420, 320)
    win.show()
    tb.setFixedHeight(height)
    QApplication.processEvents()
    tb.layout().activate()
    QApplication.processEvents()
    return win, tb, acts


def test_overflow_detected_and_panel_pins_open():
    win, tb, acts = _make_overflowing_toolbar()
    overflow = tb._overflow_actions()
    assert overflow, "expected some actions to overflow the short toolbar"
    assert tb.extension_button() is not None

    # Not pinned by default → no panel shown.
    assert tb._panel is None or not tb._panel.isVisible()

    tb.set_pinned(True)
    QApplication.processEvents()
    assert tb.is_pinned()
    assert tb._panel.isVisible()
    assert len(tb._panel._buttons) == len(overflow)

    tb.set_pinned(False)
    QApplication.processEvents()
    assert not tb._panel.isVisible()


def test_ellipsis_click_toggles_pin_and_emits():
    win, tb, acts = _make_overflowing_toolbar()
    tb._refresh()                       # ensure the ⋯ button is hooked
    seen = []
    tb.pin_changed.connect(seen.append)
    ext = tb.extension_button()
    assert ext is not None

    ext.click()                         # real ⋯ click
    QApplication.processEvents()
    assert tb.is_pinned() and tb._panel.isVisible()

    ext.click()                         # click again → unpin
    QApplication.processEvents()
    assert not tb.is_pinned() and not tb._panel.isVisible()

    assert seen == [True, False]


def test_native_transient_expansion_never_lingers():
    # The native overflow is checkable and tracks its own expanded state. After
    # each ⋯ click that state must be forced back to collapsed, or it desyncs
    # from our pin and the next click toggles the wrong way.
    win, tb, acts = _make_overflowing_toolbar()
    tb._refresh()
    ext = tb.extension_button()

    ext.click()
    QApplication.processEvents()
    assert tb.is_pinned()
    assert not ext.isChecked()          # native popup squashed, not showing

    ext.click()
    QApplication.processEvents()
    assert not tb.is_pinned()
    assert not ext.isChecked()


def test_pinned_panel_resyncs_when_overflow_shrinks():
    win, tb, acts = _make_overflowing_toolbar(height=160)
    tb.set_pinned(True)
    QApplication.processEvents()
    before = len(tb._panel._buttons)

    tb.setFixedHeight(280)   # more buttons fit → fewer overflow
    QApplication.processEvents()
    tb.layout().activate()
    QApplication.processEvents()
    tb._refresh()

    after = len(tb._panel._buttons)
    assert after == len(tb._overflow_actions())
    assert after < before


def test_no_overflow_means_no_panel_even_when_pinned():
    win, tb, acts = _make_overflowing_toolbar(n=3, height=400)
    assert tb._overflow_actions() == []
    tb.set_pinned(True)
    QApplication.processEvents()
    assert tb._panel is None or not tb._panel.isVisible()
