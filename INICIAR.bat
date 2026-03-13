@echo off
chcp 65001 >nul 2>&1
title Auditor Portatil - Faturamento
echo.
echo ============================================
echo    AUDITOR PORTATIL - GERACAO DE FATURAMENTO
echo ============================================
echo.

REM Check Python
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Python nao encontrado!
    echo Por favor, instale o Python 3.10+ em https://python.org
    echo Marque "Add Python to PATH" durante a instalacao.
    pause
    exit /b 1
)

REM Navigate to script directory
cd /d "%~dp0"

REM Create venv if not exists
if not exist "venv" (
    echo [INFO] Criando ambiente virtual...
    python -m venv venv
)

REM Activate venv
call venv\Scripts\activate.bat

REM Install dependencies if needed
if not exist "venv\.deps_installed" (
    echo [INFO] Instalando dependencias...
    pip install fastapi uvicorn pdfplumber pydantic python-multipart >nul 2>&1
    echo ok > venv\.deps_installed
)

echo.
echo [OK] Iniciando servidor em http://127.0.0.1:8123
echo [OK] O navegador abrira automaticamente.
echo [OK] Para encerrar, feche esta janela.
echo.

REM Run the server
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8123

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERRO] O servidor parou inesperadamente.
    echo Verifique se ja existe uma instancia do App aberta ou se a porta 8123 esta ocupada.
    pause
)
