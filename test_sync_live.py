"""Live SFTP sync test against the configured server (uses a throwaway remote dir)."""

import json
import tempfile
from pathlib import Path

import paramiko

from sync_service import load_sync_config, sync_all


def main() -> None:
    config = load_sync_config()
    config["remote_dir"] = "desk_op_sync_test"
    data = Path(tempfile.gettempdir()) / "desk_op_sync_live.json"
    log = Path(tempfile.gettempdir()) / "desk_op_sync_live.log"
    if data.exists():
        data.unlink()
    payload = {
        "version": 1,
        "todos": [
            {
                "id": "live-test",
                "title": "同步测试",
                "due": "2026-08-05 10:00",
                "updated_at": "2026-08-04 12:00",
            }
        ],
        "settings": {"voice_enabled": True, "updated_at": "2026-08-04 12:00"},
    }
    data.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    log.write_text("sync live test log\n", encoding="utf-8")

    result = sync_all(config, data, log)
    assert result.log_uploaded

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
            with sftp.open("desk_op_sync_test/todos.json", "rb") as fh:
                remote = json.loads(fh.read().decode("utf-8"))
            assert any(t["id"] == "live-test" for t in remote["todos"])
            sftp.remove("desk_op_sync_test/todos.json")
            for name in sftp.listdir("desk_op_sync_test/logs"):
                sftp.remove(f"desk_op_sync_test/logs/{name}")
            sftp.rmdir("desk_op_sync_test/logs")
            sftp.rmdir("desk_op_sync_test")
        finally:
            sftp.close()
    finally:
        client.close()

    if data.exists():
        data.unlink()
    print("live server sync test OK")


if __name__ == "__main__":
    main()
