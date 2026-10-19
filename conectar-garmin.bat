@echo off
rem Primer login en Garmin Connect. Solo hace falta UNA vez (el token dura ~1 anio).
rem Se escribe el correo y la contrasenia aqui, en esta ventana: no se guardan en ningun sitio.
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo No encuentro el entorno de Python del proyecto en .venv\Scripts\python.exe
  echo Ejecuta este fichero desde la carpeta del proyecto Entrenador.
  echo.
  pause
  exit /b 1
)

.venv\Scripts\python.exe scripts\garmin_conectar.py login

echo.
echo (Si ha ido bien, ya puedes cerrar esta ventana.)
pause
