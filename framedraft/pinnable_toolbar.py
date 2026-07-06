"""A QToolBar whose overflow ("⋯") pop-out can be PINNED open.

Qt's native overflow button reveals the hidden actions in a *transient* popup
that auto-hides on the next click or focus change. Users asked for a toggle
instead: click ⋯ to pop the hidden tools out and keep them out across
operations, click ⋯ again to collapse, and remember that choice.

Rather than fight Qt's internal (transient, auto-collapsing) expansion, we let
the native ⋯ button act purely as a click trigger: each click attempts a native
expand, which we immediately squash and translate into a toggle of our own
pop-out — a plain child widget that never auto-hides. It mirrors exactly the
actions Qt has marked as overflowed (their toolbar buttons go invisible), so it
stays in sync as the window is resized or buttons are shown/hidden.
"""
from PySide6.QtCore import Qt, QEvent, QPoint, QTimer, Signal
from PySide6.QtWidgets import QToolBar, QToolButton, QFrame, QGridLayout




class _OverflowPanel(QFrame):
    """Non-auto-hiding panel of QToolButtons mirroring the overflowed actions.

    It is a plain child of the main window (no window flags) so it follows the
    window and renders as an overlay beside the toolbar; it never grabs focus.
    """

    def __init__(self, toolbar: "PinnableToolBar"):
        super().__init__()
        self._tb = toolbar
        self.setObjectName("overflowPanel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self._grid.setSpacing(2)
        self._buttons: list[QToolButton] = []
        self.apply_theme(False)

    def apply_theme(self, dark: bool):
        from . import theme
        bg, border = theme.color("chrome.bg"), theme.color("chrome.border")
        self.setStyleSheet(
            f"#overflowPanel {{ background-color: {bg}; "
            f"border: 1px solid {border}; border-radius: 4px; }}"
        )

    def rebuild(self, actions: list):
        for b in self._buttons:
            b.setParent(None)
            b.deleteLater()
        self._buttons.clear()

        style = self._tb.toolButtonStyle()
        isize = self._tb.iconSize()
        # Wrap into columns so a long overflow never runs off the screen.
        win = self._tb.window()
        avail = (win.height() if win else 800) - 48
        row_h = max(1, isize.height() + 14)
        max_rows = max(1, min(len(actions), avail // row_h))

        for idx, act in enumerate(actions):
            btn = QToolButton(self)
            btn.setDefaultAction(act)          # shares icon/state/trigger
            btn.setToolButtonStyle(style)
            btn.setIconSize(isize)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._grid.addWidget(btn, idx % max_rows, idx // max_rows)
            self._buttons.append(btn)
        self.adjustSize()

    def reposition(self):
        tb = self._tb
        win = tb.window()
        if win is None:
            return
        if self.parent() is not win:
            self.setParent(win)
        ext = tb.extension_button()
        # x: just past the toolbar's right edge.
        x = tb.mapTo(win, QPoint(tb.width(), 0)).x()
        # y: bottom-aligned with the ⋯ button so the panel grows upward beside it.
        if ext is not None:
            y = ext.mapTo(win, QPoint(0, ext.height())).y() - self.height()
        else:
            y = tb.mapTo(win, QPoint(0, tb.height())).y() - self.height()
        x = max(0, min(x, win.width() - self.width()))
        y = max(0, min(y, win.height() - self.height()))
        self.move(x, y)


class PinnableToolBar(QToolBar):
    """QToolBar with a persistent (pinnable) overflow pop-out.

    Emits ``pin_changed(bool)`` whenever the user toggles the pin so the host
    can persist the preference.
    """

    pin_changed = Signal(bool)

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self._pinned = False
        self._dark = False
        self._ext_btn: QToolButton | None = None
        self._panel: _OverflowPanel | None = None
        self._squashing = False
        # Coalesce refreshes; child timer so a pending tick is cancelled when
        # the toolbar is destroyed (avoids firing _refresh on a dead C++ object).
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(0)
        self._refresh_timer.timeout.connect(self._refresh)

    # ------------------------------------------------------------------ API
    def is_pinned(self) -> bool:
        return self._pinned

    def set_pinned(self, pinned: bool, *, persist: bool = True):
        pinned = bool(pinned)
        changed = pinned != self._pinned
        self._pinned = pinned
        self._refresh()
        if changed and persist:
            self.pin_changed.emit(self._pinned)

    def set_dark(self, dark: bool):
        self._dark = bool(dark)
        if self._panel is not None:
            self._panel.apply_theme(self._dark)
        self._apply_ext_icon()   # re-ink the ⋯ glyph for the new mode

    def extension_button(self) -> "QToolButton | None":
        return self._ext_btn

    # ------------------------------------------------------------- internals
    def _hook_ext(self):
        ext = self.findChild(QToolButton, "qt_toolbar_ext_button")
        if ext is not self._ext_btn:
            self._ext_btn = ext
            if ext is not None:
                # clicked() fires exactly once per physical click, AFTER Qt's own
                # (transient) expand slot — so our collapse below always wins.
                ext.clicked.connect(self._on_ext_clicked)
                self._apply_ext_icon()

    def _apply_ext_icon(self):
        """Replace Qt's style-drawn extension glyph with our own ellipsis.

        The native glyph is painted from the style's palette, which renders
        white in light mode against the pale button face — unreadable. An
        explicit theme-inked icon reads correctly in both modes."""
        if self._ext_btn is None:
            return
        from . import theme
        from .icons import make_icon
        ink = theme.color("chrome.ink")
        self._ext_btn.setIcon(make_icon("ellipsis", ink, ink))

    def _on_ext_clicked(self, *args):
        # We never use Qt's native transient expansion: collapse whatever the
        # click just expanded, then translate the click into a pin toggle.
        self._collapse_native()
        self.set_pinned(not self._pinned)

    def _collapse_native(self):
        """Undo Qt's native overflow expansion and reset the ⋯ button state.

        The native extension button is checkable and tracks the expanded state;
        if we leave it set, its checked state desyncs from our pin and the next
        click toggles the wrong way. Force both back to collapsed/unchecked.
        """
        if self._squashing:
            return
        self._squashing = True
        try:
            self.layout().setExpanded(False)
        except Exception:
            pass
        if self._ext_btn is not None:
            self._ext_btn.setChecked(False)
        self._squashing = False

    def _overflow_actions(self) -> list:
        out = []
        for act in self.actions():
            if act.isSeparator() or not act.isVisible():
                continue
            w = self.widgetForAction(act)
            if w is not None and not w.isVisible():   # hidden by overflow only
                out.append(act)
        return out

    def _refresh(self):
        self._hook_ext()
        self._collapse_native()   # we never use Qt's transient expansion
        if not self._pinned:
            if self._panel is not None:
                self._panel.hide()
            return
        actions = self._overflow_actions()
        if not actions:
            if self._panel is not None:
                self._panel.hide()
            return
        if self._panel is None:
            self._panel = _OverflowPanel(self)
            self._panel.apply_theme(self._dark)
        self._panel.rebuild(actions)
        self._panel.reposition()
        self._panel.show()
        self._panel.raise_()

    def _schedule_refresh(self):
        # Defer so layout/visibility is settled before we read overflow state.
        self._refresh_timer.start()

    # ---------------------------------------------------------------- events
    def showEvent(self, e):
        super().showEvent(e)
        self._schedule_refresh()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._schedule_refresh()

    def actionEvent(self, e):
        super().actionEvent(e)
        self._schedule_refresh()

    def event(self, e):
        if e.type() == QEvent.Type.LayoutRequest:
            self._schedule_refresh()
        return super().event(e)
