import pytz
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session, select
from jose import JWTError, jwt
from database import get_db, Player, Inventory, Item, ScoreLog
from routes.auth import SECRET_KEY, ALGORITHM, get_current_user
from datetime import datetime
from typing import List
from pydantic import BaseModel

# Cấu hình để lấy Token từ Header
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# 2. Đổi Tag thành "Player Area" cho đồng bộ
router = APIRouter(tags=["Player Area"])
router_public = APIRouter(tags=["Public Info"])

class AddMembersRequest(BaseModel):
    player_ids: List[int]
# 1. API Lấy danh sách học sinh chưa có tổ (Free Agents)
@router.get("/players/free-agents")
def get_free_agents(db: Session = Depends(get_db)):
    # Lấy những người có team_id = 0 (Chưa vào tổ) và không phải Admin
    statement = select(Player).where(Player.team_id == 0).where(Player.role != "admin")
    players = db.exec(statement).all()
    return players

# 2. API Kết nạp thành viên (Bulk Add)
@router.post("/team/add-members")
def add_members_to_team(
    req: AddMembersRequest, 
    current_user: Player = Depends(get_current_user), # Cần login để biết tổ trưởng là ai
    db: Session = Depends(get_db)
):
    # Chỉ U1 (Tổ trưởng) mới được dùng
    if current_user.role != "U1":
         raise HTTPException(status_code=403, detail="Chỉ Tổ Trưởng (U1) mới được quyền tuyển quân!")

    if current_user.team_id == 0:
         raise HTTPException(status_code=400, detail="Bạn chưa thuộc tổ nào nên không thể tuyển người!")

    count = 0
    for pid in req.player_ids:
        player = db.get(Player, pid)
        if player and player.team_id == 0: # Chỉ nhận người chưa có tổ
            player.team_id = current_user.team_id
            player.role = "U3" # Mặc định vào là Thành viên (U3)
            db.add(player)
            count += 1
            
    db.commit()
    return {"success": True, "message": f"Đã kết nạp thành công {count} chiến binh vào Tổ {current_user.team_id}!"}

# --- HÀM BẢO VỆ: Đổi Token lấy thông tin User ---
# Lưu ý: Hàm này cũng cần dùng db từ Depends(get_db)
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Không thể xác thực thông tin đăng nhập",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    # 3. Dùng db được inject vào, không tự mở Session(engine) nữa
    statement = select(Player).where(Player.username == username)
    player = db.exec(statement).first()
    if player is None:
        raise credentials_exception
    return player

# --- API 1: Xem thông tin bản thân (Profile) ---
@router.get("/users/me")
def read_users_me(current_user: Player = Depends(get_current_user)):
    """
    Player gọi API này để xem chỉ số của chính mình.
    Yêu cầu phải có Token (Header: Authorization: Bearer <token>)
    """
    return {
        "id": current_user.id,
        "username": current_user.username,
        "full_name": current_user.full_name,
        "kpi": current_user.kpi,
        "tri_thuc": current_user.tri_thuc,
        "chien_tich": current_user.chien_tich,
        "vinh_du": current_user.vinh_du,
        "hp": current_user.hp,
        "hp_max": current_user.hp_max,
        "level": current_user.level,
        "exp": current_user.exp
    }

# --- API 2: Xem túi đồ cá nhân ---
@router.get("/users/my-inventory")
def read_my_inventory(
    current_user: Player = Depends(get_current_user), 
    db: Session = Depends(get_db) # Inject db vào đây
):
    """
    Lấy danh sách vật phẩm trong túi của người đang đăng nhập.
    """
    # 4. Query chuẩn: Join bảng Inventory với Item 
    statement = (
        select(Inventory, Item)
        .join(Item)
        .where(Inventory.player_id == current_user.id)
    )
    results = db.exec(statement).all()
    
    inventory_list = []
    for inv, item in results:
        inventory_list.append({
            "item_id": item.id,
            "name": item.name,
            "quantity": inv.quantity,
            "description": item.description, # Nếu bảng Item có cột này
            # Lưu ý: Bảng Item dùng config JSON, nên nếu muốn lấy category/rarity
            # có thể cần parse JSON hoặc lấy trường mặc định nếu có.
            # Tạm thời map các trường cơ bản:
            "image_url": item.image_url,
            "currency_type": item.currency_type
        })
        
    return inventory_list

@router_public.get("/players/{username}")
def get_public_player_info(username: str, db: Session = Depends(get_db)):
    """API lấy thông tin công khai của người chơi (Cho Lôi đài & Soi info)"""
    player = db.exec(select(Player).where(Player.username == username)).first()
    
    if not player:
        # Nếu không thấy thì trả về thông tin mặc định để không crash game
        return {
            "username": username,
            "full_name": "Unknown",
            "kpi": 0,
            "class_type": "Novice"
        }
    
    return {
        "username": player.username,
        "full_name": player.full_name,
        "class_type": player.class_type,
        "kpi": player.kpi or 0,
        "hp": player.hp,
        "hp_max": 100 # Hoặc tính theo công thức
    }
# =================================================================
#  👇 DÁN VÀO CUỐI FILE backend/routes/users.py
#  Đã bỏ Archer, dùng đúng công thức tính Dame/HP của bạn
# =================================================================

# 1. XỬ LÝ CHỌN CLASS (Khớp Frontend: /player/choose-class)
# Trong file users.py
@router.post("/player/choose-class")
def handle_choose_class(
    username: str = Query(...), 
    class_name: str = Query(...), 
    db: Session = Depends(get_db)
):
    # [CAMERA 1]: Kiểm tra xem code có chạy vào đây không
    print(f"🔥 DEBUG: Đang xử lý chọn Class cho {username} -> {class_name}")

    player = db.exec(select(Player).where(Player.username == username)).first()
    if not player:
        print("❌ DEBUG: Không tìm thấy User!")
        raise HTTPException(status_code=404, detail="Không tìm thấy User")

    # Logic chọn class
    valid_classes = ["WARRIOR", "MAGE"]
    if class_name not in valid_classes:
        raise HTTPException(status_code=400, detail="Class không hợp lệ")

    player.class_type = class_name
    
    # [CAMERA 2]: Kiểm tra chỉ số trước khi cộng
    print(f"📊 DEBUG: KPI hiện tại: {player.kpi}")

    # Logic cộng chỉ số
    base_hp_bonus = 300 if class_name == "WARRIOR" else 100
    base_atk_bonus = 5 if class_name == "WARRIOR" else 20 # Thêm atk cho máu lửa

    current_kpi = player.kpi if player.kpi else 0
    
    # Tính toán
    # Tính toán
    new_hp = int(10 + current_kpi + base_hp_bonus)
    new_atk = int(10 + (current_kpi / 10) + base_atk_bonus)

    player.hp = new_hp
    player.hp_max = new_hp  # <--- BẮT BUỘC PHẢI CÓ DÒNG NÀY
    player.atk = new_atk

    # [CAMERA 3]: Kiểm tra kết quả tính toán
    print(f"✅ DEBUG: Sau khi tính -> HP: {player.hp}, ATK: {player.atk}")

    db.add(player)
    db.commit()
    db.refresh(player)
    
    return {"message": f"Đã chuyển thành {class_name}. Máu: {player.hp}"}


# 2. XỬ LÝ DASHBOARD (Khớp Frontend: /api/player/dashboard)
@router_public.get("/player/dashboard")
def handle_get_dashboard(username: str, db: Session = Depends(get_db)):
    # 1. TÌM USER
    current_user = db.exec(select(Player).where(Player.username == username)).first()
    if not current_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # 2. LẤY DỮ LIỆU CƠ BẢN
    kpi = current_user.kpi or 0.0
    vi_pham = current_user.diem_vi_pham or 0
    class_type = (current_user.class_type or "NOVICE").upper()
    
    # Tổng điểm học tập (Để hiển thị thống kê, ko dùng tính dame nữa)
    d_phat_bieu = current_user.diem_phat_bieu or 0
    d_tx = current_user.diem_tx or 0
    d_hk = current_user.diem_hk or 0
    d_san_pham = current_user.diem_san_pham or 0
    total_test_score = d_phat_bieu + d_tx + d_hk + d_san_pham

    # =========================================================
    # 3. LẤY CHỈ SỐ TỪ DATABASE (QUAN TRỌNG)
    # =========================================================
    # Thay vì tính toán lại, ta lấy số liệu mà hệ thống Level Up đã lưu
    final_max_hp = current_user.hp_max
    if final_max_hp < 100: final_max_hp = 100 # Fallback nếu DB lỗi
    
    final_atk = current_user.atk
    if final_atk < 10: final_atk = 10 # Fallback nếu DB lỗi

    # =========================================================
    # 4. TÍNH HP HIỆN TẠI - LOGIC ÁN TỬ & HỒI SINH
    # =========================================================
    now = datetime.now()
    
    # [CASE 1] ĐANG CÓ ÁN TỬ HÌNH
    if current_user.revive_at:
        # Nếu giờ hồi sinh ở tương lai -> VẪN CHẾT
        if current_user.revive_at > now:
            current_hp = 0  # 💀 GÁN CỨNG = 0
        
        # Nếu giờ hồi sinh đã qua (Hết án phạt) -> HỒI SINH NGAY
        else:
            current_user.revive_at = None
            current_user.hp = final_max_hp # Hồi đầy máu
            
            db.add(current_user)
            db.commit()
            db.refresh(current_user)
            
            current_hp = final_max_hp

    # [CASE 2] NGƯỜI BÌNH THƯỜNG
    else:
        current_hp = current_user.hp
        
        # Logic an toàn dữ liệu
        if current_hp is None:
            current_hp = final_max_hp
        elif current_hp <= 0:
            # Lạ: Không có án tử mà máu <= 0 -> Hồi phục luôn
            current_user.hp = final_max_hp
            db.add(current_user)
            db.commit()
            current_hp = final_max_hp
        elif current_hp > final_max_hp:
            current_hp = final_max_hp

    # 5. TRẢ VỀ KẾT QUẢ (Đã thêm atk vào info)
    return {
        "info": {
            "username": current_user.username,
            "fullname": current_user.full_name, # Giữ cả 2 key cho chắc
            "full_name": current_user.full_name,
            "class_type": class_type,
            "level": current_user.level,
            "role": getattr(current_user, "role", "student"),
            "avatar": f"/assets/images/avatars/{class_type.lower()}.png" if class_type != "NOVICE" else "/assets/images/avatars/default.png",
            
            # 👇 CHỈ SỐ CHÍNH (Đã lấy từ DB)
            "hp": current_hp,
            "hp_max": final_max_hp,
            "atk": final_atk,  # ✅ Đã thêm dòng này!
            
            "kpi": kpi,
            "revive_at": current_user.revive_at, 
            "exp": current_user.exp,
            "next_level_exp": current_user.next_level_exp if current_user.next_level_exp else 100
        },
        # Vẫn giữ stats cho tương thích ngược (nếu cần)
        "stats": {
            "hp": current_hp,
            "max_hp": final_max_hp,
            "atk": final_atk,
            "kpi": kpi,
            "violation": vi_pham,
            "total_score": total_test_score
        },
        "scores": {
            "total_test": total_test_score,
            "speech": d_phat_bieu,
            "midterm": d_tx,
            "final": d_hk,
            "product": d_san_pham
        },
        "wallet": {
            "tri_thuc": current_user.tri_thuc,
            "chien_tich": current_user.chien_tich,
            "vinh_du": current_user.vinh_du
        },
        "history": []
    }

# --- Thêm vào cuối file backend/routes/users.py ---

@router.get("/team/members")
def get_team_members(
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 1. Kiểm tra nếu chưa có tổ
    if current_user.team_id == 0:
        return {
            "team_id": 0,
            "total_kpi": 0,
            "members": []
        }

    # 2. Lấy tất cả thành viên trong tổ (bao gồm cả Tổ trưởng)
    statement = select(Player).where(Player.team_id == current_user.team_id)
    members = db.exec(statement).all()

    # 3. Tính tổng KPI
    total_kpi = sum(m.kpi for m in members)

    return {
        "team_id": current_user.team_id,
        "total_kpi": total_kpi,
        "members": members
    }

# --- Thêm vào cuối file backend/routes/users.py ---

# 1. Schema dữ liệu đầu vào
class ScoreRequest(BaseModel):
    target_player_id: int
    score_type: str # "speech" (phát biểu), "tx" (thường xuyên), "product" (sản phẩm), "hk" (học kỳ)
    value: float

class ViolationRequest(BaseModel):
    target_player_id: int
    reason: str     # Lý do (để lưu log nếu cần)
    penalty: int    # Điểm trừ (ví dụ: -3, -5)

# 1. CẬP NHẬT API Nhập Điểm Học Tập
@router.post("/team/submit-score")
def submit_academic_score(
    req: ScoreRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != "U1":
        raise HTTPException(status_code=403, detail="Chỉ Tổ Trưởng mới được nhập điểm!")

    target = db.get(Player, req.target_player_id)
    if not target:
        raise HTTPException(status_code=404, detail="Không tìm thấy học sinh")

    # Cộng điểm vào chỉ số tương ứng
    desc = ""
    if req.score_type == "speech":
        target.diem_phat_bieu += int(req.value)
        desc = "Phát biểu"
    elif req.score_type == "tx":
        target.diem_tx += req.value
        desc = "Kiểm tra TX"
    elif req.score_type == "product":
        target.diem_san_pham += req.value
        desc = "Sản phẩm"
    elif req.score_type == "hk":
        target.diem_hk = req.value
        desc = "Thi Học Kỳ"
    
    # Cộng KPI và Vàng
    target.kpi += req.value
    target.tri_thuc += int(req.value * 100) # Thưởng 100 vàng mỗi điểm

    # --- 👇 LƯU LỊCH SỬ (LOG) 👇 ---
    new_log = ScoreLog(
        sender_name=current_user.full_name,
        target_name=target.full_name,
        category="academic",
        description=desc,
        value_change=req.value,
        target_id=target.id,
        sender_id=current_user.id,
        created_at=get_vn_time()
    )
    db.add(new_log)
    # -------------------------------

    db.add(target)
    db.commit()
    return {"success": True, "message": f"Đã cộng {req.value} điểm cho {target.full_name}"}

# 2. CẬP NHẬT API Phạt Vi Phạm
@router.post("/team/submit-violation")
def submit_violation(
    req: ViolationRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != "U1":
        raise HTTPException(status_code=403, detail="Chỉ Tổ Trưởng mới được xử phạt!")

    target = db.get(Player, req.target_player_id)
    if not target:
        raise HTTPException(status_code=404, detail="Không tìm thấy học sinh")

    # Cộng điểm vi phạm và Trừ KPI
    target.diem_vi_pham += req.penalty # Cộng số âm (VD: -3)
    target.kpi += req.penalty          # Trừ KPI
    
    # --- 👇 LƯU LỊCH SỬ (LOG) 👇 ---
    new_log = ScoreLog(
        sender_name=current_user.full_name,
        target_name=target.full_name,
        category="violation",
        description=req.reason, # Ví dụ: "Đi trễ"
        value_change=req.penalty,
        target_id=target.id,
        sender_id=current_user.id,
        created_at=get_vn_time()
    )
    db.add(new_log)
    # -------------------------------

    db.add(target)
    db.commit()
    return {"success": True, "message": f"Đã phạt {target.full_name} lỗi {req.reason}"}

# 3. THÊM API LẤY LỊCH SỬ (Cho Dashboard hiển thị)
@router.get("/logs")
def get_activity_logs(
    current_user: Player = Depends(get_current_user), # Cần biết ai đang xem
    db: Session = Depends(get_db)
):
    # Logic cũ: Lấy hết (Ai cũng thấy của nhau) --> SAI
    # statement = select(ScoreLog).order_by(ScoreLog.created_at.desc()).limit(20)

    # ✅ LOGIC MỚI: Chỉ lấy log CỦA CHÍNH MÌNH (Mình là người được cộng/trừ)
    statement = select(ScoreLog).where(
        ScoreLog.target_id == current_user.id
    ).order_by(ScoreLog.created_at.desc()).limit(20)
    
    logs = db.exec(statement).all()
    return logs

# Hàm phụ trợ lấy giờ Việt Nam
def get_vn_time():
    utc_now = datetime.utcnow()
    return utc_now # Lưu UTC vào DB, Frontend sẽ tự đổi sang giờ VN

# --- Thêm vào cuối file backend/routes/users.py ---

class PromoteRequest(BaseModel):
    target_id: int

@router.post("/team/promote")
def promote_member(
    req: PromoteRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 1. Chỉ U1 mới được quyền bổ nhiệm
    if current_user.role != "U1":
        raise HTTPException(status_code=403, detail="Chỉ Tổ Trưởng mới được quyền bổ nhiệm!")

    # 2. Tìm thành viên
    target = db.get(Player, req.target_id)
    if not target:
        raise HTTPException(status_code=404, detail="Không tìm thấy thành viên này")

    # 3. Kiểm tra xem có cùng tổ không
    if target.team_id != current_user.team_id:
        raise HTTPException(status_code=400, detail="Thành viên này không thuộc tổ của bạn")

    # 4. Logic Bổ nhiệm / Bãi nhiệm
    if target.role == "U3":
        target.role = "U2"
        message = f"Đã bổ nhiệm {target.full_name} làm Tổ Phó (U2)!"
    elif target.role == "U2":
        target.role = "U3"
        message = f"Đã bãi nhiệm {target.full_name} xuống thành viên (U3)!"
    elif target.role == "U1":
        raise HTTPException(status_code=400, detail="Bạn không thể tự giáng chức mình!")
    else:
        raise HTTPException(status_code=400, detail="Vai trò không hợp lệ để thao tác.")

    db.add(target)
    db.commit()
    return {"success": True, "message": message}