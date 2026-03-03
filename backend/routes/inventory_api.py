from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, desc
from sqlalchemy.orm import joinedload
from typing import List, Optional
from database import get_db, Player, Item, Inventory, MarketListing, PlayerItem, SystemConfig, Companion
from pydantic import BaseModel
from game_logic import item_processor  # Import bộ xử lý
from game_logic.stats import recalculate_player_stats
from game_logic.item_processor import forge_item
import traceback
import json

router = APIRouter()

# --- MODEL DỮ LIỆU ĐẦU VÀO ---
class EquipRequest(BaseModel):
    username: str
    item_id: int
    slot_index: int # 1, 2, 3, 4

class UnequipRequest(BaseModel):
    username: str
    slot_index: int

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

class ForgeRequest(BaseModel):
    username: str
    charm_id: int
class EquipCompanionRequest(BaseModel):
    username: str
    companion_id: str  # ID của thẻ bài (Chuỗi)
    slot_index: int    # Từ 1 đến 3

class UnequipCompanionRequest(BaseModel):
    username: str
    slot_index: int

# ==========================================
# 1. API LẤY DỮ LIỆU KHO ĐỒ
# ==========================================
@router.get("/inventory/get")
def get_inventory(username: str, db: Session = Depends(get_db)):
    # 1. Tìm người chơi
    player = db.exec(select(Player).where(Player.username == username)).first()
    if not player: 
        raise HTTPException(status_code=404, detail="Player not found")

    inventory_list = []

    # ==========================================================
    # PHẦN 1: LẤY ITEM THƯỜNG (Code của bạn - Đã giữ nguyên logic tốt)
    # ==========================================================
    stmt = (
        select(Inventory, Item)
        .join(Item)
        .where(Inventory.player_id == player.id)
        .where(Inventory.amount > 0)
    )
    results = db.exec(stmt).all()

    for inv, item in results:
        item_config = {}
        try:
            if item.config: item_config = json.loads(item.config)
        except: pass

        is_usable = False
        if item.type == "consumable" or item_config.get("action"):
            is_usable = True

        safe_amount = int(inv.amount)
        clean_name = item.name.replace("\xa0", " ").strip() if item.name else f"Item {item.id}"
        safe_image = item.image_url if item.image_url else "/assets/items/charms/default.png"

        inventory_list.append({
            "id": item.id,      # ID mẫu vật phẩm
            "item_id": item.id,
            "name": clean_name,
            "image": safe_image,
            "image_url": safe_image,
            "description": item.description,
            "amount": safe_amount,
            "quantity": safe_amount,
            "is_equippable": item.can_equip,
            "is_usable": is_usable,
            "config": item_config,
            # Item thường không có rarity
        })

    # ==========================================================
    # PHẦN 2: LẤY CHARM / ĐỒ ĐỘC BẢN (PHẦN MỚI BẮT BUỘC PHẢI CÓ)
    # ==========================================================
    # Lấy từ bảng PlayerItem, chỉ lấy những món ĐANG TRONG TÚI (chưa mặc)
    charms = db.exec(
        select(PlayerItem)
        .where(PlayerItem.player_id == player.id)
        .where(PlayerItem.is_equipped == False) 
    ).all()

    for charm in charms:
        inventory_list.append({
            "id": charm.id,          # ID riêng (quan trọng để rèn/bán)
            "item_id": charm.id,     # Map tạm để frontend không lỗi
            "name": charm.name,
            "image": charm.image_url,
            "image_url": charm.image_url,
            "amount": 1,             # Charm luôn là 1
            "quantity": 1,
            "description": f"Cấp cường hóa: +{charm.enhance_level}",
            
            # 🔥 CÁC TRƯỜNG QUAN TRỌNG ĐỂ FRONTEND VẼ KHUNG MÀU:
            "rarity": charm.rarity,          # MAGIC / EPIC / LEGEND
            "stats_data": charm.stats_data,  # {"atk": 10...}
            "enhance_level": charm.enhance_level,
            
            "is_usable": False,
            "is_equippable": True,   
            "type": "charm"          # Đánh dấu để Frontend biết xử lý
        })

    # =======================================================
    # PHẦN 3: LẤY TRANG BỊ ĐANG MẶC
    # =======================================================
    equipped_data = {} 
    
    # A. Lấy Charm đang mặc (Giữ nguyên của bạn) 
    equipped_charms = db.exec( 
        select(PlayerItem) 
        .where(PlayerItem.player_id == player.id) 
        .where(PlayerItem.is_equipped == True) 
    ).all() 

    for charm in equipped_charms: 
        current_slot = charm.slot_index if charm.slot_index and charm.slot_index > 0 else 1 
        slot_key = f"slot_{current_slot}" 
        equipped_data[slot_key] = { 
            "id": charm.id, 
            "name": charm.name, 
            "image_url": charm.image_url, 
            "image": charm.image_url, 
            "rarity": charm.rarity, 
            "stats_data": charm.stats_data, 
            "enhance_level": charm.enhance_level, 
            "type": "charm"  # Đánh dấu loại để Frontend phân biệt
        }

    # B. Lấy Thẻ Đồng Hành đang mặc (MỚI)
    # Import joinedload nếu chưa có ở đầu file: from sqlalchemy.orm import joinedload
    equipped_companions = db.exec(
        select(Companion)
        .options(joinedload(Companion.template)) # Lấy luôn info ảnh/tên từ template
        .where(Companion.player_id == player.id)
        .where(Companion.is_equipped == True)
    ).all()

    for comp in equipped_companions:
        # Lưu vào key dạng comp_slot_1, comp_slot_2... để không đụng hàng với Charm
        current_slot = comp.slot_index if comp.slot_index and comp.slot_index > 0 else 1
        slot_key = f"comp_slot_{current_slot}"
        
        # Lấy thông tin an toàn
        c_name = comp.temp_name or (comp.template.name if comp.template else "Lỗi Thẻ")
        c_image = comp.template.image_path if comp.template else "/assets/card/back.png"
        c_rarity = comp.template.rarity if comp.template else "N/A"

        equipped_data[slot_key] = {
            "id": comp.id,
            "name": c_name,
            "image_url": c_image,
            "image": c_image,
            "rarity": c_rarity,
            "star": comp.star,
            "stats_data": {"atk": comp.atk, "hp": comp.hp}, # Đóng gói lại cho giống Charm
            "type": "companion" # Đánh dấu loại
        }

    # 4. Trả về kết quả đầy đủ (Giữ nguyên)
    return { 
        "bag": inventory_list, 
        "equipment": equipped_data, 
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

# ==========================================================
# API MẶC TRANG BỊ (CHARM)
# ==========================================================
@router.post("/inventory/equip")
async def equip_item(req: EquipRequest, db: Session = Depends(get_db)):
    # 1. Tìm người chơi
    player = db.exec(select(Player).where(Player.username == req.username)).first()
    if not player:
        raise HTTPException(status_code=404, detail="Không tìm thấy người chơi")

    # 2. Tìm món đồ cần mặc (Phải là đồ của người đó)
    item_to_equip = db.exec(select(PlayerItem).where(
        PlayerItem.id == req.item_id,
        PlayerItem.player_id == player.id
    )).first()

    if not item_to_equip:
        raise HTTPException(status_code=404, detail="Không tìm thấy vật phẩm này trong túi")

    # 3. Kiểm tra Slot hợp lệ (1-4)
    if req.slot_index < 1 or req.slot_index > 4:
        raise HTTPException(status_code=400, detail="Slot không hợp lệ (Phải từ 1-4)")

    # 4. XỬ LÝ SLOT: Nếu slot đó đang có đồ khác -> Tháo món đó ra trước
    current_item_in_slot = db.exec(select(PlayerItem).where(
        PlayerItem.player_id == player.id,
        PlayerItem.is_equipped == True,
        PlayerItem.slot_index == req.slot_index
    )).first()

    if current_item_in_slot:
        # Tháo món cũ ra
        current_item_in_slot.is_equipped = False
        current_item_in_slot.slot_index = 0
        db.add(current_item_in_slot)

    # 5. MẶC MÓN MỚI
    item_to_equip.is_equipped = True
    item_to_equip.slot_index = req.slot_index
    db.add(item_to_equip)
    db.commit() # Commit để lưu trạng thái mặc trước

    # 🔥 GỌI HÀM TÍNH LẠI STATS
    recalculate_player_stats(db, player, heal_mode="MAINTAIN_PERCENT")

    return {"status": "success", "message": f"Đã trang bị và cập nhật lực chiến!"}

# ==========================================================
# API THÁO TRANG BỊ
# ==========================================================
@router.post("/inventory/unequip")
async def unequip_item(req: UnequipRequest, db: Session = Depends(get_db)):
    player = db.exec(select(Player).where(Player.username == req.username)).first()
    if not player:
        raise HTTPException(status_code=404, detail="User not found")

    # Tìm món đồ đang mặc ở slot đó
    item_in_slot = db.exec(select(PlayerItem).where(
        PlayerItem.player_id == player.id,
        PlayerItem.is_equipped == True,
        PlayerItem.slot_index == req.slot_index
    )).first()

    if not item_in_slot:
        raise HTTPException(status_code=404, detail="Không có đồ nào ở slot này")

    # Tháo ra
    item_in_slot.is_equipped = False
    item_in_slot.slot_index = 0
    db.add(item_in_slot)
    db.commit()

    # 🔥 GỌI HÀM TÍNH LẠI STATS
    recalculate_player_stats(db, player, heal_mode="MAINTAIN_PERCENT")

    return {"status": "success", "message": "Đã tháo và cập nhật lực chiến!"}

# 2. THÊM API CƯỜNG HÓA VÀO CUỐI FILE
@router.post("/inventory/forge")
async def enhance_item_api(req: ForgeRequest, db: Session = Depends(get_db)):
    # A. Tìm người chơi
    player = db.exec(select(Player).where(Player.username == req.username)).first()
    if not player: 
        raise HTTPException(status_code=404, detail="Không tìm thấy người chơi")

    # B. Gọi hàm logic forge_item mà bạn đã viết trong item_processor
    # Lưu ý: stone_item_id là ID của Đá cường hóa trong DB (Ví dụ: 100)
    # Bạn cần đảm bảo trong bảng Item có item ID 100 là Đá Cường Hóa, hoặc sửa số này
    result = forge_item(db, req.charm_id, player.id)

    # C. Nếu thành công -> Tính lại Stats nhân vật & Hồi máu thưởng
    if result["status"] == "success":
        # Dùng chế độ HEAL_BONUS như đã thảo luận (Tăng bao nhiêu Max HP thì hồi bấy nhiêu)
        recalculate_player_stats(db, player, heal_mode="HEAL_BONUS")
    
    # D. Trả kết quả về cho Frontend
    return result

#api lấy cấu hình cường hóa từ admin setup
@router.get("/inventory/system-config")
async def get_system_config(db: Session = Depends(get_db)):
    """API để Frontend lấy cấu hình (Tỷ lệ đập đồ, giá đá...)"""
    try:
        # Tìm cấu hình forge_setup trong DB
        record = db.exec(select(SystemConfig).where(SystemConfig.key == "forge_setup")).first()
        
        if record and record.value:
            return {"status": "success", "config": json.loads(record.value)}
        else:
            # Trả về mặc định nếu Admin chưa chỉnh gì
            return {"status": "default", "config": None}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ==========================================
# API TRANG BỊ THẺ ĐỒNG HÀNH (BẢN LƯỚI QUÉT)
# ==========================================
@router.post("/inventory/equip-companion")
async def equip_companion(req: EquipCompanionRequest, db: Session = Depends(get_db)):
    player = db.exec(select(Player).where(Player.username == req.username)).first()
    if not player:
        raise HTTPException(status_code=404, detail="Không tìm thấy người chơi")

    if req.slot_index < 1 or req.slot_index > 3:
        raise HTTPException(status_code=400, detail="Slot thẻ bài chỉ từ 1 đến 3")

    # --- BẮT ĐẦU LOGIC "LƯỚI QUÉT" THÔNG MINH ---
    companion_to_equip = None
    req_id_clean = str(req.companion_id).strip().lower() # Dọn dẹp khoảng trắng, đưa về chữ thường
    
    # Lấy tất cả thẻ của người chơi ra để tự soi bằng Python
    all_comps = db.exec(select(Companion).where(Companion.player_id == player.id)).all()
    
    print(f"\n🔍 ĐANG TÌM THẺ GỬI LÊN TỪ WEB: '{req_id_clean}'")
    
    for c in all_comps:
        db_id_clean = str(c.id).strip().lower()
        db_template_clean = str(c.template_id).strip().lower()
        
        # 1. Khớp chính xác ID hoặc Template ID
        if db_id_clean == req_id_clean or db_template_clean == req_id_clean:
            companion_to_equip = c
            break
            
        # 2. Logic bóc tách: So sánh phần "Đuôi" của ID
        # Web gửi: 'r_r_11_7b94' -> Lấy đuôi '7b94'
        # DB lưu: 'r_1770802315_7b94' -> Lấy đuôi '7b94'
        req_suffix = req_id_clean.split('_')[-1]
        db_suffix = db_id_clean.split('_')[-1]
        
        if req_suffix == db_suffix:
            companion_to_equip = c
            break

    # Nếu lưới quét vẫn không tìm thấy -> Báo lỗi
    if not companion_to_equip:
        print("❌ KẾT QUẢ: KHÔNG TÌM THẤY THẺ NÀY!")
        raise HTTPException(status_code=404, detail="Không tìm thấy thẻ này trong kho")

    print(f"✅ TÌM THẤY! Đang trang bị thẻ có ID gốc: {companion_to_equip.id}")
    # --- KẾT THÚC LOGIC LƯỚI QUÉT ---

    # 3. Tháo thẻ cũ ở slot hiện tại
    current_companion_in_slot = db.exec(select(Companion).where(
        Companion.player_id == player.id,
        Companion.is_equipped == True,
        Companion.slot_index == req.slot_index
    )).first()

    if current_companion_in_slot:
        current_companion_in_slot.is_equipped = False
        current_companion_in_slot.slot_index = 0
        db.add(current_companion_in_slot)

    # 4. Mặc thẻ mới
    companion_to_equip.is_equipped = True
    companion_to_equip.slot_index = req.slot_index
    db.add(companion_to_equip)
    
    # 5. Lưu ID thẻ vào Player 
    if req.slot_index == 1: player.companion_slot_1 = str(companion_to_equip.id)
    elif req.slot_index == 2: player.companion_slot_2 = str(companion_to_equip.id)
    elif req.slot_index == 3: player.companion_slot_3 = str(companion_to_equip.id)
    
    db.add(player)
    db.commit()

    # 6. Tính lại Stats
    recalculate_player_stats(db, player, heal_mode="MAINTAIN_PERCENT")

    return {"status": "success", "message": "Đã trang bị Thẻ Đồng Hành thành công!"}

# ==========================================
# API THÁO THẺ ĐỒNG HÀNH
# ==========================================
@router.post("/inventory/unequip-companion")
async def unequip_companion(req: UnequipCompanionRequest, db: Session = Depends(get_db)):
    player = db.exec(select(Player).where(Player.username == req.username)).first()
    if not player:
        raise HTTPException(status_code=404, detail="User not found")

    companion_in_slot = db.exec(select(Companion).where(
        Companion.player_id == player.id,
        Companion.is_equipped == True,
        Companion.slot_index == req.slot_index
    )).first()

    if not companion_in_slot:
        raise HTTPException(status_code=404, detail="Không có thẻ nào ở slot này")

    # Tháo ra
    companion_in_slot.is_equipped = False
    companion_in_slot.slot_index = 0
    db.add(companion_in_slot)
    
    # Xóa khỏi Player
    if req.slot_index == 1: player.companion_slot_1 = None
    elif req.slot_index == 2: player.companion_slot_2 = None
    elif req.slot_index == 3: player.companion_slot_3 = None
    
    db.add(player)
    db.commit()

    # 🔥 TÍNH LẠI STATS
    recalculate_player_stats(db, player, heal_mode="MAINTAIN_PERCENT")

    return {"status": "success", "message": "Đã tháo Thẻ Đồng Hành!"}