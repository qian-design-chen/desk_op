"""PySide6 desktop assistant: todos with due-date reminders."""

from __future__ import annotations

import argparse
import calendar
import logging
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_logger import APP_LOGGER_NAME, log_file_path, setup_logging
from excel_inspector_tool import open_excel_inspector_gui
from sync_service import SyncResult, load_sync_config, sync_all
from unzip_tool import open_unzip_gui
from speech_recognition import SpeechRecognitionController, recognize_wav_file
from voice import AUTO_VOICE_LABEL, VoiceInfo, list_voices, speak_text_async
from todo_store import (
    APP_NAME,
    LEAD_CHOICES,
    PRIORITIES,
    PRIORITY_HIGH,
    TIME_FORMAT,
    Todo,
    TodoStore,
    default_due_str,
    format_remaining,
    parse_dt,
    voice_reminder_text,
)

FONT_FAMILY = "Microsoft YaHei UI"

BG = "#f3f5f8"
PANEL_BG = "#ffffff"
HEADER_BG = "#143d3a"
ACCENT = "#0f766e"
ACCENT_DARK = "#115e59"
TEXT = "#1f2937"
MUTED = "#6b7280"
BORDER = "#d5dbe1"
STATUS_BG = "#e8edf2"

TAG_COLORS = {
    "done": "#8a929b",
    "overdue": "#c62828",
    "high": "#d84315",
    "soon": "#b26a00",
    "snoozed": "#7b1fa2",
    "normal": TEXT,
}

REMINDER_MODE_LABELS = {
    "none": "不重复",
    "hourly": "按小时提醒",
    "daily": "按天提醒",
}

logger = logging.getLogger(APP_LOGGER_NAME)


def _lead_text(minutes: int) -> str:
    return "到期时提醒" if minutes == 0 else f"提前 {minutes} 分钟"


def _daily_reminder_time(settings: dict) -> tuple[int, int]:
    value = settings.get("daily_reminder_time", "20:00")
    try:
        hour_str, minute_str = str(value).split(":", 1)
        hour = int(hour_str)
        minute = int(minute_str)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    except (TypeError, ValueError):
        pass
    return 20, 0


def _daily_reminder_voice_text(todos: list[Todo], now: datetime | None = None) -> str:
    count = len(todos)
    text = f"请注意，现在还有{count}项工作未完成。"
    for todo in todos[:5]:
        text += voice_reminder_text(todo, now)
    if count > 5:
        text += f"其余{count - 5}项请打开桌面办公助手查看。"
    return text


def _apply_base_style(widget) -> None:
    qss = """
    QWidget { font-family: "Microsoft YaHei UI"; font-size: 10pt; }
    QLabel { color: #1f2937; }
    QMainWindow, QDialog { background: #f3f5f8; }
    QFrame#header { background: #143d3a; border: none; }
    QLabel#titleLabel { color: white; font-size: 16pt; font-weight: bold; }
    QLabel#clockLabel { color: #d7ece9; font-size: 11pt; }
    QFrame#statCard { background: white; border: 1px solid #d5dbe1; border-radius: 8px; }
    QLabel#statValue { color: #1f2937; font-size: 18pt; font-weight: bold; }
    QLabel#statCaption { color: #6b7280; font-size: 9pt; }
    QPushButton#accentButton { background: #0f766e; color: white; border: none;
                               border-radius: 6px; padding: 8px 14px; font-weight: bold; }
    QPushButton#accentButton:hover { background: #115e59; }
    QPushButton#accentButton:disabled { background: #9ca3af; color: #e5e7eb; }
    QPushButton#toolButton { background: white; color: #1f2937;
                             border: 1px solid #d5dbe1; border-radius: 6px; padding: 6px 12px; }
    QPushButton#toolButton:hover { background: #e4efed; border-color: #0f766e; }
    QPushButton#toolButton:disabled { color: #aab2ba; background: #f1f3f5; }
    QFrame#panel { background: white; border: 1px solid #d5dbe1; border-radius: 8px; }
    QLabel#detailLabel { color: #1f2937; }
    QTableWidget { background: white; color: #1f2937; border: none;
                   gridline-color: #d5dbe1; alternate-background-color: #f7f9fb;
                   selection-background-color: #0f766e; selection-color: white; }
    QHeaderView::section { background: #e9edf2; color: #1f2937; border: none;
                           padding: 8px; font-weight: bold; }
    QStatusBar { background: #e8edf2; color: #6b7280; }
    QCheckBox { color: #1f2937; }
    QLineEdit, QComboBox, QSpinBox, QPlainTextEdit { background: white;
                border: 1px solid #d5dbe1; border-radius: 4px; padding: 5px 8px; }
    QFrame#reminderHeader { background: #0f766e; border: none; }
    QLabel#reminderHeaderLabel { color: white; font-size: 13pt; font-weight: bold; }
    """
    widget.setStyleSheet(qss)


class TodoDialog(QDialog):
    def __init__(self, parent, store: TodoStore, todo: Todo | None = None) -> None:
        super().__init__(parent)
        self.result: dict | None = None
        self.store = store
        self.todo = todo
        self.setWindowTitle("编辑事项" if todo else "添加事项")
        self.setModal(True)
        self.setMinimumWidth(520)

        default_lead = int(store.settings.get("default_lead_minutes", 5))
        if default_lead not in LEAD_CHOICES:
            default_lead = 5

        initial_due = parse_dt(todo.due) if todo else None
        initial_due = initial_due or parse_dt(default_due_str())
        self.title_edit = QLineEdit(todo.title if todo else "")
        self.year_combo = QComboBox()
        self.month_combo = QComboBox()
        self.day_combo = QComboBox()
        self.hour_combo = QComboBox()
        self.minute_combo = QComboBox()
        self.priority_combo = QComboBox()
        self.lead_combo = QComboBox()
        self.tag_edit = QLineEdit(todo.tag if todo else "")
        self.notes_edit = QPlainTextEdit()
        self.reminder_combo = QComboBox()
        self.reminder_interval_spin = QSpinBox()
        self.progress_edit = QPlainTextEdit()
        self.daily_history_edit = QPlainTextEdit()
        self.daily_history_edit.setReadOnly(True)
        self.daily_history_edit.setPlaceholderText("暂无每日进展记录")
        self.daily_history_edit.setFixedHeight(90)
        self.daily_progress_edit = QLineEdit()
        self.daily_progress_edit.setPlaceholderText("例如：已完成 50%")
        self.voice_check = QCheckBox("到期时语音播报提醒")
        self.due_preview_label = QLabel("")

        current_year = datetime.now().year
        year_values = [str(y) for y in range(current_year - 1, current_year + 4)]
        if str(initial_due.year) not in year_values:
            year_values.append(str(initial_due.year))
        self._fill_combo(self.year_combo, year_values, str(initial_due.year))
        self._fill_combo(self.month_combo, [str(m) for m in range(1, 13)], str(initial_due.month))
        self._fill_combo(
            self.day_combo,
            [str(d) for d in range(1, 32)],
            str(initial_due.day),
        )
        self._fill_combo(
            self.hour_combo,
            [f"{h:02d}" for h in range(24)],
            f"{initial_due.hour:02d}",
        )
        self._fill_combo(
            self.minute_combo,
            [f"{m:02d}" for m in range(60)],
            f"{initial_due.minute:02d}",
        )
        self._fill_combo(
            self.priority_combo,
            list(PRIORITIES),
            todo.priority if todo else PRIORITIES[1],
        )
        self._fill_combo(
            self.lead_combo,
            [str(m) for m in LEAD_CHOICES],
            str(todo.lead_minutes if todo is not None else default_lead),
        )
        reminder_mode = todo.reminder_mode if todo else "none"
        if reminder_mode not in REMINDER_MODE_LABELS:
            reminder_mode = "none"
        self._fill_combo(
            self.reminder_combo,
            list(REMINDER_MODE_LABELS.values()),
            REMINDER_MODE_LABELS[reminder_mode],
        )
        self.reminder_interval_spin.setRange(1, 72)
        self.reminder_interval_spin.setValue(
            max(1, int(todo.reminder_interval or 1)) if todo else 1
        )
        if todo and todo.progress:
            self.progress_edit.setPlainText(todo.progress)
        history = todo.progress_history if todo else {}
        if history:
            self.daily_history_edit.setPlainText(
                "\n".join(f"{day}：{text}" for day, text in sorted(history.items()))
            )
        self.reminder_combo.currentTextChanged.connect(
            lambda _text: self._update_reminder_ui()
        )
        self.voice_check.setChecked(
            todo.voice_enabled if todo else bool(store.settings.get("voice_enabled", True))
        )
        if todo and todo.notes:
            self.notes_edit.setPlainText(todo.notes)

        self.year_combo.currentTextChanged.connect(self._refresh_days)
        self.month_combo.currentTextChanged.connect(self._refresh_days)
        self.day_combo.currentTextChanged.connect(self._update_due_preview)
        self.hour_combo.currentTextChanged.connect(self._update_due_preview)
        self.minute_combo.currentTextChanged.connect(self._update_due_preview)

        self._build()
        self._update_reminder_ui()
        self._refresh_days()
        self.title_edit.setFocus()

    @staticmethod
    def _fill_combo(combo: QComboBox, values: list[str], current: str) -> None:
        combo.addItems(values)
        combo.setCurrentText(current)
        combo.setEditable(False)

    def _reminder_mode(self) -> str:
        for key, label in REMINDER_MODE_LABELS.items():
            if self.reminder_combo.currentText() == label:
                return key
        return "none"

    def _update_reminder_ui(self) -> None:
        mode = self._reminder_mode()
        enabled = mode != "none"
        self.reminder_interval_spin.setEnabled(enabled)
        if mode == "hourly":
            self.reminder_interval_spin.setRange(1, 72)
            self.reminder_interval_spin.setSuffix(" 小时")
        elif mode == "daily":
            self.reminder_interval_spin.setRange(1, 30)
            self.reminder_interval_spin.setSuffix(" 天")
        else:
            self.reminder_interval_spin.setSuffix("")

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(8)

        root.addWidget(QLabel("标题 *"))
        root.addWidget(self.title_edit)

        root.addWidget(QLabel("截止时间 *"))
        due_row = QHBoxLayout()
        due_row.addWidget(self.year_combo)
        due_row.addWidget(QLabel("年"))
        due_row.addWidget(self.month_combo)
        due_row.addWidget(QLabel("月"))
        due_row.addWidget(self.day_combo)
        due_row.addWidget(QLabel("日"))
        due_row.addWidget(self.hour_combo)
        due_row.addWidget(QLabel("时"))
        due_row.addWidget(self.minute_combo)
        due_row.addWidget(QLabel("分"))
        due_row.addStretch(1)
        root.addLayout(due_row)
        root.addWidget(self.due_preview_label)

        root.addWidget(QLabel("优先级"))
        root.addWidget(self.priority_combo)

        root.addWidget(QLabel("提前提醒"))
        lead_row = QHBoxLayout()
        lead_row.addWidget(self.lead_combo)
        lead_row.addWidget(QLabel("单位：分钟，0 表示到期时提醒"))
        lead_row.addStretch(1)
        root.addLayout(lead_row)

        root.addWidget(QLabel("提醒方式"))
        reminder_row = QHBoxLayout()
        reminder_row.addWidget(self.reminder_combo)
        reminder_row.addWidget(self.reminder_interval_spin)
        reminder_row.addStretch(1)
        root.addLayout(reminder_row)

        root.addWidget(QLabel("最新进展"))
        root.addWidget(self.progress_edit)

        root.addWidget(QLabel("每日进展记录"))
        root.addWidget(self.daily_history_edit)
        root.addWidget(QLabel("今日进展"))
        root.addWidget(self.daily_progress_edit)

        root.addWidget(QLabel("标签"))
        root.addWidget(self.tag_edit)

        root.addWidget(QLabel("备注"))
        root.addWidget(self.notes_edit)
        root.addWidget(self.voice_check)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("toolButton")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存")
        save.setObjectName("accentButton")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    def _compose_due(self) -> str:
        try:
            year = int(self.year_combo.currentText())
            month = int(self.month_combo.currentText())
            day = min(int(self.day_combo.currentText()), calendar.monthrange(year, month)[1])
            return (
                f"{year:04d}-{month:02d}-{day:02d} "
                f"{int(self.hour_combo.currentText()):02d}:{int(self.minute_combo.currentText()):02d}"
            )
        except ValueError:
            return ""

    def _update_due_preview(self) -> None:
        due = self._compose_due()
        self.due_preview_label.setText(f"时间：{due}" if due else "时间：—")

    def _refresh_days(self) -> None:
        try:
            year = int(self.year_combo.currentText())
            month = int(self.month_combo.currentText())
        except ValueError:
            return
        days_in_month = calendar.monthrange(year, month)[1]
        current = self.day_combo.currentText()
        self.day_combo.clear()
        self.day_combo.addItems([str(d) for d in range(1, days_in_month + 1)])
        try:
            day = int(current)
        except ValueError:
            day = 1
        if day > days_in_month:
            day = days_in_month
        self.day_combo.setCurrentText(str(day))
        self._update_due_preview()

    def _save(self) -> None:
        title = self.title_edit.text().strip()
        due = self._compose_due()
        if not title:
            QMessageBox.warning(self, "提示", "请填写事项标题。")
            return
        due_dt = parse_dt(due)
        if due_dt is None:
            QMessageBox.warning(self, "提示", "截止时间格式不正确，请使用：YYYY-MM-DD HH:MM")
            return
        if self.todo is None and due_dt < datetime.now():
            QMessageBox.warning(self, "提示", "截止时间不能早于当前时间。")
            return
        try:
            lead = int(self.lead_combo.currentText())
        except ValueError:
            lead = 0
        reminder_mode = self._reminder_mode()
        reminder_interval = max(1, int(self.reminder_interval_spin.value() or 1))
        progress_text = self.progress_edit.toPlainText().strip()
        daily_text = self.daily_progress_edit.text().strip()
        if daily_text and not progress_text:
            progress_text = daily_text
        self.result = {
            "title": title,
            "due": due,
            "priority": self.priority_combo.currentText(),
            "tag": self.tag_edit.text().strip(),
            "notes": self.notes_edit.toPlainText().strip(),
            "lead_minutes": lead,
            "voice_enabled": self.voice_check.isChecked(),
            "reminder_mode": reminder_mode,
            "reminder_interval": reminder_interval,
            "progress": progress_text,
            "daily_progress_text": daily_text,
        }
        if self.todo is not None and (
            due != self.todo.due
            or reminder_mode != self.todo.reminder_mode
            or reminder_interval != int(self.todo.reminder_interval or 0)
        ):
            self.result["last_reminder_at"] = ""
            self.result["last_notified_due"] = ""
        self.accept()


class SettingsDialog(QDialog):
    def __init__(self, parent, store: TodoStore) -> None:
        super().__init__(parent)
        self.store = store
        self.saved = False
        self.setWindowTitle("设置")
        self.setModal(True)
        self.setMinimumWidth(560)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(10, 600)
        self.interval_spin.setSingleStep(5)
        self.interval_spin.setValue(int(store.settings.get("check_interval_seconds", 30)))

        self.lead_combo = QComboBox()
        self.lead_combo.addItems([str(m) for m in LEAD_CHOICES])
        self.lead_combo.setCurrentText(str(store.settings.get("default_lead_minutes", 5)))

        self.sound_check = QCheckBox("提醒时播放提示音")
        self.sound_check.setChecked(bool(store.settings.get("sound_enabled", True)))
        self.voice_check = QCheckBox("到期时语音播报提醒")
        self.voice_check.setChecked(bool(store.settings.get("voice_enabled", True)))

        self.available_voices: list[VoiceInfo] = list_voices()
        self.voice_choices = {AUTO_VOICE_LABEL: ""}
        for voice in self.available_voices:
            self.voice_choices[voice.description] = voice.description
        self.voice_combo = QComboBox()
        self.voice_combo.addItems(list(self.voice_choices))
        saved_voice = store.settings.get("voice_name", "")
        self.voice_combo.setCurrentText(
            saved_voice if saved_voice in self.voice_choices else AUTO_VOICE_LABEL
        )

        self.daily_enabled_check = QCheckBox("每日提醒")
        self.daily_enabled_check.setChecked(
            bool(store.settings.get("daily_reminder_enabled", True))
        )
        daily_hour, daily_minute = _daily_reminder_time(store.settings)
        self.daily_hour_combo = QComboBox()
        self.daily_hour_combo.addItems([f"{h:02d}" for h in range(24)])
        self.daily_hour_combo.setCurrentText(f"{daily_hour:02d}")
        self.daily_minute_combo = QComboBox()
        self.daily_minute_combo.addItems([f"{m:02d}" for m in range(60)])
        self.daily_minute_combo.setCurrentText(f"{daily_minute:02d}")

        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(10)

        root.addWidget(QLabel("提醒检查间隔"))
        interval_row = QHBoxLayout()
        interval_row.addWidget(self.interval_spin)
        interval_row.addWidget(QLabel("秒"))
        interval_row.addStretch(1)
        root.addLayout(interval_row)

        root.addWidget(QLabel("默认提前提醒"))
        lead_row = QHBoxLayout()
        lead_row.addWidget(self.lead_combo)
        lead_row.addWidget(QLabel("分钟，0 表示到期时提醒"))
        lead_row.addStretch(1)
        root.addLayout(lead_row)

        root.addWidget(self.sound_check)
        voice_row = QHBoxLayout()
        voice_row.addWidget(self.voice_check)
        test_voice = QPushButton("测试语音")
        test_voice.setObjectName("toolButton")
        test_voice.clicked.connect(self._test_voice)
        voice_row.addWidget(test_voice)
        voice_row.addStretch(1)
        root.addLayout(voice_row)

        root.addWidget(QLabel("语音音色"))
        timbre_row = QHBoxLayout()
        timbre_row.addWidget(self.voice_combo)
        timbre_row.addWidget(QLabel("选择系统语音音色"))
        timbre_row.addStretch(1)
        root.addLayout(timbre_row)

        daily_row = QHBoxLayout()
        daily_row.addWidget(self.daily_enabled_check)
        daily_row.addWidget(self.daily_hour_combo)
        daily_row.addWidget(QLabel("时"))
        daily_row.addWidget(self.daily_minute_combo)
        daily_row.addWidget(QLabel("分"))
        test_daily = QPushButton("测试每日提醒")
        test_daily.setObjectName("toolButton")
        test_daily.clicked.connect(self._test_daily_reminder)
        daily_row.addWidget(test_daily)
        daily_row.addWidget(QLabel("汇总未完成事项"))
        daily_row.addStretch(1)
        root.addLayout(daily_row)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("toolButton")
        cancel.clicked.connect(self.reject)
        open_log = QPushButton("打开日志目录")
        open_log.setObjectName("toolButton")
        open_log.clicked.connect(self._open_log_dir)
        save = QPushButton("保存")
        save.setObjectName("accentButton")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(open_log)
        buttons.addWidget(save)
        root.addLayout(buttons)

    def _save(self) -> None:
        try:
            interval = max(10, min(600, int(self.interval_spin.value())))
        except ValueError:
            interval = 30
        try:
            lead = int(self.lead_combo.currentText())
        except ValueError:
            lead = 5
        if lead not in LEAD_CHOICES:
            lead = 5
        selected_voice = self.voice_combo.currentText()
        voice_name = "" if selected_voice == AUTO_VOICE_LABEL else selected_voice
        daily_hour = int(self.daily_hour_combo.currentText())
        daily_minute = int(self.daily_minute_combo.currentText())
        self.store.save_settings(
            {
                "check_interval_seconds": interval,
                "default_lead_minutes": lead,
                "sound_enabled": self.sound_check.isChecked(),
                "voice_enabled": self.voice_check.isChecked(),
                "voice_name": voice_name,
                "daily_reminder_enabled": self.daily_enabled_check.isChecked(),
                "daily_reminder_time": f"{daily_hour:02d}:{daily_minute:02d}",
            }
        )
        self.saved = True
        self.accept()

    def _test_voice(self) -> None:
        selected = self.voice_combo.currentText()
        voice_name = "" if selected == AUTO_VOICE_LABEL else selected
        speak_text_async("语音提醒测试，请注意，还有五分钟到期。", voice_name=voice_name)

    def _test_daily_reminder(self) -> None:
        selected = self.voice_combo.currentText()
        voice_name = "" if selected == AUTO_VOICE_LABEL else selected
        speak_text_async("每日提醒测试，请注意，还有5项工作未完成。", voice_name=voice_name)

    def _open_log_dir(self) -> None:
        log_path = log_file_path()
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(
                ["explorer", str(log_path.parent)],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            pass


class SyncWorker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, config: dict, data_path: Path, log_path: Path) -> None:
        super().__init__()
        self.config = config
        self.data_path = data_path
        self.log_path = log_path

    def run(self) -> None:
        try:
            result = sync_all(self.config, self.data_path, self.log_path)
            self.done.emit(result)
        except Exception as exc:
            logger.exception("同步失败")
            self.failed.emit(str(exc))


class DesktopAssistantApp(QMainWindow):
    def __init__(self, store: TodoStore | None = None) -> None:
        super().__init__()
        if QApplication.instance() is None:
            QApplication([])
        self.store = store or TodoStore()
        self.popups: dict[str, QDialog] = {}
        self.current_todo_id = ""
        self.stat_labels: dict[str, QLabel] = {}
        self._sync_worker: SyncWorker | None = None

        self.setWindowTitle(APP_NAME)
        self.resize(1080, 680)
        self.setMinimumSize(920, 600)
        self._setup_styles()
        self._build_ui()
        self._setup_asr()
        self.refresh()
        self._schedule_check(immediate=True)
        self._tick_clock()

    def _report_exception(self, exc_type, exc_value, exc_tb) -> None:
        logger.error("界面操作异常", exc_info=(exc_type, exc_value, exc_tb))

    def _speak(self, text: str) -> None:
        speak_text_async(text, voice_name=self.store.settings.get("voice_name", ""))

    def _setup_asr(self) -> None:
        self._asr = SpeechRecognitionController(start_hotkey=False, parent=self)
        self._asr.state_changed.connect(self._on_asr_state)
        self._asr.partial_text.connect(self._on_asr_partial)
        self._asr.result_text.connect(self._on_asr_result)
        self._asr.error.connect(self._on_asr_error)
        self._asr.log_message.connect(self._on_asr_log)
        self._asr.start_hotkey()
        self.asr_timeout_timer = QTimer(self)
        self.asr_timeout_timer.timeout.connect(self._asr.check_timeout)
        self.asr_timeout_timer.start(1000)

    def _setup_styles(self) -> None:
        _apply_base_style(self)
        sys.excepthook = self._report_exception

    def _build_ui(self) -> None:
        central = QFrame(self)
        central.setObjectName("root")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame(central)
        header.setObjectName("header")
        header.setFixedHeight(62)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 0, 18, 0)
        title_label = QLabel(APP_NAME, header)
        title_label.setObjectName("titleLabel")
        self.clock_label = QLabel(header)
        self.clock_label.setObjectName("clockLabel")
        header_layout.addWidget(title_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.clock_label)
        layout.addWidget(header)

        stats = QHBoxLayout()
        stats.setContentsMargins(16, 14, 16, 4)
        stats.setSpacing(10)
        for key, caption in (
            ("total", "全部事项"),
            ("pending", "待完成"),
            ("today", "今日到期"),
            ("overdue", "已过期"),
        ):
            stats.addWidget(self._stat_card(key, caption))
        layout.addLayout(stats)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(16, 12, 16, 8)
        toolbar.setSpacing(8)
        self.add_btn = self._tool_button("添加事项", self._add_todo, accent=True)
        self.toggle_btn = self._tool_button("标记完成", self._toggle_completed)
        self.edit_btn = self._tool_button("编辑", self._edit_todo)
        self.daily_btn = self._tool_button("今日进展", self._record_daily_progress)
        self.delete_btn = self._tool_button("删除", self._delete_todo)
        self.clear_btn = self._tool_button("清理已完成", self._clear_completed)
        settings_btn = self._tool_button("设置", self._open_settings)
        self.sync_btn = self._tool_button("同步", self._sync_now)
        toolbar.addWidget(self.add_btn)
        toolbar.addWidget(self.toggle_btn)
        toolbar.addWidget(self.edit_btn)
        toolbar.addWidget(self.daily_btn)
        toolbar.addWidget(self.delete_btn)
        toolbar.addWidget(self.clear_btn)
        toolbar.addWidget(settings_btn)
        toolbar.addWidget(self.sync_btn)
        self.asr_btn = self._tool_button("语音转文字", self._toggle_asr)
        toolbar.addWidget(self.asr_btn)
        toolbar.addStretch(1)

        self.hide_done_check = QCheckBox("隐藏已完成")
        self.hide_done_check.toggled.connect(self.refresh_todo_list)
        toolbar.addWidget(self.hide_done_check)
        toolbar.addWidget(QLabel("搜索"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("标题 / 标签 / 备注")
        self.filter_edit.setFixedWidth(180)
        self.filter_edit.textChanged.connect(self.refresh_todo_list)
        toolbar.addWidget(self.filter_edit)
        layout.addLayout(toolbar)

        body = QVBoxLayout()
        body.setContentsMargins(16, 0, 16, 8)
        body.setSpacing(8)

        self.detail_label = QLabel("选择一个事项查看详情")
        self.detail_label.setObjectName("detailLabel")
        self.detail_label.setWordWrap(True)
        detail_panel = QFrame()
        detail_panel.setObjectName("panel")
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(12, 10, 12, 10)
        detail_layout.addWidget(self.detail_label)
        body.addWidget(detail_panel)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["截止时间", "标题", "剩余时间", "优先级", "标签", "状态"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        widths = {"due": 110, "title": 300, "remaining": 150, "priority": 70, "tag": 120, "status": 80}
        header = self.table.horizontalHeader()
        for col, (name, width) in enumerate(
            (("due", 110), ("title", 300), ("remaining", 150), ("priority", 70), ("tag", 120), ("status", 80))
        ):
            header.resizeSection(col, width)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.cellDoubleClicked.connect(lambda *_a: self._edit_todo())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        return_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Return), self.table)
        return_shortcut.activated.connect(self._edit_todo)
        body.addWidget(self.table, 1)

        layout.addLayout(body)

        self.status_label = QLabel("")
        self.statusBar().addWidget(self.status_label)
        self.sync_status_label = QLabel("未同步")
        self.statusBar().addPermanentWidget(self.sync_status_label)
        self.asr_status_label = QLabel("语音识别：就绪（F9）")
        self.statusBar().addPermanentWidget(self.asr_status_label)

        self.toggle_btn.setEnabled(False)
        self.edit_btn.setEnabled(False)
        self.delete_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)

        self._build_asr_dock()
        self._build_menus()

    def _build_menus(self) -> None:
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件")
        add_action = QAction("添加事项", self)
        add_action.setShortcut(QKeySequence("Ctrl+N"))
        add_action.triggered.connect(self._add_todo)
        file_menu.addAction(add_action)
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        tools_menu = menubar.addMenu("工具")
        tools_menu.addAction("批量解压工具", self._open_unzip_tool)
        tools_menu.addSeparator()
        tools_menu.addAction("Excel批量检测工具", self._open_excel_inspector_tool)

        voice_menu = menubar.addMenu("语音")
        voice_menu.addAction("开始 / 停止录音（F9）", self._toggle_asr)
        voice_menu.addAction("复制最后识别结果", self._copy_asr_result)
        voice_menu.addAction("显示 / 隐藏识别面板", self._toggle_asr_dock)

        settings_menu = menubar.addMenu("设置")
        settings_action = QAction("打开设置", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self._open_settings)
        settings_menu.addAction(settings_action)

        help_menu = menubar.addMenu("帮助")
        help_menu.addAction("关于", self._show_about)

    def _build_asr_dock(self) -> None:
        dock = QDockWidget("语音识别", self)
        dock.setObjectName("asrDock")
        dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        container = QWidget(dock)
        v = QVBoxLayout(container)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)
        self.asr_current_label = QLabel("就绪（F9 开始 / 停止）")
        self.asr_current_label.setWordWrap(True)
        self.asr_current_label.setStyleSheet(f"color: {ACCENT}; font-weight: bold;")
        v.addWidget(self.asr_current_label)
        self.asr_history = QPlainTextEdit(container)
        self.asr_history.setReadOnly(True)
        self.asr_history.setPlaceholderText("识别结果会显示在这里，并自动复制到剪贴板。")
        v.addWidget(self.asr_history, 1)
        dock.setWidget(container)
        dock.setMinimumWidth(240)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.asr_dock = dock
        dock.show()

    def _toggle_asr(self) -> None:
        if self._asr is not None:
            self._asr.toggle()

    def _copy_asr_result(self) -> None:
        if self._asr is None or not self._asr.last_result:
            self.asr_current_label.setText("还没有识别结果")
            return
        QGuiApplication.clipboard().setText(self._asr.last_result)
        self.asr_current_label.setText("已复制最后识别结果到剪贴板")
        logger.info("手动复制语音识别结果")

    def _toggle_asr_dock(self) -> None:
        self.asr_dock.setVisible(not self.asr_dock.isVisible())

    def _on_asr_state(self, state: str) -> None:
        if state == "recording":
            self.asr_btn.setText("停止录音")
            self.asr_current_label.setText("正在录音，再次按 F9 停止")
            self.asr_status_label.setText("语音识别：录音中")
        elif state == "recognizing":
            self.asr_btn.setText("识别中...")
            self.asr_btn.setEnabled(False)
            self.asr_current_label.setText("正在识别...")
            self.asr_status_label.setText("语音识别：识别中")
        else:
            self.asr_btn.setText("语音转文字")
            self.asr_btn.setEnabled(True)
            self.asr_current_label.setText("就绪（F9 开始 / 停止）")
            self.asr_status_label.setText("语音识别：就绪（F9）")

    def _on_asr_partial(self, text: str) -> None:
        self.asr_current_label.setText(f"识别中：{text[-120:]}")

    def _on_asr_result(self, text: str) -> None:
        if self._asr and self._asr.config.get("auto_copy", True):
            QGuiApplication.clipboard().setText(text)
        stamp = datetime.now().strftime("%H:%M:%S")
        self.asr_history.appendPlainText(f"[{stamp}] {text}")
        self.asr_current_label.setText("识别完成，已复制到剪贴板")
        logger.info("语音识别结果：%s", text)
        self._save_speech_record(text)

    def _on_asr_error(self, message: str) -> None:
        self.asr_current_label.setText(message)
        self.asr_status_label.setText("语音识别：出错")
        logger.error("语音识别错误：%s", message)

    def _on_asr_log(self, message: str) -> None:
        logger.info("语音识别：%s", message)

    def _save_speech_record(self, text: str) -> None:
        try:
            speech_dir = self.store.path.parent / "speech"
            speech_dir.mkdir(parents=True, exist_ok=True)
            target = speech_dir / f"{datetime.now():%Y-%m-%d}.txt"
            with target.open("a", encoding="utf-8") as fh:
                fh.write(f"[{datetime.now():%H:%M:%S}] {text}\n")
        except OSError:
            logger.exception("保存语音识别记录失败")

    def _stat_card(self, key: str, caption: str) -> QFrame:
        card = QFrame()
        card.setObjectName("statCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        value = QLabel("0")
        value.setObjectName("statValue")
        cap = QLabel(caption)
        cap.setObjectName("statCaption")
        layout.addWidget(value)
        layout.addWidget(cap)
        self.stat_labels[key] = value
        return card

    def _tool_button(self, text: str, command, accent: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("accentButton" if accent else "toolButton")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(command)
        return btn

    def refresh(self) -> None:
        self.refresh_todo_list()
        self.refresh_stats()
        self.refresh_status()

    def refresh_todo_list(self) -> None:
        current = self.current_todo_id
        self.table.setRowCount(0)
        query = self.filter_edit.text().strip().lower()
        hide_done = self.hide_done_check.isChecked()
        now = datetime.now()
        visible = []
        for todo in self.store.todos:
            if todo.completed and hide_done:
                continue
            haystack = " ".join((todo.title, todo.tag, todo.notes)).lower()
            if query and query not in haystack:
                continue
            if todo.due_dt() is None:
                continue
            visible.append(todo)
        visible.sort(key=lambda t: (t.completed, t.due_dt() or datetime.max))

        self.table.setRowCount(len(visible))
        for row, todo in enumerate(visible):
            due = todo.due_dt() or datetime.now()
            if todo.completed:
                status = "已完成"
                tag = "done"
            elif todo.is_overdue(now):
                status = "已过期"
                tag = "overdue"
            elif todo.snoozed_until and (snooze := parse_dt(todo.snoozed_until)) and snooze > now:
                status = "提醒中"
                tag = "snoozed"
            else:
                status = "待办"
                if todo.priority == PRIORITY_HIGH:
                    tag = "high"
                elif (due - now).total_seconds() <= 3600:
                    tag = "soon"
                else:
                    tag = "normal"
            values = (
                due.strftime("%m-%d %H:%M"),
                todo.title,
                format_remaining(due, now),
                todo.priority,
                todo.tag or "—",
                status,
            )
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, todo.id)
                item.setForeground(QColor(TAG_COLORS[tag]))
                self.table.setItem(row, col, item)

        if current:
            found = False
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item and item.data(Qt.ItemDataRole.UserRole) == current:
                    self.table.selectRow(row)
                    self.table.setCurrentCell(row, 0)
                    found = True
                    break
            if not found:
                self.current_todo_id = ""
        else:
            self.current_todo_id = ""
        self._on_select()

    def refresh_stats(self) -> None:
        now = datetime.now()
        total = len(self.store.todos)
        pending = sum(1 for t in self.store.todos if not t.completed)
        due_today = sum(
            1
            for t in self.store.todos
            if not t.completed and t.due_dt() is not None and t.due_dt().date() == now.date()
        )
        overdue = sum(1 for t in self.store.todos if t.is_overdue(now))
        self.stat_labels["total"].setText(str(total))
        self.stat_labels["pending"].setText(str(pending))
        self.stat_labels["today"].setText(str(due_today))
        self.stat_labels["overdue"].setText(str(overdue))

    def refresh_status(self) -> None:
        now = datetime.now()
        next_remind: datetime | None = None
        for todo in self.store.todos:
            if todo.completed:
                continue
            next_at = todo.next_reminder_at(now)
            if next_at is None:
                continue
            snooze = parse_dt(todo.snoozed_until)
            if snooze and snooze > now:
                next_at = max(next_at, snooze)
            if next_at > now and (next_remind is None or next_at < next_remind):
                next_remind = next_at
        interval = int(self.store.settings.get("check_interval_seconds", 30))
        parts = [f"提醒检查间隔 {interval} 秒"]
        if next_remind:
            parts.append(f"下次提醒 {next_remind.strftime(TIME_FORMAT)}")
        if self.store.settings.get("daily_reminder_enabled", True):
            hour, minute = _daily_reminder_time(self.store.settings)
            daily_target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if daily_target <= now:
                daily_target += timedelta(days=1)
            parts.append(f"每日提醒 {daily_target.strftime('%H:%M')}")
        parts.append(f"数据文件 {self.store.path}")
        self.status_label.setText("  ~  ".join(parts))

    def _schedule_check(self, immediate: bool = False) -> None:
        if not hasattr(self, "check_timer"):
            self.check_timer = QTimer(self)
            self.check_timer.timeout.connect(self._check_reminders)
        self.check_timer.stop()
        try:
            interval = max(10, int(self.store.settings.get("check_interval_seconds", 30)))
        except ValueError:
            interval = 30
        self.check_timer.setInterval(interval * 1000)
        self.check_timer.start()
        if immediate:
            QTimer.singleShot(0, self._check_reminders)

    def _check_reminders(self) -> None:
        now = datetime.now()
        pending = [t for t in self.store.todos if t.reminder_pending(now)]
        for todo in pending:
            if todo.id in self.popups:
                continue
            todo.mark_notified(now)
            self.store.save()
            next_at = todo.next_reminder_at(now)
            logger.info(
                "下次提醒：%s",
                next_at.strftime(TIME_FORMAT) if next_at else "无（仅提醒一次）",
            )
            if self.store.settings.get("voice_enabled", True) and todo.voice_enabled:
                self._speak(voice_reminder_text(todo, now))
            self._show_reminder(todo)
        self._check_daily_reminder(now)
        self.refresh()

    def _show_reminder(self, todo: Todo) -> None:
        logger.info("弹出到期提醒：%s（截止 %s）", todo.title, todo.due)
        win = QDialog(self)
        win.setWindowTitle("事项提醒")
        win.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        win.setModal(False)
        layout = QVBoxLayout(win)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame(win)
        header.setObjectName("reminderHeader")
        header.setFixedHeight(54)
        header_layout = QVBoxLayout(header)
        header_label = QLabel("到期提醒")
        header_label.setObjectName("reminderHeaderLabel")
        header_layout.addWidget(header_label)
        layout.addWidget(header)

        body = QVBoxLayout()
        body.setContentsMargins(22, 16, 22, 10)
        body.setSpacing(6)
        title = QLabel(todo.title)
        title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        title.setWordWrap(True)
        due = todo.due_dt()
        due_text = due.strftime(TIME_FORMAT) if due else "—"
        remaining = format_remaining(due) if due else "—"
        body.addWidget(title)
        body.addWidget(QLabel(f"截止时间：{due_text}"))
        body.addWidget(QLabel(f"剩余时间：{remaining}"))
        if todo.notes:
            notes = QLabel(f"备注：{todo.notes}")
            notes.setWordWrap(True)
            body.addWidget(notes)
        current_progress = (todo.progress or "").strip()
        body.addWidget(QLabel(f"当前进展：{current_progress or '未填写'}"))
        progress_edit = QPlainTextEdit()
        progress_edit.setObjectName("reminderProgressEdit")
        progress_edit.setPlaceholderText("填写最新进展后点击“更新进展”")
        progress_edit.setFixedHeight(60)
        body.addWidget(progress_edit)
        layout.addLayout(body)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(22, 4, 22, 16)
        buttons.addStretch(1)
        replay = QPushButton("再播报一次")
        replay.setObjectName("toolButton")
        replay.clicked.connect(lambda: self._speak(voice_reminder_text(todo)))
        buttons.addWidget(replay)
        for minutes in (5, 15):
            snooze_btn = QPushButton(f"推迟{minutes}分钟")
            snooze_btn.setObjectName("toolButton")
            snooze_btn.clicked.connect(lambda _=False, m=minutes: self._snooze(todo.id, m))
            buttons.addWidget(snooze_btn)
        update_progress = QPushButton("更新进展")
        update_progress.setObjectName("toolButton")
        update_progress.clicked.connect(
            lambda: self._save_progress(todo.id, progress_edit.toPlainText())
        )
        buttons.addWidget(update_progress)
        ok = QPushButton("知道了")
        ok.setObjectName("accentButton")
        ok.clicked.connect(lambda: self._close_popup(todo.id))
        buttons.addWidget(ok)
        layout.addLayout(buttons)

        self.popups[todo.id] = win
        win.finished.connect(lambda _result, key=todo.id: self.popups.pop(key, None))
        win.adjustSize()
        win.setMinimumWidth(460)
        screen = QGuiApplication.primaryScreen().availableGeometry()
        open_count = len(self.popups)
        x = max(0, screen.right() - win.width() - 36)
        y = max(0, screen.bottom() - win.height() - 70 - (open_count - 1) * 18)
        win.move(x, y)
        win.show()
        if self.store.settings.get("sound_enabled", True):
            QApplication.beep()

    def _check_daily_reminder(self, now: datetime) -> None:
        settings = self.store.settings
        if not settings.get("daily_reminder_enabled", True):
            return
        hour, minute = _daily_reminder_time(settings)
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        today = now.strftime("%Y-%m-%d")
        if now < target:
            return
        if settings.get("last_daily_reminder_date") == today:
            return
        pending = [t for t in self.store.todos if not t.completed]
        self.store.save_settings({"last_daily_reminder_date": today})
        if not pending:
            logger.info("每日提醒：今天没有未完成事项")
            return
        logger.info("每日提醒触发：%d 项未完成", len(pending))
        self._speak(_daily_reminder_voice_text(pending, now))
        self._show_daily_reminder(pending)

    def _show_daily_reminder(self, todos: list[Todo]) -> None:
        if "daily" in self.popups:
            return
        win = QDialog(self)
        win.setWindowTitle("每日工作提醒")
        win.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        win.setModal(False)
        layout = QVBoxLayout(win)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame(win)
        header.setObjectName("reminderHeader")
        header.setFixedHeight(54)
        header_layout = QVBoxLayout(header)
        header_label = QLabel("每日工作提醒")
        header_label.setObjectName("reminderHeaderLabel")
        header_layout.addWidget(header_label)
        layout.addWidget(header)

        body = QVBoxLayout()
        body.setContentsMargins(22, 16, 22, 10)
        body.setSpacing(8)
        summary = QLabel(f"现在还有 {len(todos)} 项工作未完成：")
        summary.setStyleSheet("font-size: 12pt; font-weight: bold;")
        body.addWidget(summary)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setMinimumHeight(min(12, max(3, len(todos))) * 22 + 10)
        for todo in todos[:12]:
            due = todo.due_dt()
            remaining = format_remaining(due) if due else "—"
            due_text = due.strftime("%m-%d %H:%M") if due else "—"
            text.appendPlainText(f"{todo.title}    截止 {due_text}    {remaining}")
        body.addWidget(text)
        layout.addLayout(body)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(22, 4, 22, 16)
        buttons.addStretch(1)
        replay = QPushButton("再播报一次")
        replay.setObjectName("toolButton")
        replay.clicked.connect(lambda: self._speak(_daily_reminder_voice_text(todos)))
        buttons.addWidget(replay)
        ok = QPushButton("知道了")
        ok.setObjectName("accentButton")
        ok.clicked.connect(lambda: self._close_popup("daily"))
        buttons.addWidget(ok)
        layout.addLayout(buttons)

        self.popups["daily"] = win
        win.finished.connect(lambda _result: self.popups.pop("daily", None))
        win.adjustSize()
        win.setMinimumWidth(520)
        screen = QGuiApplication.primaryScreen().availableGeometry()
        x = max(0, screen.right() - win.width() - 36)
        y = max(0, screen.bottom() - win.height() - 70)
        win.move(x, y)
        win.show()
        if self.store.settings.get("sound_enabled", True):
            QApplication.beep()

    def _close_popup(self, todo_id: str) -> None:
        win = self.popups.get(todo_id)
        if win is not None:
            win.close()
        self.popups.pop(todo_id, None)

    def _snooze(self, todo_id: str, minutes: int) -> None:
        todo = self.store.get(todo_id)
        logger.info("推迟提醒 %d 分钟：%s", minutes, todo.title if todo else todo_id)
        if todo is not None:
            todo.snooze(minutes)
            self.store.save()
        self._close_popup(todo_id)
        self.refresh()

    def _save_progress(self, todo_id: str, text: str) -> None:
        todo = self.store.get(todo_id)
        if todo is None:
            return
        self.store.add_daily_progress(todo_id, text)
        self.refresh()
        self._close_popup(todo_id)

    def _record_daily_progress(self) -> None:
        todo = self.store.get(self.current_todo_id)
        if todo is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"记录每日进展 - {todo.title}")
        layout = QVBoxLayout(dialog)
        edit = QLineEdit()
        edit.setPlaceholderText("输入今天的进展")
        layout.addWidget(edit)
        buttons = QHBoxLayout()
        cancel = QPushButton("取消")
        cancel.setObjectName("toolButton")
        cancel.clicked.connect(dialog.reject)
        save = QPushButton("保存")
        save.setObjectName("accentButton")
        save.clicked.connect(dialog.accept)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted and edit.text().strip():
            self.store.add_daily_progress(todo.id, edit.text())
            self.refresh()

    def _on_select(self) -> None:
        items = self.table.selectedItems()
        if not items:
            self.current_todo_id = ""
            self.detail_label.setText("选择一个事项查看详情")
            self.toggle_btn.setEnabled(False)
            self.edit_btn.setEnabled(False)
            self.daily_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            self.clear_btn.setEnabled(any(t.completed for t in self.store.todos))
            return
        row = items[0].row()
        item = self.table.item(row, 0)
        todo_id = item.data(Qt.ItemDataRole.UserRole) if item else ""
        todo = self.store.get(todo_id)
        if todo is None:
            return
        self.current_todo_id = todo_id
        due = todo.due_dt()
        lines = [
            f"标题：{todo.title}",
            f"截止时间：{todo.due}",
            f"剩余时间：{format_remaining(due) if due else '—'}",
            (
                f"优先级：{todo.priority}    标签：{todo.tag or '—'}    "
                f"提前提醒：{_lead_text(todo.lead_minutes)}    "
                f"语音播报：{'开' if todo.voice_enabled else '关'}"
            ),
        ]
        if todo.reminder_mode in REMINDER_MODE_LABELS:
            mode_label = REMINDER_MODE_LABELS[todo.reminder_mode]
            if todo.reminder_mode in ("hourly", "daily"):
                unit = "小时" if todo.reminder_mode == "hourly" else "天"
                mode_label += f"（每 {max(1, int(todo.reminder_interval or 1))} {unit}）"
            lines.append(f"提醒方式：{mode_label}")
        if todo.progress:
            lines.append(f"最新进展：{todo.progress}")
        history = todo.progress_history or {}
        if history:
            recent = sorted(history.items())[-5:]
            lines.append("每日进展：" + "；".join(f"{day} {text}" for day, text in recent))
        if todo.notes:
            lines.append(f"备注：{todo.notes}")
        self.detail_label.setText("    ".join(lines))
        self.toggle_btn.setText("取消完成" if todo.completed else "标记完成")
        self.toggle_btn.setEnabled(True)
        self.edit_btn.setEnabled(True)
        self.daily_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
        self.clear_btn.setEnabled(any(t.completed for t in self.store.todos))

    def _show_context_menu(self, pos) -> None:
        item = self.table.itemAt(pos)
        if item is None:
            return
        row = item.row()
        self.table.selectRow(row)
        self._on_select()
        todo = self.store.get(self.current_todo_id)
        if todo is None:
            return
        menu = QMenu(self)
        menu.addAction("取消完成" if todo.completed else "标记完成", self._toggle_completed)
        menu.addAction("编辑", self._edit_todo)
        menu.addAction("删除", self._delete_todo)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _add_todo(self) -> None:
        dialog = TodoDialog(self, self.store)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result:
            data = dict(dialog.result)
            daily_text = data.pop("daily_progress_text", "")
            todo = self.store.add_todo(**data)
            if daily_text:
                self.store.add_daily_progress(todo.id, daily_text)
            self.refresh()

    def _edit_todo(self) -> None:
        todo = self.store.get(self.current_todo_id)
        if todo is None:
            return
        dialog = TodoDialog(self, self.store, todo)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result:
            data = dict(dialog.result)
            daily_text = data.pop("daily_progress_text", "")
            self.store.update_todo(todo.id, **data)
            if daily_text:
                self.store.add_daily_progress(todo.id, daily_text)
            self.refresh()

    def _toggle_completed(self) -> None:
        todo = self.store.get(self.current_todo_id)
        if todo is None:
            return
        self.store.set_completed(todo.id, not todo.completed)
        self.refresh()

    def _delete_todo(self) -> None:
        todo = self.store.get(self.current_todo_id)
        if todo is None:
            return
        answer = QMessageBox.question(
            self,
            "确认删除",
            f"确定删除「{todo.title}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.store.delete_todo(todo.id)
        self.current_todo_id = ""
        self.refresh()

    def _clear_completed(self) -> None:
        count = sum(1 for t in self.store.todos if t.completed)
        if count == 0:
            return
        answer = QMessageBox.question(
            self,
            "清理已完成",
            f"确定删除 {count} 条已完成事项吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.store.delete_completed()
        self.current_todo_id = ""
        self.refresh()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self, self.store)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.saved:
            self._schedule_check()
            self.refresh_status()

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "关于",
            f"{APP_NAME} v1.0\n\n事项数据以 JSON 文件保存在本地，不写入注册表。",
        )

    def _sync_now(self) -> None:
        try:
            config = load_sync_config()
        except Exception as exc:
            logger.error("读取同步配置失败：%s", exc)
            self.sync_status_label.setText("同步失败：配置缺失")
            QMessageBox.critical(self, "同步失败", str(exc))
            return
        self.sync_btn.setEnabled(False)
        self.sync_status_label.setText("正在同步…")
        worker = SyncWorker(config, self.store.path, log_file_path())
        worker.done.connect(self._on_sync_done)
        worker.failed.connect(self._on_sync_failed)
        self._sync_worker = worker
        worker.start()

    def _on_sync_done(self, result: SyncResult) -> None:
        self._sync_worker = None
        self.sync_btn.setEnabled(True)
        self.store.load()
        self.refresh()
        stamp = datetime.now().strftime("%H:%M:%S")
        parts = [f"上传 {result.uploaded_todos} 条", f"下载 {result.downloaded_todos} 条"]
        if result.settings_changed:
            parts.append("设置已合并")
        if result.log_uploaded:
            parts.append("日志已上传")
        self.sync_status_label.setText(f"已同步 {stamp}")
        logger.info("同步完成：%s", "；".join(parts))
        QMessageBox.information(self, "同步完成", "；".join(parts) + "\n" + result.message)

    def _on_sync_failed(self, message: str) -> None:
        self._sync_worker = None
        self.sync_btn.setEnabled(True)
        self.sync_status_label.setText("同步失败")
        logger.error("同步失败：%s", message)
        QMessageBox.critical(self, "同步失败", message)

    def _open_unzip_tool(self) -> None:
        try:
            open_unzip_gui(self)
            logger.info("打开工具：批量解压工具")
        except Exception:
            logger.exception("打开批量解压工具失败")
            QMessageBox.critical(self, "错误", "打开批量解压工具失败，请查看日志。")

    def _open_excel_inspector_tool(self) -> None:
        try:
            open_excel_inspector_gui(self)
            logger.info("打开工具：Excel批量检测工具")
        except Exception:
            logger.exception("打开Excel批量检测工具失败")
            QMessageBox.critical(self, "错误", "打开Excel批量检测工具失败，请查看日志。")

    def _tick_clock(self) -> None:
        if not hasattr(self, "clock_timer"):
            self.clock_timer = QTimer(self)
            self.clock_timer.timeout.connect(self._tick_clock)
            self.clock_timer.start(1000)
        self.clock_label.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def closeEvent(self, event) -> None:
        if self._sync_worker is not None and self._sync_worker.isRunning():
            self._sync_worker.wait(3000)
        if getattr(self, "_asr", None) is not None:
            self._asr.shutdown()
        try:
            self.store.save()
        except OSError:
            logger.exception("退出时保存数据失败")
        for popup in list(self.popups.values()):
            popup.close()
        self.popups.clear()
        logger.info("程序退出")
        event.accept()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--data", help="指定数据文件路径（用于测试）")
    parser.add_argument("--self-test", action="store_true", help="启动后自动关闭，用于验证程序可运行")
    parser.add_argument("--voice-test", action="store_true", help="启动后播报一句语音测试并自动关闭")
    parser.add_argument("--asr-test-audio", help="用 WAV 文件验证语音识别链路并退出")
    parser.add_argument("--asr-mic-test", action="store_true", help="录音自检并退出")
    parser.add_argument("--tool-test", action="store_true", help="启动后打开批量解压工具并自动关闭")
    parser.add_argument("--excel-test", action="store_true", help="启动后打开Excel批量检测工具并自动关闭")
    args = parser.parse_args(argv)

    if args.asr_test_audio:
        setup_logging()
        text = recognize_wav_file(args.asr_test_audio)
        print(text)
        return 0

    if args.asr_mic_test:
        setup_logging()
        import time
        from recorder import MicRecorder
        rec = MicRecorder(sample_rate=16000)
        rec.start()
        time.sleep(1.0)
        pcm = rec.stop()
        logger.info("麦克风录音自检完成：%d 字节", len(pcm))
        print(f"mic ok {len(pcm)}")
        return 0
    qt_app = QApplication.instance() or QApplication([])
    if args.data:
        setup_logging(Path(args.data).expanduser().resolve().parent / "logs")
    else:
        setup_logging()
    logger.info("程序启动")
    store = TodoStore(Path(args.data).expanduser().resolve() if args.data else None)
    window = DesktopAssistantApp(store=store)
    window.show()

    if args.voice_test:
        speak_text_async("语音提醒测试，请注意，还有五分钟到期。")
        QTimer.singleShot(2500, window.close)
    if args.tool_test:
        open_unzip_gui(window)
        QTimer.singleShot(2000, window.close)
    if args.excel_test:
        open_excel_inspector_gui(window)
        QTimer.singleShot(2000, window.close)
    if args.self_test:
        QTimer.singleShot(1500, window.close)

    try:
        return qt_app.exec()
    except Exception:
        logger.exception("程序运行异常")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
