@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] No se encontro .venv\Scripts\python.exe
  echo Crea el entorno virtual e instala dependencias primero.
  pause
  exit /b 1
)

rem Cierra cualquier proceso previo en el puerto 5009
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":5009 .*LISTENING"') do (
  taskkill /PID %%P /F >nul 2>nul
)

set "DB_MODE=supabase"

echo Iniciando CMMS (SUPABASE) en http://127.0.0.1:5009 ...
echo.
".venv\Scripts\python.exe" app.py

endlocal
