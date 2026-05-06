@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE=%AMVISION_PYTHON_EXECUTABLE%"
if defined PYTHON_EXE goto run
if exist "%SCRIPT_DIR%python\python.exe" set "PYTHON_EXE=%SCRIPT_DIR%python\python.exe"
if defined PYTHON_EXE goto run
set "PYTHON_EXE=python"
:run
"%PYTHON_EXE%" "%SCRIPT_DIR%stop_amvision_full.py" %*
endlocal