import json
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from database import get_db, Player, SkillTemplate
from routes.auth import get_current_user

router = APIRouter()



# 1. API HỌC KỸ NĂNG & AUTO TRANG BỊ
@router.post("/learn/{skill_id}")
def learn_skill(
    skill_id: str, 
    db: Session = Depends(get_db),
    current_user: Player = Depends(get_current_user) # 👈 LẤY USER THẬT
):
    # Lưu ý: Code dưới đây dùng 'current_user' thay vì 'player'
    
    # 1. Lấy thông tin Skill
    skill_temp = db.exec(select(SkillTemplate).where(SkillTemplate.skill_id == skill_id)).first()
    if not skill_temp:
        raise HTTPException(status_code=404, detail="Kỹ năng không tồn tại")

    # 2. Lấy giá tiền từ Config
    config = {}
    if skill_temp.config_data:
        try:
            config = json.loads(skill_temp.config_data)
        except:
            pass
    
    cost = config.get("base_cost", 0) 

    # --- KIỂM TRA ĐIỀU KIỆN ---

    # A. Kiểm tra Level
    required_level = skill_temp.min_level
    if current_user.level < required_level:
        raise HTTPException(
            status_code=400, 
            detail=f"Trình độ chưa đủ! Bạn cần đạt Level {required_level} để học kỹ năng này (Hiện tại: Lv.{current_user.level})"
        )

    # B. Kiểm tra Tiền (Tri Thức)
    if current_user.tri_thuc < cost:
        missing = cost - current_user.tri_thuc
        raise HTTPException(
            status_code=400, 
            detail=f"Không đủ Tri Thức! Cần {cost} (Thiếu {missing} điểm). Yêu cầu Level {required_level}."
        )

    # C. Kiểm tra đã học chưa
    player_skills = json.loads(current_user.skills_data or "{}")
    if skill_id in player_skills:
        raise HTTPException(status_code=400, detail="Bạn đã học kỹ năng này rồi!")

    # --- XỬ LÝ GIAO DỊCH ---
    
    # 1. Trừ tiền
    current_user.tri_thuc -= cost
    
    # 2. Lưu skill vào danh sách
    player_skills[skill_id] = 1
    current_user.skills_data = json.dumps(player_skills)

    # 3. Auto trang bị nếu là Active
    message = "Lĩnh ngộ thành công!"
    if skill_temp.skill_type == "ACTIVE":
        current_user.equipped_skill = skill_id
        message += " Đã tự động trang bị."
    
    # 4. Lưu vào Database
    db.add(current_user)
    db.commit()
    
    return {"status": "success", "message": message}

# 2. API TRANG BỊ THỦ CÔNG (Đổi skill)
@router.post("/equip/{skill_id}")
def equip_skill(
    skill_id: str, 
    db: Session = Depends(get_db),
    current_user: Player = Depends(get_current_user) # 👈 Dùng User thật
):
    # Tìm skill trong DB để kiểm tra xem có phải skill ACTIVE không
    skill_temp = db.exec(select(SkillTemplate).where(SkillTemplate.skill_id == skill_id)).first()
    
    if not skill_temp:
        raise HTTPException(404, detail="Kỹ năng không tồn tại")
    
    if skill_temp.skill_type != "ACTIVE":
        raise HTTPException(400, detail="Chỉ trang bị được skill Chủ Động (Active)")
        
    # Cập nhật cho user hiện tại
    current_user.equipped_skill = skill_id
    
    db.add(current_user)
    db.commit()
    
    return {"status": "success", "message": f"Đã trang bị {skill_temp.name}"}

# 3. API GỠ SKILL
@router.post("/unequip")
def unequip_skill(
    db: Session = Depends(get_db),
    current_user: Player = Depends(get_current_user) # 👈 Dùng User thật
):
    current_user.equipped_skill = None
    
    db.add(current_user)
    db.commit()
    
    return {"status": "success", "message": "Đã gỡ kỹ năng."}

# 4. API LẤY TRẠNG THÁI NGƯỜI CHƠI
@router.get("/my-status")
def get_status(
    current_user: Player = Depends(get_current_user) # 👈 Dùng User thật
):
    # Hàm này chỉ cần đọc dữ liệu từ current_user, không cần query DB thêm
    return {
        "tri_thuc": current_user.tri_thuc,
        # Parse JSON an toàn (tránh lỗi nếu data null)
        "learned": json.loads(current_user.skills_data or "{}"),
        "equipped": current_user.equipped_skill,
        "class_type": current_user.class_type
    }
@router.get("/get-all")
def get_all_skills(
    db: Session = Depends(get_db),
    # 👇 Thay get_fake_user bằng dòng này
    current_user: Player = Depends(get_current_user) 
):
    print(f"DEBUG: Đang lấy skill cho {current_user.username} - Class: {current_user.class_type}")

    # Query chỉ lấy skill đúng Class hoặc skill Chung
    statement = select(SkillTemplate).where(
        (SkillTemplate.class_type == current_user.class_type) | 
        (SkillTemplate.class_type == "COMMON")
    )
    
    skills = db.exec(statement).all()
    return skills