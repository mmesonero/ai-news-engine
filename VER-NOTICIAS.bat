@echo off
REM ============================================================
REM  Ver las noticias REALES de la nube (Neon) en el navegador.
REM  Doble clic. Solo lectura — no ejecuta el pipeline.
REM
REM  Requiere una vez: copiar .env.cloud.example -> .env.cloud
REM  y pegar tus URLs de Neon.
REM ============================================================
title Ver Noticias IA (cloud)
cd /d "%~dp0"

if not exist ".env.cloud" (
    echo.
    echo  FALTA el archivo .env.cloud
    echo  Copia .env.cloud.example a .env.cloud y pega tus URLs de Neon.
    echo.
    pause
    exit /b 1
)

echo  [1/3] Arrancando Docker si hace falta...
docker info >nul 2>&1
if errorlevel 1 (
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    :waitdocker
    timeout /t 4 /nobreak >nul
    docker info >nul 2>&1
    if errorlevel 1 goto waitdocker
)

echo  [2/3] Levantando el visor (conecta a la nube)...
docker compose -f docker-compose.viewer.yml up -d --build

echo  [3/3] Esperando a que responda...
:waitapi
timeout /t 2 /nobreak >nul
curl -s -o nul -w "%%{http_code}" http://localhost:8001/health 2>nul | findstr "200" >nul
if errorlevel 1 goto waitapi

start "" "http://localhost:8001/viewer"
echo.
echo  Listo. Noticias de la nube en:  http://localhost:8001/viewer
echo  Para apagarlo:  docker compose -f docker-compose.viewer.yml down
echo.
timeout /t 6 /nobreak >nul
