@echo off
cd /d "%~dp0server"
echo Starting Audit_bot server on http://127.0.0.1:8000
echo   Field app:   http://127.0.0.1:8000/app/
echo   Admin panel: http://127.0.0.1:8000/admin/
start "" http://127.0.0.1:8000/admin/
..\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
