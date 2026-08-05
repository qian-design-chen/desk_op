"""Server-relay sync for the desktop assistant using SFTP."""

from __future__ import annotations

import json
import logging
import os
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore", message="Blowfish has been deprecated")
import paramiko  # noqa: E402

from todo_store import TIME_FORMAT, parse_dt

logger = logging.getLogger("desktop_assistant")


@dataclass
class SyncResult:
    uploaded_todos: int = 0
    downloaded_todos: int = 0
    settings_changed: bool = False
    log_uploaded: bool = False
    message: str = ""


def sync_config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "sync_config.json"
    return Path(__file__).resolve().parent / "sync_config.json"


def load_sync_config(path: Path | str | None = None) -> dict:
    cfg_path = Path(path) if path else sync_config_path()
    if not cfg_path.exists():
        raise FileNotFoundError(f"同步配置文件不存在：{cfg_path}")
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    required = ("host", "port", "username", "password", "remote_dir")
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise ValueError(f"同步配置缺少字段：{', '.join(missing)}")
    return data


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _read_remote_json(sftp, remote_path: str) -> dict | None:
    try:
        with sftp.open(remote_path, "rb") as fh:
            data = json.loads(fh.read().decode("utf-8"))
        return data if isinstance(data, dict) else None
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return None


def _write_local_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _write_remote_json(sftp, remote_path: str, payload: dict) -> None:
    with sftp.open(remote_path, "w") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))


def _sftp_mkdir_p(sftp, remote_dir: str) -> None:
    parts = [part for part in remote_dir.replace("\\", "/").split("/") if part]
    current = ""
    for part in parts:
        current = f"{current}/{part}" if current else part
        try:
            sftp.mkdir(current)
        except IOError:
            pass


def _todo_sort_key(item: dict) -> datetime:
    return parse_dt(item.get("updated_at", "")) or datetime.min


def merge_payloads(local: dict, remote: dict | None) -> tuple[dict, SyncResult]:
    """Merge two todos.json payloads, newest per todo id wins."""
    result = SyncResult()
    local_todos = {
        item["id"]: item
        for item in local.get("todos", [])
        if isinstance(item, dict) and item.get("id")
    }
    remote_todos = {
        item["id"]: item
        for item in (remote or {}).get("todos", [])
        if isinstance(item, dict) and item.get("id")
    }
    merged: dict[str, dict] = {}
    for todo_id, local_item in local_todos.items():
        remote_item = remote_todos.get(todo_id)
        if remote_item is None:
            merged[todo_id] = local_item
            result.uploaded_todos += 1
        elif _todo_sort_key(local_item) >= _todo_sort_key(remote_item):
            merged[todo_id] = local_item
            if _todo_sort_key(local_item) > _todo_sort_key(remote_item):
                result.uploaded_todos += 1
        else:
            merged[todo_id] = remote_item
            result.downloaded_todos += 1
    for todo_id, remote_item in remote_todos.items():
        if todo_id not in merged:
            merged[todo_id] = remote_item
            result.downloaded_todos += 1

    local_settings = dict(local.get("settings") or {})
    remote_settings = dict((remote or {}).get("settings") or {})
    local_ts = parse_dt(local_settings.get("updated_at", ""))
    remote_ts = parse_dt(remote_settings.get("updated_at", ""))
    if remote_ts and (local_ts is None or remote_ts > local_ts):
        merged_settings = {**local_settings, **remote_settings}
        result.settings_changed = True
    else:
        merged_settings = {**remote_settings, **local_settings}
        if remote_ts is None or (local_ts and local_ts > remote_ts):
            result.settings_changed = True

    payload = {
        "version": 1,
        "todos": sorted(merged.values(), key=_todo_sort_key),
        "settings": merged_settings,
    }
    return payload, result


def sync_all(
    config: dict,
    local_data_path: Path | str,
    log_path: Path | str | None = None,
) -> SyncResult:
    """Download, merge, upload todos.json and upload logs over SFTP."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=config["host"],
        port=int(config.get("port", 22)),
        username=config["username"],
        password=config["password"],
        timeout=int(config.get("timeout", 15)),
        look_for_keys=False,
        allow_agent=False,
    )
    try:
        sftp = client.open_sftp()
        try:
            remote_dir = config["remote_dir"].strip("/") or "desk_op_sync"
            _sftp_mkdir_p(sftp, remote_dir)
            remote_path = f"{remote_dir}/todos.json"
            local_payload = _read_json(Path(local_data_path)) or {
                "version": 1,
                "todos": [],
                "settings": {},
            }
            remote_payload = _read_remote_json(sftp, remote_path)
            merged, result = merge_payloads(local_payload, remote_payload)
            _write_local_json(Path(local_data_path), merged)
            _write_remote_json(sftp, remote_path, merged)

            if log_path and Path(log_path).exists():
                remote_log_dir = f"{remote_dir}/logs"
                _sftp_mkdir_p(sftp, remote_log_dir)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                sftp.put(str(log_path), f"{remote_log_dir}/desktop_assistant.log")
                sftp.put(str(log_path), f"{remote_log_dir}/desktop_assistant-{stamp}.log")
                result.log_uploaded = True
            result.message = f"远程目录：{remote_dir}"
            return result
        finally:
            sftp.close()
    finally:
        client.close()
