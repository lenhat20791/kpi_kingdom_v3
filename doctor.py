import os
import sys
import time
import subprocess
import threading
import signal
import re
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import platform

# --- CẤU HÌNH ---
GAME_PORT = 8000     # Cổng game
DOCTOR_PORT = 9999   # Cổng bác sĩ
MAX_LOG_LINES = 100  # Lưu log nhiều hơn chút để dễ soi

# Lệnh chạy server (Tự động tìm đường dẫn python chuẩn)
GAME_SERVER_CMD = [
    sys.executable, "-u", "backend/main.py" 
]
# Lưu ý: Nếu bạn muốn chạy uvicorn trực tiếp thì đổi thành:
# [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"]

# --- BỘ NHỚ TẠM (RAM) ---
server_process = None
console_logs = []
system_status = "STOPPED"

# =========================================================
# 1. CHỨC NĂNG "DIỆT TẬN GỐC" (HARD KILL) - MỚI 🔪
# =========================================================
def kill_process_on_port(port):
    """Tìm và diệt bất kỳ tiến trình nào đang chiếm cổng quy định"""
    print(f"🔍 Đang quét cổng {port} để tìm tiến trình ẩn...")
    
    try:
        if platform.system() == "Windows":
            # 1. Tìm PID đang chiếm cổng
            # Lệnh: netstat -ano | findstr :8000
            result = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True).decode()
            
            lines = result.strip().split('\n')
            killed_pids = set()

            for line in lines:
                if "LISTENING" in line:
                    # Parse lấy PID (cột cuối cùng)
                    parts = re.split(r'\s+', line.strip())
                    pid = parts[-1]
                    
                    if pid and pid != "0" and pid not in killed_pids:
                        print(f"🔪 PHÁT HIỆN GHOST PROCESS (PID: {pid}) -> TIÊU DIỆT NGAY!")
                        subprocess.run(f"taskkill /F /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        killed_pids.add(pid)
            
            if not killed_pids:
                print(f"✅ Cổng {port} sạch sẽ, không có ma!")
        else:
            # Linux/Mac (Dùng lsof hoặc fuser)
            os.system(f"fuser -k {port}/tcp")
            
    except Exception as e:
        # Nếu lỗi (thường là do không tìm thấy process nào) thì bỏ qua
        pass
    
    # Chờ 1 giây để Window kịp nhả cổng
    time.sleep(1)

# =========================================================
# 2. QUẢN LÝ SERVER GAME
# =========================================================
def log_reader(proc):
    """Đọc log từ server game và lưu vào biến tạm"""
    global console_logs
    try:
        for line in iter(proc.stdout.readline, ''):
            if line:
                decoded_line = line.strip()
                print(f"[GAME] {decoded_line}") # In ra cmd chính
                console_logs.append(decoded_line)
                if len(console_logs) > MAX_LOG_LINES:
                    console_logs.pop(0)
    except Exception as e:
        pass

def run_game_server():
    global server_process, system_status
    
    # BƯỚC 1: DỌN DẸP SẠCH SẼ TRƯỚC KHI CHẠY
    kill_process_on_port(GAME_PORT)
    
    print("🚀 Đang khởi động Server Game mới...")
    system_status = "RUNNING"
    
    try:
        # Chạy process mới
        server_process = subprocess.Popen(
            GAME_SERVER_CMD,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        )
        
        # Tạo luồng đọc log riêng
        t = threading.Thread(target=log_reader, args=(server_process,), daemon=True)
        t.start()
        
        server_process.wait()
        
        # Khi server tắt
        if system_status == "RUNNING":
            system_status = "STOPPED"
            print("⚠️ Server Game đã dừng đột ngột!")
            
    except Exception as e:
        print(f"❌ Lỗi không thể chạy server: {e}")
        system_status = "ERROR"

def restart_server():
    global server_process, system_status, console_logs
    print("\n🔄 YÊU CẦU KHỞI ĐỘNG LẠI TỪ BÁC SĨ...")
    system_status = "RESTARTING"
    
    # Gửi tín hiệu dừng cho thread cũ (nếu còn)
    if server_process:
        try:
            server_process.terminate()
        except:
            pass
            
    # Xóa log cũ cho sạch mắt
    console_logs = ["--- ĐÃ RESET SERVER & CẬP NHẬT CODE MỚI ---"]
    
    # Chạy lại luồng mới (Hàm run_game_server sẽ tự gọi kill_port)
    t = threading.Thread(target=run_game_server, daemon=True)
    t.start()


# =========================================================
# 3. GIAO DIỆN WEB DOCTOR (CONTROL CENTER) - COPY LOGS
# =========================================================
class DoctorHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        
        # Xử lý lệnh Restart
        if parsed.path == "/restart":
            restart_server()
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<h1>Dang khoi dong lai... Vui long doi...</h1><script>setTimeout(function(){window.location.href='/';}, 3000);</script>")
            return

        # Render Giao diện
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        
        # 1. Trạng thái hệ thống
        status_color = "green" if system_status == "RUNNING" else "red"
        status_text = "ĐANG CHẠY" if system_status == "RUNNING" else "ĐÃ DỪNG"
        if system_status == "RESTARTING": 
            status_color = "orange"
            status_text = "ĐANG KHỞI ĐỘNG..."

        from datetime import datetime
        server_time = datetime.now().strftime("%H:%M:%S")
        
        # 2. Quét Code
        scan_result = scan_code_issues()

        # 3. Xử lý Log (Tô màu cho đẹp)
        formatted_logs = []
        raw_logs_text = "" # Biến này lưu text thuần để copy
        
        for line in console_logs:
            raw_logs_text += line + "\\n" # Cộng dồn text để script JS đọc
            
            color = "#4ade80" # Xanh lá
            if "ERROR" in line or "Exception" in line or "Traceback" in line: color = "#f87171" # Đỏ
            elif "WARNING" in line: color = "#fbbf24" # Vàng
            elif "GET /" in line or "POST /" in line: color = "#60a5fa" # Xanh dương
            
            formatted_logs.append(f"<div style='border-bottom:1px solid #333; padding:2px; color:{color};'>{line}</div>")
        
        logs_html = "<br>".join(formatted_logs)

        # HTML GIAO DIỆN
        html = f"""
        <html>
        <head>
            <title>KPI KINGDOM CONTROL CENTER</title>
            <meta http-equiv="refresh" content="5">
            <style>
                body {{ background: #0f172a; color: #e2e8f0; font-family: 'Segoe UI', Consolas, sans-serif; padding: 20px; font-size: 14px; margin: 0; }}
                .header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding-bottom: 20px; border-bottom: 2px solid #334155; }}
                .card {{ background: #1e293b; padding: 15px; border-radius: 10px; margin-bottom: 20px; border: 1px solid #334155; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.5); }}
                .btn {{ padding: 12px 20px; text-decoration: none; border-radius: 8px; font-weight: bold; display: inline-flex; align-items: center; gap: 8px; transition: 0.2s; border: none; cursor: pointer; color: white; }}
                .btn:hover {{ transform: translateY(-2px); filter: brightness(110%); }}
                .btn-restart {{ background: #dc2626; box-shadow: 0 4px 6px -1px rgba(220, 38, 38, 0.5); }}
                .btn-admin {{ background: #d97706; box-shadow: 0 4px 6px -1px rgba(217, 119, 6, 0.5); }}
                .btn-player {{ background: #2563eb; box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.5); }}
                .btn-copy {{ background: #475569; font-size: 12px; padding: 6px 12px; }}
                
                .log-box {{ background: #0f172a; padding: 10px; height: 400px; overflow-y: scroll; border: 1px solid #334155; font-family: 'Consolas', monospace; font-size: 12px; white-space: pre-wrap; border-radius: 6px; }}
                .status-badge {{ background: {status_color}; color: white; padding: 4px 10px; border-radius: 20px; font-weight: bold; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }}
                .grid {{ display: grid; grid-template-columns: 2fr 1fr; gap: 20px; }}
                ::-webkit-scrollbar {{ width: 8px; }}
                ::-webkit-scrollbar-track {{ background: #0f172a; }}
                ::-webkit-scrollbar-thumb {{ background: #475569; border-radius: 4px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <div>
                    <h1 style="margin:0; font-size: 24px;">🚀 TRUNG TÂM ĐIỀU KHIỂN (DOCTOR V3)</h1>
                    <div style="margin-top: 10px; display: flex; gap: 15px; align-items: center;">
                        <span>Trạng thái: <span class="status-badge">{status_text}</span></span>
                        <span>⏱️ Giờ Server: <b style="color:#fbbf24">{server_time}</b></span>
                        <span>🔌 Cổng Game: <b>{GAME_PORT}</b></span>
                    </div>
                </div>
                <div style="display: flex; gap: 10px;">
                    <a href="http://localhost:{GAME_PORT}/admin.html" target="_blank" class="btn btn-admin">
                        👑 MỞ ADMIN
                    </a>

                    <a href="http://localhost:{GAME_PORT}/player_dashboard.html" target="_blank" class="btn btn-player">
                        ⚔️ MỞ PLAYER
                    </a>
                    <a href="/restart" class="btn btn-restart">🔥 HARD RESET SERVER</a>
                </div>
            </div>

            <div class="grid">
                <div class="card">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                        <h3 style="margin:0; color:#94a3b8">🖥️ LIVE LOGS (ADMIN & PLAYER)</h3>
                        <button onclick="copyLogs()" class="btn btn-copy">📋 COPY LOGS</button>
                    </div>
                    <div class="log-box" id="logbox">{logs_html}</div>
                </div>
                <div class="card">
                    <h3 style="margin-top:0; color:#94a3b8">👮 CODE POLICE (SCANNER)</h3>
                    <div style="height: 400px; overflow-y: auto;">{scan_result}</div>
                </div>
            </div>

            <script>
                // 1. Auto Scroll
                var logBox = document.getElementById("logbox");
                logBox.scrollTop = logBox.scrollHeight;

                // 2. Hàm Copy Logs
                function copyLogs() {{
                    var logText = document.getElementById("logbox").innerText;
                    navigator.clipboard.writeText(logText).then(function() {{
                        // Hiệu ứng thông báo nhỏ
                        var btn = document.querySelector('.btn-copy');
                        var originalText = btn.innerText;
                        btn.innerText = "✅ ĐÃ COPY!";
                        btn.style.background = "#22c55e";
                        setTimeout(function() {{
                            btn.innerText = originalText;
                            btn.style.background = "#475569";
                        }}, 2000);
                    }}, function(err) {{
                        alert("❌ Lỗi copy: " + err);
                    }});
                }}
            </script>
        </body>
        </html>
        """
        self.wfile.write(html.encode('utf-8'))

# =========================================================
# 4. CHẠY CHƯƠNG TRÌNH
# =========================================================
def start_doctor():
    # 1. Chạy server game lần đầu
    t_game = threading.Thread(target=run_game_server, daemon=True)
    t_game.start()
    
    # 2. Chạy server Doctor
    try:
        server = HTTPServer(('0.0.0.0', DOCTOR_PORT), DoctorHandler)
        print(f"\n==================================================")
        print(f"🚑 BÁC SĨ ĐANG TRỰC TẠI: http://localhost:{DOCTOR_PORT}")
        print(f"🎮 SERVER GAME CHẠY TẠI: http://localhost:{GAME_PORT}")
        print(f"==================================================\n")
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐang tắt hệ thống...")
        kill_process_on_port(GAME_PORT)

# =========================================================
# 5. MODULE CẢNH SÁT CODE (LINTER) - MỚI
# =========================================================
def scan_code_issues():
    """Quét các file giao diện để tìm lỗi sai tên biến phổ biến"""
    warnings = []
    
    # Danh sách các file cần soi (Bạn có thể thêm file khác vào đây)
    target_files = ["player_dashboard.html", "frontend/player_dashboard.html"]
    
    # Luật bắt lỗi: "Từ khóa nghi vấn": "Lời khuyên"
    rules = {
        "max_hp": "⚠️ Nghi vấn: Backend trả về 'hp_max', nhưng JS đang dùng 'max_hp'?",
        "fullname": "⚠️ Nghi vấn: Backend trả về 'full_name', nhưng JS đang dùng 'fullname'?",
        "user_name": "⚠️ Nghi vấn: Backend trả về 'username', nhưng JS đang dùng 'user_name'?",
        "current_hp": "⚠️ Lưu ý: DB dùng 'hp', JS dùng 'current_hp'. Hãy chắc chắn bạn đã map dữ liệu đúng.",
        "location.reload": "🚫 Cảnh báo: Hạn chế dùng 'location.reload()' để tránh reset biến game."
    }

    found_files = False
    for filepath in target_files:
        if os.path.exists(filepath):
            found_files = True
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    for i, line in enumerate(lines):
                        for bad_term, msg in rules.items():
                            # Nếu tìm thấy từ khóa xấu (mà không phải dòng comment)
                            if bad_term in line and "//" not in line:
                                # Cắt ngắn dòng code để hiển thị cho gọn
                                code_snippet = line.strip()[:60] + "..."
                                warnings.append(f"""
                                    <div style='color: #fbbf24; border-bottom: 1px dashed #444; padding: 5px;'>
                                        <b>[{os.path.basename(filepath)} : Dòng {i+1}]</b> <span style='color:#f87171'>"{bad_term}"</span><br>
                                        <i style='font-size: 0.9em; color: #9ca3af;'>➥ {msg}</i><br>
                                        <code style='font-size: 0.8em; color: #6ee7b7; background: #222; padding: 2px;'>{code_snippet}</code>
                                    </div>
                                """)
            except Exception as e:
                warnings.append(f"<div style='color:red'>Lỗi đọc file {filepath}: {e}</div>")
    
    if not found_files:
        return "<div style='color:gray'><i>Không tìm thấy file player_dashboard.html để quét.</i></div>"
        
    if not warnings:
        return "<div style='color:#4ade80'>✅ Tuyệt vời! Không phát hiện tên biến nào đáng ngờ.</div>"
    
    return "".join(warnings)

if __name__ == "__main__":
    start_doctor()