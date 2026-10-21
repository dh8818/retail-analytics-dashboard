@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  便利店经营分析看板 - 一键运行
echo ============================================

where uv >nul 2>nul
if %errorlevel%==0 (
    echo [1/4] 准备运行环境...
    if not exist ".venv\Scripts\python.exe" uv venv .venv
    uv pip install -q --python ".venv\Scripts\python.exe" -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
) else (
    echo [1/3] 用 python venv 准备运行环境...
    if not exist ".venv\Scripts\python.exe" python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)

if not exist "data\pos.csv" (
    echo [2/4] 没有检测到 data\pos.csv，生成模拟数据...
    ".venv\Scripts\python.exe" gen_data.py
) else (
    echo [2/4] 检测到 data\pos.csv，使用真实数据
)

dir /b "data\*.xlsx" >nul 2>nul
if not errorlevel 1 (
    echo [2.5/4] 发现 data 目录下的 Excel，自动导入...
    ".venv\Scripts\python.exe" import_data.py
    if errorlevel 1 (
        echo 导入失败，请看上面的提示（通常是列名对不上）。
        pause
        exit /b 1
    )
)

echo [3/4] 生成看板...
".venv\Scripts\python.exe" build.py
if %errorlevel% neq 0 (
    echo 生成失败，请把上面的报错发给我。
    pause
    exit /b 1
)
start "" "output\便利店经营看板.html"
echo 完成！看板已在浏览器打开。
pause
