import json
import random
from sqlmodel import Session, select
from database import engine, Player, Item, Inventory
from game_logic import item_processor

def chuan_doan_benh():
    print("\n" + "="*50)
    print("🔍 BẮT ĐẦU KIỂM TRA HỆ THỐNG ITEM")
    print("="*50)
    
    with Session(engine) as db:
        # 1. Tìm người chơi test
        player = db.exec(select(Player)).first()
        if not player:
            print("❌ LỖI: Không có người chơi nào trong DB.")
            return
        print(f"👤 Test với User: {player.username} (ID: {player.id})")

        # 2. Tìm cái rương ID 3
        chest_id = 3 
        item_template = db.get(Item, chest_id)
        if not item_template:
            print(f"❌ LỖI: Không tìm thấy Item ID {chest_id} trong bảng Item.")
            return
        
        print(f"📦 Mở rương: {item_template.name}")
        print(f"⚙️ Config gốc: {item_template.config}")

        # 3. Chạy thử hàm Processor
        try:
            print("\n--- ĐANG CHẠY LOGIC MỞ RƯƠNG ---")
            success, message, data = item_processor.apply_item_effects(player, item_template, db)
            
            print(f"✅ Kết quả hàm: {success}")
            print(f"💬 Thông báo: {message}")
            print(f"📊 Dữ liệu (Data) trả về: {json.dumps(data, indent=4, ensure_ascii=False)}")

            # 4. SOI LỖI KIỂU DỮ LIỆU (Thủ phạm gây sập Frontend)
            print("\n--- PHÂN TÍCH KIỂU DỮ LIỆU ---")
            
            if not isinstance(data, dict):
                print("❌ LỖI: 'data' trả về không phải là Object JSON.")
            
            # Kiểm tra xem có trường received không (Frontend rất cần cái này)
            if 'received' not in data:
                print("⚠️ CẢNH BÁO: Dữ liệu thiếu key 'received'. Frontend có thể bị lặp vô tận hoặc crash.")
            elif not isinstance(data['received'], list):
                print("❌ LỖI: 'received' phải là một DANH SÁCH (Array) để Frontend hiển thị.")

        except Exception as e:
            print(f"💥 BACKEND CRASH THẬT SỰ: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    chuan_doan_benh()