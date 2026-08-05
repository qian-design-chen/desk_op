"""讯飞语音听写集成模块：全局快捷键、麦克风录音、识别结果信号。"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from app_logger import APP_LOGGER_NAME

logger = logging.getLogger(APP_LOGGER_NAME)

DEFAULT_CONFIG = {
    "app_id": "21d87645",
    "api_key": "2df391fc08aaf9b920e43aff242f9115",
    "api_secret": "ODY1NTY0YzcxN2FlOWU0YjBmZmEzYTQw",
    "hotkey": "<f9>",
    "language": "zh_cn",
    "accent": "mandarin",
    "sample_rate": 16000,
    "punctuation": True,
    "auto_copy": True,
    "auto_save_text": True,
    "max_seconds": 120,
    "save_dir": "",
}


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def load_asr_config(config: dict | str | Path | None = None) -> dict:
    """读取 asr_config.json；没有文件时返回内置默认配置。"""
    if isinstance(config, dict):
        return {**DEFAULT_CONFIG, **config}
    cfg_path = Path(config) if config else app_base_dir() / "asr_config.json"
    loaded = dict(DEFAULT_CONFIG)
    if cfg_path.exists():
        try:
            loaded.update(json.loads(cfg_path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            logger.warning("读取语音识别配置失败：%s", exc)
    return loaded


class RecognizeWorker(QThread):
    """后台线程：把 PCM 音频发送到讯飞听写接口。"""

    partial = Signal(str)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, pcm: bytes, config: dict, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.pcm = pcm
        self.config = config

    def run(self) -> None:
        try:
            from iflytek_iat import IATError, recognize_pcm
        except ImportError:
            self.failed.emit("语音识别依赖未安装，请先执行 pip install -r requirements.txt")
            return
        try:
            text = recognize_pcm(
                self.pcm,
                self.config["app_id"],
                self.config["api_key"],
                self.config["api_secret"],
                language=self.config.get("language", "zh_cn"),
                accent=self.config.get("accent", "mandarin"),
                sample_rate=int(self.config.get("sample_rate", 16000)),
                punctuation=bool(self.config.get("punctuation", True)),
                on_partial=self.partial.emit,
            )
        except IATError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:
            self.failed.emit(f"识别失败: {exc}")
            return
        if text:
            self.done.emit(text)
        else:
            self.failed.emit("未识别到内容")


class SpeechRecognitionController(QObject):
    """管理录音、识别、全局热键和状态信号。"""

    state_changed = Signal(str)
    partial_text = Signal(str)
    result_text = Signal(str)
    error = Signal(str)
    log_message = Signal(str)
    _toggle_request = Signal()

    def __init__(
        self,
        config: dict | str | Path | None = None,
        start_hotkey: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = load_asr_config(config)
        self.sample_rate = int(self.config.get("sample_rate", 16000))
        self.recorder = None
        self.recording = False
        self.recognizing = False
        self.record_started_at: float | None = None
        self.last_result = ""
        self._worker: RecognizeWorker | None = None
        self._hotkey = None
        self._toggle_request.connect(self.toggle)
        if start_hotkey:
            self.start_hotkey()

    def start_hotkey(self) -> None:
        try:
            from pynput import keyboard

            combo = self.config.get("hotkey", "<f9>")
            self._hotkey = keyboard.GlobalHotKeys({combo: self._request_toggle})
            self._hotkey.start()
            logger.info("语音识别全局快捷键已注册: %s", combo)
        except Exception as exc:
            logger.warning("语音识别快捷键注册失败: %s", exc)
            self.error.emit(f"全局快捷键注册失败: {exc}")

    def _request_toggle(self) -> None:
        self._toggle_request.emit()

    def toggle(self) -> None:
        if self.recognizing:
            self.log_message.emit("正在识别中，请稍候")
            return
        if self.recording:
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        if self.recording or self.recognizing:
            return
        if self.recorder is None:
            try:
                from recorder import MicRecorder

                self.recorder = MicRecorder(sample_rate=self.sample_rate)
            except ImportError:
                self.error.emit("录音依赖未安装，请先执行 pip install -r requirements.txt")
                return
        try:
            self.recorder.start()
        except Exception as exc:
            self.error.emit(f"无法启动麦克风: {exc}")
            return
        self.recording = True
        self.record_started_at = time.time()
        self._emit_state("recording")
        self.log_message.emit("开始录音，再次按 F9 停止")

    def stop(self) -> None:
        if not self.recording:
            return
        self.recording = False
        try:
            pcm = self.recorder.stop()
        except Exception as exc:
            self._emit_state("idle")
            self.error.emit(f"录音出错: {exc}")
            return
        seconds = time.time() - (self.record_started_at or time.time())
        self.log_message.emit(f"录音结束，时长 {seconds:.1f} 秒")
        if not pcm:
            self._emit_state("idle")
            self.error.emit("未录到声音")
            return
        self.recognizing = True
        self._emit_state("recognizing")
        self._worker = RecognizeWorker(pcm, self.config, self)
        self._worker.partial.connect(self.partial_text)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_done(self, text: str) -> None:
        self.last_result = text
        self.recognizing = False
        self.result_text.emit(text)
        self._emit_state("idle")

    def _on_failed(self, message: str) -> None:
        self.recognizing = False
        self.error.emit(message)
        self._emit_state("idle")

    def _on_worker_finished(self) -> None:
        self._worker = None

    def check_timeout(self) -> None:
        if not self.recording or self.record_started_at is None:
            return
        max_seconds = int(self.config.get("max_seconds", 120))
        if time.time() - self.record_started_at >= max_seconds:
            self.log_message.emit("达到最长录音时间，自动停止")
            self.stop()

    def shutdown(self) -> None:
        try:
            if self._hotkey is not None:
                self._hotkey.stop()
        except Exception:
            pass
        if self.recording:
            try:
                self.recorder.stop()
            except Exception:
                pass
            self.recording = False
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(3000)
        self._emit_state("idle")

    def _emit_state(self, state: str) -> None:
        self.state_changed.emit(state)


def recognize_wav_file(path: str | Path, config: dict | str | Path | None = None) -> str:
    """命令行验证用：识别一个 16kHz 单声道 WAV 文件。"""
    cfg = load_asr_config(config)
    try:
        from iflytek_iat import recognize_wav
    except ImportError as exc:
        raise RuntimeError("语音识别依赖未安装，请先执行 pip install -r requirements.txt") from exc
    return recognize_wav(
        str(path),
        cfg["app_id"],
        cfg["api_key"],
        cfg["api_secret"],
        language=cfg.get("language", "zh_cn"),
        accent=cfg.get("accent", "mandarin"),
        sample_rate=int(cfg.get("sample_rate", 16000)),
        punctuation=bool(cfg.get("punctuation", True)),
    )
