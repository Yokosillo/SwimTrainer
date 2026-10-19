@echo off
rem Levanta el servidor del Entrenador: sirve el cuadro de mando y recibe los partes que subas del portal.
rem Deja esta ventana abierta mientras rellenas partes; para pararlo, cierrala o pulsa Ctrl+C.
cd /d "%~dp0"
echo.
echo   Entrenador: cuadro de mando y "Subir" del portal.
echo   Deja esta ventana abierta. Se para cerrandola o con Ctrl+C.
echo.
".venv\Scripts\python.exe" -m entrenador.cli servir --abrir
if errorlevel 1 (
  echo.
  echo   Algo ha fallado. Si dice que el puerto esta ocupado, cierra la otra ventana
  echo   del entrenador y vuelve a probar.
  echo.
  pause
)
