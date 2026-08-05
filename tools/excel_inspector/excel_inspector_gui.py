"""PySide6 GUI for the Excel batch inspection tool."""

from __future__ import annotations

import csv
import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .excel_inspector import (
    SUPPORTED_FORMATS,
    inspect_files,
    scan_excel_files,
)

MODE_TEXT = "text"
MODE_GT = "gt"
MODE_LT = "lt"
MODE_RANGE = "range"

MODE_LABELS = {
    MODE_TEXT: "文本搜索（模糊）",
    MODE_GT: "大于",
    MODE_LT: "小于",
    MODE_RANGE: "范围内",
}


class ExcelInspectorGUI(QDialog):
    result_signal = Signal(object, object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Excel批量检测工具")
        self.resize(960, 640)
        self.setMinimumSize(760, 520)
        self._running = False
        self._matches = []
        self._files: list[Path] = []

        self.src_edit = QLineEdit(os.getcwd())
        self.recurse_check = QCheckBox("包含子目录")
        self.recurse_check.setChecked(True)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(list(MODE_LABELS.values()))
        self.file_count_label = QLabel("未扫描")
        self.keyword_edit = QLineEdit()
        self.min_edit = QLineEdit()
        self.max_edit = QLineEdit()
        self.status_label = QLabel("就绪")
        self.progress_label = QLabel("")

        self._build_ui()
        self.mode_combo.currentTextChanged.connect(self._update_mode_ui)
        self.result_signal.connect(self._render_results)
        self._update_mode_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(4)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("源文件夹："))
        row1.addWidget(self.src_edit, 1)
        browse_src = QPushButton("浏览…")
        browse_src.clicked.connect(self._browse_src)
        row1.addWidget(browse_src)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        self.recurse_check.toggled.connect(self._refresh_file_count)
        row2.addWidget(self.recurse_check)
        row2.addWidget(QLabel("  检测类型："))
        row2.addWidget(self.mode_combo)
        row2.addWidget(QLabel("Excel 文件："))
        row2.addWidget(self.file_count_label)
        row2.addStretch(1)
        root.addLayout(row2)

        row3 = QHBoxLayout()
        self.keyword_label = QLabel("搜索内容：")
        row3.addWidget(self.keyword_label)
        row3.addWidget(self.keyword_edit)
        row3.addSpacing(12)
        self.min_label = QLabel("大于：")
        row3.addWidget(self.min_label)
        row3.addWidget(self.min_edit)
        row3.addSpacing(12)
        self.max_label = QLabel("小于：")
        row3.addWidget(self.max_label)
        row3.addWidget(self.max_edit)
        inspect_btn = QPushButton("开始检测")
        inspect_btn.clicked.connect(self._inspect)
        row3.addWidget(inspect_btn)
        self.export_btn = QPushButton("导出结果")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._export_csv)
        row3.addWidget(self.export_btn)
        row3.addStretch(1)
        root.addLayout(row3)

        result_group = QGroupBox("检测结果")
        result_layout = QVBoxLayout(result_group)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["文件", "工作表", "单元格", "内容"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        result_layout.addWidget(self.table)
        root.addWidget(result_group, 1)

        row5 = QHBoxLayout()
        row5.addWidget(self.status_label, 1)
        row5.addWidget(self.progress_label)
        root.addLayout(row5)

    def _update_mode_ui(self) -> None:
        mode = self.mode_combo.currentText()
        if mode == MODE_LABELS[MODE_TEXT]:
            self.keyword_label.setText("搜索内容：")
            self.keyword_edit.setEnabled(True)
            self.min_label.setText("大于：")
            self.min_edit.setEnabled(False)
            self.max_label.setText("小于：")
            self.max_edit.setEnabled(False)
        elif mode == MODE_LABELS[MODE_GT]:
            self.keyword_label.setText("搜索内容：")
            self.keyword_edit.setEnabled(False)
            self.min_label.setText("大于：")
            self.min_edit.setEnabled(True)
            self.max_label.setText("小于：")
            self.max_edit.setEnabled(False)
        elif mode == MODE_LABELS[MODE_LT]:
            self.keyword_label.setText("搜索内容：")
            self.keyword_edit.setEnabled(False)
            self.min_label.setText("大于：")
            self.min_edit.setEnabled(False)
            self.max_label.setText("小于：")
            self.max_edit.setEnabled(True)
        else:
            self.keyword_label.setText("搜索内容：")
            self.keyword_edit.setEnabled(False)
            self.min_label.setText("最小：")
            self.min_edit.setEnabled(True)
            self.max_label.setText("最大：")
            self.max_edit.setEnabled(True)
        self._refresh_file_count()

    def _browse_src(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择要检测的文件夹",
            self.src_edit.text(),
        )
        if folder:
            self.src_edit.setText(folder)
            self._refresh_file_count()

    def _refresh_file_count(self) -> None:
        root = Path(self.src_edit.text())
        self._files = scan_excel_files(root, self.recurse_check.isChecked())
        self.file_count_label.setText(f"{len(self._files)} 个")

    @staticmethod
    def _parse_float(text: str) -> float | None:
        value = text.strip()
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def _inspect(self) -> None:
        if self._running:
            return
        self._refresh_file_count()
        if not self._files:
            QMessageBox.information(self, "提示", "未找到 Excel 文件。")
            return

        mode = self.mode_combo.currentText()
        keyword = self.keyword_edit.text().strip()
        if mode == MODE_LABELS[MODE_TEXT] and not keyword:
            QMessageBox.warning(self, "提示", "请输入要搜索的内容。")
            return

        min_value = None
        max_value = None
        if mode in (MODE_LABELS[MODE_GT], MODE_LABELS[MODE_RANGE]):
            min_value = self._parse_float(self.min_edit.text())
            if min_value is None:
                QMessageBox.warning(self, "提示", "请输入有效的数字。")
                return
        if mode in (MODE_LABELS[MODE_LT], MODE_LABELS[MODE_RANGE]):
            max_value = self._parse_float(self.max_edit.text())
            if max_value is None:
                QMessageBox.warning(self, "提示", "请输入有效的数字。")
                return
        if mode == MODE_LABELS[MODE_RANGE] and min_value > max_value:
            QMessageBox.warning(self, "提示", "最小值不能大于最大值。")
            return

        core_mode = {
            MODE_LABELS[MODE_TEXT]: MODE_TEXT,
            MODE_LABELS[MODE_GT]: MODE_GT,
            MODE_LABELS[MODE_LT]: MODE_LT,
            MODE_LABELS[MODE_RANGE]: MODE_RANGE,
        }[mode]

        self._running = True
        self.table.setRowCount(0)
        self.status_label.setText("正在检测…")
        self.progress_label.setText("")
        self.export_btn.setEnabled(False)
        files = list(self._files)

        def worker() -> None:
            matches, errors, per_file = inspect_files(
                files,
                core_mode,
                keyword=keyword,
                min_value=min_value,
                max_value=max_value,
            )
            self.result_signal.emit(matches, errors, per_file)

        threading.Thread(target=worker, daemon=True).start()

    def _render_results(self, matches, errors, per_file) -> None:
        self._matches = matches
        self.table.setRowCount(0)
        self.table.setRowCount(len(matches))
        for row, match in enumerate(matches):
            self.table.setItem(row, 0, QTableWidgetItem(match.file))
            self.table.setItem(row, 1, QTableWidgetItem(match.sheet))
            self.table.setItem(row, 2, QTableWidgetItem(match.cell))
            self.table.setItem(row, 3, QTableWidgetItem(str(match.value)))
        file_count = len(per_file)
        error_count = len(errors)
        self.status_label.setText(
            f"匹配：{len(matches)} 个│涉及文件：{file_count} 个│读取失败：{error_count} 个"
        )
        self.progress_label.setText("完成")
        self.export_btn.setEnabled(bool(matches))
        self._running = False
        if errors:
            QMessageBox.warning(
                self,
                "部分文件读取失败",
                f"有 {error_count} 个文件读取失败，请检查文件是否损坏或加密。",
            )

    def _export_csv(self) -> None:
        if not self._matches:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出检测结果",
            "excel_detection_result.csv",
            "CSV 文件 (*.csv)",
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh)
                writer.writerow(["文件", "工作表", "单元格", "内容"])
                for match in self._matches:
                    writer.writerow([match.file, match.sheet, match.cell, match.value])
        except OSError as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        QMessageBox.information(self, "导出成功", f"结果已保存到：\n{path}")

    def run(self) -> None:
        self._refresh_file_count()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = ExcelInspectorGUI()
    gui.show()
    sys.exit(app.exec())
