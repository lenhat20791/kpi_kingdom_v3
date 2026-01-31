@echo off
title KPI Kingdom V3 - Hệ thống Quản trị
cls

echo ======================================================
echo    DANG KHOI DONG VUONG QUOC KPI KINGDOM V3...
echo ======================================================

:: 1. Di chuyen vao thu muc backend
cd /d %~dp0backend

:: 2. Mo trang Admin tren trinh duyet (cho 3 giay de server kip load)
echo [*] Dang mo trinh duyet...
start "" "http://127.0.0.1:8000/player_dashboard"

:: 3. Chay Server FastAPI
echo [*] Dang khoi chay Server tai cong 8000...
echo [!] Nhan Ctrl+C de dung he thong.
echo ------------------------------------------------------

:: Neu ban co dung moi truong ao (venv), hay bo dau :: o dong duoi day:
:: call venv\Scripts\activate

python main.py

pause