import sys
import os

# --- THÊM ĐOẠN NÀY ĐỂ FIX LỖI IMPORT ---
# Lấy đường dẫn thư mục hiện tại và trỏ vào folder "backend"
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_path = os.path.join(current_dir, "backend")
sys.path.append(backend_path)
# ---------------------------------------

from sqlmodel import Session, text
# Bây giờ dòng này mới chạy được vì đã trỏ đúng đường dẫn
from database import engine 

def add_bonus_columns():
    with Session(engine) as session:
        try:
            # Thêm cột ATK Bonus
            session.exec(text("ALTER TABLE player ADD COLUMN item_atk_bonus INTEGER DEFAULT 0"))
            print("✅ Đã thêm cột 'item_atk_bonus'")
        except Exception as e:
            print(f"⚠️ Cột item_atk_bonus có thể đã tồn tại: {e}")

        try:
            # Thêm cột HP Bonus
            session.exec(text("ALTER TABLE player ADD COLUMN item_hp_bonus INTEGER DEFAULT 0"))
            print("✅ Đã thêm cột 'item_hp_bonus'")
        except Exception as e:
            print(f"⚠️ Cột item_hp_bonus có thể đã tồn tại: {e}")
            
        session.commit()
        print("🎉 Hoàn tất cập nhật Database!")

if __name__ == "__main__":
    add_bonus_columns()