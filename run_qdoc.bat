@echo off
cd /d %~dp0
python -m pip install -r requirements.txt
python check_db.py
python app.py
pause
