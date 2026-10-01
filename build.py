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
    excludes = [
        "numpy",
        "scipy",
        "mkl",
        "setuptools._distutils.compat.numpy",
        "PySide6.QtNetwork",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.QtQuickControls2",
        "PySide6.QtQuickTest",
        "PySide6.QtQuickWidgets",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtOpenGL",
        "PySide6.QtOpenGLWidgets",
        "PySide6.QtPrintSupport",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtConcurrent",
        "PySide6.QtDBus",
        "PySide6.QtDesigner",
        "PySide6.QtXml",
        "PySide6.QtHelp",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtPositioning",
        "PySide6.QtLocation",
        "PySide6.QtNetworkAuth",
        "PySide6.QtNfc",
        "PySide6.QtRemoteObjects",
        "PySide6.QtScxml",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtSerialBus",
        "PySide6.QtStateMachine",
        "PySide6.QtTextToSpeech",
        "PySide6.QtCharts",
        "PySide6.QtSpatialAudio",
        "PySide6.QtSvg",
        "PySide6.QtSvgWidgets",
        "PySide6.QtDataVisualization",
        "PySide6.QtGraphs",
        "PySide6.QtGraphsWidgets",
        "PySide6.QtBluetooth",
        "PySide6.QtUiTools",
        "PySide6.QtAxContainer",
        "PySide6.QtWebChannel",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtWebSockets",
        "PySide6.QtHttpServer",
        "PySide6.QtWebView",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DExtras",
    ]
    for name in excludes:
        cmd += ["--exclude-module", name]
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
