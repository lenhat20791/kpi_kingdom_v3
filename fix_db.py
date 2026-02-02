import sqlite3
import os

# Đường dẫn đến file db của bạn
db_path = os.path.join("data", "game.db")

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Lệnh thêm cột grade
    cursor.execute("ALTER TABLE questionbank ADD COLUMN grade INTEGER DEFAULT 6;")
    
    conn.commit()
    print("✅ Đã thêm cột 'grade' vào bảng questionbank thành công!")
except sqlite3.OperationalError as e:
    print(f"⚠️ Thông báo: {e} (Có thể cột đã tồn tại rồi)")
finally:
    if conn:
        conn.close()