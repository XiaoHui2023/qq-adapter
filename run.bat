@echo off
cd /d %~dp0

if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
    pip install -e .\packages\protocol
) else (
    call .venv\Scripts\activate.bat
)

python src --config config.yaml
pause
