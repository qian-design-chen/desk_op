"""Data layer for the desktop assistant.

Todos and settings live in a plain JSON file next to the app, so the program
never touches the Windows registry and stays portable.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

APP_NAME = "桌面办公助手"
DATA_DIR_NAME = "data"
DATA_FILE_NAME = "todos.json"

PRIORITY_HIGH = "高"
PRIORITY_MEDIUM = "中"
PRIORITY_LOW = "低"
PRIORITIES = (PRIORITY_HIGH, PRIORITY_MEDIUM, PRIORITY_LOW)

LEAD_CHOICES = (0, 5, 10, 15, 30, 60, 120, 1440)
SNOOZE_CHOICES = (5, 10, 15, 30)
REMINDER_MODES = ("none", "hourly", "daily")

DEFAULT_SETTINGS = {
    "check_interval_seconds": 30,
    "default_lead_minutes": 5,
    "sound_enabled": True,
    "voice_enabled": True,
    "voice_name": "",
    "daily_reminder_enabled": True,
    "daily_reminder_time": "20:00",
    "last_daily_reminder_date": "",
}

TIME_FORMAT = "%Y-%m-%d %H:%M"

logger = logging.getLogger("desktop_assistant")


def now_str() -> str:
    return datetime.now().strftime(TIME_FORMAT)


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in (TIME_FORMAT, "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


@dataclass
class Todo:
    id: str = ""
    title: str = ""
    due: str = ""
    priority: str = PRIORITY_MEDIUM
    tag: str = ""
    notes: str = ""
    lead_minutes: int = 0
    voice_enabled: bool = True
    completed: bool = False
    created_at: str = ""
    completed_at: str = ""
    last_notified_due: str = ""
    snoozed_until: str = ""
    reminder_mode: str = "none"
    reminder_interval: int = 0
    progress: str = ""
    progress_history: dict[str, str] = field(default_factory=dict)
    last_reminder_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = now_str()

    def due_dt(self) -> datetime | None:
        return parse_dt(self.due)

    def remind_at(self) -> datetime | None:
        due = self.due_dt()
        if due is None:
            return None
        return due - timedelta(minutes=max(0, int(self.lead_minutes or 0)))

    def reminder_pending(self, now: datetime | None = None) -> bool:
        if self.completed:
            return False
        now = now or datetime.now()
        if self.snoozed_until:
            snooze_until = parse_dt(self.snoozed_until)
            if snooze_until and now < snooze_until:
                return False
        target = self.remind_at()
        if target is None:
            return False
        if self.reminder_mode in ("hourly", "daily"):
            last = parse_dt(self.last_reminder_at)
            if last is not None:
                interval = max(1, int(self.reminder_interval or 1))
                if self.reminder_mode == "hourly":
                    return now >= last + timedelta(hours=interval)
                return now >= last + timedelta(days=interval)
            return now >= target
        return self.last_notified_due != self.due and now >= target

    def next_reminder_at(self, now: datetime | None = None) -> datetime | None:
        if self.completed:
            return None
        now = now or datetime.now()
        target = self.remind_at()
        if target is None:
            return None
        if self.reminder_mode in ("hourly", "daily"):
            last = parse_dt(self.last_reminder_at)
            if last is not None:
                interval = max(1, int(self.reminder_interval or 1))
                if self.reminder_mode == "hourly":
                    return last + timedelta(hours=interval)
                return last + timedelta(days=interval)
            return target
        if self.last_notified_due == self.due:
            return None
        return target

    def is_overdue(self, now: datetime | None = None) -> bool:
        due = self.due_dt()
        return not self.completed and due is not None and due < (now or datetime.now())

    def mark_notified(self, now: datetime | None = None) -> None:
        self.last_notified_due = self.due
        self.last_reminder_at = (now or datetime.now()).strftime(TIME_FORMAT)
        self.updated_at = now_str()
        self.snoozed_until = ""

    def snooze(self, minutes: int) -> None:
        self.snoozed_until = (datetime.now() + timedelta(minutes=minutes)).strftime(TIME_FORMAT)
        self.last_notified_due = ""
        self.updated_at = now_str()


def format_remaining(due: datetime, now: datetime | None = None) -> str:
    now = now or datetime.now()
    delta = due - now
    if delta.total_seconds() < 0:
        overdue = -delta
        days = overdue.days
        hours = overdue.seconds // 3600
        minutes = (overdue.seconds % 3600) // 60
        if days > 0:
            return f"已过期 {days}天{hours}小时"
        if hours > 0:
            return f"已过期 {hours}小时{minutes}分"
        return f"已过期 {minutes}分钟"
    days = delta.days
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60
    if days > 0:
        return f"剩余 {days}天{hours}小时"
    if hours > 0:
        return f"剩余 {hours}小时{minutes}分"
    if minutes > 0:
        return f"剩余 {minutes}分钟"
    return "即将到期"


def voice_reminder_text(todo: Todo, now: datetime | None = None) -> str:
    due = todo.due_dt()
    if due is None:
        return ""
    now = now or datetime.now()
    delta = due - now
    title = todo.title
    if delta.total_seconds() <= 0:
        return f"请注意，事项「{title}」已经到期，请尽快处理。"
    parts = []
    if delta.days > 0:
        parts.append(f"{delta.days}天")
    hours = delta.seconds // 3600
    if hours > 0:
        parts.append(f"{hours}小时")
    minutes = (delta.seconds % 3600) // 60
    if minutes > 0:
        parts.append(f"{minutes}分钟")
    if not parts:
        return f"请注意，事项「{title}」即将到期。"
    return f"请注意，事项「{title}」还有{''.join(parts)}到期。"


def _writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def data_file_path() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent / DATA_DIR_NAME
    else:
        base = Path(__file__).resolve().parent / DATA_DIR_NAME
    if _writable_dir(base):
        return base / DATA_FILE_NAME
    fallback = Path.home() / "Documents" / (APP_NAME + "数据") / DATA_DIR_NAME
    if _writable_dir(fallback):
        return fallback / DATA_FILE_NAME
    return base / DATA_FILE_NAME


class TodoStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self._lock = threading.RLock()
        self.path = Path(path) if path else data_file_path()
        self.settings = dict(DEFAULT_SETTINGS)
        self.todos: list[Todo] = []
        self.load()

    def load(self) -> None:
        data = {"version": 1, "todos": [], "settings": {}}
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = raw
            except (OSError, ValueError):
                self._backup_corrupted_file()
        self.settings = {**DEFAULT_SETTINGS, **(data.get("settings") or {})}
        self.todos = []
        for item in data.get("todos") or []:
            if not isinstance(item, dict):
                continue
            try:
                todo = Todo(**item)
            except TypeError:
                continue
            if not todo.title or not parse_dt(todo.due):
                continue
            self.todos.append(todo)
        self.sort_todos()
        logger.info("加载数据：%d 条事项，数据文件 %s", len(self.todos), self.path)

    def sort_todos(self) -> None:
        self.todos.sort(key=lambda t: (t.completed, t.due_dt() or datetime.max))

    def save(self) -> None:
        payload = {
            "version": 1,
            "todos": [asdict(t) for t in self.todos],
            "settings": self.settings,
        }
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)

    def _backup_corrupted_file(self) -> None:
        try:
            backup = self.path.with_name(self.path.stem + ".corrupt.bak")
            os.replace(self.path, backup)
            logger.warning("数据文件损坏，已备份为 %s", backup)
        except OSError:
            pass

    def add_todo(
        self,
        title: str,
        due: str,
        priority: str = PRIORITY_MEDIUM,
        tag: str = "",
        notes: str = "",
        lead_minutes: int = 0,
        voice_enabled: bool = True,
        reminder_mode: str = "none",
        reminder_interval: int = 0,
        progress: str = "",
    ) -> Todo:
        todo = Todo(
            title=title.strip(),
            due=due,
            priority=priority,
            tag=tag.strip(),
            notes=notes.strip(),
            lead_minutes=int(lead_minutes or 0),
            voice_enabled=voice_enabled,
            reminder_mode=reminder_mode if reminder_mode in REMINDER_MODES else "none",
            reminder_interval=max(0, int(reminder_interval or 0)),
            progress=progress.strip(),
            updated_at=now_str(),
        )
        with self._lock:
            self.todos.append(todo)
            self.save()
        logger.info("添加事项：%s（截止 %s）", todo.title, todo.due)
        return todo

    def get(self, todo_id: str) -> Todo | None:
        with self._lock:
            for todo in self.todos:
                if todo.id == todo_id:
                    return todo
        return None

    def update_todo(self, todo_id: str, **changes) -> Todo | None:
        with self._lock:
            todo = self.get(todo_id)
            if todo is None:
                return None
            changed_fields = [key for key in changes if hasattr(todo, key)]
            for key, value in changes.items():
                if hasattr(todo, key):
                    setattr(todo, key, value)
            todo.updated_at = now_str()
            self.sort_todos()
            self.save()
            logger.info("编辑事项：%s（修改字段：%s）", todo.title, "、".join(changed_fields))
            return todo

    @staticmethod
    def _apply_progress(todo: Todo, text: str, day: str) -> None:
        history = dict(todo.progress_history or {})
        history[day] = text
        todo.progress_history = history
        todo.progress = text
        todo.updated_at = now_str()

    def add_daily_progress(self, todo_id: str, text: str, date: str | None = None) -> Todo | None:
        text = (text or "").strip()
        if not text:
            return self.get(todo_id)
        day = date or datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            todo = self.get(todo_id)
            if todo is None:
                return None
            self._apply_progress(todo, text, day)
            self.save()
            logger.info("每日进展：%s %s - %s", day, todo.title, text)
            return todo

    def update_progress(self, todo_id: str, progress: str) -> Todo | None:
        text = (progress or "").strip()
        if not text:
            return self.get(todo_id)
        day = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            todo = self.get(todo_id)
            if todo is None:
                return None
            self._apply_progress(todo, text, day)
            self.save()
            logger.info("更新进展：%s - %s", todo.title, text)
            return todo

    def delete_todo(self, todo_id: str) -> bool:
        with self._lock:
            before = len(self.todos)
            removed = next((t for t in self.todos if t.id == todo_id), None)
            self.todos = [t for t in self.todos if t.id != todo_id]
            if len(self.todos) != before:
                self.save()
                logger.info("删除事项：%s", removed.title if removed else todo_id)
                return True
        return False

    def set_completed(self, todo_id: str, completed: bool) -> Todo | None:
        todo = self.get(todo_id)
        if todo is None:
            return None
        updated = self.update_todo(
            todo_id,
            completed=completed,
            completed_at=now_str() if completed else "",
            last_notified_due=todo.due if completed else todo.last_notified_due,
        )
        logger.info("%s：%s", "标记完成" if completed else "取消完成", todo.title)
        return updated

    def save_settings(self, settings: dict) -> None:
        self.settings = {**self.settings, **settings, "updated_at": now_str()}
        self.save()
        logger.info("修改设置：%s", settings)

    def delete_completed(self) -> int:
        with self._lock:
            before = len(self.todos)
            self.todos = [t for t in self.todos if not t.completed]
            removed = before - len(self.todos)
            if removed:
                self.save()
                logger.info("清理已完成事项：%d 条", removed)
            return removed


def default_due_str(hours_ahead: int = 1) -> str:
    return (datetime.now() + timedelta(hours=hours_ahead)).strftime(TIME_FORMAT)
