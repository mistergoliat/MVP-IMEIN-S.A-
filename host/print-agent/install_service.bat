@echo off
set NSSM_PATH=%~dp0nssm.exe
if not exist "%NSSM_PATH%" (
  echo NSSM no encontrado en %NSSM_PATH%
  exit /b 1
)
%NSSM_PATH% install PickingPrintAgent "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\python.exe" "%~dp0agent.py"
%NSSM_PATH% set PickingPrintAgent AppDirectory "%~dp0"
%NSSM_PATH% set PickingPrintAgent DisplayName "Picking Print Agent"
%NSSM_PATH% set PickingPrintAgent Description "Agente de impresión Zebra ZD888t"
%NSSM_PATH% start PickingPrintAgent
