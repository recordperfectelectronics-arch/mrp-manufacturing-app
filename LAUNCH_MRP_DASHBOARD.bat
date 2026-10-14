@echo off
title InvenMRP Dashboard
cd /d "%~dp0"
echo ========================================================
echo   INVENMRP: REAL-TIME MRP, OPEN ORDER & BOM SHORTAGE
echo   Theme: Modern Dark (InvenTree & ERPNext Aesthetic)
echo ========================================================
echo.
echo Local Dashboard:    http://localhost:8080/mrp_dashboard.html
echo Factory Wi-Fi URL:  http://%COMPUTERNAME%:8080/mrp_dashboard.html
echo.
echo Starting InvenMRP Web Server on Port 8080...
start http://localhost:8080/mrp_dashboard.html
python -m http.server 8080 --bind 0.0.0.0
pause
