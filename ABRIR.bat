@echo off
REM ============================================================
REM  AI News Engine - lanzador de un clic
REM  Doble clic en este archivo abre todo.
REM ============================================================
title AI News Engine
cd /d "%~dp0"

echo.
echo  [1/4] Arrancando Docker Desktop si hace falta...
docker info >nul 2>&1
if errorlevel 1 (
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    echo        Esperando al motor de Docker...
    :waitdocker
    timeout /t 4 /nobreak >nul
    docker info >nul 2>&1
    if errorlevel 1 goto waitdocker
)
echo        Docker listo.

echo.
echo  [2/4] Levantando el stack (base de datos + API)...
docker compose up -d

echo.
echo  [3/4] Esperando a que la API responda...
:waitapi
timeout /t 2 /nobreak >nul
curl -s -o nul -w "%%{http_code}" http://localhost:8000/health 2>nul | findstr "200" >nul
if errorlevel 1 goto waitapi
echo        API arriba.

echo.
echo  [4/4] Abriendo el visor en el navegador...
start "" "http://localhost:8000/viewer"

echo.
echo  Listo. El visor esta en:  http://localhost:8000/viewer
echo  Puedes cerrar esta ventana.
echo.
timeout /t 6 /nobreak >nul
