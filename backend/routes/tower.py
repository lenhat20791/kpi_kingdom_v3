import random
import json
import os
import sys
import unicodedata
from game_logic import item_processor
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlmodel import Session, select
from sqlalchemy import func
from typing import List, Optional
from pydantic import BaseModel
from routes.auth import get_current_user
from game_logic.level import add_exp_to_player
# 1. Import Database & Models
# Lưu ý: Import Inventory as PlayerItem để code ngữ nghĩa hơn (giống pets.py)
from database import get_db, Player, QuestionBank, TowerProgress, TowerSetting, Item, Inventory as PlayerItem

current_dir = os.path.dirname(os.path.abspath(__file__)) # Đang ở backend/routes
parent_dir = os.path.dirname(current_dir)              # Ra ngoài thư mục cha (backend)
sys.path.append(parent_dir)
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
    monster_atk = 50 + (floor // 1) 

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
    req: StartCombatRequest, 
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    floor = req.floor
    """Phiên bản sửa lỗi Tiếng Việt & Logic tìm đáp án"""

    # 1. KIỂM TRA TIẾN ĐỘ
    progress = db.exec(select(TowerProgress).where(TowerProgress.player_id == current_user.id)).first()
    if not progress:
        progress = TowerProgress(player_id=current_user.id, current_floor=1, max_floor=1)
        db.add(progress)
        db.commit()
    
    current_floor_allowed = progress.current_floor
    if floor > current_floor_allowed:
         raise HTTPException(status_code=400, detail=f"Chưa mở tầng {floor}!")

    # 2. LẤY CÂU HỎI
    target_diff = get_difficulty_by_floor(floor)
    statement = select(QuestionBank).where(func.lower(QuestionBank.difficulty) == target_diff.lower()).order_by(func.random()).limit(10)
    questions_db = db.exec(statement).all()

    if not questions_db:
        fallback_stmt = select(QuestionBank).order_by(func.random()).limit(10)
        questions_db = db.exec(fallback_stmt).all()

    if not questions_db:
         raise HTTPException(status_code=404, detail="Kho câu hỏi rỗng!")

    # =========================================================
    # 3. LOGIC TÌM ĐÁP ÁN ĐÚNG (FIX UNICODE TIẾNG VIỆT)
    # =========================================================
    
    def clean_text(s):
        if not s: return ""
        # 1. Chuyển thành chuỗi
        s = str(s)
        # 2. Chuẩn hóa Unicode (NFC) để sửa lỗi font tiếng Việt (á vs a + sắc)
        s = unicodedata.normalize('NFC', s)
        # 3. Chữ thường + Xóa khoảng trắng thừa + Xóa dấu chấm cuối câu
        return s.strip().lower().rstrip('.')

    formatted_questions = []
    
    for q in questions_db:
        try:
            options_list = json.loads(q.options_json)
            while len(options_list) < 4: options_list.append("")

            val_a = options_list[0]
            val_b = options_list[1]
            val_c = options_list[2]
            val_d = options_list[3]

            # Làm sạch đáp án đúng từ DB
            raw_correct = str(q.correct_answer).strip()
            target_ans = clean_text(raw_correct)
            
            # --- CHIẾN THUẬT SO SÁNH 3 LỚP ---
            final_char = None # Không đặt mặc định là 'a' vội để dễ debug

            # Lớp 1: Kiểm tra xem DB có lưu thẳng là "a", "b", "c", "d" không?
            if raw_correct.lower() in ['a', 'b', 'c', 'd', 'a.', 'b.', 'c.', 'd.']:
                final_char = raw_correct.lower().replace('.', '')
            
            # Lớp 2: So sánh nội dung (Text vs Text) - Chính xác 100%
            elif target_ans == clean_text(val_a): final_char = "a"
            elif target_ans == clean_text(val_b): final_char = "b"
            elif target_ans == clean_text(val_c): final_char = "c"
            elif target_ans == clean_text(val_d): final_char = "d"

            # Lớp 3: So sánh tương đối (Chứa trong nhau) - Dùng khi dữ liệu DB thiếu/thừa từ
            else:
                # Kiểm tra: Đáp án DB nằm trong Option (VD: DB="So sánh", Option="B. So sánh")
                if target_ans in clean_text(val_a): final_char = "a"
                elif target_ans in clean_text(val_b): final_char = "b"
                elif target_ans in clean_text(val_c): final_char = "c"
                elif target_ans in clean_text(val_d): final_char = "d"
                # Kiểm tra ngược lại: Option nằm trong DB (VD: DB="Biện pháp so sánh", Option="So sánh")
                elif clean_text(val_a) in target_ans: final_char = "a"
                elif clean_text(val_b) in target_ans: final_char = "b"
                elif clean_text(val_c) in target_ans: final_char = "c"
                elif clean_text(val_d) in target_ans: final_char = "d"

            # CỨU CÁNH CUỐI CÙNG: Nếu vẫn không tìm thấy -> Buộc phải gán A và in Log lỗi
            if final_char is None:
                print(f"❌ LỖI DATA ID {q.id}: Không khớp đáp án nào!")
                print(f"   - DB Correct: '{q.correct_answer}' (Clean: {target_ans})")
                print(f"   - Option A: '{val_a}' (Clean: {clean_text(val_a)})")
                print(f"   - Option B: '{val_b}' (Clean: {clean_text(val_b)})")
                final_char = "a" # Fallback để game không crash

            formatted_questions.append({
                "id": q.id,
                "content": q.content,
                "option_a": val_a,
                "option_b": val_b,
                "option_c": val_c,
                "option_d": val_d,
                "correct_ans": final_char, 
                "explain": q.explanation if hasattr(q, "explanation") else f"Đáp án đúng: {final_char.upper()}"
            })

        except Exception as e:
            print(f"Lỗi parse câu hỏi ID {q.id}: {e}")
            continue

    return {
        "floor": floor,
        "difficulty": target_diff,
        "monster": get_monster_stats_by_floor(floor),
        "questions": formatted_questions
    }

@router.post("/complete-floor")
async def complete_floor(
    req: TowerCompleteRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Xử lý kết quả trận đấu: Tính quà & Mở tầng mới"""
    
    # 1. TÌM HOẶC TẠO TIẾN ĐỘ CHO NGƯỜI MỚI
    progress = db.exec(select(TowerProgress).where(TowerProgress.player_id == current_user.id)).first()
    if not progress:
        progress = TowerProgress(player_id=current_user.id, current_floor=1, max_floor=1)
        db.add(progress)
        db.commit()
        db.refresh(progress)

    # Biến an toàn (Khởi tạo trước để tránh lỗi UnboundLocalError)
    new_floor_val = progress.current_floor 
    is_new_record = False
    received_rewards = []

    # Ép kiểu dữ liệu ngay từ đầu để so sánh chuẩn xác
    client_floor = int(req.floor)
    server_floor = int(progress.current_floor)

    # Check gian lận
    if client_floor > server_floor:
         return {"status": "cheat", "message": "Gian lận! Tầng chưa mở."}

    # ---------------------------------------------------------
    # 2. XỬ LÝ KHI THUA (LOSE)
    # ---------------------------------------------------------
    if not req.is_win:
        consolation_msg = "Thất bại. Hãy cố gắng lần sau!"
        earned_exp = 0
        
        # Logic tính quà an ủi (Giữ nguyên code của bạn)
        try:
            setting_record = db.exec(select(TowerSetting).where(TowerSetting.id == 1)).first()
            if setting_record and setting_record.config_data:
                config = json.loads(setting_record.config_data)
                difficulty = get_difficulty_by_floor(client_floor)
                reward_pool = config.get("rewards", {}).get(difficulty, [])
                
                total_config_exp = sum(int(item.get("amount", 0)) for item in reward_pool if item.get("type", "").lower() == "exp")
                
                if total_config_exp > 0:
                    earned_exp = total_config_exp // 3
                    if earned_exp > 0:
                        add_exp_to_player(current_user, earned_exp)
                        db.add(current_user)
                        db.commit()
                        consolation_msg = f"Thất bại! Nhận +{earned_exp} EXP an ủi."
        except Exception as e:
            print(f"Lỗi tính quà an ủi: {e}")

        return {
            "status": "failed", 
            "message": consolation_msg,
            "rewards_text": [f"+{earned_exp} EXP (An ủi)"] if earned_exp > 0 else []
        }

    # ---------------------------------------------------------
    # 3. XỬ LÝ KHI THẮNG (WIN) - TÍNH QUÀ (ĐÃ FIX LỖI NHẬN DIỆN TÊN)
    # ---------------------------------------------------------
    try:
        setting_record = db.exec(select(TowerSetting).where(TowerSetting.id == 1)).first()
        if setting_record and setting_record.config_data:
            config = json.loads(setting_record.config_data)
            difficulty = get_difficulty_by_floor(client_floor)
            reward_pool = config.get("rewards", {}).get(difficulty, [])
            
            for item in reward_pool:
                # Random tỉ lệ rơi
                if random.randint(1, 100) <= int(item.get("rate", 0)):
                    item_type = str(item.get("type", "")).strip().lower()
                    
                    # 🔥 Lấy tên gốc từ DB ("Điểm KPI (Chính)", "Tri Thức (Xanh)")
                    raw_name = str(item.get("name", "")).strip() 
                    qty = int(item.get("amount", 0))

                    if qty <= 0: continue

                    # --- 1. XỬ LÝ EXP ---
                    if item_type == "exp":
                        add_exp_to_player(current_user, qty)
                        received_rewards.append(f"+{qty} EXP")
                    
                    # --- 2. XỬ LÝ TIỀN TỆ (ĐÃ NÂNG CẤP NHẬN DIỆN) ---
                    elif item_type == "currency":
                        is_added = False
                        
                        # Chuyển về chữ thường để so sánh tìm từ khóa
                        name_lower = raw_name.lower()
                        
                        # 🔥 LOGIC MAP TÊN HIỂN THỊ -> TÊN BIẾN TRONG DB
                        if "kpi" in name_lower:
                            current_user.kpi = float(current_user.kpi or 0.0) + float(qty)
                            received_rewards.append(f"+{qty} KPI")
                            is_added = True
                            
                        elif "tri th" in name_lower or "tri_thuc" in name_lower: # Bắt dính "Tri Thức (Xanh)"
                            current_user.tri_thuc = int(current_user.tri_thuc or 0) + qty
                            received_rewards.append(f"+{qty} Tri Thức")
                            is_added = True
                            
                        elif "chien tich" in name_lower or "chiến tích" in name_lower:
                            current_user.chien_tich = int(current_user.chien_tich or 0) + qty
                            received_rewards.append(f"+{qty} Chiến Tích")
                            is_added = True
                            
                        elif "vinh du" in name_lower or "vinh dự" in name_lower:
                            current_user.vinh_du = int(current_user.vinh_du or 0) + qty
                            received_rewards.append(f"+{qty} Vinh Dự")
                            is_added = True
                        
                        # Nếu cộng thành công thì lưu ngay
                        if is_added:
                            db.add(current_user)
                    
                    # --- 3. XỬ LÝ VẬT PHẨM ---
                    elif item_type == "item":
                        try:
                            # Nếu tên là số (ID) thì dùng luôn, nếu không thì bỏ qua
                            if raw_name.isdigit():
                                item_id = int(raw_name)
                                inv_item = db.exec(select(PlayerItem).where(
                                    PlayerItem.player_id == current_user.id,
                                    PlayerItem.item_id == item_id
                                )).first()
                                
                                if inv_item: 
                                    inv_item.quantity += qty
                                    db.add(inv_item)
                                else: 
                                    db.add(PlayerItem(player_id=current_user.id, item_id=item_id, quantity=qty))
                                
                                game_item = db.get(Item, item_id)
                                item_name = game_item.name if game_item else f"Item {item_id}"
                                received_rewards.append(f"+{qty} {item_name}")
                        except: pass
                    # --- 4. XỬ LÝ CHARM (MỚI) ---
                    elif item_type == "charm":
                        try:
                            # Lấy mã độ hiếm từ tên (VD: RANDOM_CHARM_MAGIC -> MAGIC)
                            # Lưu ý: Code này giả định Admin lưu mã charm vào trường "name"
                            rarity = raw_name.replace("RANDOM_CHARM_", "")
                            
                            # Gọi hàm tạo Charm
                            new_charm = item_processor.generate_charm(db, current_user.id, rarity)
                            
                            if new_charm:
                                received_rewards.append(f"Trang bị: {new_charm.name}")
                        except Exception as e:
                            print(f"❌ Lỗi tạo Charm: {e}")

    except Exception as e:
        print(f"Lỗi chia quà: {e}")

    # ---------------------------------------------------------
    # 4. LOGIC TĂNG TẦNG & ĐỒNG BỘ DỮ LIỆU (FIXED DEADLOCK)
    # ---------------------------------------------------------
    
    print(f"🔍 DEBUG: Client={client_floor} | Server={server_floor}")

    # A. Nếu đánh đúng tầng hiện tại -> Lên cấp
    if client_floor == server_floor:
        progress.current_floor += 1
        if progress.current_floor > progress.max_floor:
            progress.max_floor = progress.current_floor
        is_new_record = True
        print(f"🚀 UP TẦNG: {server_floor} -> {progress.current_floor}")

    # B. 🔥 BẮT BUỘC ĐỒNG BỘ SANG BẢNG PLAYER (DÙ LÀ FARM HAY LEO THÁP)
    # Đây là dòng quan trọng nhất để sửa lỗi cái nút không nhảy số
    if current_user.tower_floor < progress.current_floor:
        print(f"🔧 AUTO-FIX: Player {current_user.tower_floor} -> {progress.current_floor}")
        current_user.tower_floor = progress.current_floor
        db.add(current_user)

    # Cập nhật giá trị trả về
    new_floor_val = progress.current_floor

    # 5. LƯU TẤT CẢ VÀO DB
    try:
        db.add(progress)
        db.add(current_user) # Lưu tiền, exp, và tower_floor
        db.commit()
        
        db.refresh(progress)
        db.refresh(current_user)
        
    except Exception as e:
        print(f"❌ LỖI DATABASE: {e}")
        db.rollback()
        return {"status": "error", "message": "Lỗi lưu dữ liệu"}

    return {
        "status": "success",
        "new_floor": new_floor_val, 
        "is_new_record": is_new_record,
        "rewards_text": received_rewards
    }