"""Tooltips wrap and can be switched off — GuildModel's filter and ? button,
carried over. The ? sits at the foot of the toolbar, where the ⋯ overflow
cannot take it."""
import json

import pytest
from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QFont, QFontMetrics, QHelpEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton, QToolTip

from framedraft.tooltips import LINE_CHARS, TooltipFilter, format_tooltip

LONG = ("Temple Copy: send a mirrored copy of this temple's content into the other "
        "temple workspace (R to L or L to R). Asks for confirmation, because it "
        "replaces everything in the target workspace.")


def _tip_labels():
    return [w for w in QApplication.topLevelWidgets()
            if w.metaObject().className() == "QTipLabel" and w.isVisible()]


def _hide_tip():
    """Hide the tip and wait for it to go — it fades on a timer, slower
    when the suite is busy."""
    QToolTip.hideText()
    for _ in range(40):
        QTest.qWait(100)
        if not _tip_labels():
            return


# ------------------------------------------------------------------ wrapping

def test_a_plain_tooltip_is_rebroken_into_balanced_lines():
    fm = QFontMetrics(QFont())
    out = format_tooltip(LONG, fm)
    assert "<" not in out                     # plain text; Qt keeps the breaks
    lines = out.split("\n")
    assert len(lines) >= 3
    limit = fm.averageCharWidth() * LINE_CHARS
    assert all(fm.horizontalAdvance(line) <= limit for line in lines)
    widths = [fm.horizontalAdvance(line) for line in lines[:-1]]
    assert max(widths) - min(widths) < limit * 0.35       # balanced, not ragged
    assert "".join(out.split()) == "".join(LONG.split())  # every character kept


def test_hand_wrapped_tips_reflow_but_paragraphs_colons_and_bullets_hold():
    fm = QFontMetrics(QFont())
    assert format_tooltip("a\nb", fm) == "a b"
    assert format_tooltip("a\n\nb", fm) == "a\n\nb"
    # GuildDraw's own idiom: "Snap Node to Endpoint (E):" heads its lines
    assert format_tooltip("Snap Node (E):\nMove the node.", fm) == \
        "Snap Node (E):\nMove the node."
    assert format_tooltip("Uses:\n• one\n• two", fm) == "Uses:\n• one\n• two"
    assert format_tooltip("<b>rich</b>", fm) == "<b>rich</b>"
    assert format_tooltip("", fm) == ""
    assert format_tooltip(LONG, None) == LONG


def test_the_filter_shows_a_narrow_tip_and_swallows_when_off():
    btn = QPushButton("b")
    btn.setToolTip(LONG)
    btn.show()
    QApplication.processEvents()
    filt = TooltipFilter(enabled=True)
    ev = QHelpEvent(QEvent.Type.ToolTip, QPoint(5, 5), btn.mapToGlobal(QPoint(5, 5)))
    _hide_tip()                               # none left over from earlier tests
    try:
        assert filt.eventFilter(btn, ev) is True
        QApplication.processEvents()
        tips = _tip_labels()
        assert tips, "the wrapped tip was not shown"
        fm = btn.fontMetrics()
        assert tips[0].width() <= fm.averageCharWidth() * LINE_CHARS * 1.4
        assert tips[0].height() > fm.height() * 2                 # it wrapped
        _hide_tip()
        assert not _tip_labels()

        filt.enabled = False
        assert filt.eventFilter(btn, ev) is True                  # swallowed
        QTest.qWait(100)
        assert not _tip_labels()
        filt.set_exempt([btn])
        assert filt.eventFilter(btn, ev) is True                  # exempt: shown anyway
        QTest.qWait(100)
        assert _tip_labels()
        _hide_tip()
        # anything but a tooltip event passes straight through
        assert filt.eventFilter(btn, QEvent(QEvent.Type.Resize)) is False
    finally:
        btn.close()
        btn.deleteLater()


# ------------------------------------------------------------------ the window

@pytest.fixture()
def win(tmp_path, monkeypatch):
    import framedraft.prefs as prefs_mod
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    from framedraft.app import MainWindow
    monkeypatch.setattr(MainWindow, "_AUTOSAVE_DIR", tmp_path / "autosave")
    w = MainWindow()
    yield w
    w._dirty = False
    w.close()
    w.deleteLater()


def test_the_question_mark_sits_below_the_overflow_and_is_exempt(win):
    win.resize(1200, 700)                     # short enough that the bar overflows
    win.show()
    for _ in range(4):
        QApplication.processEvents()
    tb = win._toolbar
    btn = tb.trailing_button()
    assert isinstance(btn, QToolButton) and btn.defaultAction() is win._act_tooltips
    assert not win._act_tooltips.icon().isNull()
    assert btn in win._tooltip_filter._exempt
    assert win._act_tooltips not in tb.actions()      # outside the layout: never overflows
    assert tb._overflow_actions(), "the bar was expected to overflow at 700 px"
    assert btn.isVisible()
    ext = tb.extension_button()
    assert ext is not None and ext.isVisible()
    # below the ⋯, inside the bar, clear of every laid-out button
    assert btn.geometry().top() >= ext.geometry().bottom()
    assert btn.geometry().bottom() <= tb.height()
    for act in tb.actions():
        w = tb.widgetForAction(act)
        if w is not None and w.isVisible():
            assert not w.geometry().intersects(btn.geometry()), act.text()


def test_the_switch_turns_tips_off_and_is_remembered(win, tmp_path):
    assert win._act_tooltips.isChecked() and win._tooltip_filter.enabled
    win._act_tooltips.trigger()
    assert win._tooltip_filter.enabled is False
    assert "off" in win._act_tooltips.toolTip()
    saved = json.loads((tmp_path / "prefs.json").read_text(encoding="utf-8"))
    assert saved["tooltips"] is False
    win._act_tooltips.trigger()
    assert win._tooltip_filter.enabled is True
    saved = json.loads((tmp_path / "prefs.json").read_text(encoding="utf-8"))
    assert saved["tooltips"] is True


def test_a_saved_off_starts_the_window_with_tips_off(tmp_path, monkeypatch):
    import framedraft.prefs as prefs_mod
    monkeypatch.setattr(prefs_mod, "_DIR", tmp_path)
    monkeypatch.setattr(prefs_mod, "_FILE", tmp_path / "prefs.json")
    p = prefs_mod.load()
    p["tooltips"] = False
    prefs_mod.save(p)
    from framedraft.app import MainWindow
    monkeypatch.setattr(MainWindow, "_AUTOSAVE_DIR", tmp_path / "autosave")
    w = MainWindow()
    try:
        assert not w._act_tooltips.isChecked()
        assert w._tooltip_filter.enabled is False
    finally:
        w._dirty = False
        w.close()
        w.deleteLater()
