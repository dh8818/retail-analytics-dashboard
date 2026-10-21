@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo 首次使用，正在准备运行环境（约 1-2 分钟）...
    where uv >nul 2>nul
    if %errorlevel%==0 (
        uv venv .venv
        uv pip install -q --python ".venv\Scripts\python.exe" -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    ) else (
        python -m venv .venv
        ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    )
)

echo 正在启动网页版分析工具...
echo 浏览器地址： http://localhost:8501
echo 关闭这个窗口就会停止服务。
start "" http://localhost:8501
".venv\Scripts\python.exe" run_streamlit.py
pause
