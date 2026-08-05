"""Small smoke tests for the data layer (run with a real UTF-8 file)."""

import logging
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from app_logger import APP_LOGGER_NAME, setup_logging
from desktop_assistant import _daily_reminder_time, _daily_reminder_voice_text
from todo_store import TIME_FORMAT, Todo, TodoStore, format_remaining, voice_reminder_text
from voice import speak_script


def main() -> None:
    path = Path(tempfile.gettempdir()) / "desktop_assistant_smoke.json"
    if path.exists():
        path.unlink()

    store = TodoStore(path)
    assert store.settings.get("daily_reminder_enabled") is True
    assert store.settings.get("daily_reminder_time") == "20:00"
    todo = store.add_todo(
        "测试事项",
        (datetime.now() + timedelta(hours=1)).strftime(TIME_FORMAT),
        priority="高",
        tag="工作",
        notes="备注",
        lead_minutes=5,
    )
    assert len(store.todos) == 1
    assert store.get(todo.id) is not None
    assert not todo.reminder_pending()

    reloaded = TodoStore(path)
    assert reloaded.todos[0].title == "测试事项"
    assert reloaded.todos[0].priority == "高"
    assert reloaded.todos[0].voice_enabled is True

    store.set_completed(todo.id, True)
    assert store.todos[0].completed
    assert store.delete_completed() == 1

    overdue = store.add_todo(
        "过期事项",
        (datetime.now() - timedelta(minutes=1)).strftime(TIME_FORMAT),
        lead_minutes=0,
    )
    assert overdue.reminder_pending()
    overdue.mark_notified()
    assert not overdue.reminder_pending()

    store.update_todo(overdue.id, voice_enabled=False)
    reloaded2 = TodoStore(path)
    assert reloaded2.todos[0].voice_enabled is False

    now = datetime(2026, 8, 1, 12, 0)
    voice_todo = Todo(title="会议", due=(now + timedelta(hours=1, minutes=30)).strftime(TIME_FORMAT))
    assert voice_reminder_text(voice_todo, now) == "请注意，事项「会议」还有1小时30分钟到期。"
    expired = Todo(title="会议", due=(now - timedelta(minutes=1)).strftime(TIME_FORMAT))
    assert "已经到期" in voice_reminder_text(expired, now)
    soon = Todo(title="会议", due=(now + timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S"))
    assert "即将到期" in voice_reminder_text(soon, now)

    assert _daily_reminder_time({"daily_reminder_time": "08:30"}) == (8, 30)
    assert _daily_reminder_time({"daily_reminder_time": "bad"}) == (20, 0)
    daily_text = _daily_reminder_voice_text(
        [
            Todo(title="任务A", due=(now + timedelta(hours=1)).strftime(TIME_FORMAT)),
            Todo(title="任务B", due=(now + timedelta(hours=2)).strftime(TIME_FORMAT)),
        ],
        now,
    )
    assert "2项工作未完成" in daily_text
    assert "任务A" in daily_text
    assert "任务B" in daily_text

    log_dir = Path(tempfile.gettempdir()) / "desktop_assistant_log_test"
    setup_logging(log_dir)
    logging.getLogger(APP_LOGGER_NAME).info("smoke log message")
    assert (log_dir / "desktop_assistant.log").exists()
    logging.shutdown()

    script = speak_script("测试", voice_name="Microsoft Huihui")
    assert "Microsoft Huihui" in script
    assert "804" in script

    future = datetime.now() + timedelta(hours=1)
    past = datetime.now() - timedelta(minutes=1)
    assert "剩余" in format_remaining(future)
    assert "已过期" in format_remaining(past)

    path.unlink()
    print("data layer smoke tests OK")


if __name__ == "__main__":
    main()
