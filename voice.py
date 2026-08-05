"""Windows SAPI voice helpers for the desktop assistant."""

from __future__ import annotations

import base64
import logging
import subprocess
import sys
from dataclasses import dataclass

from app_logger import APP_LOGGER_NAME

logger = logging.getLogger(APP_LOGGER_NAME)

AUTO_VOICE_LABEL = "自动（中文优先）"


@dataclass
class VoiceInfo:
    description: str
    name: str
    language: str


_voices_cache: list[VoiceInfo] | None = None


def _encode_script(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _run_powershell(script: str, timeout: int = 8) -> subprocess.CompletedProcess:
    encoded = _encode_script(script)
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def list_voices_script() -> str:
    return (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
        "$voice = New-Object -ComObject SAPI.SpVoice\n"
        "$voice.GetVoices() | ForEach-Object { "
        "$_.GetDescription() + '|' + $_.GetAttribute('Name') + '|' + "
        "$_.GetAttribute('Language') }\n"
    )


def speak_script(text: str, voice_name: str = "") -> str:
    safe_text = text.replace("'", "''")
    safe_voice = voice_name.replace("'", "''")
    return (
        "$voice = New-Object -ComObject SAPI.SpVoice\n"
        "$selected = $false\n"
        f"if ('{safe_voice}' -ne '') {{\n"
        f"  $target = $voice.GetVoices() | Where-Object {{ "
        f"$_.GetDescription() -eq '{safe_voice}' -or "
        f"$_.GetAttribute('Name') -eq '{safe_voice}' }} | Select-Object -First 1\n"
        "  if ($target) { $voice.Voice = $target; $selected = $true }\n"
        "}\n"
        "if (-not $selected) {\n"
        "  $zh = $voice.GetVoices() | Where-Object { "
        "$_.GetAttribute('Language') -like '804*' } | Select-Object -First 1\n"
        "  if ($zh) { $voice.Voice = $zh }\n"
        "}\n"
        f"$voice.Speak('{safe_text}')\n"
    )


def list_voices(force: bool = False) -> list[VoiceInfo]:
    """Return installed SAPI voices, cached after the first query."""
    global _voices_cache
    if _voices_cache is None or force:
        voices: list[VoiceInfo] = []
        if sys.platform.startswith("win"):
            try:
                result = _run_powershell(list_voices_script())
                for line in result.stdout.decode("utf-8", errors="replace").splitlines():
                    parts = line.strip().split("|")
                    if len(parts) >= 2 and parts[0]:
                        voices.append(
                            VoiceInfo(
                                description=parts[0],
                                name=parts[1],
                                language=parts[2] if len(parts) > 2 else "",
                            )
                        )
            except (OSError, subprocess.TimeoutExpired):
                logger.warning("读取系统语音列表失败")
        _voices_cache = voices
    return list(_voices_cache)


def speak_text_async(text: str, voice_name: str = "") -> None:
    """Speak text asynchronously; empty voice_name means auto Chinese voice."""
    if not text or not sys.platform.startswith("win"):
        return
    logger.info("语音播报：%s", text)
    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                _encode_script(speak_script(text, voice_name)),
            ],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        logger.exception("启动语音播报失败")
