@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ============================================
echo  提交改动并推送到 GitHub
echo  （推送后 Streamlit 会自动重新部署）
echo ============================================
echo.
.venv\Scripts\python.exe push_update.py %*
echo.
pause
