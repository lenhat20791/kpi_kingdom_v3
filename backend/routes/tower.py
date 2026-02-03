from fastapi import APIRouter, Depends, HTTPException, Body
from sqlmodel import Session, select
from sqlalchemy import func
from typing import List, Optional
import random
import json
from pydantic import BaseModel
from routes.auth import get_current_user
from game_logic.level import add_exp_to_player
# 1. Import Database & Models
# Lưu ý: Import Inventory as PlayerItem để code ngữ nghĩa hơn (giống pets.py)
from database import get_db, Player, QuestionBank, TowerProgress, TowerSetting, Item, Inventory as PlayerItem

router = APIRouter()

# --- MODEL DỮ LIỆU (SCHEMA) ---
# Player gửi lên không cần player_id nữa, Server tự biết là ai
class TowerCompleteRequest(BaseModel):
    floor: int
    is_win: bool

# --- CÁC HÀM HELPER (LOGIC GỐC TỪ ADMIN.PY) ---

def get_difficulty_by_floor(floor: int) -> str:
    """Xác định độ khó dựa trên số tầng (Quy tắc 1-100)"""
    if 1 <= floor <= 10: return "Medium"
    elif 11 <= floor <= 20: return "Hard"
    elif 21 <= floor <= 60: return "Extreme"
    elif 61 <= floor <= 100: return "Hell"
    return "Medium"

def get_monster_stats_by_floor(floor: int) -> dict:
    """Tính chỉ số Quái vật (HP/ATK) theo công thức lũy tiến"""
    # 1. HP cơ bản (Giữ nguyên công thức của bạn)
    base_hp = 50 + (floor * 15)
    
    # 2. Hệ số nhân (Multiplier) theo bậc
    if floor <= 10: multiplier = 1.0
    elif floor <= 20: multiplier = 1.2
    elif floor <= 60: multiplier = 1.5
    else: multiplier = 2.0
        
    final_hp = int(base_hp * multiplier)
    
    # 3. Sát thương (ATK)
    monster_atk = 50 + (floor // 5) 

    # --- CẬP NHẬT MỚI: ẢNH NGẪU NHIÊN 1-10 ---
    # Random từ 1 đến 10 bất kể tầng nào
    random_img_id = random.randint(1, 10)
    image_path = f"assets/monsters/{random_img_id}.png"

    return {
        "monster_hp": final_hp,
        "monster_atk": monster_atk,
        # Lưu ý: Frontend đang đọc 'monster_name' nên tôi đổi key 'name' -> 'monster_name' cho khớp
        "monster_name": f"Hộ Vệ Tầng {floor}", 
        "image": image_path
    }

# --- API GAMEPLAY (DÀNH CHO PLAYER) ---

# Tạo model nhận dữ liệu
class StartCombatRequest(BaseModel):
    floor: int
# --- 2. API BẮT ĐẦU leo tháp(POST /start) ---
@router.post("/start") 
async def start_floor_combat(
    req: StartCombatRequest, # ✅ Khớp với class ở trên
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    floor = req.floor
    """Bắt đầu leo tháp: Trả về Quái & Câu hỏi"""
    
    # 1. KIỂM TRA TIẾN ĐỘ (Chống nhảy cóc)
    progress = db.exec(select(TowerProgress).where(TowerProgress.player_id == current_user.id)).first()
    
    # Nếu chưa chơi bao giờ, tạo mới luôn
    if not progress:
        progress = TowerProgress(player_id=current_user.id, current_floor=1, max_floor=1)
        db.add(progress)
        db.commit()
    
    current_floor_allowed = progress.current_floor
    
    # Nếu đòi đánh tầng cao hơn tầng hiện tại -> Chặn
    if floor > current_floor_allowed:
         raise HTTPException(status_code=400, detail=f"Bạn chưa mở khóa tầng {floor}! Hãy vượt qua tầng {current_floor_allowed} trước.")

    # 2. LẤY CÂU HỎI (FIX: TÌM KIẾM KHÔNG PHÂN BIỆT HOA THƯỜNG)
    target_diff = get_difficulty_by_floor(floor)
    
    # Dùng func.lower để 'Medium' hay 'medium' đều tìm được
    statement = (
        select(QuestionBank)
        .where(func.lower(QuestionBank.difficulty) == target_diff.lower())
        .order_by(func.random())
        .limit(5)
    )
    questions_db = db.exec(statement).all()

    # Fallback: Nếu không tìm thấy câu đúng độ khó, lấy ngẫu nhiên 5 câu bất kỳ
    if not questions_db:
        print(f"⚠️ Không tìm thấy câu hỏi độ khó '{target_diff}'. Đang lấy ngẫu nhiên...")
        fallback_stmt = select(QuestionBank).order_by(func.random()).limit(5)
        # ✅ LƯU Ý: Phải gán vào biến questions_db
        questions_db = db.exec(fallback_stmt).all()

    # Nếu kho rỗng hoàn toàn
    if not questions_db:
         raise HTTPException(status_code=404, detail="Hệ thống chưa có dữ liệu câu hỏi trong QuestionBank!")

    # XỬ LÝ DỮ LIỆU: Thêm trường 'explain' tự động cho Frontend
    formatted_questions = []
    for q in questions_db:
        try:
            # a. Giải nén mảng options từ chuỗi JSON
            # VD: '["Đáp án A", "Đáp án B",...]' -> ["Đáp án A", "Đáp án B"]
            options_list = json.loads(q.options_json)
            
            # Đảm bảo có đủ 4 đáp án (nếu thiếu thì điền rỗng)
            while len(options_list) < 4:
                options_list.append("")

            val_a = options_list[0]
            val_b = options_list[1]
            val_c = options_list[2]
            val_d = options_list[3]

            # b. Tìm xem đáp án nào là đúng (Map về 'a', 'b', 'c', 'd')
            correct_char = "a" # Mặc định
            
            # So sánh nội dung đáp án đúng với từng option
            if q.correct_answer == val_a: correct_char = "a"
            elif q.correct_answer == val_b: correct_char = "b"
            elif q.correct_answer == val_c: correct_char = "c"
            elif q.correct_answer == val_d: correct_char = "d"
            
            # c. Tạo object trả về
            q_final = {
                "id": q.id,
                "content": q.content,
                "option_a": val_a,
                "option_b": val_b,
                "option_c": val_c,
                "option_d": val_d,
                "correct_ans": correct_char, # Frontend cần 'a', 'b'..
                "explain": q.explanation if hasattr(q, "explanation") else f"Đáp án đúng là: {correct_char.upper()}"
            }
            formatted_questions.append(q_final)

        except Exception as e:
            print(f"Lỗi parse câu hỏi ID {q.id}: {e}")
            continue

    # 4. LẤY QUÁI
    monster = get_monster_stats_by_floor(floor)

    return {
        "floor": floor,
        "difficulty": target_diff,
        "monster": monster,
        "questions": formatted_questions
    }   

@router.post("/complete-floor")
async def complete_floor(
    req: TowerCompleteRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Xử lý kết quả trận đấu: Tính quà & Mở tầng mới"""
    
    # 1. KIỂM TRA HỢP LỆ
    progress = db.exec(select(TowerProgress).where(TowerProgress.player_id == current_user.id)).first()
    
    if not progress:
        progress = TowerProgress(player_id=current_user.id, current_floor=1, max_floor=1)
        db.add(progress)
        db.commit()
        db.refresh(progress)

    # Chỉ xử lý nếu đánh đúng tầng hiện tại (Hoặc tầng cũ để farm, nhưng ko mở tầng mới)
    if req.floor > progress.current_floor:
         return {"status": "cheat", "message": "Gian lận! Tầng chưa mở."}

    if not req.is_win:
        return {"status": "failed", "message": "Thất bại. Hãy cố gắng lần sau!"}

    # 2. TÍNH QUÀ THƯỞNG (Dựa trên TowerSetting)
    # Đọc cấu hình từ DB
    setting_record = db.exec(select(TowerSetting).where(TowerSetting.id == 1)).first()
    
    received_rewards = []
    
    # Nếu có cấu hình quà
    if setting_record and setting_record.config_data:
        try:
            config = json.loads(setting_record.config_data)
            difficulty = get_difficulty_by_floor(req.floor)
            reward_pool = config.get("rewards", {}).get(difficulty, [])
            
            # Quay số RNG
            for item in reward_pool:
                rate = int(item.get("rate", 0))
                roll = random.randint(1, 100)
                
                if roll <= rate:
                    item_type = item.get("type", "").lower()
                    name_code = item.get("name")
                    qty = int(item.get("amount", 0))

                    # A. Cộng EXP/Tiền tệ
                    if item_type == "exp":
                        add_exp_to_player(current_user, qty)
                        received_rewards.append(f"+{qty} EXP")
                        
                    elif item_type == "currency":
                        if name_code == "kpi": current_user.kpi += qty
                        elif name_code == "tri_thuc": current_user.tri_thuc += qty
                        elif name_code == "chien_tich": current_user.chien_tich += qty
                        elif name_code == "vinh_du": current_user.vinh_du += qty
                        received_rewards.append(f"+{qty} {name_code.upper()}")

                    # B. Cộng Vật Phẩm
                    elif item_type == "item":
                        # Cần tìm item_id từ bảng Item (Giả sử name lưu ID)
                        # Nếu name lưu tên text thì phải query tìm ID. Ở đây giả định admin lưu ID.
                        try:
                            item_id = int(name_code)
                            game_item = db.get(Item, item_id)
                            if game_item:
                                # Kiểm tra túi
                                inv_item = db.exec(select(PlayerItem).where(
                                    PlayerItem.player_id == current_user.id,
                                    PlayerItem.item_id == item_id
                                )).first()
                                
                                if inv_item:
                                    inv_item.quantity += qty
                                else:
                                    # Thêm mới vào túi
                                    new_inv = PlayerItem(player_id=current_user.id, item_id=item_id, quantity=qty)
                                    db.add(new_inv)
                                    
                                received_rewards.append(f"+{qty} {game_item.name}")
                        except:
                            pass # Bỏ qua nếu lỗi ID item
        except Exception as e:
            print(f"Lỗi chia quà: {e}")

    # Nếu không có quà cấu hình -> Thưởng mặc định an ủi
    if not received_rewards:
        base_gold = 10 * req.floor
        current_user.chien_tich += base_gold
        received_rewards.append(f"+{base_gold} Chiến Tích (Mặc định)")

    # 3. CẬP NHẬT TIẾN ĐỘ (MỞ KHÓA TẦNG MỚI)
    is_new_record = False
    if req.floor == progress.current_floor:
        progress.current_floor += 1
        if progress.current_floor > progress.max_floor:
            progress.max_floor = progress.current_floor
        is_new_record = True
        db.add(progress)

    # 4. LƯU TẤT CẢ (Atomic Commit)
    db.add(current_user)
    db.commit()

    return {
        "status": "success",
        "new_floor": progress.current_floor,
        "is_new_record": is_new_record,
        "rewards_text": received_rewards
    }