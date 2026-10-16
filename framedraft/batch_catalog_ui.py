"""The two dialogs of File ▸ Export ▸ Catalog PDFs for a Folder… (BUILDPLAN
*Road to 1.4*, item 3): the options after the folder is picked, and the
progress with one verdict per file. The engine is export/batch_catalog.py.
"""
from __future__ import annotations

import os

from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QProgressBar, QPushButton, QSpinBox, QVBoxLayout,
)

from .canvas.scene import DEFAULT_INLAY_FILL_COLOR
from .export.batch_catalog import BatchCatalogOptions


class BatchCatalogOptionsDialog(QDialog):
    """What to do with the folder just picked: the fill color and opacity,
    the Inlay Fill's if it is set too, where the PDFs go, whether the fills
    are saved into the files (originals backed up first) and whether a
    temple's Ghost is switched off."""

    def __init__(self, parent, library: str, last: dict):
        super().__init__(parent)
        self.setWindowTitle("Catalog PDFs for a Folder")
        self._library = library
        self._color = str(last.get("color", "#000000")).lower()
        self._inlay_color = str(last.get("inlay_color",
                                         DEFAULT_INLAY_FILL_COLOR)).lower()

        form = QFormLayout(self)
        form.setSpacing(8)
        folder = QLabel(library)
        folder.setWordWrap(True)
        folder.setToolTip("Every .gdraw at the top of this folder; subfolders "
                          "are left alone.")
        form.addRow("Folder:", folder)

        out_row = QHBoxLayout()
        self._out_edit = QLineEdit(last.get("out", ""))
        self._out_edit.setPlaceholderText(os.path.join(library, "catalog"))
        self._out_edit.setToolTip("Where the PDFs go, one per design. Empty "
                                  "= a catalog folder inside the library.")
        out_browse = QPushButton("Browse…")
        out_browse.clicked.connect(self._browse_out)
        out_row.addWidget(self._out_edit, 1)
        out_row.addWidget(out_browse)
        form.addRow("PDFs to:", out_row)

        fill_row = QHBoxLayout()
        self._color_btn = QPushButton("Color…")
        self._color_btn.setToolTip("The Frame Fill color set in every design "
                                   "(front and both temples).")
        self._color_btn.clicked.connect(self._pick_color)
        self._update_swatch()
        self._opacity = QSpinBox()
        self._opacity.setRange(0, 100)
        self._opacity.setSuffix(" %")
        self._opacity.setValue(int(last.get("opacity_pct", 100)))
        self._opacity.setToolTip("The fill's opacity.")
        fill_row.addWidget(self._color_btn)
        fill_row.addWidget(QLabel("at"))
        fill_row.addWidget(self._opacity)
        fill_row.addStretch(1)
        form.addRow("Frame Fill:", fill_row)

        inlay_row = QHBoxLayout()
        self._inlay_chk = QCheckBox("Set")
        self._inlay_chk.setChecked(bool(last.get("inlay_fill", False)))
        self._inlay_chk.setToolTip(
            "Also turn the Inlay Fill on, at this color and opacity, on every "
            "tab with a closed INLAY seat. Off: each design's Inlay Fill stays "
            "as it is.")
        self._inlay_color_btn = QPushButton("Color…")
        self._inlay_color_btn.setToolTip("The Inlay Fill color.")
        self._inlay_color_btn.clicked.connect(self._pick_inlay_color)
        self._update_inlay_swatch()
        self._inlay_opacity = QSpinBox()
        self._inlay_opacity.setRange(0, 100)
        self._inlay_opacity.setSuffix(" %")
        self._inlay_opacity.setValue(int(last.get("inlay_opacity_pct", 85)))
        self._inlay_opacity.setToolTip("The Inlay Fill's opacity.")
        inlay_row.addWidget(self._inlay_chk)
        inlay_row.addWidget(self._inlay_color_btn)
        inlay_row.addWidget(QLabel("at"))
        inlay_row.addWidget(self._inlay_opacity)
        inlay_row.addStretch(1)
        form.addRow("Inlay Fill:", inlay_row)
        self._inlay_chk.toggled.connect(self._sync_inlay_row)
        self._sync_inlay_row(self._inlay_chk.isChecked())

        self._save_chk = QCheckBox("Save the fill into the files (originals "
                                   "backed up first)")
        self._save_chk.setChecked(bool(last.get("save_fill", True)))
        self._save_chk.setToolTip(
            "Each design whose fill changes is written back, after a copy of "
            "the original goes to _backup/<timestamp>/ in the folder. Off: "
            "the PDFs show the fill, the files stay as they are.")
        self._ghost_chk = QCheckBox("Switch the Ghost off in the temple tabs")
        self._ghost_chk.setChecked(bool(last.get("temple_ghost_off", False)))
        self._ghost_chk.setToolTip(
            "A Ghost left on in a temple tab prints a flipped second outline "
            "over the temple on the catalog page.")
        self._dry_chk = QCheckBox("Report only; write nothing")
        self._dry_chk.setToolTip("See what would change without writing a "
                                 "file or a PDF.")
        for chk in (self._save_chk, self._ghost_chk, self._dry_chk):
            form.addRow(chk)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Run")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _update_swatch(self):
        pm = QPixmap(16, 16)
        pm.fill(QColor(self._color))
        self._color_btn.setIcon(QIcon(pm))
        self._color_btn.setText(self._color)

    def _pick_color(self):
        c = QColorDialog.getColor(QColor(self._color), self, "Frame Fill color")
        if c.isValid():
            self._color = c.name().lower()
            self._update_swatch()

    def _update_inlay_swatch(self):
        pm = QPixmap(16, 16)
        pm.fill(QColor(self._inlay_color))
        self._inlay_color_btn.setIcon(QIcon(pm))
        self._inlay_color_btn.setText(self._inlay_color)

    def _pick_inlay_color(self):
        c = QColorDialog.getColor(QColor(self._inlay_color), self,
                                  "Inlay Fill color")
        if c.isValid():
            self._inlay_color = c.name().lower()
            self._update_inlay_swatch()

    def _sync_inlay_row(self, on: bool):
        self._inlay_color_btn.setEnabled(on)
        self._inlay_opacity.setEnabled(on)

    def _browse_out(self):
        start = self._out_edit.text().strip() or self._library
        d = QFileDialog.getExistingDirectory(self, "Folder for the PDFs", start)
        if d:
            self._out_edit.setText(d)

    def options(self) -> BatchCatalogOptions:
        out = self._out_edit.text().strip() or None
        return BatchCatalogOptions(
            color=self._color,
            opacity=round(self._opacity.value() / 100.0, 4),
            out=out,
            dry_run=self._dry_chk.isChecked(),
            save=self._save_chk.isChecked(),
            temple_ghost_off=self._ghost_chk.isChecked(),
            inlay_color=self._inlay_color if self._inlay_chk.isChecked() else None,
            inlay_opacity=round(self._inlay_opacity.value() / 100.0, 4),
        )

    def remembered(self) -> dict:
        """What the next run starts from (prefs ▸ batch_catalog)."""
        return {"library": self._library,
                "out": self._out_edit.text().strip(),
                "color": self._color,
                "opacity_pct": int(self._opacity.value()),
                "save_fill": self._save_chk.isChecked(),
                "temple_ghost_off": self._ghost_chk.isChecked(),
                "inlay_fill": self._inlay_chk.isChecked(),
                "inlay_color": self._inlay_color,
                "inlay_opacity_pct": int(self._inlay_opacity.value())}


class BatchCatalogProgressDialog(QDialog):
    """A bar, one line per file as it is done, and Cancel — which turns into
    Close when the run ends with the summary appended."""

    def __init__(self, parent, n_files: int):
        super().__init__(parent)
        self.setWindowTitle("Catalog PDFs for a Folder")
        self.setModal(True)
        self.setMinimumWidth(560)
        self._canceled = False
        lay = QVBoxLayout(self)
        self._bar = QProgressBar()
        self._bar.setRange(0, max(n_files, 1))
        self._bar.setValue(0)
        lay.addWidget(self._bar)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(220)
        mono = QFont("Courier New")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._log.setFont(mono)
        lay.addWidget(self._log, 1)
        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self._buttons.rejected.connect(self._on_cancel)
        lay.addWidget(self._buttons)

    def canceled(self) -> bool:
        return self._canceled

    def _on_cancel(self):
        if self._buttons.button(QDialogButtonBox.StandardButton.Close):
            self.accept()
            return
        if not self._canceled:
            self._canceled = True
            self._log.appendPlainText("Stopping after this file…")

    def step(self, i: int, n: int, line: str):
        self._bar.setRange(0, max(n, 1))
        self._bar.setValue(i)
        self._log.appendPlainText(line)

    def finish(self, summary: str):
        self._log.appendPlainText("")
        self._log.appendPlainText(summary)
        self._buttons.clear()
        self._buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self._buttons.button(QDialogButtonBox.StandardButton.Close).setDefault(True)

    def reject(self):
        # Esc and the title bar's close button are Cancel while the run goes
        # on and Close after it: the window never goes with the run behind it.
        self._on_cancel()
