import json
import shutil
import pandas as pd
import sys
import os
import io
import random 
import traceback
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

current_dir = os.path.dirname(os.path.abspath(__file__)) 
parent_dir = os.path.dirname(current_dir) 
sys.path.append(parent_dir)
from fastapi import Body, APIRouter, HTTPException, Depends, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from sqlmodel import Session, select, delete, func
from sqlalchemy import func, desc
from database import (
    get_db, Player, Inventory, Item, 
    Boss, BossLog, TowerSetting, TowerProgress,
    PlayerPet, SystemStatus, generate_username,
    QuestionBank, ArenaMatch, ArenaParticipant,
    SkillTemplate, Title, SystemConfig,
    ScoreLog, ShopHistory, ActiveEffect, PlayerSkill, MarketListing,
    PlayerItem, Companion, Notification, ChatLog, ChatWarningLog, ChatBan,
    CampaignPlayer, TroopMovement, BattleReport, CampaignChat,
    SpaceStationMatch, SpaceStationPlayer, SpaceStationAction, SpaceStationLog,
    StudyDeckCard, StudyDeck, StudyCardInstance, StudyPlayerPack,
    StudyPvpRoom, StudyPvpActionLedger, StudyRankedPlayer, StudyRankedMatch,
    StudyBattle, StudyActiveRun, StudyBattleResolution, StudyActionLedger,
    StudyRunHistory, StudyPlayerRelic, StudyPvpRelicLoadout,
)

from io import BytesIO
from unidecode import unidecode
from pydantic import BaseModel
from typing import List, Dict, Optional
from passlib.context import CryptContext
from .auth import get_password_hash, verify_password
from datetime import datetime
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Cấu trúc cho từng thẻ phần thưởng
class RewardItem(BaseModel):
    type: str
    name: str
    amount: int
    rate: int
#cấu trúc bảng skill
class SkillSchema(BaseModel):
    skill_id: str
    name: str
    description: str
    class_type: str
    skill_type: str  # ACTIVE / PASSIVE
    min_level: int = 1           # Cấp độ yêu cầu
    prerequisite_id: Optional[str] = None
    base_mult: float = 1.0
    vfx_class: str
    currency: str = "TRI_THUC"
    base_cost: int = 0               
    scaling: float = 0.0
    config_type: Optional[str] = None  # Ví dụ: "passive_dmg"
    value: float = 0.0                 # Ví dụ: 0.15 (15%)
    vfx_target: str = "enemy"
    condition: Optional[str] = None
    threshold: Optional[float] = 0.0
    config_data: Optional[str] = None

# Cấu trúc tổng thể gửi từ hàm saveTowerFullConfig()
class TowerGlobalConfig(BaseModel):
    monster_pool: str
    bg_pool: str
    rewards: Dict[str, List[RewardItem]] # Key là Medium, Hard, Extreme, Hell

router = APIRouter(
    prefix="",
    tags=["Admin Powers"]
)

# Model nhận dữ liệu khi hoàn thành tầng
class TowerCompleteRequest(BaseModel):
    player_id: int
    floor: int
    is_win: bool # True = Thắng, False = Thua
# class cho CHARMS
# Schema cho 1 cấp độ hiếm (VD: Magic)
class RarityConfig(BaseModel):
    lines: int
    atk_range: List[int] # [min, max]
    hp_range: List[int]  # [min, max]

# Schema tổng cho bảng Setup Charm
class CharmSetupPayload(BaseModel):
    MAGIC: RarityConfig
    EPIC: RarityConfig
    LEGEND: RarityConfig

# Schema cho bảng Setup Lò Rèn
class ForgeGroupConfig(BaseModel):
    min: int
    max: int
    rate: int
    stone: int
    bonus_pct: int

class ForgeSetupPayload(BaseModel):
    group_1: ForgeGroupConfig
    group_2: ForgeGroupConfig
    group_3: ForgeGroupConfig

@router.get("/players/overview")
def get_all_players_overview(db: Session = Depends(get_db)): # Dùng Dependency Injection
    """
    API lấy danh sách học sinh (Cấu trúc phẳng cho Frontend Admin)
    """
    # 1. Lấy tất cả người chơi
    players = db.exec(select(Player)).all()
    inventory_by_player = {player.id: [] for player in players}

    if inventory_by_player:
        inventory_rows = db.exec(
            select(Inventory, Item)
            .join(Item, Inventory.item_id == Item.id)
            .where(Inventory.player_id.in_(inventory_by_player))
        ).all()

        for inv, item_obj in inventory_rows:
            inventory_by_player[inv.player_id].append({
                "item_name": item_obj.name,
                "amount": inv.amount,
                "category": getattr(item_obj, "category", "Vật phẩm"),
                "rarity": getattr(item_obj, "rarity", "Thường")
            })

    result = []
    for p in players:
        # 3. Trả về cấu trúc phẳng (Đã khớp với Database mới 4 loại tiền tệ)
        result.append({
            "id": p.id,
            "full_name": p.full_name,
            "username": p.username,
            "kpi": p.kpi,          # Điểm tổng kết
            "tri_thuc": p.tri_thuc,# Xanh
            "chien_tich": p.chien_tich, # Cam
            "vinh_du": p.vinh_du,  # Tím
            "hp": p.hp,
            "hp_max": p.hp_max,
            "role": p.role,       
            "team_id": p.team_id,                
            "inventory": inventory_by_player[p.id]
        })
        
    return result

@router.patch("/players/{player_identifier}/stats")
def update_player_stats(
    player_identifier: str, 
    kpi_change: float = Query(0), # Đổi sang float để nhận điểm lẻ
    tri_thuc_change: int = Query(0),
    chien_tich_change: int = Query(0),
    vinh_du_change: int = Query(0),
    hp_change: int = Query(0),
    db: Session = Depends(get_db)
):
    print(f"DEBUG: Nhận lệnh update cho {player_identifier}")
    
    try:
        # 1. Xác định danh sách học sinh cần cập nhật
        if player_identifier == "ALL":
            # CHỈ lấy học sinh, loại bỏ admin để tránh tặng nhầm cho admin
            players = db.exec(select(Player).where(Player.role != "admin")).all()
            print(f"DEBUG: Chế độ ALL - Tìm thấy {len(players)} học sinh.")
        else:
            try:
                p_id = int(player_identifier)
            except ValueError:
                raise HTTPException(status_code=400, detail="ID không hợp lệ")
            
            player = db.get(Player, p_id)
            if not player:
                raise HTTPException(status_code=404, detail="Không tìm thấy học sĩ")
            players = [player]

        # 2. Vòng lặp cập nhật (Dùng chung cho cả 1 người hoặc ALL)
        count = 0
        for p in players:
            # --- Cập nhật Tiền tệ (Các dòng bạn bị thiếu đây) ---
            if kpi_change != 0:
                p.kpi = (p.kpi or 0.0) + kpi_change
            
            if tri_thuc_change != 0:
                p.tri_thuc = (p.tri_thuc or 0) + tri_thuc_change
            
            if chien_tich_change != 0:
                p.chien_tich = (p.chien_tich or 0) + chien_tich_change
            
            if vinh_du_change != 0:
                p.vinh_du = (p.vinh_du or 0) + vinh_du_change

            # --- Cập nhật HP (Giữ nguyên logic tính Max HP của bạn) ---
            if hp_change != 0:
                c_type = p.class_type if p.class_type else "NOVICE"
                # Logic tính Max HP dựa trên class và KPI
                base_bonus = 300 if c_type == "WARRIOR" else (100 if c_type == "MAGE" else 0)
                max_hp = 10 + int(p.kpi or 0) + base_bonus
                
                new_hp = (p.hp or 0) + hp_change
                # Giới hạn HP trong khoảng [0, max_hp]
                if new_hp > max_hp: new_hp = max_hp
                if new_hp < 0: new_hp = 0
                p.hp = new_hp

            db.add(p)
            count += 1

        # 3. Kết thúc
        db.commit()
        print(f"DEBUG: Hoàn tất cập nhật cho {count} người.")
        
        return {
            "success": True, 
            "message": f"Đã cập nhật chỉ số cho {count} học sĩ thành công!"
        }

    except Exception as e:
        db.rollback()
        print("❌❌❌ LỖI NGHIÊM TRỌNG:")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Lỗi server: {str(e)}")
# Sửa tham số đầu vào thành 'player_identifier' (str) để nhận được cả số và chữ "ALL"

# --- Giữ nguyên các hàm Vật phẩm (Item) không đổi ---
# 1. API TẠO VẬT PHẨM (Sửa để lưu vào bảng ITEM mới)
@router.post("/items/templates") # Giữ nguyên URL để frontend đỡ phải sửa
def create_item_template(
    item_data: dict = Body(...), # Nhận toàn bộ JSON từ Frontend
    db: Session = Depends(get_db)
):
    try:
        # Kiểm tra trùng tên trong bảng ITEM mới
        existing_item = db.exec(select(Item).where(Item.name == item_data.get("name"))).first()
        if existing_item:
            raise HTTPException(status_code=400, detail="Vật phẩm này đã tồn tại trong Shop!")

        # Tạo vật phẩm theo cấu trúc Shop mới (Đa tiền tệ)
        new_item = Item(
            name=item_data.get("name"),
            image_url=item_data.get("image_url", ""), # Frontend gửi lên image_url
            description=item_data.get("description", ""),
            currency_type=item_data.get("currency_type", "kpi"), # kpi, tri_thuc...
            price=int(item_data.get("price", 0)),
            is_hidden=item_data.get("is_hidden", False),
            limit_type=int(item_data.get("limit_type", 0)),
            config=item_data.get("config", "{}") # Logic tư duy (Hồi máu, Gacha...)
        )
        
        db.add(new_item)
        db.commit()
        db.refresh(new_item)
        
        return {"success": True, "item": new_item}
        
    except Exception as e:
        db.rollback()
        print(f"Lỗi tạo Item: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 2. API XÓA VẬT PHẨM
@router.delete("/items/templates/{item_id}")
def delete_item_template(
    item_id: int, 
    db: Session = Depends(get_db)
):
    try:
        # 1. Tìm vật phẩm theo ID
        item = db.get(Item, item_id)
        
        # 2. Nếu không tìm thấy -> Báo lỗi
        if not item:
            raise HTTPException(status_code=404, detail="Không tìm thấy vật phẩm này!")
            
        # 3. Thực hiện xóa
        db.delete(item)
        db.commit()
        
        return {"success": True, "message": f"Đã xóa vật phẩm: {item.name}"}

    except Exception as e:
        db.rollback()
        print(f"Lỗi xóa Item: {e}")
        # Trường hợp item đang được sử dụng trong túi đồ của user (Inventory), 
        # database có thể chặn xóa (Foreign Key Constraint).
        raise HTTPException(status_code=500, detail="Không thể xóa vật phẩm (Có thể đang có người sở hữu).")
    
# Tìm và thay thế hàm list_item_templates cũ
@router.get("/items/templates")
def list_item_templates(db: Session = Depends(get_db)):
    """API lấy danh sách vật phẩm mẫu để hiển thị trong Dropdown"""
    try:
        items = db.exec(select(Item)).all()
        return items
    except Exception as e:
        print(f"Lỗi lấy Item Template: {e}")
        return []

# tặng và thu hồi quà cho player
@router.post("/players/{player_id}/items")
def give_item_to_player(
    player_id: str, # Đổi thành str để nhận "ALL"
    item_id: int, 
    amount: int = Query(1), 
    db: Session = Depends(get_db)
):
    try:
        game_item = db.get(Item, item_id) # [cite: 165]
        if not game_item:
            raise HTTPException(404, detail="Vật phẩm không tồn tại")

        # Xác định đối tượng
        if player_id == "ALL":
            players = db.exec(select(Player).where(Player.role != "admin")).all()
        else:
            p = db.get(Player, int(player_id))
            if not p: raise HTTPException(404)
            players = [p]

        for p in players:
            statement = select(Inventory).where(
                Inventory.player_id == p.id, 
                Inventory.item_id == item_id
            )
            inv_item = db.exec(statement).first() # [cite: 166]
            
            if inv_item:
                inv_item.amount += amount # Nếu amount âm sẽ là thu hồi 
                if inv_item.amount <= 0:
                    db.delete(inv_item) # Xóa nếu số lượng về 0 
                else:
                    db.add(inv_item)
            elif amount > 0:
                # Chỉ thêm mới nếu là tặng (số dương) [cite: 169]
                new_item = Inventory(player_id=p.id, item_id=item_id, amount=amount)
                db.add(new_item)

        db.commit()
        return {"success": True, "message": "Thao tác vật phẩm thành công!"}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail=str(e))

# --- tặng và thu hồi tiền tệ ---

# --- BỔ SUNG CÁC MODEL NHẬN DỮ LIỆU ---
class UpdateTeamRequest(BaseModel):
    team_id: int

class UpdateRoleRequest(BaseModel):
    role: str

class ResetPasswordRequest(BaseModel):
    username: str

# --- 1. API CHUYỂN TỔ (Update Team) ---
@router.patch("/players/{player_id}/team")
def update_player_team(
    player_id: int, 
    req: UpdateTeamRequest, 
    db: Session = Depends(get_db) # 👈 QUAN TRỌNG: Phải thêm dòng này!
):
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Không tìm thấy học sĩ")
    
    # Kiểm tra team_id hợp lệ (0-4)
    if req.team_id < 0 or req.team_id > 4:
            raise HTTPException(status_code=400, detail="Team ID không hợp lệ (0-4)")

    player.team_id = req.team_id
    player.role = "U3" # Reset về thành viên thường khi sang tổ mới
    
    db.add(player)
    db.commit()
    db.refresh(player) # Làm mới lại dữ liệu trước khi trả về
    return {"success": True, "message": f"Đã chuyển {player.full_name} sang Tổ {req.team_id}"}

# --- 2. API ĐỔI CHỨC VỤ (Update Role) ---
@router.patch("/players/{player_id}/role")
def update_player_role(
    player_id: int, 
    req: UpdateRoleRequest, 
    db: Session = Depends(get_db) # 👈 QUAN TRỌNG: Đừng quên dòng này!
):
    player = db.get(Player, player_id)
    if not player:
        raise HTTPException(status_code=404, detail="Không tìm thấy học sĩ")
    
    valid_roles = ["U1", "U2", "U3"]
    if req.role.upper() not in valid_roles:
        raise HTTPException(status_code=400, detail="Chức vụ không hợp lệ (U1, U2, U3)")
        
    player.role = req.role.upper()
    db.add(player)
    db.commit()
    db.refresh(player)
    return {"success": True, "message": f"Đã thăng chức {player.full_name} lên {player.role}"}

# --- 3. API RESET MẬT KHẨU (Đã cập nhật để Admin soi được) ---
@router.post("/security/reset-password")
def reset_password(req: ResetPasswordRequest, db: Session = Depends(get_db)):
    # 1. Tìm user theo username
    player = db.exec(select(Player).where(Player.username == req.username)).first()
    
    if not player:
        raise HTTPException(status_code=404, detail="Không tìm thấy Username này")
        
    # Mật khẩu mới
    new_pass = "123456"

    # 2. Mã hóa mật khẩu để hệ thống dùng đăng nhập
    # (Đảm bảo bạn đã import hàm get_password_hash từ file auth.py)
    player.password_hash = get_password_hash(new_pass) 
    
    # 3. Lưu mật khẩu thô vào cột plain_password để Admin giám sát
    player.plain_password = new_pass 
    
    db.add(player)
    db.commit()
    
    return {"success": True, "message": f"Đã reset mật khẩu của {req.username} về {new_pass}"}


@router.post("/security/reset-all") 
async def reset_all_passwords_api(db: Session = Depends(get_db)):
    try:
        # Lấy tất cả trừ admin
        players = db.exec(select(Player).where(Player.username != "admin")).all()
        
        new_pass = "123456"
        hashed_pass = get_password_hash(new_pass) 

        for p in players:
            p.password_hash = hashed_pass
            p.plain_password = new_pass # Lưu mật khẩu thô để admin soi
            db.add(p)
            
        db.commit()
        return {"status": "success", "message": "Thành công"}

    except Exception:
        db.rollback()
        # 🔥 ĐÂY LÀ TOOL SOI: Lấy toàn bộ lỗi chi tiết dưới dạng văn bản
        full_error = traceback.format_exc() 
        
        # Gửi toàn bộ đống lỗi này về trình duyệt qua detail
        raise HTTPException(
            status_code=500, 
            detail={
                "error_type": "Server Crash",
                "debug_info": full_error  # Gửi toàn bộ nội dung lỗi về Console
            }
        )

@router.post("/import-excel")
async def import_excel(
    file: UploadFile = File(...),
    grade: int = Form(6),
    db: Session = Depends(get_db),
):
    if grade not in (6, 7, 8, 9):
        raise HTTPException(status_code=400, detail="Khối lớp phải là 6, 7, 8 hoặc 9")
    try:
        # =================================================================================
        # 🛡️ BƯỚC 0: ĐẢM BẢO ADMIN LUÔN TỒN TẠI (CHỐT CHẶN AN TOÀN)
        # =================================================================================
        # Chỉ cần bước này là đủ để bảo vệ Admin
        master_admin = db.exec(select(Player).where(Player.username == "admin")).first()
        
        if not master_admin:
            print("⚠️ Chưa thấy Admin, đang khởi tạo mặc định...")
            master_admin = Player(
                username="admin", 
                password_hash="123456", # Chỉ đặt pass khi tạo mới
                full_name="Quản Trị Viên", 
                role="admin", 
                team_id=0, kpi=9999, hp=9999
            )
            db.add(master_admin)
            db.commit()
            print("✅ Đã tạo Admin mặc định.")
        # 1. Đọc file vào RAM (Tránh lỗi seekable)
        contents = await file.read()
        file_stream = BytesIO(contents)
        df = pd.read_excel(file_stream)
        
        from unidecode import unidecode
        
        def normalize_str(s):
            return unidecode(str(s)).lower().strip().replace(" ", "").replace("_", "")

        # 2. Tạo map: { "hovaten": "Họ và Tên", "mahs": "Mã HS" ... }
        col_map_raw = {normalize_str(c): c for c in df.columns}
        normalized_cols = list(col_map_raw.keys())
        
        print(f"👉 CÁC CỘT ĐÃ CHUẨN HÓA: {normalized_cols}") # <--- Xem cái này ở màn hình đen

        # 3. TỪ KHÓA ĐỂ NHẬN DIỆN (Thêm từ khóa thoải mái vào đây)
        keywords_name = ['hovaten', 'hoten', 'ten', 'fullname', 'name', 'hocsinh', 'sinhvien']
        keywords_user = ['ma', 'id', 'code', 'user', 'taikhoan', 'account', 'mssv']
        keywords_team = ['to', 'nhom', 'doi', 'team', 'group', 'class']

        # Hàm tìm cột khớp với từ khóa
        def find_column(keywords):
            for kw in keywords:
                for col_norm in normalized_cols:
                    if kw in col_norm: # Ví dụ: tìm thấy "ten" trong "hovaten"
                        return col_map_raw[col_norm] # Trả về tên gốc "Họ và Tên"
            return None

        # Xác định cột nào là Tên, User, Tổ
        col_name_origin = find_column(keywords_name)
        col_user_origin = find_column(keywords_user)
        col_team_origin = find_column(keywords_team)
        # Cột khối/lớp trong Excel (nếu có) sẽ ghi đè khối chọn trên giao diện
        col_grade_origin = next((col_map_raw[c] for c in normalized_cols if c.startswith('khoi') or c in ('lop', 'grade')), None)
        col_class_origin = next((
            col_map_raw[c] for c in normalized_cols
            if 'lop' in c or c in ('class', 'classname', 'homeroom', 'section')
        ), None)

        import re
        def parse_grade(val):
            m = re.search(r'[6-9]', str(val)) if pd.notna(val) else None
            return int(m.group()) if m else None

        def parse_class_name(val):
            if pd.isna(val):
                return None
            match = re.search(r'(?<!\d)([6-9])\s*[./-]\s*(\d{1,2})(?!\d)', str(val))
            if not match:
                return None
            return f"{match.group(1)}.{int(match.group(2))}"

        print(f"✅ MAP CỘT: Tên=[{col_name_origin}] | User=[{col_user_origin}] | Tổ=[{col_team_origin}]")

        count_added = 0
        count_updated = 0
        generated_username_occurrences = {}
        used_generated_usernames = set()
        
        # 4. DUYỆT TỪNG DÒNG
        for index, row in df.iterrows():
            # --- LẤY HỌ TÊN ---
            full_name = row[col_name_origin] if col_name_origin else (row.iloc[0] if len(row) > 0 else f"Học sinh {index + 1}")
            if pd.isna(full_name) or not str(full_name).strip():
                continue
            full_name = str(full_name).strip()
            class_source = col_class_origin or col_grade_origin
            class_name = parse_class_name(row[class_source]) if class_source else None
            row_grade = (
                (parse_grade(row[col_grade_origin]) if col_grade_origin else None)
                or (parse_grade(row[class_source]) if class_source else None)
                or grade
            )
            # --- LẤY/TẠO USERNAME ---
            if col_user_origin:
                username = str(row[col_user_origin]).strip()
            else:
                base_username = generate_username(str(full_name))
                occurrence = generated_username_occurrences.get(base_username, 0)
                generated_username_occurrences[base_username] = occurrence + 1

                matching_player = None
                if class_name:
                    matching_player = next(
                        (
                            player for player in db.exec(
                                select(Player).where(
                                    Player.full_name == full_name,
                                    Player.class_name == class_name,
                                )
                            ).all()
                            if player.username not in used_generated_usernames
                        ),
                        None,
                    )
                if matching_player:
                    username = matching_player.username
                else:
                    candidate_count = occurrence
                    username = base_username if candidate_count == 0 else f"{base_username}{candidate_count}"

                    # Reuse a matching account on re-import, while retaining unique usernames for duplicate names.
                    while True:
                        exists = db.exec(select(Player).where(Player.username == username)).first()
                        if (
                            username not in used_generated_usernames
                            and (exists is None or exists.full_name == full_name)
                        ):
                            break
                        candidate_count += 1
                        username = f"{base_username}{candidate_count}"

                used_generated_usernames.add(username)

            # --- LẤY TỔ ---
            team_id = 0
            if col_team_origin:
                try:
                    val = row[col_team_origin]
                    if pd.notna(val): team_id = int(val)
                except: team_id = 0

            # --- LƯU DATABASE ---
            # (Logic cũ của bạn)
            existing_user = db.exec(select(Player).where(Player.username == username)).first()
            
            if not existing_user:
                # ✅ 1. Dùng hàm mã hóa chuẩn (thay vì pwd_context.hash thủ công)
                # Đảm bảo bạn đã import: from routes.auth import get_password_hash
                raw_pass = "123456"
                hashed_pass = get_password_hash(raw_pass)

                new_player = Player(
                    username=username,
                    password_hash=hashed_pass, # Pass mã hóa để đăng nhập
                    plain_password=raw_pass,   # 👈 QUAN TRỌNG: Lưu pass thô để Admin soi được
                    full_name=str(full_name),
                    
                    # 👇 CHỐT CHẶN QUAN TRỌNG NHẤT 👇
                    # Ép cứng bằng 0 luôn, bất chấp file Excel có cột "Tổ" hay không.
                    # Để đảm bảo họ luôn là "Học sinh tự do" chờ U1 tuyển.
                    team_id=0,       
                    
                    role="U3", # Mặc định là dân thường
                    grade=row_grade,
                    class_name=class_name,
                    kpi=0, 
                    hp=0,
                    level=1,
                    xp=0
                )
                db.add(new_player)
                count_added += 1
            else:
                # Nếu user đã tồn tại, chỉ cập nhật tên, KHÔNG cập nhật tổ
                # (Tránh việc import lại làm lính đang ở tổ này nhảy sang tổ khác)
                existing_user.full_name = str(full_name)
                existing_user.grade = row_grade
                if class_name:
                    existing_user.class_name = class_name
                # existing_user.team_id = team_id # 👈 Bỏ dòng này đi, không cho update tổ từ Excel nữa
                db.add(existing_user)
                count_updated += 1
                
        db.commit()
        return {
            "success": True,
            "added": count_added,
            "updated": count_updated,
            "message": f"Đã tạo {count_added} tài khoản mới, cập nhật {count_updated} (khối mặc định {grade}). Cột tên: '{col_name_origin}'",
        }
        
    except Exception as e:
        print(f"Lỗi: {e}")
        raise HTTPException(status_code=400, detail=f"Lỗi: {str(e)}")

# --- LOGIC ĐỔI MẬT KHẨU ADMIN ---
# Tạo Schema để nhận dữ liệu từ Frontend
class ChangePassSchema(BaseModel):
    old_password: str
    new_password: str

@router.post("/security/change-admin-password")
async def change_admin_password(req: ChangePassSchema, db: Session = Depends(get_db)):
    print(f"🔄 Đang xử lý đổi mật khẩu cho Admin...")

    # 1. Tìm tài khoản Admin
    # Sửa lỗi: dùng biến 'db' thay vì 'session'
    admin_user = db.exec(select(Player).where(Player.username == "admin")).first()
    
    if not admin_user:
        raise HTTPException(status_code=404, detail="Lỗi: Không tìm thấy tài khoản Admin!")

    # 2. Kiểm tra mật khẩu cũ (Phải dùng hàm verify_password)
    # req.old_password là "123456", admin_user.password_hash là "$2b$..."
    if not verify_password(req.old_password, admin_user.password_hash):
        print("❌ Mật khẩu cũ không khớp!")
        raise HTTPException(status_code=400, detail="Mật khẩu hiện tại không đúng!")

    # 3. Mã hóa mật khẩu mới trước khi lưu
    hashed_new_pass = get_password_hash(req.new_password)

    # 4. Lưu vào Database
    admin_user.password_hash = hashed_new_pass  # Lưu bản mã hóa (để đăng nhập)
    admin_user.plain_password = req.new_password # Lưu bản thường (để hiển thị nếu cần)
    
    db.add(admin_user)
    db.commit()
    
    print("✅ Đã đổi mật khẩu Admin thành công!")
    return {"success": True, "message": "Đổi mật khẩu thành công! Hãy ghi nhớ mật khẩu mới."}

# --- API ĐẶC BIỆT: Lấy danh sách đầy đủ (kèm mật khẩu) cho Tab Bảo Mật ---
@router.get("/security/all-players")
def get_all_players_security(db: Session = Depends(get_db)):
    try:
        # Code chuẩn mới: Dùng db, không dùng session cũ
        # Sắp xếp theo ID giảm dần (người mới nhất lên đầu)
        statement = select(Player).order_by(Player.id.desc())
        players = db.exec(statement).all()
        return players
    except Exception as e:
        print(f"Lỗi API Security Players: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/security/reset-season")
async def reset_season(db: Session = Depends(get_db)):
    try:
        # --- NHÓM 1: XÓA DỮ LIỆU SỞ HỮU & GIAO DỊCH (Xóa trước để tránh lỗi khóa ngoại) ---
        db.exec(delete(Inventory))      # Xóa túi đồ [cite: 1]
        db.exec(delete(PlayerSkill))    # Xóa kỹ năng người chơi đã học [cite: 160]
        db.exec(delete(PlayerPet))      # Xóa thú cưng đang sở hữu [cite: 156]
        db.exec(delete(MarketListing))  # Xóa các món đang treo bán trên Chợ Đen [cite: 158]
        db.exec(delete(ShopHistory))    # Xóa lịch sử mua hàng tại Shop [cite: 153]

        # --- NHÓM 2: XÓA LỊCH SỬ HOẠT ĐỘNG & TIẾN TRÌNH ---
        db.exec(delete(TowerProgress))  # Xóa tầng tháp cao nhất của từng người [cite: 154]
        db.exec(delete(BossLog))        # Xóa nhật ký sát thương Boss [cite: 149]
        db.exec(delete(ScoreLog))       # Xóa lịch sử nhập điểm/vi phạm [cite: 168]
        db.exec(delete(ActiveEffect))   # Xóa các hiệu ứng bùa chú đang kích hoạt [cite: 143]

        # Xóa dữ liệu Lôi đài (Participant trước, Match sau)
        db.exec(delete(ArenaParticipant)) # [cite: 165]
        db.exec(delete(ArenaMatch))       # [cite: 162]

        # --- NHÓM 2B: ĐỒ CÁ NHÂN, ĐỒNG HÀNH, CHAT, CHIẾN DỊCH, TRẠM VŨ TRỤ ---
        db.exec(delete(PlayerItem))
        db.exec(delete(Companion))
        db.exec(delete(ChatLog))
        db.exec(delete(ChatWarningLog))
        db.exec(delete(ChatBan))
        db.exec(delete(BattleReport))
        db.exec(delete(CampaignChat))
        db.exec(delete(TroopMovement))
        db.exec(delete(CampaignPlayer))
        db.exec(delete(SpaceStationLog))
        db.exec(delete(SpaceStationAction))
        db.exec(delete(SpaceStationPlayer))
        db.exec(delete(SpaceStationMatch))

        # --- NHÓM 2C: STUDY SPIRE (thẻ bài, deck, run, PvP, xếp hạng) ---
        db.exec(delete(StudyBattle))
        db.exec(delete(StudyActiveRun))
        db.exec(delete(StudyBattleResolution))
        db.exec(delete(StudyActionLedger))
        db.exec(delete(StudyRunHistory))
        db.exec(delete(StudyPlayerRelic))
        db.exec(delete(StudyPvpRelicLoadout))
        db.exec(delete(StudyPvpActionLedger))
        db.exec(delete(StudyPvpRoom))
        db.exec(delete(StudyRankedMatch))
        db.exec(delete(StudyRankedPlayer))
        db.exec(delete(StudyDeckCard))
        db.exec(delete(StudyDeck))
        db.exec(delete(StudyCardInstance))
        db.exec(delete(StudyPlayerPack))

        # --- NHÓM 3: XÓA NGƯỜI CHƠI (LUÔN GIỮ TÀI KHOẢN ADMIN HỆ THỐNG) ---
        master_admin = db.exec(select(Player).where(Player.username == "admin")).first()
        if master_admin and master_admin.role != "admin":
            master_admin.role = "admin"
            db.add(master_admin)
        statement = delete(Player).where(Player.role != "admin", Player.username != "admin")
        db.exec(statement)

        # Admin giữ lại nhưng xóa sạch trang bị / tiến trình gắn với mùa cũ
        for admin in db.exec(select(Player).where(Player.role == "admin")).all():
            admin.equip_slot_1 = admin.equip_slot_2 = admin.equip_slot_3 = admin.equip_slot_4 = None
            admin.companion_slot_1 = admin.companion_slot_2 = admin.companion_slot_3 = None
            admin.skills_data = "{}"
            admin.equipped_skill = None
            admin.tower_floor = 1
            admin.revive_at = None
            db.add(admin)

        db.commit()

        remaining = db.exec(
            select(func.count()).select_from(Player).where(
                Player.role != "admin",
                Player.username != "admin",
            )
        ).one()
        if remaining:
            raise RuntimeError(f"Reset chưa sạch: còn {remaining} người chơi")
        return {
            "success": True, 
            "message": "Mùa giải đã kết thúc! Toàn bộ học sinh và lịch sử đã được dọn dẹp. Hệ thống sẵn sàng nạp danh sách lớp mới."
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Lỗi Server: {str(e)}")

# =================================================================================
# 🐉 MODULE QUẢN LÝ BOSS (PVE CENTER)
# =================================================================================

# 1. API LƯU & TRIỆU HỒI BOSS MỚI
@router.post("/boss/save")
async def save_boss(boss_data: Boss, db: Session = Depends(get_db)):
    try:
        # A. Dọn dẹp Boss cũ đang Active (Quy tắc: Chỉ 1 Boss tồn tại)
        # Tìm Boss đang sống
        active_bosses = db.exec(select(Boss).where(Boss.status == "active")).all()
        for b in active_bosses:
            # Xóa hoặc chuyển về inactive (Ở đây ta xóa luôn cho nhẹ DB)
            db.delete(b)
            
            # Xóa luôn nhật ký của boss cũ để tránh lẫn lộn
            db.exec(delete(BossLog).where(BossLog.boss_id == b.id))
            
        # B. Thiết lập Boss mới
        boss_data.id = None # Đảm bảo tạo mới
        boss_data.current_hp = boss_data.max_hp # Máu khởi đầu đầy cây
        boss_data.status = "active" # Kích hoạt ngay
        
        # C. Lưu vào DB
        db.add(boss_data)
        db.commit()
        db.refresh(boss_data)
        
        return {"success": True, "message": f"Đã triệu hồi {boss_data.name} (HP: {boss_data.max_hp})!"}
        
    except Exception as e:
        print(f"Lỗi Save Boss: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# 2. API LẤY THÔNG TIN BOSS ĐANG HOẠT ĐỘNG
@router.get("/boss/current")
async def get_current_boss(db: Session = Depends(get_db)):
    # Lấy con Boss đầu tiên đang có status = 'active'
    boss = db.exec(select(Boss).where(Boss.status == "active")).first()
    
    if not boss:
        return None # Không có boss nào
        
    return boss

# 3. API HỦY TRẬN ĐẤU (XÓA BOSS & LOG)
@router.post("/boss/delete")
async def delete_boss(db: Session = Depends(get_db)):
    try:
        # Tìm Boss đang active
        boss = db.exec(select(Boss).where(Boss.status == "active")).first()
        
        if boss:
            # 1. Xóa Nhật ký chiến đấu trước (Do dính khóa ngoại)
            db.exec(delete(BossLog).where(BossLog.boss_id == boss.id))
            
            # 2. Xóa Boss
            db.delete(boss)
            db.commit()
            return {"success": True, "message": "Đã hủy trận đấu và dọn dẹp hiện trường!"}
        else:
            return {"success": False, "message": "Hiện không có Boss nào đang hoạt động."}
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 4. API DỌN DẸP NHẬT KÝ (Bonus cho nút 'Dọn dẹp nhật ký')
@router.post("/boss/logs/clear")
async def clear_boss_logs(db: Session = Depends(get_db)):
    try:
        # Xóa toàn bộ bảng Log
        db.exec(delete(BossLog))
        db.commit()
        return {"success": True, "message": "Đã xóa sạch nhật ký chiến đấu."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

#API Lấy Danh Sách Câu Hỏi   
@router.get("/tower/questions") # Giữ nguyên URL để Frontend không phải sửa nhiều
async def get_tower_questions(db: Session = Depends(get_db)):
    statement = (
        select(TowerQuestion.subject, TowerQuestion.difficulty, func.count(TowerQuestion.id))
        .group_by(TowerQuestion.subject, TowerQuestion.difficulty)
    )
    results = db.exec(statement).all()
    
    stats = {}
    for sub, diff, count in results:
        if sub not in stats:
            stats[sub] = {"total": 0, "details": {}}
        stats[sub]["details"][diff] = count
        stats[sub]["total"] += count
    return stats

# ==================================================================
# API NẠP CÂU HỎI (Vỏ cũ - Ruột mới thông minh)
# ==================================================================
@router.post("/tower/import-questions")
async def import_tower_questions(
    file: UploadFile = File(...), 
    mode: str = Form(...), 
    db: Session = Depends(get_db)
):
    try:
        contents = await file.read()
        questions_raw = json.loads(contents)
    except Exception:
        raise HTTPException(status_code=400, detail="File lỗi format JSON!")

    if not isinstance(questions_raw, list):
        raise HTTPException(status_code=400, detail="JSON phải là một danh sách []!")

    # --- XÓA CŨ (NẾU CHỌN REPLACE) ---
    if mode == "replace":
        combinations = set()
        for q in questions_raw:
            s = q.get('subject', 'General')
            d = q.get('difficulty', 'medium')
            combinations.add((s, d))
        
        for subject, diff in combinations:
            statement = delete(QuestionBank).where(
                QuestionBank.subject == subject, 
                QuestionBank.difficulty == diff
            )
            db.exec(statement)
        db.commit()

    # --- NẠP MỚI ---
    added_count = 0
    for q in questions_raw:
        try:
            # 1. Lấy đáp án (Ưu tiên chữ thường a,b,c,d theo mẫu JSON của bạn)
            val_a = str(q.get('a') or q.get('A') or '').strip()
            val_b = str(q.get('b') or q.get('B') or '').strip()
            val_c = str(q.get('c') or q.get('C') or '').strip()
            val_d = str(q.get('d') or q.get('D') or '').strip()

            options_list = [val_a, val_b, val_c, val_d]

            # 2. Xử lý đáp án đúng (Map từ 'b' sang '109')
            raw_correct = str(q.get('correct') or '').strip().lower() # Chuyển về chữ thường để so sánh
            
            final_correct = raw_correct # Mặc định
            
            if raw_correct == 'a': final_correct = val_a
            elif raw_correct == 'b': final_correct = val_b
            elif raw_correct == 'c': final_correct = val_c
            elif raw_correct == 'd': final_correct = val_d

            # 3. Tạo câu hỏi
            new_q = QuestionBank(
                subject=q.get('subject', 'Khác'),
                difficulty=q.get('difficulty', 'easy'),
                content=q.get('content', 'Nội dung lỗi'),
                options_json=json.dumps(options_list), # Lưu mảng JSON string
                correct_answer=final_correct,
                explanation=q.get('explain', "")
            )
            db.add(new_q)
            added_count += 1
        except Exception as e:
            print(f"Lỗi dòng {added_count}: {e}")
            continue 
    
    db.commit()
    return {"success": True, "message": f"Đã nạp thành công {added_count} câu hỏi."}
#API Thống kê đang có bn câu hỏi

# ==================================================================
# API THỐNG KÊ (Đã cập nhật sang QuestionBank)
# ==================================================================
@router.get("/tower/stats") # Giữ nguyên đường dẫn cũ cho Frontend
async def get_tower_stats(db: Session = Depends(get_db)):
    # 1. Truy vấn dữ liệu từ bảng QuestionBank
    statement = (
        select(QuestionBank.subject, QuestionBank.difficulty, func.count(QuestionBank.id))
        .group_by(QuestionBank.subject, QuestionBank.difficulty)
    )
    results = db.exec(statement).all()
    
    # 2. Xử lý dữ liệu về dạng Dictionary
    stats = {}
    for sub, diff, count in results:
        # Xử lý null
        subject_name = sub if sub else "Chưa phân loại"
        difficulty = diff if diff else "unknown"

        # Khởi tạo key nếu chưa có
        if subject_name not in stats:
            stats[subject_name] = {
                "total": 0, 
                "details": {}
            }
        
        # Gán dữ liệu
        stats[subject_name]["details"][difficulty] = count
        stats[subject_name]["total"] += count
        
    return stats

# ==================================================================
# 3. API XÓA MÔN (Cho nút thùng rác)
# ==================================================================
@router.delete("/tower/delete-subject/{subject}")
async def delete_tower_subject(subject: str, db: Session = Depends(get_db)):
    statement = delete(QuestionBank).where(QuestionBank.subject == subject)
    try:
        db.exec(statement)
        db.commit()
        return {"status": "success", "message": f"Đã xóa môn {subject}"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/tower/save-config")
async def save_tower_config(data: dict = Body(...), db: Session = Depends(get_db)):
    try:
        # 1. Tìm bản ghi cấu hình duy nhất
        db_setting = db.get(TowerSetting, 1)
        
        if not db_setting:
            db_setting = TowerSetting(id=1)
            
        # 2. Chuyển dict nhận được thành chuỗi JSON để cất vào DB
        # Việc dùng json.dumps giúp lưu trữ mượt mà 4 bậc độ khó: Medium, Hard, Extreme, Hell
        db_setting.config_data = json.dumps(data)
        
        db.add(db_setting)
        db.commit()
        
        return {"status": "success", "message": "Đã lưu cấu hình chiến trường!"}
    except Exception as e:
        db.rollback()
        print(f"Lỗi lưu Tower Config: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# API LẤY CẤU HÌNH (Gọi khi F5 trang hoặc khi vào game)
@router.get("/tower/get-config")
async def get_tower_config(db: Session = Depends(get_db)):
    statement = select(TowerSetting)
    db_setting = db.exec(statement).first()
    
    if not db_setting:
        # Trả về cấu trúc trống nếu chưa bao giờ lưu
        return {"monster_pool": "", "bg_pool": "", "rewards": {"Medium":[], "Hard":[], "Extreme":[], "Hell":[]}}
    
    # Giải mã chuỗi JSON từ DB trả về cho Frontend
    return json.loads(db_setting.config_data)


# ==========================================
# KHU VỰC: QUẢN LÝ DỮ LIỆU & THỐNG KÊ
# ==========================================

# 1. API THỐNG KÊ DASHBOARD (Top KPI, Vi Phạm, Tổ Đội)
@router.get("/data/dashboard-stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    # A. Top 5 Học sinh xuất sắc (KPI cao nhất)
    top_kpi = db.exec(select(Player).order_by(Player.kpi.desc()).limit(5)).all()
    
    # B. Top 5 Cần nhắc nhở (Ví dụ: Vinh dự thấp nhất hoặc HP thấp nhất)
    # Ở đây ta lấy Vinh Dự thấp nhất làm tiêu chí vi phạm
    top_violation = db.exec(select(Player).order_by(Player.vinh_du.asc()).limit(5)).all()

    # C. Thống kê theo Tổ đội (Team)
    # Giả sử ta có 4 tổ (Team ID 1, 2, 3, 4). Nếu DB chưa phân tổ, trả về mẫu.
    teams_stats = []
    for i in range(1, 5):
        players_in_team = db.exec(select(Player).where(Player.team_id == i)).all()
        total_kpi = sum(p.kpi for p in players_in_team)
        teams_stats.append({"team_id": i, "total_kpi": total_kpi, "member_count": len(players_in_team)})

    return {
        "top_kpi": top_kpi,
        "top_violation": top_violation,
        "teams": teams_stats
    }

# 2. API LẤY NHẬT KÝ HỆ THỐNG (LOGS)
@router.get("/data/logs")
def get_system_logs(limit: int = 50, type_filter: str = "all", db: Session = Depends(get_db)):
    # Lưu ý: Cần đảm bảo bạn đã có bảng GameLog trong database.py
    # Nếu chưa có, hãy tạo model GameLog đơn giản: id, timestamp, actor_name, action, details
    
    query = select(GameLog).order_by(GameLog.id.desc()).limit(limit)
    
    if type_filter != "all":
        # Giả sử trong Log có cột 'action_type' hoặc lọc theo text
        query = query.where(GameLog.action.contains(type_filter))
        
    logs = db.exec(query).all()
    return logs

# 3. API SAO LƯU DỮ LIỆU (BACKUP)
@router.get("/data/backup")
def backup_database():
    db_path = "game.db"
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="Không tìm thấy file Database!")
    
    # Trả về file để trình duyệt tải xuống
    return FileResponse(path=db_path, filename=f"backup_game_{generate_username('now')}.db", media_type='application/octet-stream')

# 4. API KHÔI PHỤC DỮ LIỆU (RESTORE) - NGUY HIỂM
@router.post("/data/restore")
async def restore_database(file: UploadFile = File(...)):
    # 1. Lưu file upload tạm
    temp_filename = "temp_restore.db"
    with open(temp_filename, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # 2. Thay thế file game.db chính (Cần cẩn trọng)
    try:
        # Đóng kết nối DB hiện tại (FastAPI tự quản lý, nhưng OS có thể khóa file)
        # Cách an toàn nhất trên Windows: Rename file cũ -> Move file mới -> Xóa file cũ
        if os.path.exists("game.db"):
            os.replace("game.db", "game.db.bak") # Backup tự động 1 bản
            
        os.rename(temp_filename, "game.db")
        
        return {"success": True, "message": "Đã khôi phục dữ liệu thành công! Hãy khởi động lại Server."}
    except Exception as e:
        return {"success": False, "message": f"Lỗi khôi phục: {str(e)}"}
    
# 1. API Lấy trạng thái bảo trì
@router.get("/data/maintenance-status")
def get_maintenance_status(db: Session = Depends(get_db)):
    status = db.get(SystemStatus, 1)
    if not status:
        # Nếu chưa có thì tạo mặc định
        status = SystemStatus(id=1, is_maintenance=False)
        db.add(status)
        db.commit()
        db.refresh(status)
    return status

# 2. API Cập nhật trạng thái bảo trì
@router.post("/data/maintenance-update")
def update_maintenance_status(
    is_maintenance: bool = Body(...), 
    message: str = Body(...), 
    db: Session = Depends(get_db)
):
    try:
        status = db.get(SystemStatus, 1)
        
        # Nếu chưa có thì tạo mới
        if not status:
            status = SystemStatus(id=1)
        
        # Cập nhật dữ liệu
        status.is_maintenance = is_maintenance
        status.message = message
        
        # 👇 SỬA ĐÚNG: Chuyển thời gian thành chuỗi "Năm-Tháng-Ngày Giờ:Phút:Giây"
        status.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        db.add(status)
        db.commit()
        db.refresh(status) # Refresh để lấy dữ liệu mới nhất
        
        return {"success": True, "message": "Đã cập nhật trạng thái hệ thống!"}

    except Exception as e:
        print(f"❌ Lỗi: {e}")
        return JSONResponse(status_code=500, content={"message": str(e)})

# 1. API Tạo Pet (Lưu vào bảng Item với config đặc biệt)
@router.post("/pets/create")
def create_pet(
    name: str = Body(...),
    image_url: str = Body(...),
    rarity: str = Body(...), # "common", "rare", "epic", "legendary"
    effect_type: str = Body(...), # "hp_buff", "atk_buff", etc.
    effect_value: float = Body(...),
    db: Session = Depends(get_db)
):
    # Sử dụng cột config kiểu TEXT để lưu JSON theo đúng quy ước 
    pet_config = {
        "is_pet": True,
        "rarity": rarity,
        "effect": {"type": effect_type, "value": effect_value}
    }
    
    new_pet = Item(
        name=name,
        image_url=image_url,
        currency_type="kpi", # Mặc định
        config=json.dumps(pet_config)
    )
    db.add(new_pet)
    db.commit()
    return {"success": True, "pet": new_pet}

# 2. API Cấu hình Gacha
# Model nhận dữ liệu (Để code rõ ràng hơn)
class GachaSetupRequest(BaseModel):
    chest_id: int          # ID của cái rương muốn cài đặt
    drops: list            # Danh sách đồ rơi: [{"id": 1, "rate": 50}, ...]

@router.post("/gacha/setup")
def setup_gacha(data: GachaSetupRequest, db: Session = Depends(get_db)):
    """
    Cấu hình tỷ lệ rơi đồ cho một Item Rương cụ thể.
    Lưu vào cột Item.config dưới dạng JSON: { "drops": [...] }
    """
    # 1. Tìm cái rương cần sửa
    chest_item = db.get(Item, data.chest_id)
    if not chest_item:
        return {"status": "error", "message": "Không tìm thấy Item Rương này!"}

    # 2. Lấy config cũ (để không làm mất các cài đặt khác nếu có)
    current_config = {}
    if chest_item.config:
        try:
            current_config = json.loads(chest_item.config)
        except:
            current_config = {}

    # 3. Cập nhật danh sách Drops
    # data.drops sẽ là: [{"id": 10, "rate": 20}, {"id": 15, "rate": 80}]
    current_config["drops"] = data.drops
    
    # Đánh dấu item này là rương (để frontend biết mà xử lý)
    current_config["action"] = "gacha_open" 
    # (Dòng này giúp đoạn filter ở admin.html hoạt động đúng: action !== 'gacha_open')

    # 4. Lưu ngược vào Database
    chest_item.config = json.dumps(current_config)
    chest_item.type = "chest" # Đảm bảo type đúng
    
    db.add(chest_item)
    db.commit()

    return {"status": "success", "message": f"Đã cập nhật tỷ lệ Gacha cho rương: {chest_item.name}"}

#api hệ thống kỹ năng
@router.get("/get-skills")
def get_all_skills(db: Session = Depends(get_db)):
    skills = db.exec(select(SkillTemplate)).all()
    # Parse config_data từ string sang dict trước khi gửi về
    result = []
    for s in skills:
        item = s.dict()
        try:
            item['config'] = json.loads(s.config_data) if s.config_data else {}
        except:
            item['config'] = {}
            
        result.append(item)
    return result


@router.post("/save-skill")
def save_skill(req: SkillSchema, db: Session = Depends(get_db)):
    try:
        print(f"DEBUG: Đang lưu skill {req.name}")

        # 1. XỬ LÝ ID (Logic cũ)
        current_id = req.skill_id
        if not current_id or current_id == "NEW_SKILL":
             current_id = f"skill_{int(time.time())}"

        # 2. XỬ LÝ JSON CONFIG (QUAN TRỌNG NHẤT) 🛠️
        # Frontend gửi lên 2 phần riêng biệt:
        # - req.config_data: Chứa logic Passive/Active (đang là chuỗi JSON)
        # - req.base_mult, req.base_cost...: Các chỉ số rời
        # => TA PHẢI GỘP CHÚNG LẠI THÀNH 1 DICT

        # A. Parse config_data hiện tại ra dict
        try:
            final_config_dict = json.loads(req.config_data) if req.config_data else {}
        except:
            final_config_dict = {}

        # B. Nhét thêm các chỉ số sức mạnh vào dict này
        # (Để hàm selectSkillForEdit ở JS có thể đọc được c.base_mult, c.base_cost...)
        final_config_dict["base_mult"] = req.base_mult
        final_config_dict["base_cost"] = req.base_cost
        final_config_dict["vfx_class"] = req.vfx_class
        final_config_dict["vfx_target"] = req.vfx_target
        final_config_dict["currency"] = req.currency

        # C. Ép ngược lại thành chuỗi JSON để lưu vào DB
        final_config_json_string = json.dumps(final_config_dict, ensure_ascii=False)


        # 3. LƯU VÀO DB
        skill = db.exec(select(SkillTemplate).where(SkillTemplate.skill_id == current_id)).first()

        if not skill:
            # --- TẠO MỚI ---
            skill = SkillTemplate(
                skill_id=current_id,
                name=req.name,
                description=req.description,
                class_type=req.class_type,
                skill_type=req.skill_type,
                min_level=req.min_level,
                prerequisite_id=req.prerequisite_id if req.prerequisite_id else None,
                
                # 👇 QUAN TRỌNG: Lưu chuỗi JSON đã gộp tất cả chỉ số
                config_data=final_config_json_string 
            )
            db.add(skill)
        else:
            # --- CẬP NHẬT ---
            skill.name = req.name
            skill.description = req.description
            skill.class_type = req.class_type
            skill.skill_type = req.skill_type
            skill.min_level = req.min_level
            skill.prerequisite_id = req.prerequisite_id if req.prerequisite_id else None
            
            # 👇 Cập nhật JSON mới
            skill.config_data = final_config_json_string
            
            db.add(skill)
            
        db.commit()
        
        return {
            "status": "success", 
            "message": f"Đã lưu kỹ năng {req.name}",
            "real_id": current_id
        }

    except Exception as e:
            print("❌ LỖI LƯU SKILL:", str(e))
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=f"Lỗi Server: {str(e)}")
    
# ==========================================
# QUẢN LÝ DANH HIỆU (TITLES)
# ==========================================

# 1. Lấy danh sách danh hiệu (Sắp xếp theo KPI tăng dần)
@router.get("/titles")
def get_titles(db: Session = Depends(get_db)):
    # Sắp xếp KPI từ thấp đến cao để dễ nhìn lộ trình
    titles = db.exec(select(Title).order_by(Title.min_kpi)).all()
    return titles

# 2. Tạo danh hiệu mới
class TitleRequest(BaseModel):
    name: str
    min_kpi: int
    color: str = "#fbbf24"

@router.post("/titles")
def create_title(req: TitleRequest, db: Session = Depends(get_db)):
    # Kiểm tra trùng tên hoặc trùng mốc KPI (tùy chọn)
    existing = db.exec(select(Title).where(Title.min_kpi == req.min_kpi)).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Đã có danh hiệu '{existing.name}' ở mốc KPI {req.min_kpi} rồi!")

    new_title = Title(name=req.name, min_kpi=req.min_kpi, color=req.color)
    db.add(new_title)
    db.commit()
    db.refresh(new_title)
    return {"status": "success", "data": new_title}

# 3. Xóa danh hiệu
@router.delete("/titles/{title_id}")
def delete_title(title_id: int, db: Session = Depends(get_db)):
    title = db.get(Title, title_id)
    if not title:
        raise HTTPException(status_code=404, detail="Danh hiệu không tồn tại")
    
    db.delete(title)
    db.commit()
    return {"status": "success", "message": "Đã xóa danh hiệu"}

# Hệ thống quản lý loi đài admin

# 2. Lấy lịch sử trận đấu đã xong (Completed)
@router.get("/arena/history")
def get_arena_history(limit: int = 50, db: Session = Depends(get_db)):
    statement = select(ArenaMatch).where(ArenaMatch.status == "completed").order_by(desc(ArenaMatch.created_at)).limit(limit)
    matches = db.exec(statement).all()
    return matches

# 3. Admin Hủy trận đấu (Xóa hoặc đổi status sang cancelled)
@router.post("/arena/cancel/{match_id}")
def admin_cancel_match(match_id: int, db: Session = Depends(get_db)):
    match = db.get(ArenaMatch, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Không tìm thấy trận đấu")
    
    # Chuyển trạng thái sang cancelled thay vì xóa để lưu vết
    match.status = "cancelled"
    db.add(match)
    db.commit()
    return {"success": True, "message": f"Đã hủy trận đấu #{match_id}"}
@router.get("/arena/data")
def get_admin_arena_data(db: Session = Depends(get_db)):
    # Lấy trận đấu đang treo (pending) 
    pending_matches = db.exec(
        select(ArenaMatch)
        .where(ArenaMatch.status == "pending")
        .order_by(desc(ArenaMatch.created_at))
    ).all()

    # Lấy lịch sử trận đã xong (completed) 
    history_matches = db.exec(
        select(ArenaMatch)
        .where(ArenaMatch.status == "completed")
        .order_by(desc(ArenaMatch.created_at))
        .limit(50)
    ).all()

    return {
        "success": True,
        "pending": pending_matches,
        "history": history_matches
    }

@router.get("/get-system-config") 
def get_system_config(db: Session = Depends(get_db)):
    # Lấy Config Charm
    charm_record = db.exec(select(SystemConfig).where(SystemConfig.key == "charm_setup")).first()
    charm_data = json.loads(charm_record.value) if charm_record else None

    # Lấy Config Forge
    forge_record = db.exec(select(SystemConfig).where(SystemConfig.key == "forge_setup")).first()
    forge_data = json.loads(forge_record.value) if forge_record else None

    return {
        "charm_setup": charm_data,
        "forge_setup": forge_data
    }

# 3. API Lưu cấu hình hệ thống tạo charm

@router.post("/save-system-config")
def save_system_config(
    charm_data: Optional[CharmSetupPayload] = None, 
    forge_data: Optional[ForgeSetupPayload] = None, 
    db: Session = Depends(get_db)
):
    try:
        # Lưu cấu hình Charm
        if charm_data:
            charm_json = charm_data.json()
            record = db.exec(select(SystemConfig).where(SystemConfig.key == "charm_setup")).first()
            if not record:
                record = SystemConfig(key="charm_setup", value=charm_json)
                db.add(record)
            else:
                record.value = charm_json
                db.add(record)

        # Lưu cấu hình Forge
        if forge_data:
            forge_json = forge_data.json()
            record = db.exec(select(SystemConfig).where(SystemConfig.key == "forge_setup")).first()
            if not record:
                record = SystemConfig(key="forge_setup", value=forge_json)
                db.add(record)
            else:
                record.value = forge_json
                db.add(record)

        db.commit()
        return {"status": "success", "message": "Đã cập nhật cấu hình hệ thống!"}

    except Exception as e:
        print("Lỗi lưu config:", e)
        raise HTTPException(status_code=500, detail=str(e))
# hàm đọc file excel nhập điểm từ admin cho trang ph xem
@router.post("/gradebook/import-scores")
async def import_scores(file: UploadFile = File(...), semester: str = Form(...), db: Session = Depends(get_db)):
    try:
        contents = await file.read()
        # Đọc file không lấy header trước để dò tìm
        df_raw = pd.read_excel(BytesIO(contents), header=None)
        
        # 1. TỰ ĐỘNG TÌM HÀNG CHỨA TIÊU ĐỀ "Họ tên"
        header_row_index = None
        for i, row in df_raw.iterrows():
            # Kiểm tra xem trong hàng này có ô nào chứa chữ "họ" và "tên" không
            if any("họ" in str(cell).lower() and "tên" in str(cell).lower() for cell in row):
                header_row_index = i
                break
        
        if header_row_index is None:
            return {"status": "error", "message": "Không thể tìm thấy hàng tiêu đề có cột 'Họ tên' trong file Excel!"}

        # 2. Thiết lập lại DataFrame từ hàng tiêu đề đã tìm thấy
        df = pd.read_excel(BytesIO(contents), header=header_row_index)
        df.columns = [str(c).strip() for c in df.columns] # Làm sạch tên cột

        # --- Giữ nguyên logic mapping và update bên dưới ---
        subject_map = {
            "Toán": f"toan_{semester}",
            "Ngữ văn": f"van_{semester}",
            "Ngoại ngữ": f"anh_{semester}",
            "GDCD": f"gdcd_{semester}",
            "Công nghệ": f"cong_nghe_{semester}",
            "Tin học": f"tin_{semester}",
            "Khoa học": f"khtn_{semester}",
            "Lịch sử": f"lsdl_{semester}"
        }

        name_col = next((c for c in df.columns if "họ" in c.lower() and "tên" in c.lower()), None)
        updated_count = 0
        
        for _, row in df.iterrows():
            full_name = str(row[name_col]).strip()
            if not full_name or full_name.lower() == "nan": continue

            student = db.exec(select(Player).where(Player.full_name == full_name)).first()
            if student:
                for excel_keyword, db_field in subject_map.items():
                    actual_col = next((c for c in df.columns if excel_keyword.lower() in c.lower()), None)
                    if actual_col:
                        val = row[actual_col]
                        clean_score = float(val) if pd.notnull(val) else 0.0
                        setattr(student, db_field, clean_score)
                db.add(student)
                updated_count += 1
        
        db.commit()
        return {"status": "success", "message": f"Đã cập nhật điểm {semester.upper()} cho {updated_count} học sinh."}

    except Exception as e:
        return {"status": "error", "message": f"Lỗi: {str(e)}"}