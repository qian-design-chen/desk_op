"""Build the desktop assistant into a standalone exe with PyInstaller."""

from __future__ import annotations

import site
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "桌面办公助手"


def main() -> None:
    root = Path(__file__).resolve().parent
    script = root / "desktop_assistant.py"
    dist = root / "dist"
    work = root / "build"
    icon_script = root / "make_icon.py"
    icon = root / "app.ico"
    icon_result = subprocess.run([sys.executable, str(icon_script)])
    if icon_result.returncode != 0:
        raise SystemExit("Icon generation failed.")
    if not icon.exists():
        raise SystemExit("Icon file was not created.")

    cmd = [
        sys.executable,
        "-S",
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        APP_NAME,
        "--distpath",
        str(dist),
        "--workpath",
        str(work),
        "--specpath",
        str(root),
        "--icon",
        str(icon),
    ]
    user_site = Path(site.getusersitepackages())
    cmd += ["--paths", str(user_site)]
    base_site = Path(sys.prefix) / "Lib" / "site-packages"
    if base_site.is_dir():
        cmd += ["--paths", str(base_site)]
    cmd += ["--collect-all", "sounddevice", "--collect-submodules", "pynput"]
    cmd.append(str(script))
    print(" ".join(cmd))
    env = dict(os.environ)
    env["PYTHONPATH"] = str(user_site)
    lib_bin = Path(sys.prefix) / "Library" / "bin"
    if lib_bin.is_dir():
        env["PATH"] = str(lib_bin) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(cmd, env=env)
    if result.returncode != 0:
        raise SystemExit(f"PyInstaller failed with exit code {result.returncode}")

    exe = dist / (APP_NAME + ".exe")
    if not exe.exists():
        raise SystemExit("Build finished but the exe was not created.")
    config_src = root / "sync_config.json"
    if config_src.exists():
        shutil.copy2(config_src, dist / config_src.name)
        print(f"sync config copied: {dist / config_src.name}")
    asr_config_src = root / "asr_config.json"
    if asr_config_src.exists():
        shutil.copy2(asr_config_src, dist / asr_config_src.name)
        print(f"asr config copied: {dist / asr_config_src.name}")
    print(f"\nBuild OK: {exe}")


if __name__ == "__main__":
    main()
