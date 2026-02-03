from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, desc
from typing import List, Optional
from database import get_db, Player, Item, Inventory, MarketListing
from pydantic import BaseModel
from game_logic import item_processor  # Import bộ xử lý
import traceback
import json

router = APIRouter()

# --- MODEL DỮ LIỆU ĐẦU VÀO ---
class EquipRequest(BaseModel):
    username: str
    item_id: int
    slot_index: int # 1, 2, 3, 4

class UseItemRequest(BaseModel):
    username: str
    item_id: int

class SellRequest(BaseModel):
    username: str
    item_id: int
    amount: int
    price: int
    currency: str 

class BuyRequest(BaseModel):
    buyer_username: str
    listing_id: int

# ==========================================
# 1. API LẤY DỮ LIỆU KHO ĐỒ
# ==========================================
@router.get("/inventory/get")
def get_inventory(username: str, db: Session = Depends(get_db)):
    # 1. Tìm người chơi
    player = db.exec(select(Player).where(Player.username == username)).first()
    if not player: 
        raise HTTPException(status_code=404, detail="Player not found")

    # 2. Lấy dữ liệu
    stmt = (
        select(Inventory, Item)
        .join(Item)
        .where(Inventory.player_id == player.id)
        .where(Inventory.amount > 0)
    )
    results = db.exec(stmt).all()

    inventory_list = []
    
    for inv, item in results:
        item_config = {}
        try:
            if item.config: item_config = json.loads(item.config)
        except: pass

        is_usable = False
        if item.type == "consumable" or item_config.get("action"):
            is_usable = True

        # 🔥 FIX QUAN TRỌNG: Ép kiểu số lượng về int
        safe_amount = int(inv.amount)

        # 👇 THÊM ĐOẠN NÀY: VỆ SINH TÊN VẬT PHẨM (QUAN TRỌNG NHẤT)
        clean_name = item.name.replace("\xa0", " ").strip() if item.name else f"Item {item.id}"
        safe_image = item.image_url if item.image_url else "/assets/items/default.png"

        inventory_list.append({
            "id": item.id,
            "item_id": item.id,
            "name": clean_name,         # <--- SỬA DÒNG NÀY (Thay item.name bằng clean_name)
            "image": safe_image,        # <--- SỬA DÒNG NÀY (Cho an toàn)
            "image_url": safe_image,    # <--- SỬA DÒNG NÀY
            "description": item.description,
            "amount": safe_amount,
            "quantity": safe_amount,
            "is_equippable": item.can_equip,
            "is_usable": is_usable,
            "config": item_config
        })

    return {
        "bag": inventory_list,
        "inventory": inventory_list
    }

# ==========================================
# 2. API SỬ DỤNG VẬT PHẨM (ĐÃ SỬA LỖI CRASH)
# ==========================================
@router.post("/inventory/use")
def use_item(req: UseItemRequest, db: Session = Depends(get_db)):
    try:
        # 1. Tìm người chơi
        player = db.exec(select(Player).where(Player.username == req.username)).first()
        if not player: return {"status": "error", "message": "Không tìm thấy người chơi"}

        # 2. Kiểm tra kho đồ (Tìm chính xác món đồ)
        # Lưu ý: req.item_id là int, DB cũng phải so sánh đúng
        inventory_item = db.exec(select(Inventory).where(
            Inventory.player_id == player.id,
            Inventory.item_id == req.item_id
        )).first()

        # 🔥 FIX CRASH 1: Ép kiểu amount ra số nguyên trước khi so sánh
        if not inventory_item:
            return {"status": "error", "message": "Bạn không có vật phẩm này!"}
        
        current_qty = int(inventory_item.amount) # Ép kiểu an toàn
        
        if current_qty < 1:
            return {"status": "error", "message": "Số lượng không đủ!"}

        # 3. Lấy thông tin Item gốc
        item_template = db.get(Item, req.item_id)
        if not item_template:
            return {"status": "error", "message": "Vật phẩm lỗi data"}

        # 4. GỌI ITEM PROCESSOR
        # (Đây là nơi xử lý mở rương, cộng quà...)
        success, message, data = item_processor.apply_item_effects(player, item_template, db)

        if success:
            # 👇 THAY TOÀN BỘ ĐOẠN TRỪ SỐ LƯỢNG CŨ BẰNG ĐOẠN NÀY 👇
            
            # 1. Tìm lại item mới nhất (Vì item cũ đã bị stale sau khi processor commit)
            fresh_inv = db.exec(select(Inventory).where(
                Inventory.player_id == player.id,
                Inventory.item_id == req.item_id
            )).first()
            
            remaining_qty = 0
            
            # 2. Trừ số lượng an toàn trên item mới tìm được
            if fresh_inv:
                new_amt = int(fresh_inv.amount) - 1
                fresh_inv.amount = new_amt
                remaining_qty = new_amt
                
                if new_amt <= 0:
                    db.delete(fresh_inv)
                else:
                    db.add(fresh_inv)
            
            db.commit() # Lưu thay đổi

            # 3. Trả về kết quả (Vệ sinh cả message để Frontend không sập)
            return {
                "status": "success", 
                "message": str(message).replace("\xa0", " "), 
                "data": data if data else {},
                "remaining": remaining_qty
            }
        else:
            return {"status": "error", "message": message}

    except Exception as e:
        print(f"❌ LỖI USE ITEM: {e}")
        traceback.print_exc() # In lỗi chi tiết ra CMD để debug
        return {"status": "error", "message": "Lỗi hệ thống khi dùng vật phẩm"}

# ==========================================
# 3. CÁC API KHÁC
# ==========================================
@router.post("/inventory/equip")
def equip_item(req: EquipRequest, db: Session = Depends(get_db)):
    player = db.exec(select(Player).where(Player.username == req.username)).first()
    if not player: raise HTTPException(404, "Player not found")

    slot_field = f"equip_slot_{req.slot_index}"
    if not hasattr(player, slot_field):
        return {"status": "error", "message": "Slot không hợp lệ"}

    setattr(player, slot_field, req.item_id)
    db.add(player)
    db.commit()
    
    return {"status": "success", "message": "Đã trang bị thành công"}