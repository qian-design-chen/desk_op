"""Launcher for the embedded unzip_qian batch extraction tool."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QWidget

from tools.unzip_qian import batch_extract_gui


def open_unzip_gui(parent: QWidget | None = None) -> QDialog:
    win = batch_extract_gui.BatchExtractGUI(parent)
    win.setWindowTitle("批量解压工具")
    win.run()
    win.show()
    return win
