import os
import random
import traceback
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import SQLModel, Session, select
from database import get_db, Companion, CompanionTemplate, CompanionConfig, Player

# Tạo Router riêng cho tính năng này
router = APIRouter()

# ==========================================
# 1. ADMIN: QUÉT ẢNH ĐỂ TẠO PHÔI (AUTO SCAN) - PHIÊN BẢN SỬA LỖI PATH
# ==========================================
@router.post("/admin/companions/scan")
def scan_companion_templates(db: Session = Depends(get_db)):
    """
    Hàm này sẽ duyệt qua thư mục frontend/assets/card/
    và tự động tạo dữ liệu vào bảng CompanionTemplate.
    """
    
    # --- FIX LỖI ĐƯỜNG DẪN ---
    # 1. Lấy vị trí của file hiện tại (backend/routes/companion.py)
    current_file_path = os.path.abspath(__file__)
    
    # 2. Lùi lại 2 cấp để ra thư mục gốc dự án (kpi_kingdom_v3)
    # routes -> backend -> kpi_kingdom_v3
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(current_file_path)))
    
    # 3. Nối vào đường dẫn frontend/assets/card (Tự động dùng \ hoặc / tùy window/linux)
    base_path = os.path.join(root_dir, "frontend", "assets", "card")

    print(f"🔍 Đang quét tại: {base_path}") # In ra CMD để debug

    rarities = ["r", "sr", "ssr", "usr"]
    
    added_count = 0
    updated_count = 0
    
    # Kiểm tra xem thư mục gốc có tồn tại không
    if not os.path.exists(base_path):
        print(f"❌ Không tìm thấy thư mục gốc: {base_path}")
        return {"status": "error", "message": f"Không tìm thấy thư mục: {base_path}. Hãy kiểm tra lại tên folder!"}

    for rarity in rarities:
        folder_path = os.path.join(base_path, rarity)
        
        # Nếu chưa tạo thư mục con thì bỏ qua
        if not os.path.exists(folder_path):
            print(f"⚠️ Bỏ qua {rarity.upper()} vì chưa có thư mục: {folder_path}")
            continue
            
        print(f"📂 Đang quét thư mục: {rarity.upper()}...")

        # Duyệt qua từng file ảnh trong thư mục
        for file_name in os.listdir(folder_path):
            if file_name.lower().endswith((".png", ".webp", ".jpg", ".jpeg")):
                
                # --- XỬ LÝ TẠO ID ---
                # Ví dụ file: "vo-nguyen-giap.png"
                name_slug = file_name.rsplit(".", 1)[0] # Lấy "vo-nguyen-giap"
                
                # Tạo Template ID chuẩn: SR_VO_NGUYEN_GIAP
                clean_slug = name_slug.replace("-", "_").replace(" ", "_").upper()
                template_id = f"{rarity.upper()}_{clean_slug}"
                
                # Tạo Tên hiển thị: Võ Nguyên Giáp
                display_name = name_slug.replace("-", " ").replace("_", " ").title()
                
                # Đường dẫn ảnh (Lưu vào DB đường dẫn tương đối để frontend load)
                image_rel_path = f"/assets/card/{rarity}/{file_name}"

                # --- LƯU VÀO DATABASE ---
                existing = db.get(CompanionTemplate, template_id)
                
                if not existing:
                    # Nếu chưa có -> Tạo mới
                    new_tpl = CompanionTemplate(
                        template_id=template_id,
                        name=display_name,
                        rarity=rarity.upper(),
                        image_path=image_rel_path
                    )
                    db.add(new_tpl)
                    print(f"   ➕ Thêm mới: {template_id}")
                    added_count += 1
                else:
                    # Nếu có rồi -> Cập nhật lại đường dẫn ảnh
                    if existing.image_path != image_rel_path:
                        existing.image_path = image_rel_path
                        db.add(existing)
                        updated_count += 1

    db.commit()
    return {
        "status": "success", 
        "message": f"Quét hoàn tất! Đã thêm mới: {added_count}, Cập nhật: {updated_count}. (Xem Log CMD để biết chi tiết)",
        "details": {"added": added_count, "updated": updated_count}
    }

# ==========================================
# 2. ADMIN: LẤY DANH SÁCH PHÔI (TEMPLATES)
# ==========================================
@router.get("/admin/companions/templates")
def get_templates(rarity: str = None, db: Session = Depends(get_db)):
    query = select(CompanionTemplate)
    if rarity and rarity != "ALL":
        query = query.where(CompanionTemplate.rarity == rarity.upper())
    
    templates = db.exec(query).all()
    return templates

# ... (Giữ nguyên code cũ phần Scan và Templates) ...

# ==========================================
# 3. ADMIN: QUẢN LÝ CẤU HÌNH (CONFIG)
# ==========================================

# Lấy cấu hình hiện tại để hiển thị lên bảng
@router.get("/admin/companions/config")
def get_companion_config(db: Session = Depends(get_db)):
    config = db.get(CompanionConfig, 1)
    if not config:
        # Nếu chưa có thì trả về mặc định giả
        return {"fodder_required": 3, "stats_config": "{}"}
    return config

# Lưu cấu hình mới
class ConfigUpdate(SQLModel):
    fodder_required: int
    stats_config: str # JSON string

@router.post("/admin/companions/config")
def update_companion_config(data: ConfigUpdate, db: Session = Depends(get_db)):
    config = db.get(CompanionConfig, 1)
    if not config:
        config = CompanionConfig(id=1)
    
    config.fodder_required = data.fodder_required
    config.stats_config = data.stats_config
    
    db.add(config)
    db.commit()
    return {"message": "Đã lưu cấu hình thành công!"}

# ==========================================
# 4. PLAYER: LẤY DANH SÁCH THẺ ĐỒNG HÀNH ĐÃ SỞ HỮU
# ==========================================
@router.get("/my-cards")
def get_player_companions(username: str, db: Session = Depends(get_db)):
    try:
        # 1. Tìm Player
        player = db.exec(select(Player).where(Player.username == username)).first()
        if not player:
            return {"status": "error", "message": "Người chơi không tồn tại"}

        # 2. Truy vấn JOIN
        query = (
            select(Companion, CompanionTemplate)
            .join(CompanionTemplate, Companion.template_id == CompanionTemplate.template_id)
            .where(Companion.player_id == player.id)
        )
        results = db.exec(query).all()

        cards_list = []
        for comp, temp in results:
            try:
                # 3. Xử lý ID an toàn
                raw_id = comp.id
                ui_suffix = ""

                # Kiểm tra xem ID là chuỗi hay số để lấy hậu tố phù hợp
                if isinstance(raw_id, str):
                    # Nếu ID là chuỗi, lấy 4 ký tự cuối
                    ui_suffix = raw_id[-4:].upper()
                else:
                    # Nếu ID là số, chuyển sang hex
                    ui_suffix = hex(int(raw_id))[2:].upper()
                
                # Tạo UI ID (Dòng này phải nằm ngang hàng với if/else, không được nằm trong else)
                ui_id = f"{temp.rarity}_{temp.template_id}_{ui_suffix}"

                # Thêm vào danh sách
                cards_list.append({
                    "id": ui_id,           # Dùng cho giao diện (Chuỗi)
                    "real_id": comp.id,    # Dùng cho DB (Số nguyên/Chuỗi gốc)
                    "name": comp.temp_name or temp.name,
                    "rarity": temp.rarity,
                    "star": comp.star,
                    "hp": comp.hp,
                    "atk": comp.atk,
                    "image": temp.image_path,
                    "is_locked": comp.is_locked
                })
            except Exception as e:
                # Nếu 1 thẻ bị lỗi, in log và bỏ qua, không làm sập toàn bộ danh sách
                print(f"⚠️ Bỏ qua thẻ lỗi (ID: {comp.id}): {e}")
                continue

        print(f"✅ Đã tải thành công {len(cards_list)} thẻ bài cho {username}")
        return {"status": "success", "cards": cards_list}

    except Exception as e:
        # In lỗi chi tiết ra Terminal nếu API bị sập hoàn toàn
        print("❌ LỖI BACKEND RỒI:")
        traceback.print_exc() 
        return {"status": "error", "message": str(e)}