@echo off
cd /d %~dp0
git pull
pip install -r requirements.txt
pause