@echo off
cd /d "%~dp0"
python -m venv venv 2>/dev/null
call venv\Scripts\activate.bat
pip install -r requirements.txt -q 2>/dev/null
python src\ui\dual_app.py
pause
