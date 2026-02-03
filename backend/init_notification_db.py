# File: init_notification_db.py
from sqlmodel import SQLModel
from database import engine, Notification 
# 👆 QUAN TRỌNG: Phải import class Notification từ database.py 
# để SQLModel biết sự tồn tại của nó

def update_database():
    print("⏳ Đang kết nối vào game.db...")
    
    # Lệnh này sẽ quét tất cả các class đã import
    # Nếu thấy bảng nào chưa có trong DB, nó sẽ tạo mới.
    # Nếu bảng đã có rồi, nó sẽ BỎ QUA (không làm mất dữ liệu cũ).
    SQLModel.metadata.create_all(engine)
    
    print("========================================")
    print("✅ ĐÃ TẠO BẢNG 'NOTIFICATION' THÀNH CÔNG!")
    print("========================================")

if __name__ == "__main__":
    try:
        update_database()
    except ImportError as e:
        print("❌ Lỗi Import: Hãy chắc chắn bạn đã thêm class Notification vào file database.py rồi!")
        print(f"Chi tiết lỗi: {e}")
    except Exception as e:
        print(f"❌ Lỗi không xác định: {e}")