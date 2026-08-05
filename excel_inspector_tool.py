"""Launcher for the embedded Excel batch inspection tool."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QWidget

from tools.excel_inspector import excel_inspector_gui


def open_excel_inspector_gui(parent: QWidget | None = None) -> QDialog:
    win = excel_inspector_gui.ExcelInspectorGUI(parent)
    win.setWindowTitle("Excel批量检测工具")
    win.run()
    win.show()
    return win
