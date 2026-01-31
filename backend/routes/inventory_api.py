from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, desc
from typing import List, Optional
from database import get_db, Player, Item, Inventory, MarketListing
from pydantic import BaseModel
from game_logic import item_processor  # Import bộ xử lý mới
import traceback

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
    currency: str # tri_thuc, chien_tich

class BuyRequest(BaseModel):
    buyer_username: str
    listing_id: int

# ==========================================
# 1. API LẤY DỮ LIỆU KHO ĐỒ (Túi + Trang bị)
# ==========================================

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from database import get_db, Player, Item, Inventory
import json

router = APIRouter()

@router.get("/inventory/get")
def get_inventory(username: str, db: Session = Depends(get_db)):
    # 1. Tìm người chơi
    player = db.exec(select(Player).where(Player.username == username)).first()
    if not player: 
        raise HTTPException(status_code=404, detail="Player not found")

    # 2. Lấy dữ liệu (Join bảng Inventory và Item)
    # QUAN TRỌNG: Chỉ lấy những món có số lượng (amount) > 0
    stmt = (
        select(Inventory, Item)
        .join(Item)
        .where(Inventory.player_id == player.id)
        .where(Inventory.amount > 0)  # <--- Đã sửa thành amount cho khớp DB
    )
    results = db.exec(stmt).all()

    inventory_list = []
    
    for inv, item in results:
        # Xử lý an toàn cho config
        item_config = {}
        try:
            if item.config: item_config = json.loads(item.config)
        except: pass

        # Xác định loại vật phẩm
        is_usable = False
        if item.type == "consumable" or item_config.get("action"):
            is_usable = True

        inventory_list.append({
            "id": item.id,
            "item_id": item.id,
            "name": item.name,
            
            # 👇 TRẢ VỀ CẢ 2 TÊN ĐỂ TRÁNH LỖI FRONTEND
            "image": item.image_url,    
            "image_url": item.image_url,
            
            "description": item.description,
            
            # 👇 TRẢ VỀ CẢ 2 TÊN SỐ LƯỢNG
            "amount": inv.amount,      # <--- Lấy từ cột amount trong DB
            "quantity": inv.amount,    # Backup cho frontend cũ
            
            "is_equippable": item.can_equip,
            "is_usable": is_usable,
            "config": item_config
        })

    # Trả về cấu trúc chuẩn
    return {
        "bag": inventory_list,      # Frontend gọi là data.bag
        "inventory": inventory_list # Backup nếu gọi data.inventory
    }

# ==========================================
# 2. API SỬ DỤNG VẬT PHẨM (MỚI THÊM VÀO)
# ==========================================
@router.post("/inventory/use")
def use_item(req: UseItemRequest, db: Session = Depends(get_db)):
    # 1. Tìm người chơi
    player = db.exec(select(Player).where(Player.username == req.username)).first()
    if not player: raise HTTPException(404, "Không tìm thấy người chơi")

    # 2. Kiểm tra kho đồ
    inventory_item = db.exec(select(Inventory).where(
        Inventory.player_id == player.id,
        Inventory.item_id == req.item_id
    )).first()

    if not inventory_item or inventory_item.amount < 1:
        return {"status": "error", "message": "Bạn không còn vật phẩm này!"}

    # 3. Lấy thông tin Item gốc để check loại
    item_template = db.get(Item, req.item_id)
    if not item_template:
        return {"status": "error", "message": "Vật phẩm lỗi data"}

    # 4. GỌI ITEM PROCESSOR (Bộ não xử lý)
    success, message, data = item_processor.apply_item_effects(player, item_template, db)

    if success:
        # 5. Nếu dùng thành công -> Trừ số lượng
        inventory_item.amount -= 1
        if inventory_item.amount <= 0:
            db.delete(inventory_item) # Hết thì xóa dòng luôn cho sạch DB
        else:
            db.add(inventory_item)
            
        db.commit() # Lưu tất cả thay đổi (Máu, Tiền, Số lượng item)
        
        return {
            "status": "success", 
            "message": message,
            "data": data, # Trả về data (máu mới...) để Frontend cập nhật ngay
            "remaining": inventory_item.amount if inventory_item.amount > 0 else 0
        }
    else:
        # Dùng thất bại (VD: Đầy máu rồi) -> Không trừ đồ
        return {"status": "error", "message": message}

# ==========================================
# 3. CÁC API KHÁC (GIỮ NGUYÊN)
# ==========================================

@router.post("/inventory/equip")
def equip_item(req: EquipRequest, db: Session = Depends(get_db)):
    player = db.exec(select(Player).where(Player.username == req.username)).first()
    if not player: raise HTTPException(404, "Player not found")

    # Logic tháo/mặc trang bị (Giữ nguyên logic cũ của bạn nếu có)
    # ... (Phần này trong file cũ của bạn có vẻ chưa hoàn thiện logic đổi slot, 
    # nhưng tạm thời ta tập trung vào Use Item trước)
    
    # Đây là logic update slot đơn giản:
    slot_field = f"equip_slot_{req.slot_index}"
    if not hasattr(player, slot_field):
        return {"status": "error", "message": "Slot không hợp lệ"}

    setattr(player, slot_field, req.item_id)
    db.add(player)
    db.commit()
    
    return {"status": "success", "message": "Đã trang bị thành công!"}

