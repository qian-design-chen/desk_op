#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PySide6 GUI for batch extraction with size filtering."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .batch_extract import (
    ensure_output_dir,
    extract_archive,
    resolve_ext,
    supports_format,
)


def format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def parse_size_mb(text: str) -> float | None:
    """Parse a size in MB; an empty string returns None."""
    s = text.strip()
    if not s:
        return None
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


class BatchExtractGUI(QDialog):
    row_signal = Signal(str, str)
    log_signal = Signal(str)
    progress_signal = Signal(float, str)
    finish_signal = Signal(int, int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("批量解压工具")
        self.resize(820, 620)
        self.setMinimumSize(640, 500)
        self._running = False
        self._archives: list[Path] = []
        self._build_ui()
        self.row_signal.connect(self._update_row)
        self.log_signal.connect(self._log)
        self.progress_signal.connect(self._set_progress)
        self.finish_signal.connect(self._finish)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(4)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("源文件夹："))
        self.src_edit = QLineEdit(os.getcwd())
        row1.addWidget(self.src_edit, 1)
        browse_src = QPushButton("浏览…")
        browse_src.clicked.connect(self._browse_src)
        row1.addWidget(browse_src)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        self.recurse_check = QCheckBox("递归子目录")
        self.recurse_check.setChecked(True)
        row2.addWidget(self.recurse_check)
        row2.addWidget(QLabel("  输出到："))
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("留空则解压到原目录")
        row2.addWidget(self.out_edit, 1)
        browse_out = QPushButton("浏览…")
        browse_out.clicked.connect(self._browse_out)
        row2.addWidget(browse_out)
        root.addLayout(row2)

        filter_group = QGroupBox("大小过滤")
        filter_row = QHBoxLayout(filter_group)
        filter_row.addWidget(QLabel("跳过小于"))
        self.min_edit = QLineEdit()
        self.min_edit.setFixedWidth(70)
        self.min_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        filter_row.addWidget(self.min_edit)
        filter_row.addWidget(QLabel("MB"))
        filter_row.addWidget(QLabel("    跳过大于"))
        self.max_edit = QLineEdit()
        self.max_edit.setFixedWidth(70)
        self.max_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        filter_row.addWidget(self.max_edit)
        filter_row.addWidget(QLabel("MB"))
        filter_row.addSpacing(14)
        filter_row.addWidget(QLabel("总大小："))
        self.total_label = QLabel("—")
        self.total_label.setStyleSheet("font-weight: bold;")
        filter_row.addWidget(self.total_label)
        filter_row.addSpacing(10)
        filter_row.addWidget(QLabel("   匹配："))
        self.file_count_label = QLabel("未扫描")
        filter_row.addWidget(self.file_count_label)
        filter_row.addStretch(1)
        root.addWidget(filter_group)

        row4 = QHBoxLayout()
        scan_btn = QPushButton("扫描压缩包")
        scan_btn.clicked.connect(self._scan)
        row4.addWidget(scan_btn)
        self.extract_btn = QPushButton("开始解压")
        self.extract_btn.setEnabled(False)
        self.extract_btn.clicked.connect(self._extract)
        row4.addWidget(self.extract_btn)
        row4.addStretch(1)
        root.addLayout(row4)

        row5 = QHBoxLayout()
        list_group = QGroupBox("发现的压缩包")
        list_layout = QVBoxLayout(list_group)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["文件名", "大小", "状态"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        list_layout.addWidget(self.table)
        row5.addWidget(list_group, 1)

        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("font-family: Consolas; font-size: 9pt;")
        log_layout.addWidget(self.log_text)
        row5.addWidget(log_group, 1)
        root.addLayout(row5, 1)

        row6 = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress_label = QLabel("")
        row6.addWidget(self.progress, 1)
        row6.addWidget(self.progress_label)
        root.addLayout(row6)

    def _browse_src(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self,
            "选择要扫描的文件夹",
            self.src_edit.text(),
        )
        if d:
            self.src_edit.setText(d)
            self._scan()

    def _browse_out(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self,
            "选择解压输出根目录（留空则解压到原目录）",
            self.out_edit.text() or self.src_edit.text(),
        )
        if d:
            self.out_edit.setText(d)

    def _scan(self) -> None:
        self.table.setRowCount(0)
        self._clear_log()
        self.extract_btn.setEnabled(False)
        self.progress.setValue(0)
        self.progress_label.setText("")
        self.total_label.setText("—")

        src = Path(self.src_edit.text())
        if not src.is_dir():
            QMessageBox.critical(self, "错误", f"文件夹不存在：{src}")
            return

        min_mb = parse_size_mb(self.min_edit.text())
        max_mb = parse_size_mb(self.max_edit.text())

        if self.recurse_check.isChecked():
            candidates = [p for p in src.rglob("*") if p.is_file()]
        else:
            candidates = [p for p in src.iterdir() if p.is_file()]

        all_found = []
        for p in candidates:
            ext = resolve_ext(p)
            if supports_format(ext):
                all_found.append(p)
        all_found.sort(key=lambda p: p.stat().st_size)
        total_all = sum(p.stat().st_size for p in all_found)

        archives = []
        filtered_out = 0
        for p in all_found:
            size_mb = p.stat().st_size / (1024 * 1024)
            if min_mb is not None and size_mb < min_mb:
                filtered_out += 1
                continue
            if max_mb is not None and size_mb > max_mb:
                filtered_out += 1
                continue
            archives.append(p)

        self._archives = archives
        self._log(f"扫描目录：{src}")
        self._log(f"  找到压缩包：共 {len(all_found)} 个（总大小 {format_size(total_all)}）")
        if filtered_out > 0:
            self._log(f"  因大小过滤跳过：{filtered_out} 个")

        if not archives:
            self.file_count_label.setText("无匹配")
            self.total_label.setText("—")
            if all_found:
                self._log("  所有压缩包均被过滤条件排除。")
            else:
                self._log("  未发现支持的压缩包。")
            return

        total_bytes = sum(p.stat().st_size for p in archives)
        self.total_label.setText(format_size(total_bytes))
        self.table.setRowCount(len(archives))
        for row, arch in enumerate(archives):
            size = format_size(arch.stat().st_size)
            name_item = QTableWidgetItem(arch.name)
            name_item.setData(Qt.ItemDataRole.UserRole, str(arch))
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(size))
            self.table.setItem(row, 2, QTableWidgetItem("等待"))

        self.file_count_label.setText(f"{len(archives)} 个")
        self._log(f"  符合条件：{len(archives)} 个，共 {self.total_label.text()}")
        if min_mb is not None or max_mb is not None:
            parts = []
            if min_mb is not None:
                parts.append(f"≥{min_mb} MB")
            if max_mb is not None:
                parts.append(f"≤{max_mb} MB")
            self._log(f"  过滤条件：{' 和 '.join(parts)}")
        self.extract_btn.setEnabled(True)

    def _extract(self) -> None:
        if self._running:
            return
        self._running = True
        self.extract_btn.setEnabled(False)
        self.progress.setValue(0)
        self._clear_log()

        archives = self._archives
        if not archives:
            self._running = False
            return

        total = len(archives)
        src_root = Path(self.src_edit.text())
        out_root = Path(self.out_edit.text()) if self.out_edit.text().strip() else None

        def worker() -> None:
            ok = fail = skip = 0
            for idx, arch in enumerate(archives, start=1):
                if not self._running:
                    break
                rel = arch.relative_to(src_root)
                self.row_signal.emit(str(arch), "解压中…")
                self.log_signal.emit(f"[{idx}/{total}] {rel}  ({format_size(arch.stat().st_size)})")

                if out_root:
                    if arch.parent != src_root:
                        dest_base = out_root / arch.parent.relative_to(src_root)
                    else:
                        dest_base = out_root
                else:
                    dest_base = arch.parent

                dest = ensure_output_dir(dest_base, arch)
                self.log_signal.emit(f"    -> {dest}")
                result = extract_archive(arch, dest)
                if result:
                    ok += 1
                    self.row_signal.emit(str(arch), "✓ 成功")
                else:
                    ext = resolve_ext(arch)
                    if ext and ext[0] in ("rar", "7z"):
                        self.row_signal.emit(str(arch), "跳过")
                        self.log_signal.emit(
                            f"    [!] {ext[0]} 格式需额外安装：pip install patool py7zr rarfile"
                        )
                        skip += 1
                    else:
                        self.row_signal.emit(str(arch), "✗ 失败")
                        fail += 1
                self.progress_signal.emit(idx / total * 100, f"{idx}/{total}")
            self.finish_signal.emit(ok, fail, skip)

        threading.Thread(target=worker, daemon=True).start()

    def _update_row(self, iid: str, status: str) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == iid:
                self.table.setItem(row, 2, QTableWidgetItem(status))
                return

    def _set_progress(self, value: float, label: str) -> None:
        self.progress.setValue(int(value))
        self.progress_label.setText(label)

    def _log(self, msg: str) -> None:
        self.log_text.appendPlainText(msg)

    def _clear_log(self) -> None:
        self.log_text.clear()

    def _finish(self, ok: int, fail: int, skip: int) -> None:
        self._running = False
        self.extract_btn.setEnabled(True)
        self.progress.setValue(100)
        done = ok + fail + skip
        self.progress_label.setText(f"{done}/{done}")
        sep = "─" * 48
        self._log("")
        self._log(sep)
        self._log(f"完成！成功：{ok}，失败：{fail}，跳过：{skip}")

    def run(self) -> None:
        self._scan()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = BatchExtractGUI()
    gui.show()
    sys.exit(app.exec())
