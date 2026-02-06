import sqlite3
import os

def update_database_full():
    # 1. Xác định đường dẫn file DB
    current_db_path = "../data/game.db" # Mặc định cho VPS
    
    # Kiểm tra các trường hợp đường dẫn khác (Local Windows)
    if not os.path.exists(current_db_path):
        if os.path.exists("data/game.db"):
            current_db_path = "data/game.db"
        elif os.path.exists("database.db"):
            current_db_path = "database.db"
        
    print(f"🔌 Đang kết nối vào: {current_db_path}")
    
    try:
        conn = sqlite3.connect(current_db_path)
        cursor = conn.cursor()

        # --- 1. Bảng Notification (Thông báo) ---
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS notification (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT,
            content TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        );
        """)
        print("✅ Đã kiểm tra bảng: Notification")

        # --- 2. Bảng ChatLog (Lịch sử chat) ---
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS chatlog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER,
            player_name TEXT,
            role TEXT,
            content TEXT,
            created_at TEXT
        );
        """)
        print("✅ Đã kiểm tra bảng: ChatLog")

        # --- 3. Bảng ChatWarningLog (Nhật ký vi phạm) ---
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS chatwarninglog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER,
            player_name TEXT,
            content TEXT,
            created_at TEXT
        );
        """)
        print("✅ Đã kiểm tra bảng: ChatWarningLog")

        # --- 4. Bảng ChatBan (Danh sách cấm) ---
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS chatban (
            player_id INTEGER PRIMARY KEY,
            player_name TEXT,
            banned_until TEXT,
            reason TEXT
        );
        """)
        print("✅ Đã kiểm tra bảng: ChatBan")

        # --- 5. Bảng ChatKeyword (Từ khóa cấm) ---
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS chatkeyword (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT
        );
        """)
        print("✅ Đã kiểm tra bảng: ChatKeyword")

        # Tạo thêm các Index để tăng tốc độ truy vấn
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_time ON chatlog (created_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_warning_time ON chatwarninglog (created_at);")
        except:
            pass

        conn.commit()
        conn.close()
        print("\n🚀 TẤT CẢ CÁC BẢNG ĐÃ ĐƯỢC CẬP NHẬT THÀNH CÔNG!")
        
    except Exception as e:
        print(f"❌ Lỗi trong quá trình cập nhật: {e}")

if __name__ == "__main__":
    update_database_full()