"""Tests for per-day progress history on each todo."""

import logging
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from app_logger import APP_LOGGER_NAME, setup_logging
from desktop_assistant import DesktopAssistantApp, TodoDialog
from todo_store import TIME_FORMAT, TodoStore


def main() -> None:
    path = Path(tempfile.gettempdir()) / "desktop_assistant_daily_test.json"
    log_dir = Path(tempfile.gettempdir()) / "desktop_assistant_daily_log"
    if path.exists():
        path.unlink()
    setup_logging(log_dir)
    logging.getLogger(APP_LOGGER_NAME).info("daily progress test start")

    store = TodoStore(path)
    todo = store.add_todo(
        "每日进展测试",
        (datetime.now() + timedelta(days=1)).strftime(TIME_FORMAT),
    )
    store.add_daily_progress(todo.id, "第一天完成一部分", date="2026-08-01")
    store.add_daily_progress(todo.id, "第二天完成更多", date="2026-08-02")
    store.update_progress(todo.id, "今天完成一半")

    reloaded = TodoStore(path)
    item = reloaded.todos[0]
    assert item.progress_history["2026-08-01"] == "第一天完成一部分"
    assert item.progress_history["2026-08-02"] == "第二天完成更多"
    today = datetime.now().strftime("%Y-%m-%d")
    assert item.progress_history[today] == "今天完成一半"
    assert item.progress == "今天完成一半"

    log_text = (log_dir / "desktop_assistant.log").read_text(encoding="utf-8")
    assert "每日进展" in log_text
    assert "更新进展" in log_text

    app = QApplication.instance() or QApplication([])
    dlg = TodoDialog(None, store, item)
    assert "2026-08-02" in dlg.daily_history_edit.toPlainText()
    assert dlg.daily_progress_edit is not None
    dlg.reject()

    win = DesktopAssistantApp(store=store)
    assert win.daily_btn.text() == "今日进展"
    win.current_todo_id = item.id
    win._show_reminder(item)
    app.processEvents()
    win._save_progress(item.id, "弹窗更新")
    assert store.get(item.id).progress_history[today] == "弹窗更新"
    win.close()
    app.processEvents()

    if path.exists():
        path.unlink()
    print("daily progress test OK")


if __name__ == "__main__":
    main()
