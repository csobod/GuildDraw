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

A *trailing* action (`set_trailing_action`) sits at the far end of the bar,
outside the action layout: the bar reserves room for it in its contents
margins, so overflow never takes it and the ⋯ lands just before it. The
tooltip switch lives there — GuildModel's ? at the end of its toolbar, where
GuildDraw's longer bar would otherwise hide it behind the ⋯.
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
        self._signature = None
        self.apply_theme(False)

    def apply_theme(self, dark: bool):
        from . import theme
        bg, border = theme.color("chrome.bg"), theme.color("chrome.border")
        self.setStyleSheet(
            f"#overflowPanel {{ background-color: {bg}; "
            f"border: 1px solid {border}; border-radius: 4px; }}"
        )

    def rebuild(self, actions: list):
        style = self._tb.toolButtonStyle()
        isize = self._tb.iconSize()
        # Same actions, same look: nothing to rebuild. Every ActionChanged
        # (a toggle clicked in the pop-out, Explode enabling on a selection)
        # used to rebuild it.
        signature = (tuple(id(a) for a in actions), style, isize.width(),
                     isize.height(), self._tb.height())
        if signature == self._signature and self._buttons:
            return
        self._signature = signature
        for b in self._buttons:
            b.setParent(None)
            b.deleteLater()
        self._buttons.clear()

        for act in actions:
            btn = QToolButton(self)
            btn.setDefaultAction(act)          # shares icon/state/trigger
            btn.setToolButtonStyle(style)
            btn.setIconSize(isize)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._buttons.append(btn)
        # Wrap into columns within the toolbar's own height, measured with the
        # real button and grid spacing: the old icon + 14 estimate against the
        # window height let the panel climb over the menu bar.
        m = self._grid.contentsMargins()
        avail = self._tb.height() - m.top() - m.bottom()
        row_h = max(1, self._buttons[0].sizeHint().height() + self._grid.spacing()) \
            if self._buttons else 1
        max_rows = max(1, min(len(actions), (avail + self._grid.spacing()) // row_h))
        for idx, btn in enumerate(self._buttons):
            self._grid.addWidget(btn, idx % max_rows, idx // max_rows)
            # A child added to a panel that is already showing stays hidden
            # until shown, and adjustSize() ignores hidden children: every
            # rebuild after the first collapsed the pop-out to a 10×10 box.
            btn.show()
        self.adjustSize()

    def button_for(self, action) -> "QToolButton | None":
        return next((b for b in self._buttons if b.defaultAction() is action),
                    None)

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
        top = tb.mapTo(win, QPoint(0, 0)).y()      # never above the toolbar (the menus)
        x = max(0, min(x, win.width() - self.width()))
        y = max(top, min(y, win.height() - self.height()))
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
        # Coalesce refreshes; child timer so a pending tick is canceled when
        # the toolbar is destroyed (avoids firing _refresh on a dead C++ object).
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(0)
        self._refresh_timer.timeout.connect(self._refresh)
        self._trailing: QToolButton | None = None
        self.iconSizeChanged.connect(lambda *_: self._fit_trailing())
        self.orientationChanged.connect(lambda *_: self._fit_trailing())

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

    def visible_panel(self) -> "_OverflowPanel | None":
        """The pinned pop-out, when it is on screen."""
        return self._panel if self._panel is not None and self._panel.isVisible() \
            else None

    def set_trailing_action(self, action) -> QToolButton:
        """Pin `action` to the far end of the bar (the bottom of a vertical
        bar, the right of a horizontal one), where overflow never reaches.
        Returns its button, which is a plain child of the bar."""
        if self._trailing is None:
            self._trailing = QToolButton(self)
            self._trailing.setObjectName("trailingButton")
            self._trailing.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._trailing.setAutoRaise(True)
        self._trailing.setDefaultAction(action)
        self._fit_trailing()
        return self._trailing

    def trailing_button(self) -> "QToolButton | None":
        return self._trailing

    def _fit_trailing(self):
        """Size the trailing button like its siblings, reserve its room in the
        bar's contents margins (QLayout lays out inside contentsRect), and
        place it."""
        btn = self._trailing
        if btn is None:
            return
        btn.setToolButtonStyle(self.toolButtonStyle())
        btn.setIconSize(self.iconSize())
        btn.adjustSize()
        gap = 6
        if self.orientation() == Qt.Orientation.Vertical:
            self.setContentsMargins(0, 0, 0, btn.sizeHint().height() + gap)
        else:
            self.setContentsMargins(0, 0, btn.sizeHint().width() + gap, 0)
        self._place_trailing()

    def _place_trailing(self):
        btn = self._trailing
        if btn is None:
            return
        size = btn.sizeHint()
        btn.resize(size)
        if self.orientation() == Qt.Orientation.Vertical:
            btn.move(max(0, (self.width() - size.width()) // 2),
                     max(0, self.height() - size.height() - 4))
        else:
            btn.move(max(0, self.width() - size.width() - 4),
                     max(0, (self.height() - size.height()) // 2))
        btn.show()
        btn.raise_()

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
        self._fit_trailing()
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
        self._place_trailing()
        self._schedule_refresh()

    def actionEvent(self, e):
        super().actionEvent(e)
        self._schedule_refresh()

    def event(self, e):
        if e.type() == QEvent.Type.LayoutRequest:
            self._schedule_refresh()
        elif e.type() == QEvent.Type.StyleChange:
            # A new stylesheet (theme, compact toolbar) resizes the buttons;
            # _refresh re-fits the trailing one.
            self._schedule_refresh()
        return super().event(e)
