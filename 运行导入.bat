@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo 首次使用，正在准备运行环境...
    where uv >nul 2>nul
    if %errorlevel%==0 (
        uv venv .venv
        uv pip install -q --python ".venv\Scripts\python.exe" -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    ) else (
        python -m venv .venv
        ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    )
)

echo 把 data 目录下的 Excel / CSV 转成看板标准格式...
".venv\Scripts\python.exe" import_data.py
echo.
pause
