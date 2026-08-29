"""Type-to-filter font picker (v1.2).

QFontComboBox draws every installed family in its own typeface the moment the
list opens. On a design workstation carrying thousands of fonts that is a
visible stall from a standing start, and the list it finally shows is the
wrong shape for the job: picking "Helvetica Neue Thin Italic" out of two dozen
near-identical siblings means scrolling, while the inline autocomplete quietly
commits to whichever sibling happens to sort first.

FontFilterCombo turns that around. Nothing is loaded until the maker types the
first character — a blank box never queues the library. From there the
matching families drop down as a short filtered list (prefix matches first,
then anything containing the text) while the best prefix match is still
completed inline, so the old type-three-letters-and-go speed survives. The
dropdown arrow re-filters on whatever is already in the box, which is how you
get from "Helvetica Neue" to its weights.
"""

from PySide6.QtCore import QEvent, QStringListModel, Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QComboBox, QCompleter

_MAX_VISIBLE = 12

_families: list[str] | None = None


def font_families() -> list[str]:
    """Installed families, sorted, queried once per process."""
    global _families
    if _families is None:
        _families = sorted(QFontDatabase.families())
    return _families


def resolve_family(name: str) -> str:
    """The installed family *name* means, or "" if none does. An exact match
    (any case) wins; failing that the first family it is a prefix of, so a
    half-typed name still lands somewhere real."""
    text = (name or "").strip()
    if not text:
        return ""
    low = text.lower()
    for fam in font_families():
        if fam.lower() == low:
            return fam
    for fam in font_families():
        if fam.lower().startswith(low):
            return fam
    return ""


class FontFilterCombo(QComboBox):
    """Editable font box that only builds its list once the maker starts typing.

    Read the chosen family with :meth:`current_family` — it always returns a
    family that is actually installed, never whatever half-word was left in
    the box.
    """

    def __init__(self, parent=None, family: str = ""):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMinimumContentsLength(22)
        self.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)

        # The combo's own model stays empty: everything the maker sees comes
        # through the completer, which is only fed on the first keystroke.
        self._model   = QStringListModel([], self)
        self._loaded  = False
        self._deleting = False

        comp = QCompleter(self._model, self)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        comp.setMaxVisibleItems(_MAX_VISIBLE)
        comp.activated[str].connect(self._on_picked)
        self.setCompleter(comp)

        edit = self.lineEdit()
        edit.setPlaceholderText("Type to filter fonts…")
        edit.installEventFilter(self)
        edit.textEdited.connect(self._on_text_edited)
        edit.editingFinished.connect(self._commit)

        self._family = ""
        self.set_family(family or QFont().family())

    # ── public API ───────────────────────────────────────────────────────

    def set_family(self, name: str):
        """Show *name* without loading the library — an unknown name is kept
        as typed so a document drawn with a font this machine lacks still
        reports what it asked for."""
        name = (name or "").strip() or QFont().family()
        self._family = name
        self.setEditText(name)

    def current_family(self) -> str:
        self._commit()
        return self._family

    # ── list loading ─────────────────────────────────────────────────────

    def _ensure_loaded(self):
        if not self._loaded:
            self._model.setStringList(font_families())
            self._loaded = True

    # ── editing behaviour ────────────────────────────────────────────────

    def showPopup(self):
        """The arrow filters on what is already in the box rather than dropping
        the whole library: with a family in it you get that family's siblings
        (its weights and italics); with an empty box, just a cursor and the
        placeholder."""
        edit = self.lineEdit()
        edit.setFocus()
        edit.selectAll()
        text = edit.text().strip()
        if not text:
            return
        self._ensure_loaded()
        comp = self.completer()
        comp.setCompletionPrefix(text)
        if comp.completionCount():
            comp.complete()

    def eventFilter(self, obj, event):
        # Backspace/Delete must not be undone by the inline completion putting
        # the deleted tail straight back.
        if obj is self.lineEdit() and event.type() == QEvent.Type.KeyPress:
            self._deleting = event.key() in (Qt.Key.Key_Backspace,
                                             Qt.Key.Key_Delete)
        return super().eventFilter(obj, event)

    def _on_text_edited(self, text: str):
        if text.strip():
            self._ensure_loaded()
        if self._deleting:
            return
        # Deferred to the next event-loop pass so QLineEdit has already driven
        # the completer for this keystroke: the drop-down keeps filtering on
        # what was typed while the box shows the completed name. `self` is the
        # context object, so a dialog dismissed on the same keystroke takes the
        # pending call down with it instead of waking on a deleted widget.
        QTimer.singleShot(0, self, lambda typed=text: self._inline_complete(typed))

    def _inline_complete(self, typed: str):
        edit = self.lineEdit()
        if not typed or edit.text() != typed:
            return                      # a later keystroke already landed
        low = typed.lower()
        for fam in font_families():
            if fam.lower().startswith(low):
                edit.setText(fam)
                edit.setSelection(len(typed), len(fam) - len(typed))
                return

    def _on_picked(self, family: str):
        self._family = family

    def _commit(self):
        """Resolve whatever is in the box to an installed family, falling back
        to the last good one. A name no font answers to would silently become
        Qt's default at render time — the engraving would come out in a face
        the maker never chose."""
        text = self.lineEdit().text().strip()
        resolved = resolve_family(text) if text else ""
        if resolved:
            self._family = resolved
        if self.lineEdit().text() != self._family:
            self.setEditText(self._family)
