import sqlite3
import os

def check_database():
    # Các vị trí nghi ngờ có file game.db
    potential_paths = ["game.db", "data/game.db", "../data/game.db"]
    found_any = False

    print("🔍 BẮT ĐẦU QUÉT DATABASE...")

    for db_path in potential_paths:
        if os.path.exists(db_path):
            found_any = True
            print(f"\n📂 TÌM THẤY FILE: {os.path.abspath(db_path)}")
            inspect_file(db_path)
    
    if not found_any:
        print("\n❌ LỖI: Không tìm thấy bất kỳ file 'game.db' nào xung quanh đây!")
        print("👉 Bạn hãy copy file script này đặt ngay cạnh file game.db rồi chạy lại.")

def inspect_file(db_path):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Lấy danh sách cột của bảng MarketListing
        cursor.execute("PRAGMA table_info(marketlisting)")
        columns_info = cursor.fetchall()
        
        # columns_info trả về list các tuple: (id, name, type, ...)
        # Ta chỉ lấy tên cột (vị trí số 1)
        column_names = [col[1] for col in columns_info]

        if not column_names:
            print("   ⚠️ Bảng 'marketlisting' chưa được tạo hoặc không có dữ liệu!")
            return

        print(f"   📋 Danh sách cột hiện có: {column_names}")

        if "item_data_json" in column_names:
            print("   ✅ KẾT QUẢ: Cột 'item_data_json' ĐÃ CÓ. (File này OK)")
        else:
            print("   ❌ KẾT QUẢ: Cột 'item_data_json' CHƯA CÓ! (Đây là nguyên nhân lỗi)")

        conn.close()

    except Exception as e:
        print(f"   ⚠️ Không đọc được file này. Lỗi: {e}")

if __name__ == "__main__":
    check_database()