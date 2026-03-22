@echo off
setlocal

echo Buscando proceso en puerto 5009...
set "FOUND=0"

for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":5009 .*LISTENING"') do (
  set "FOUND=1"
  echo Deteniendo PID %%P ...
  taskkill /PID %%P /F >nul 2>nul
)

if "%FOUND%"=="0" (
  echo No habia servidor CMMS ejecutandose en el puerto 5009.
) else (
  echo Servidor CMMS detenido.
)

echo.
pause
endlocal
