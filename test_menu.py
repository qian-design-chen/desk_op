"""Verify the assistant top menu includes the integrated tool entry."""

import os
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication

from desktop_assistant import DesktopAssistantApp
from todo_store import TodoStore


def main() -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    path = Path(tempfile.gettempdir()) / "menu_check.json"
    if path.exists():
        path.unlink()
    store = TodoStore(path)
    window = DesktopAssistantApp(store=store)

    menubar = window.menuBar()
    top_actions = menubar.actions()
    labels = [action.text() for action in top_actions]
    assert labels == ["文件", "工具", "设置", "帮助"], labels
    assert window.sync_btn.text() == "同步"
    assert window.sync_status_label.text() == "未同步"

    tools_action = top_actions[1]
    tools_menu = tools_action.menu()
    tool_labels = [action.text() for action in tools_menu.actions() if not action.isSeparator()]
    assert "批量解压工具" in tool_labels, tool_labels

    window.close()
    app.processEvents()
    if path.exists():
        path.unlink()
    print("menu integration test OK")


if __name__ == "__main__":
    main()
