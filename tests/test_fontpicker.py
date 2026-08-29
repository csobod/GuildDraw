"""Type-to-filter font picker (v1.2).

Replaces QFontComboBox in the engraving Text dialog and in Settings ▸ PDF.
The contract: nothing is loaded from the font library until the maker types,
the drop-down then narrows to the families that match, the best prefix match
is still completed inline, and whatever ends up in the box always resolves to
a font that is actually installed.

Nothing here may name a specific typeface — a CI runner's font set is its own.
Everything is driven off whatever font_families() reports.
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from framedraft.fontpicker import FontFilterCombo, font_families, resolve_family


@pytest.fixture()
def combo():
    c = FontFilterCombo()
    yield c
    c.deleteLater()


def _family_with_siblings() -> str | None:
    """A family sharing a first word with at least one other — the case the
    picker exists for ("Helvetica Neue Thin" vs "Helvetica Neue Thin Italic")."""
    seen = {}
    for fam in font_families():
        seen.setdefault(fam.split()[0].lower(), []).append(fam)
    for group in seen.values():
        if len(group) > 1:
            return group[0]
    return None


def _type(combo, text):
    """Real keystrokes into the box — the inline completion is deferred to the
    next event-loop pass, so flush it before looking."""
    QTest.keyClicks(combo.lineEdit(), text)
    QApplication.processEvents()


# ------------------------------------------------------------- laziness

def test_nothing_is_loaded_before_the_first_character(combo):
    """The whole point: a maker with thousands of fonts opens the dialog and
    the library is never touched."""
    assert combo._loaded is False
    assert combo.completer().model().rowCount() == 0


def test_showing_a_family_does_not_load_the_library(combo):
    combo.set_family(font_families()[0])
    assert combo._loaded is False


def test_the_arrow_on_an_empty_box_loads_nothing(combo):
    combo.lineEdit().clear()
    combo.showPopup()
    assert combo._loaded is False
    assert combo.completer().completionCount() == 0


def test_the_first_character_loads_the_library(combo):
    _type(combo, font_families()[0][0])
    assert combo._loaded is True
    assert combo.completer().model().rowCount() == len(font_families())


# ------------------------------------------------------------- filtering

def test_typing_narrows_the_list_to_matches(combo):
    fam = font_families()[0]
    stem = fam[:3]
    combo.lineEdit().clear()
    _type(combo, stem)
    comp = combo.completer()
    shown = [comp.completionModel().index(i, 0).data()
             for i in range(comp.completionCount())]
    assert shown, "typing a real family's stem matched nothing"
    assert all(stem.lower() in name.lower() for name in shown)
    assert len(shown) < len(font_families())


def test_the_arrow_offers_the_current_familys_siblings(combo):
    fam = _family_with_siblings()
    if fam is None:
        pytest.skip("no font family on this machine has siblings")
    combo.set_family(fam)
    combo.showPopup()
    comp = combo.completer()
    shown = [comp.completionModel().index(i, 0).data()
             for i in range(comp.completionCount())]
    assert fam in shown


# ------------------------------------------------- inline completion

def test_the_best_prefix_match_is_completed_inline(combo):
    fam = next((f for f in font_families() if len(f) > 4), None)
    if fam is None:
        pytest.skip("no font family long enough to half-type")
    stem = fam[:3]
    combo.lineEdit().clear()
    _type(combo, stem)
    shown = combo.lineEdit().text()
    assert shown.lower().startswith(stem.lower())
    assert len(shown) > len(stem), "nothing was completed"
    # …and only the completed tail is selected, so the next keystroke replaces
    # it instead of appending to a name the maker never typed.
    assert combo.lineEdit().selectedText() == shown[len(stem):]


def test_backspace_does_not_put_the_deleted_tail_back(combo):
    fam = next((f for f in font_families() if len(f) > 4), None)
    if fam is None:
        pytest.skip("no font family long enough to half-type")
    stem = fam[:3]
    combo.lineEdit().clear()
    _type(combo, stem)
    QTest.keyClick(combo.lineEdit(), Qt.Key.Key_Backspace)
    QApplication.processEvents()
    # The selected completion is what backspace eats, leaving what was typed.
    assert combo.lineEdit().text() == stem
    assert combo.lineEdit().selectedText() == ""


# ------------------------------------------------------------- resolving

def test_resolve_family_prefers_an_exact_match_any_case():
    fam = font_families()[0]
    assert resolve_family(fam.upper()) == fam
    assert resolve_family(fam.lower()) == fam


def test_resolve_family_accepts_a_prefix():
    fam = next((f for f in font_families() if len(f) > 4), None)
    if fam is None:
        pytest.skip("no font family long enough to half-type")
    assert resolve_family(fam[:3]).lower().startswith(fam[:3].lower())


def test_resolve_family_rejects_a_name_no_font_answers_to():
    assert resolve_family("Nrbnl Grtsk Zzz 9000") == ""
    assert resolve_family("") == ""


def test_a_name_no_font_answers_to_reverts_to_the_last_good_one(combo):
    """Handing an unknown family to QFont silently substitutes Qt's default —
    the engraving would come out in a face the maker never chose."""
    good = font_families()[0]
    combo.set_family(good)
    combo.lineEdit().setText("Nrbnl Grtsk Zzz 9000")
    assert combo.current_family() == good
    assert combo.lineEdit().text() == good


def test_a_half_typed_name_commits_to_the_family_it_starts(combo):
    fam = next((f for f in font_families() if len(f) > 4), None)
    if fam is None:
        pytest.skip("no font family long enough to half-type")
    combo.lineEdit().setText(fam[:3])
    assert combo.current_family().lower().startswith(fam[:3].lower())


def test_a_family_this_machine_lacks_is_kept_as_written(combo):
    """A document drawn on a machine with the font must keep reporting it, so
    saving on a machine without it doesn't quietly rewrite the design."""
    combo.set_family("Nrbnl Grtsk Zzz 9000")
    assert combo.current_family() == "Nrbnl Grtsk Zzz 9000"


def test_picking_from_the_list_commits_that_family(combo):
    fam = font_families()[-1]
    combo.completer().activated[str].emit(fam)
    combo.lineEdit().setText(fam)
    assert combo.current_family() == fam
