"""Tests for hourly/daily reminder modes, progress updates, and logging."""

import logging
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QPlainTextEdit

from app_logger import APP_LOGGER_NAME, setup_logging
from desktop_assistant import REMINDER_MODE_LABELS, DesktopAssistantApp, TodoDialog
from todo_store import TIME_FORMAT, Todo, TodoStore


def main() -> None:
    now = datetime(2026, 8, 3, 10, 0)
    hourly = Todo(
        title="小时提醒",
        due=(now + timedelta(hours=1)).strftime(TIME_FORMAT),
        reminder_mode="hourly",
        reminder_interval=2,
        lead_minutes=0,
    )
    assert not hourly.reminder_pending(now)
    fire = now + timedelta(hours=1)
    assert hourly.reminder_pending(fire)
    hourly.mark_notified(fire)
    assert not hourly.reminder_pending(fire)
    assert not hourly.reminder_pending(fire + timedelta(hours=1))
    assert hourly.reminder_pending(fire + timedelta(hours=2))
    assert hourly.next_reminder_at(fire) == fire + timedelta(hours=2)

    daily = Todo(
        title="每天提醒",
        due=(now + timedelta(hours=1)).strftime(TIME_FORMAT),
        reminder_mode="daily",
        reminder_interval=1,
        lead_minutes=0,
    )
    daily.mark_notified(now + timedelta(hours=1))
    assert daily.next_reminder_at(now + timedelta(hours=1)) == now + timedelta(days=1, hours=1)
    assert not daily.reminder_pending(now + timedelta(hours=23))
    assert daily.reminder_pending(now + timedelta(days=1, hours=1))

    path = Path(tempfile.gettempdir()) / "desktop_assistant_reminder_test.json"
    if path.exists():
        path.unlink()
    log_dir = Path(tempfile.gettempdir()) / "desktop_assistant_reminder_log"
    setup_logging(log_dir)
    logging.getLogger(APP_LOGGER_NAME).info("reminder test start")

    store = TodoStore(path)
    todo = store.add_todo(
        "进展测试",
        (datetime.now() + timedelta(hours=2)).strftime(TIME_FORMAT),
        reminder_mode="hourly",
        reminder_interval=1,
        progress="初始进展",
    )
    store.update_progress(todo.id, "完成一半")
    reloaded = TodoStore(path)
    assert reloaded.todos[0].reminder_mode == "hourly"
    assert reloaded.todos[0].reminder_interval == 1
    assert reloaded.todos[0].progress == "完成一半"

    log_text = (log_dir / "desktop_assistant.log").read_text(encoding="utf-8")
    assert "更新进展" in log_text
    assert "完成一半" in log_text

    app = QApplication.instance() or QApplication([])
    dlg = TodoDialog(None, store, reloaded.todos[0])
    assert dlg.reminder_combo.currentText() == REMINDER_MODE_LABELS["hourly"]
    assert dlg.progress_edit.toPlainText() == "完成一半"
    dlg.reject()

    win = DesktopAssistantApp(store=store)
    win.refresh()
    win._show_reminder(reloaded.todos[0])
    app.processEvents()
    assert win.findChild(QPlainTextEdit, "reminderProgressEdit") is not None
    win._save_progress(reloaded.todos[0].id, "全部完成")
    assert store.get(reloaded.todos[0].id).progress == "全部完成"
    assert reloaded.todos[0].id not in win.popups
    win.close()
    app.processEvents()

    if path.exists():
        path.unlink()
    print("reminder/progress/log test OK")


if __name__ == "__main__":
    main()
