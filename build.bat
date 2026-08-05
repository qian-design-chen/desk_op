@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY="
if exist "C:\ProgramData\anaconda3\python.exe" (
    set "PY=C:\ProgramData\anaconda3\python.exe"
) else (
    where python >nul 2>nul
    if not errorlevel 1 (
        set "PY=python"
    ) else (
        where py >nul 2>nul
        if not errorlevel 1 (
            set "PY=py -3"
        )
    )
)
if not defined PY (
    echo [错误] 未找到 Python，请先安装 Python 3.10 或更高版本并加入 PATH。
    pause
    exit /b 1
)

%PY% -m pip install -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络。
    pause
    exit /b 1
)

%PY% build.py
if errorlevel 1 (
    echo [错误] 打包失败。
    pause
    exit /b 1
)

echo.
echo 打包完成：dist\桌面办公助手.exe
pause
