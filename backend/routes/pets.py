from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from datetime import datetime
from database import get_db, Player, Item, Inventory as PlayerItem, PlayerPet
from pydantic import BaseModel

router = APIRouter()

# --- MODEL DỮ LIỆU ĐẦU VÀO ---
class FusionRequest(BaseModel):
    player_id: int
    fragment_item_id: int # ID của vật phẩm "Mảnh Pet"

class UpgradeStarRequest(BaseModel):
    player_id: int
    pet_item_id: int # Loại Pet muốn nâng sao (Vd: ID của Rồng Lửa)
    current_star: int # Muốn nâng từ sao mấy lên? (Vd: 1 lên 2)

class ActivateRequest(BaseModel):
    player_id: int
    pet_instance_id: int # ID riêng của con Pet trong túi (PlayerPet.id)

# ==========================================================
# 1. API GHÉP MẢNH (FRAGMENT FUSION)
# Logic: Cần 10 mảnh để đổi lấy 1 Pet Level 1 (1 Sao)
# ==========================================================
@router.post("/fusion")
def fuse_pet_fragments(req: FusionRequest, db: Session = Depends(get_db)):
    # 1. Kiểm tra xem người chơi có đủ 10 mảnh không
    # Tìm trong túi đồ (PlayerItem)
    statement = select(PlayerItem).where(
        PlayerItem.player_id == req.player_id,
        PlayerItem.item_id == req.fragment_item_id
    )
    fragment_stack = db.exec(statement).first()

    if not fragment_stack or fragment_stack.quantity < 10:
        raise HTTPException(status_code=400, detail="Không đủ mảnh để ghép (Cần 10 mảnh)!")

    # 2. Xác định xem Mảnh này sẽ ra con Pet nào?
    # Quy ước: Trong config của Mảnh, phải có dòng {"target_pet_id": 102}
    # Hoặc đơn giản: Admin tự quy định ID. 
    # Ở đây ta giả định: item_id của Mảnh và Pet được map trong config của Mảnh.
    fragment_info = db.get(Item, req.fragment_item_id)
    if not fragment_info:
        raise HTTPException(status_code=404, detail="Không tìm thấy thông tin mảnh!")

    # Lấy ID pet mục tiêu từ config (Backend phải parse chuỗi JSON config)
    import json
    try:
        config = json.loads(fragment_info.config)
        target_pet_id = config.get("target_pet_id")
        if not target_pet_id:
            raise HTTPException(status_code=400, detail="Mảnh này bị lỗi config (Không trỏ tới Pet nào).")
    except:
        raise HTTPException(status_code=400, detail="Lỗi đọc cấu hình mảnh.")

    # 3. Trừ 10 mảnh
    fragment_stack.quantity -= 10
    if fragment_stack.quantity <= 0:
        db.delete(fragment_stack) # Hết thì xóa dòng luôn
    
    # 4. Thêm Pet mới vào bảng PlayerPet
    new_pet = PlayerPet(
        player_id=req.player_id,
        item_id=target_pet_id,
        star_level=1, # Mặc định 1 sao
        level=1,
        is_active=False
    )
    db.add(new_pet)
    
    db.commit()
    return {"success": True, "message": "Ghép thành công! Nhận được 1 Linh Thú mới."}


# ==========================================================
# 2. API TĂNG SAO (3-IN-1 EVOLUTION)
# Logic: Hy sinh 3 con Pet cùng loại, cùng sao để tạo ra 1 con sao cao hơn
# ==========================================================
@router.post("/upgrade-star")
def upgrade_pet_star(req: UpgradeStarRequest, db: Session = Depends(get_db)):
    # 1. Tìm tất cả Pet "rác" (cùng loại, cùng sao) mà người chơi đang có
    statement = select(PlayerPet).where(
        PlayerPet.player_id == req.player_id,
        PlayerPet.item_id == req.pet_item_id,
        PlayerPet.star_level == req.current_star,
        PlayerPet.is_active == False # Không được lấy con đang active ra tế
    )
    pets = db.exec(statement).all()

    if len(pets) < 3:
        raise HTTPException(status_code=400, detail=f"Cần 3 Pet {req.current_star} sao để nâng cấp. Bạn chỉ có {len(pets)} con.")

    # 2. Thực hiện "Hiến tế"
    # Lấy 3 con đầu tiên trong danh sách
    sacrifices = pets[:3]
    
    # Xóa 3 con này đi
    for p in sacrifices:
        db.delete(p)
    
    # 3. Tạo 1 con mới cấp cao hơn (Hoặc giữ lại 1 con và nâng cấp nó - Ở đây ta chọn tạo mới cho sạch data)
    new_high_pet = PlayerPet(
        player_id=req.player_id,
        item_id=req.pet_item_id,
        star_level=req.current_star + 1, # Tăng 1 sao
        level=1, # Reset level hoặc giữ nguyên tùy logic game (tạm thời reset)
        is_active=False
    )
    db.add(new_high_pet)
    
    db.commit()
    return {"success": True, "message": f"Nâng cấp thành công! Nhận được Pet {req.current_star + 1} Sao."}


# ==========================================================
# 3. API KÍCH HOẠT AURA (CẬP NHẬT: VĨNH VIỄN - TOGGLE)
# Logic: Kích hoạt Pet này -> Tự động tắt Pet đang chạy trước đó.
# Không có giới hạn thời gian.
# ==========================================================
@router.post("/activate")
def activate_pet_aura(req: ActivateRequest, db: Session = Depends(get_db)):
    # 1. Tìm con Pet mà người chơi muốn bật
    target_pet = db.get(PlayerPet, req.pet_instance_id)
    if not target_pet:
        raise HTTPException(status_code=404, detail="Không tìm thấy Linh thú này.")
    
    if target_pet.player_id != req.player_id:
        raise HTTPException(status_code=403, detail="Linh thú này không phải của bạn!")

    # 2. Nếu con này đang bật rồi thì thôi, không làm gì cả (hoặc có thể làm logic tắt nếu muốn)
    if target_pet.is_active:
        return {"success": True, "message": "Linh thú này đang bảo vệ bạn rồi!"}

    # 3. TẮT TẤT CẢ Linh thú khác của người chơi này (Reset)
    # Tìm tất cả pet đang active của user
    statement = select(PlayerPet).where(
        PlayerPet.player_id == req.player_id,
        PlayerPet.is_active == True
    )
    active_pets = db.exec(statement).all()
    
    # Duyệt qua và tắt hết
    for pet in active_pets:
        pet.is_active = False
        db.add(pet) # Đánh dấu update vào DB
    
    # 4. BẬT con mới lên
    target_pet.is_active = True
    # active_start_time vẫn có thể lưu để biết "Bắt đầu nuôi từ bao giờ", 
    # nhưng logic game sẽ không dùng nó để tính hết hạn nữa.
    target_pet.active_start_time = datetime.utcnow() 
    
    db.add(target_pet)
    db.commit()
    
    return {"success": True, "message": f"Đã triệu hồi {target_pet.item_id}! Hào quang đã kích hoạt vĩnh viễn."}