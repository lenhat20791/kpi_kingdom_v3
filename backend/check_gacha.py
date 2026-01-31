import json
from sqlmodel import Session, select
# 👇 QUAN TRỌNG: Import cả 'engine' từ database.py
# Để đảm bảo script này đọc ĐÚNG cái file mà Server đang dùng
from database import Item, engine 

def check_chests():
    # Sử dụng engine được import từ database.py
    with Session(engine) as db:
        print("dang ket noi database...")
        # Lấy tất cả item để kiểm tra
        items = db.exec(select(Item)).all()
        
        # Lọc rương Gacha
        gacha_items = []
        for i in items:
            if i.config and ("gacha" in i.config or "drops" in i.config):
                gacha_items.append(i)

        print(f"\n====== 🔍 TÌM THẤY {len(gacha_items)} RƯƠNG GACHA TRONG DB ======")
        
        if not gacha_items:
            print("⚠️ CẢNH BÁO: Không tìm thấy item nào có cấu hình Gacha!")
            print("-> Hãy vào Admin tạo rương và bấm LƯU lại.")
        
        for item in gacha_items:
            print(f"\n📦 ID: {item.id} | Tên: {item.name}")
            print(f"📝 RAW CONFIG: {item.config}")
            
            try:
                config = json.loads(item.config)
                # Kiểm tra các key gacha
                drops = config.get("gacha_items") or config.get("drops") or config.get("loot_table")
                
                if not drops:
                    print(f"❌ LỖI: Config rỗng! Key 'gacha_items' không tồn tại.")
                else:
                    print(f"✅ HỢP LỆ. Danh sách quà:")
                    for d in drops:
                        # In chi tiết để debug
                        iid = d.get('item_id') or d.get('id')
                        rate = d.get('rate')
                        print(f"   - Item ID: {iid} (Kiểu dữ liệu: {type(iid)}) | Tỷ lệ: {rate}%")
                        
            except Exception as e:
                print(f"❌ LỖI JSON: {e}")

if __name__ == "__main__":
    check_chests()