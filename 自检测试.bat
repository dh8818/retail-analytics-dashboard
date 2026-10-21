@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ============================================
echo  跑一遍自检，确认所有公式没算错
echo ============================================
echo.
.venv\Scripts\python.exe test_checks.py
echo.
pause
