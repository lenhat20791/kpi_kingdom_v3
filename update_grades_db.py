import sqlite3
import os

def upgrade_database():
    # 1. Xác định đường dẫn chính xác đến thư mục data
    db_path = os.path.join("data", "game.db")
    
    # 2. Kiểm tra sinh tử: Nếu không có file thì không làm gì cả
    if not os.path.exists(db_path):
        print(f"❌ Lỗi: Không tìm thấy file database tại: {db_path}")
        print("Vui lòng kiểm tra lại thư mục 'data' của bạn.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Danh sách 8 môn học và 2 học kỳ
    subjects = [
        'toan', 'van', 'anh', 'gdcd', 
        'cong_nghe', 'tin', 'khtn', 'lsdl'
    ]
    semesters = ['hk1', 'hk2']
    
    print(f"🚀 Đang kết nối đến: {db_path}")
    print("⏳ Đang nâng cấp bảng điểm...")
    
    added_count = 0
    for sub in subjects:
        for sem in semesters:
            column_name = f"{sub}_{sem}"
            try:
                # REAL để lưu điểm số có dấu phẩy (vd: 9.5)
                cursor.execute(f"ALTER TABLE player ADD COLUMN {column_name} REAL DEFAULT 0.0")
                print(f"✅ Đã thêm cột: {column_name}")
                added_count += 1
            except sqlite3.OperationalError:
                # Nếu cột đã có rồi thì sqlite sẽ báo lỗi này, ta bỏ qua
                print(f"⚠️ Cột {column_name} đã tồn tại, bỏ qua.")
                
    conn.commit()
    conn.close()
    
    print("---")
    print(f"✨ Hoàn tất! Đã thêm mới {added_count} cột điểm vào database trong thư mục data.")

if __name__ == "__main__":
    upgrade_database()