@echo off
rem Executa o app trafo3d (janela desktop Flet)
cd /d "%~dp0"
.venv\Scripts\python.exe -m src.trafo3d.app
