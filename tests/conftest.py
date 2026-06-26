"""Session-wide Qt application for the whole test suite.

Some tests need a Qt application instance. Creating it here — before any test
module is imported — guarantees a single, shared QApplication. It must be the
QtWidgets variant: the widget-based tests (QMainWindow/QToolBar) crash under a
bare QGuiApplication, which is what an individual module would otherwise create
first. The default platform plugin is used (not "offscreen") so font-dependent
tests (text-outline geometry) still see real system fonts — the offscreen
plugin exposes none.
"""
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])
