@echo off
setlocal
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE=%AMVISION_PYTHON_EXECUTABLE%"
if not defined PYTHON_EXE set "PYTHON_EXE=%SCRIPT_DIR%..\..\python\python.exe"
if not exist "%PYTHON_EXE%" (
  echo [ERROR] bundled Python not found: "%PYTHON_EXE%" 1>&2
  exit /b 2
)
"%PYTHON_EXE%" "%SCRIPT_DIR%start_backend_service.py" %*
set "EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %EXIT_CODE%
