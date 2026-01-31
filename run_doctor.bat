@echo off
title KPI KINGDOM - SYSTEM STARTER
color 0B

echo ======================================================
echo    DANG KHOI DONG HE THONG GIAM SAT KPI DOCTOR
echo ======================================================

:: 1. Kiem tra Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [LOI] Khong tim thay Python! Vui long cai dat Python.
    pause
    exit
)

:: 2. Xoa sach moi thu dang treo tren cong 8000/9999 truoc khi chay
echo [*] Dang don dep cong ket noi...
taskkill /F /IM python.exe /T >nul 2>&1

:: 3. CHỈ CHẠY DOCTOR (Doctor se tu dong mo Server Game va Web)
echo [*] Dang kich hoat Doctor Monitor...
echo.
echo GHI CHU: 
echo - Khong duoc tat cua so CMD nay.
echo - Moi thong tin ve Server se hien thi tren Dashboard Doctor.
echo.
echo Dang mo Doctor Dashboard tai: http://localhost:9999

:: Mo trinh duyet vao thang trang Doctor de ban quan ly
start http://localhost:9999

:: Chay file doctor
python doctor.py

pause