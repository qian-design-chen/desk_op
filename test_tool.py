"""Smoke tests for the embedded unzip_qian tool."""

import os
import tempfile
import zipfile
from pathlib import Path

from PySide6.QtWidgets import QApplication

from tools.unzip_qian import batch_extract
from unzip_tool import open_unzip_gui


def main() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    win = open_unzip_gui()
    app.processEvents()
    assert win.windowTitle() == "批量解压工具"

    src = Path(tempfile.gettempdir()) / "unzip_tool_test"
    src.mkdir(parents=True, exist_ok=True)
    zip_path = src / "sample.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("hello.txt", "hello from unzip tool")
    dest = src / "out"
    assert batch_extract.extract_archive(zip_path, dest)
    assert (dest / "hello.txt").read_text(encoding="utf-8") == "hello from unzip tool"

    win.close()
    app.processEvents()
    print("tool smoke test OK")


if __name__ == "__main__":
    main()
