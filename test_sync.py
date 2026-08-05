"""Offline tests for server-relay sync merge logic."""

from sync_service import load_sync_config, merge_payloads


def main() -> None:
    local = {
        "version": 1,
        "todos": [
            {"id": "a", "title": "本地新", "updated_at": "2026-08-04 12:00"}
        ],
        "settings": {"daily_reminder_time": "08:00", "updated_at": "2026-08-04 12:00"},
    }
    remote = {
        "version": 1,
        "todos": [
            {"id": "a", "title": "远程旧", "updated_at": "2026-08-04 11:00"}
        ],
        "settings": {"daily_reminder_time": "20:00", "updated_at": "2026-08-04 11:00"},
    }
    merged, result = merge_payloads(local, remote)
    assert merged["todos"][0]["title"] == "本地新"
    assert merged["settings"]["daily_reminder_time"] == "08:00"
    assert result.uploaded_todos == 1

    local2 = {"version": 1, "todos": [], "settings": {}}
    remote2 = {
        "version": 1,
        "todos": [
            {"id": "b", "title": "远程新", "updated_at": "2026-08-04 12:30"}
        ],
        "settings": {"voice_enabled": False, "updated_at": "2026-08-04 12:30"},
    }
    merged2, result2 = merge_payloads(local2, remote2)
    assert len(merged2["todos"]) == 1
    assert result2.downloaded_todos == 1
    assert merged2["settings"]["voice_enabled"] is False

    config = load_sync_config()
    assert config["host"] == "47.101.138.199"
    assert config["username"] == "root"
    print("sync merge test OK")


if __name__ == "__main__":
    main()
