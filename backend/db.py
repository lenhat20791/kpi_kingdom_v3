import sqlite3
import os

TABLE_NAME = "question" 

# ==========================================
# 🌟 CẬP NHẬT ĐƯỜNG DẪN CHUẨN XÁC 🌟
# ==========================================
# Lấy vị trí của chính file script này (thư mục backend)
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# Lùi ra 1 cấp (..), chui vào thư mục 'data', và tìm 'game.db'
DB_FILE = os.path.join(CURRENT_DIR, "..", "data", "game.db")

def upgrade_database():
    print(f"🔍 Đang tìm kiếm Database tại: {DB_FILE}")
    
    if not os.path.exists(DB_FILE):
        print(f"❌ Không tìm thấy file game.db tại đường dẫn trên!")
        print("💡 Ngài hãy kiểm tra lại xem tên thư mục có đúng là 'data' viết thường không nhé.")
        return

    # Kết nối tới Database
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        print(f"🔄 Đang tiến hành giải phẫu bảng '{TABLE_NAME}'...")

        # 1. Đổi tên bảng cũ thành bảng tạm (backup)
        backup_table = f"{TABLE_NAME}_backup"
        cursor.execute(f"ALTER TABLE {TABLE_NAME} RENAME TO {backup_table};")
        
        # 2. Tạo bảng mới với CẤU TRÚC CHUẨN MỰC
        cursor.execute(f"""
            CREATE TABLE {TABLE_NAME} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                grade INTEGER NOT NULL,
                subject TEXT NOT NULL,
                content TEXT NOT NULL,
                options_json TEXT NOT NULL,
                correct_answer TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                question_type TEXT NOT NULL
            );
        """)

        # 3. Kỹ thuật quét lỗi cũ
        cursor.execute(f"PRAGMA table_info({backup_table})")
        old_columns = [row[1] for row in cursor.fetchall()]
        
        # Nếu bảng cũ có 'grade', ta copy nó. Nếu không có, gán mặc định là 6
        grade_query = "grade" if "grade" in old_columns else "6" 

        # 4. Đổ dữ liệu từ bảng cũ sang bảng mới
        cursor.execute(f"""
            INSERT INTO {TABLE_NAME} (id, grade, subject, content, options_json, correct_answer, difficulty, question_type)
            SELECT 
                id, 
                {grade_query}, 
                subject, 
                content, 
                options_json, 
                correct_answer, 
                CAST(difficulty AS TEXT), 
                'normal'
            FROM {backup_table};
        """)

        # 5. Dọn dẹp rác: Xóa bảng tạm
        cursor.execute(f"DROP TABLE {backup_table};")
        
        # 6. GHI NHẬN THAY ĐỔI
        conn.commit()
        print("✅ GIẢI PHẪU THÀNH CÔNG! File game.db của ngài đã mang sinh mệnh mới.")
        print("-> Đã đổi 'difficulty' sang dạng Chữ (Text).")
        print("-> Đã thêm chốt chặn 'question_type' (tất cả data cũ được gán là 'normal').")

    except Exception as e:
        # Nếu có lỗi, hoàn tác mọi thứ
        conn.rollback()
        print(f"❌ PHẪU THUẬT THẤT BẠI. Đã hoàn tác để bảo vệ Database.")
        print(f"Lỗi chi tiết: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    upgrade_database()