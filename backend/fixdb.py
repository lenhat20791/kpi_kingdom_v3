import sqlite3
import os

# 👇 SỬA LẠI ĐƯỜNG DẪN CHUẨN Ở ĐÂY
# '..' nghĩa là lùi ra ngoài 1 thư mục (từ backend ra kpi_kingdom_v3)
# 'data' là chui vào thư mục data
# 'game.db' là tên file
DB_FILE = os.path.join('..', 'data', 'game.db')

def upgrade_database():
    print(f"🛠️ Đang kết nối tới Database tại: {DB_FILE}")
    
    # Kiểm tra xem file có thực sự tồn tại không trước khi làm
    if not os.path.exists(DB_FILE):
        print(f"❌ LỖI: Vẫn không tìm thấy file tại {DB_FILE}. Bạn kiểm tra lại tên file nhé!")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # 1. Thêm cột cho bảng Player
    try:
        cursor.execute("ALTER TABLE player ADD COLUMN companion_slot_1 TEXT;")
        cursor.execute("ALTER TABLE player ADD COLUMN companion_slot_2 TEXT;")
        cursor.execute("ALTER TABLE player ADD COLUMN companion_slot_3 TEXT;")
        print("✅ Bảng Player: Đã thêm 3 cột slot Thẻ Đồng Hành thành công!")
    except Exception as e:
        print(f"⚠️ Bảng Player (Bỏ qua): {e}")

    # 2. Thêm cột cho bảng Companion
    try:
        cursor.execute("ALTER TABLE companion ADD COLUMN is_equipped BOOLEAN DEFAULT 0;")
        cursor.execute("ALTER TABLE companion ADD COLUMN slot_index INTEGER DEFAULT 0;")
        print("✅ Bảng Companion: Đã thêm cờ trạng thái trang bị thành công!")
    except Exception as e:
        print(f"⚠️ Bảng Companion (Bỏ qua): {e}")

    conn.commit()
    conn.close()
    print("🎉 Nâng cấp Database hoàn tất! Bật Server lên quẩy tiếp thôi!")

if __name__ == "__main__":
    upgrade_database()