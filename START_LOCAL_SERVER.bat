@echo off
title Manufacturing App Server
cd /d "%~dp0"
echo ========================================================
echo    MANUFACTURING MRP & PRODUCTION APP - LOCAL SERVER
echo ========================================================
echo.
echo Local URL:     http://localhost:8080/app.html
echo Network URL:   http://%COMPUTERNAME%:8080/app.html
echo.
echo Starting web server on port 8080...
start http://localhost:8080/app.html
python -m http.server 8080 --bind 0.0.0.0
pause
