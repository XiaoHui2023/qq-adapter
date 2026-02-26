@echo off
cd /d %~dp0

if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat
git pull
pip install --upgrade -r requirements.txt
pause