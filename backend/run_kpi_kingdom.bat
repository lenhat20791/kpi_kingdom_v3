@echo off
TITLE KPI Kingdom Server
COLOR 0A

:: Di chuyển đến thư mục chứa file bat này (để đảm bảo đúng đường dẫn)
cd /d "%~dp0"

ECHO ==========================================
ECHO      DANG KHOI DONG SERVER KPI KINGDOM
ECHO ==========================================
ECHO.

:: Chạy server
python main.py

:: Giữ màn hình không bị tắt nếu server crash
ECHO.
ECHO Server da dung hoac gap loi.
pause