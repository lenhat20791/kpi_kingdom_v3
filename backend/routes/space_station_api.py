import json
import random
import traceback
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from database import (
    get_db,
    SpaceStationMatch,
    SpaceStationPlayer,
    SpaceStationAction,
    SpaceStationLog,
    Player,
    Question
)
from game_logic.space_station_biometrics import generate_biometrics_for_crew
from game_logic.space_station_engine import resolve_night_phase

router = APIRouter(prefix="/api/spacestation", tags=["Space Station"])

# ==========================================
# PYDANTIC SCHEMAS (DATA PAYLOADS)
# ==========================================



class SubmitActionRequest(BaseModel):
    username: str
    action_type: str  # VOTE_DAY, ALIEN_BITE, PROTECT, INVESTIGATE, SPY_LETTER, SHOOT, POISON, REVIVE, SCAN_DNA
    target_id_1: Optional[int] = None
    target_id_2: Optional[int] = None
    target_ids: Optional[List[int]] = None  # Cho Điều tra viên (4 người)
    typed_lesson_text: str  # Nội dung học sinh đã gõ lại để xác thực bài học

class SpyResponseRequest(BaseModel):
    username: str
    accept: bool  # True: Đồng ý thành gián điệp, False: Từ chối nhận manh mối

class FactionRegisterRequest(BaseModel):
    username: str
    faction_choice: str
# ==========================================
# 1. NHÓM API DÀNH CHO ADMIN
# ==========================================

@router.post("/admin/create-match")
def create_match(season_name: str = "Trạm Không Gian Lạc Việt-Y26", db: Session = Depends(get_db)):
    """Tạo phòng game mới ở trạng thái LOBBY"""
    # Đóng các trận cũ nếu còn mở
    active_matches = db.exec(select(SpaceStationMatch).where(SpaceStationMatch.status.in_(["LOBBY", "RUNNING"]))).all()
    for m in active_matches:
        m.status = "ENDED"
        db.add(m)
    
    new_match = SpaceStationMatch(season_name=season_name, status="LOBBY", current_day=1)
    db.add(new_match)
    db.commit()
    db.refresh(new_match)
    return {"status": "SUCCESS", "message": "Đã mở phòng báo danh", "match_id": new_match.id}


@router.post("/admin/start-match")
def start_match(match_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Hệ thống tự động gán Role, khởi tạo Sinh trắc học và bắt đầu game (Tự động dò tìm phòng)"""
    
    # 1. Bỏ qua match_id Frontend gửi lên, tự động dò phòng LOBBY mới nhất
    match = db.exec(
        select(SpaceStationMatch)
        .where(SpaceStationMatch.status == "LOBBY")
        .order_by(SpaceStationMatch.id.desc())
    ).first()

    if not match:
        raise HTTPException(status_code=400, detail="Lỗi: Không tìm thấy sảnh chờ (LOBBY) nào đang mở!")

    # 2. Lấy danh sách học sinh dựa trên ID của phòng vừa tìm được
    st_players = db.exec(select(SpaceStationPlayer).where(SpaceStationPlayer.match_id == match.id)).all()
    num_players = len(st_players)
    
    if num_players < 10:
        raise HTTPException(status_code=400, detail=f"Sảnh hiện tại mới có {num_players} người. Cần tối thiểu 10 người!")

    # 1. Sinh trắc học cho toàn bộ người chơi
    player_db_ids = [p.id for p in st_players]
    biometrics_map = generate_biometrics_for_crew(player_db_ids)

    # ------------------------------------------------------------------
    # BƯỚC 1: TÍNH QUOTA (SỐ GHẾ) CHO TỪNG PHE 
    # ------------------------------------------------------------------
    alien_quota = min(4, num_players // 4)        # Tối đa 4 Alien
    spy_quota = min(3, max(1, num_players // 10)) # Tối thiểu 1, Tối đa 3 Gián điệp
    
    # ------------------------------------------------------------------
    # BƯỚC 2: PHÂN LOẠI NGƯỜI CHƠI VÀO CÁC HỘP NGUYỆN VỌNG
    # ------------------------------------------------------------------
    pref_aliens = []
    pref_spies = []
    pref_astros = [] # Đóng vai trò là "Kho dự trữ"

    for p in st_players:
        choice = p.registered_faction_choice
        if choice == "ALIEN":
            pref_aliens.append(p)
        elif choice == "MARS_SPY":
            pref_spies.append(p)
        else:
            pref_astros.append(p)

    # ------------------------------------------------------------------
    # BƯỚC 3: XỬ LÝ PHE ALIEN (Ưu tiên nguyện vọng)
    # ------------------------------------------------------------------
    final_aliens = []
    if len(pref_aliens) > alien_quota:
        # Thừa người -> Chọn ngẫu nhiên, số còn lại đá sang Kho dự trữ (Astro)
        final_aliens = random.sample(pref_aliens, alien_quota)
        pref_astros.extend([p for p in pref_aliens if p not in final_aliens])
    else:
        # Thiếu hoặc đủ người -> Nhận hết, nếu thiếu thì "bắt cóc" từ Kho dự trữ
        final_aliens = pref_aliens.copy()
        shortage = alien_quota - len(final_aliens)
        if shortage > 0:
            drafted = random.sample(pref_astros, min(shortage, len(pref_astros)))
            final_aliens.extend(drafted)
            for d in drafted:
                pref_astros.remove(d)

    # ------------------------------------------------------------------
    # BƯỚC 4: XỬ LÝ PHE GIÁN ĐIỆP (Tương tự Alien)
    # ------------------------------------------------------------------
    final_spies = []
    if len(pref_spies) > spy_quota:
        final_spies = random.sample(pref_spies, spy_quota)
        pref_astros.extend([p for p in pref_spies if p not in final_spies])
    else:
        final_spies = pref_spies.copy()
        shortage = spy_quota - len(final_spies)
        if shortage > 0:
            drafted = random.sample(pref_astros, min(shortage, len(pref_astros)))
            final_spies.extend(drafted)
            for d in drafted:
                pref_astros.remove(d)

    # ------------------------------------------------------------------
    # BƯỚC 5: PHÂN BỔ VAI CHỨC NĂNG CHO PHE NGƯỜI TỐT CÒN LẠI
    # ------------------------------------------------------------------
    final_astros = pref_astros # Số người còn lại chắc chắn là phe Phi Hành Gia
    
    # Xác định tổng số vai đặc biệt được mở khóa theo quy mô lớp
    if num_players < 15:
        max_special_roles = 4
    elif num_players < 25:
        max_special_roles = 7
    else:
        max_special_roles = 10

    # Thứ tự ưu tiên vai trò đã thống nhất
    special_roles_priority = [
        "SCIENTIST", "CAPTAIN", "INVESTIGATOR", "BODYGUARD", 
        "PSYCHIC", "UNDERCOVER_COP", "TWO_FACED", 
        "BODYGUARD", "SCIENTIST", "PSYCHIC_APPRENTICE"
    ]

    # Đảm bảo luôn giữ lại ít nhất 1-2 em làm "Phi hành gia bình thường" (Bia đỡ đạn)
    allowed_specials = min(max_special_roles, max(0, len(final_astros) - 1))
    
    roles_to_assign = special_roles_priority[:allowed_specials]
    roles_to_assign.extend(["ASTRONAUT_NORMAL"] * (len(final_astros) - allowed_specials))
    
    # Xóc ngẫu nhiên danh sách vai trò chức năng để phát cho phe người tốt
    random.shuffle(roles_to_assign)

    # ------------------------------------------------------------------
    # BƯỚC 6: GÁN DỮ LIỆU & TRANG BỊ VÀO DATABASE
    # ------------------------------------------------------------------
    for p in final_aliens:
        p.actual_role = "ALIEN"
    for p in final_spies:
        p.actual_role = "MARS_SPY"
    for idx, p in enumerate(final_astros):
        p.actual_role = roles_to_assign[idx]

    # Áp dụng Sinh trắc học và Kho đồ cho toàn bộ người chơi
    for p in st_players:
        p.biometrics_json = json.dumps(biometrics_map[p.id], ensure_ascii=False)
        p.is_alive = True
        
        role = p.actual_role
        if role == "SCIENTIST":
            p.items_state_json = json.dumps({"has_revive": True, "has_poison": True})
        elif role == "UNDERCOVER_COP":
            p.items_state_json = json.dumps({"has_bullet": True})
        elif role == "CAPTAIN":
            p.items_state_json = json.dumps({"has_dna_scan": True})
        elif role == "TWO_FACED":
            p.items_state_json = json.dumps({"has_switched": False})
        else:
            p.items_state_json = json.dumps({})
            
        db.add(p)

    # Đóng gói và bắt đầu ván đấu
    match.status = "RUNNING"
    match.started_at = datetime.utcnow()
    db.add(match)
    db.commit()

    return {
        "status": "SUCCESS", 
        "message": f"Game Start! Cấu hình: {len(final_aliens)} Alien, {len(final_spies)} Gián điệp, {len(final_astros)} Phi hành gia."
    }


@router.post("/admin/force-resolve")
def force_resolve_night(match_id: int, db: Session = Depends(get_db)):
    """Nút bấm kiểm thử: Chạy ngay pipeline 22h00 không cần đợi"""
    result = resolve_night_phase(match_id, db)
    return result

# ==========================================
# 2. NHÓM API DÀNH CHO HỌC SINH (NGƯỜI CHƠI)
# ==========================================

@router.post("/lobby/register")
def register_faction(req: FactionRegisterRequest, session: Session = Depends(get_db)):
    """Xử lý báo danh chuẩn khớp 100% với Database SpaceStationPlayer"""
    try:
        username = req.username
        faction_choice = req.faction_choice

        # 1. Tìm trận đấu đang ở trạng thái LOBBY
        match = session.exec(
            select(SpaceStationMatch)
            .where(SpaceStationMatch.status == "LOBBY")
            .order_by(SpaceStationMatch.id.desc())
        ).first()

        if not match:
            raise HTTPException(status_code=400, detail="Không có phòng báo danh nào đang mở.")

        # 2. Lấy ID của học sinh từ bảng Player gốc (bắt buộc để lưu vào cột player_id)
        base_player = session.exec(select(Player).where(Player.username == username)).first()
        if not base_player:
            raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản người chơi.")

        # 3. Kiểm tra xem học sinh (dựa vào player_id) đã nộp hồ sơ chưa
        st_player = session.exec(
            select(SpaceStationPlayer).where(
                SpaceStationPlayer.match_id == match.id,
                SpaceStationPlayer.player_id == base_player.id
            )
        ).first()

        # 4. Ghi nhận mới hoặc Cập nhật nguyện vọng
        if not st_player:
            # Tạo bản ghi mới, gán đúng các cột trong Database của bạn
            st_player = SpaceStationPlayer(
                match_id=match.id,
                player_id=base_player.id, 
                registered_faction_choice=faction_choice, # Lưu thẳng vào cột này
                actual_role="UNASSIGNED",
                is_alive=True
            )
            session.add(st_player)
        else:
            # Nếu học sinh đổi ý, chỉ việc cập nhật lại cột này (không cần parse JSON rườm rà nữa)
            st_player.registered_faction_choice = faction_choice
            session.add(st_player)

        # 5. Lưu xuống DB
        session.commit()
        return {"message": "Báo danh thành công", "faction": faction_choice}

    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        print("❌ LỖI KHI BÁO DANH:\n", err_msg)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/my-state")
def get_my_state(username: str, db: Session = Depends(get_db)):
    """Lấy thông tin cá nhân: Role ẩn, trạng thái sống, kho kỹ năng"""
    player = db.exec(select(Player).where(Player.username == username)).first()
    if not player:
        raise HTTPException(status_code=404, detail="User không tồn tại")

    active_match = db.exec(select(SpaceStationMatch).where(SpaceStationMatch.status == "RUNNING")).first()
    if not active_match:
        return {"in_game": False, "message": "Không có ván game nào đang chạy"}

    st_player = db.exec(
        select(SpaceStationPlayer)
        .where(SpaceStationPlayer.match_id == active_match.id, SpaceStationPlayer.player_id == player.id)
    ).first()

    if not st_player:
        return {"in_game": False, "message": "Bạn không tham gia ván đấu này"}

    # Lấy danh sách đồng đội nếu là Alien hoặc Gián điệp
    teammates = []
    if st_player.actual_role in ["ALIEN", "MARS_SPY"]:
        team_members = db.exec(
            select(SpaceStationPlayer)
            .where(
                SpaceStationPlayer.match_id == active_match.id,
                SpaceStationPlayer.actual_role == st_player.actual_role,
                SpaceStationPlayer.is_alive == True
            )
        ).all()
        for tm in team_members:
            p_obj = db.get(Player, tm.player_id)
            teammates.append({"id": tm.id, "name": p_obj.full_name})

    return {
        "in_game": True,
        "match_id": active_match.id,
        "day": active_match.current_day,
        "st_player_id": st_player.id,
        "role": st_player.actual_role,
        "is_alive": st_player.is_alive,
        "death_reason": st_player.death_reason,
        "biometrics": json.loads(st_player.biometrics_json) if st_player.biometrics_json else {},
        "items_state": json.loads(st_player.items_state_json) if st_player.items_state_json else {},
        "teammates": teammates
    }


@router.get("/crew-manifest")
def get_crew_manifest(db: Session = Depends(get_db)):
    """Lấy Hồ Sơ Phi Hành Đoàn công khai (Ai còn sống, ai ngủ đông, module sinh trắc)"""
    active_match = db.exec(select(SpaceStationMatch).where(SpaceStationMatch.status == "RUNNING")).first()
    if not active_match:
        return {"manifest": []}

    st_players = db.exec(select(SpaceStationPlayer).where(SpaceStationPlayer.match_id == active_match.id)).all()
    manifest = []
    for sp in st_players:
        p_obj = db.get(Player, sp.player_id)
        manifest.append({
            "st_player_id": sp.id,
            "full_name": p_obj.full_name,
            "is_alive": sp.is_alive,
            "death_reason": sp.death_reason,
            "biometrics": json.loads(sp.biometrics_json) if sp.biometrics_json else {}
        })
    return {"day": active_match.current_day, "manifest": manifest}


@router.get("/reports-and-logs")
def get_reports_and_logs(username: str, db: Session = Depends(get_db)):
    """Lấy bảng tin sáng 06:00 và hòm thư mật cá nhân"""
    player = db.exec(select(Player).where(Player.username == username)).first()
    active_match = db.exec(select(SpaceStationMatch).where(SpaceStationMatch.status == "RUNNING")).first()
    if not active_match or not player:
        return {"public_reports": [], "private_logs": []}

    st_player = db.exec(
        select(SpaceStationPlayer)
        .where(SpaceStationPlayer.match_id == active_match.id, SpaceStationPlayer.player_id == player.id)
    ).first()

    # 1. Báo cáo công khai
    public_logs = db.exec(
        select(SpaceStationLog)
        .where(SpaceStationLog.match_id == active_match.id, SpaceStationLog.receiver_id == None)
        .order_by(SpaceStationLog.day_number.desc())
    ).all()

    # 2. Báo cáo mật
    private_logs = []
    if st_player:
        private_logs = db.exec(
            select(SpaceStationLog)
            .where(SpaceStationLog.match_id == active_match.id, SpaceStationLog.receiver_id == st_player.id)
            .order_by(SpaceStationLog.day_number.desc())
        ).all()

    return {
        "public_reports": [{"day": l.day_number, "content": l.content_text} for l in public_logs],
        "private_logs": [{"day": l.day_number, "content": l.content_text} for l in private_logs]
    }


@router.get("/lesson-prompt")
def get_lesson_prompt(db: Session = Depends(get_db)):
    """Lấy ngẫu nhiên một đoạn nội dung văn bản bài học từ DB để học sinh gõ lại xác thực"""
    # Lấy câu hỏi từ bảng Question làm mẫu bài gõ
    questions = db.exec(select(Question)).all()
    if questions:
        q = random.choice(questions)
        prompt_text = f"Kiến thức: {q.content}. Đáp án chuẩn xác: {q.correct_answer}"
    else:
        prompt_text = "Hệ thống an ninh trạm không gian yêu cầu nhập chuỗi mã lệnh bảo vệ toàn diện."
    return {"prompt_text": prompt_text}


@router.post("/submit-action")
def submit_action(req: SubmitActionRequest, db: Session = Depends(get_db)):
    """Học sinh gửi hành động (sau khi đã gõ đúng văn bản bài học)"""
    player = db.exec(select(Player).where(Player.username == req.username)).first()
    active_match = db.exec(select(SpaceStationMatch).where(SpaceStationMatch.status == "RUNNING")).first()
    if not player or not active_match:
        raise HTTPException(status_code=400, detail="Không thể gửi lệnh lúc này")

    st_player = db.exec(
        select(SpaceStationPlayer)
        .where(SpaceStationPlayer.match_id == active_match.id, SpaceStationPlayer.player_id == player.id)
    ).first()

    if not st_player or not st_player.is_alive:
        raise HTTPException(status_code=400, detail="Bạn đã bị đưa vào buồng ngủ đông, không thể thao tác!")

    # Xóa lệnh cũ cùng loại của ngày hôm nay (nếu học sinh muốn đổi quyết định trước 22:00)
    old_action = db.exec(
        select(SpaceStationAction)
        .where(
            SpaceStationAction.match_id == active_match.id,
            SpaceStationAction.day_number == active_match.current_day,
            SpaceStationAction.sender_id == st_player.id,
            SpaceStationAction.action_type == req.action_type
        )
    ).first()
    if old_action:
        db.delete(old_action)

    # Ghi nhận lệnh mới vào hàng đợi
    new_action = SpaceStationAction(
        match_id=active_match.id,
        day_number=active_match.current_day,
        sender_id=st_player.id,
        action_type=req.action_type,
        target_id_1=req.target_id_1,
        target_id_2=req.target_id_2,
        target_ids_json=json.dumps(req.target_ids) if req.target_ids else "[]",
        lesson_text_verified=req.typed_lesson_text,
        status="PENDING"
    )
    db.add(new_action)
    db.commit()

    return {"status": "SUCCESS", "message": "Hành động đã được ghi nhận vào hàng đợi 22h00!"}

@router.get("/lobby/stats")
def get_lobby_stats(session: Session = Depends(get_db)):
    """Đếm số lượng báo danh chuẩn dựa trên bảng SpaceStationPlayer"""
    try:
        match = session.exec(
            select(SpaceStationMatch).where(
                SpaceStationMatch.status.in_(["LOBBY", "RUNNING"])
            ).order_by(SpaceStationMatch.id.desc())
        ).first()

        if not match:
            return {"total": 0, "astronaut": 0, "spy": 0, "alien": 0}

        players = session.exec(
            select(SpaceStationPlayer).where(SpaceStationPlayer.match_id == match.id)
        ).all()

        total = len(players)
        astronaut_count = 0
        spy_count = 0
        alien_count = 0

        for p in players:
            # Lấy nguyện vọng trực tiếp từ cột database
            choice = p.registered_faction_choice
            
            if p.actual_role == "MARS_SPY" or choice == "MARS_SPY":
                spy_count += 1
            elif p.actual_role == "ALIEN" or choice == "ALIEN":
                alien_count += 1
            else:
                astronaut_count += 1

        return {
            "total": total,
            "astronaut": astronaut_count,
            "spy": spy_count,
            "alien": alien_count
        }
    except Exception as e:
        print(f"❌ Lỗi tại /lobby/stats: {e}")
        return {"total": 0, "astronaut": 0, "spy": 0, "alien": 0}

@router.get("/dev/inject-bots")
def inject_test_bots(bot_count: int = 7, session: Session = Depends(get_db)):
    """API Dành riêng cho Dev để bơm nhanh Bot vào phòng chờ test game"""
    try:
        # 1. Tìm trận đấu đang ở sảnh
        match = session.exec(select(SpaceStationMatch).where(SpaceStationMatch.status == "LOBBY")).first()
        if not match:
            return {"error": "Không có sảnh Lobby nào đang mở để bơm bot!"}

        injected_names = []
        for i in range(1, bot_count + 1):
            bot_username = f"bot_test_{i}"
            
            # 2. Tự động tạo tài khoản gốc nếu chưa có (Qua mặt hệ thống)
            bot_base = session.exec(select(Player).where(Player.username == bot_username)).first()
            if not bot_base:
                bot_base = Player(
                    username=bot_username,
                    full_name=f"Bot Thử Nghiệm {i}",
                    password_hash="fake_hash",
                    role="STUDENT"
                )
                session.add(bot_base)
                session.commit() # Lưu ngay để lấy ID
                session.refresh(bot_base)

            # 3. Kiểm tra xem bot đã ở trong sảnh chưa
            st_bot = session.exec(select(SpaceStationPlayer).where(
                SpaceStationPlayer.match_id == match.id,
                SpaceStationPlayer.player_id == bot_base.id
            )).first()

            # 4. Bơm bot vào sảnh với mặc định là Phi Hành Gia
            if not st_bot:
                new_bot = SpaceStationPlayer(
                    match_id=match.id,
                    player_id=bot_base.id,
                    registered_faction_choice="ASTRONAUT", # 100% làm quần chúng
                    actual_role="UNASSIGNED",
                    is_alive=True
                )
                session.add(new_bot)
                injected_names.append(bot_username)
                
        session.commit()
        return {"status": "SUCCESS", "message": f"Đã bơm thành công {len(injected_names)} bot vào trận {match.id}!"}
        
    except Exception as e:
        return {"error": str(e)}

@router.get("/dev/nuke-test-data")
def nuke_test_data(session: Session = Depends(get_db)):
    """API dọn dẹp: Xóa sạch toàn bộ bot và dữ liệu liên quan sau khi dev xong"""
    try:
        # 1. Tìm tất cả các bot test
        bots = session.exec(select(Player).where(Player.username.startswith("bot_test_"))).all()
        if not bots:
            return {"message": "Hệ thống đã sạch sẽ, không có bot nào tồn tại!"}
            
        bot_ids = [b.id for b in bots]

        # 2. Xóa toàn bộ hành động (Actions) của bot trong các ván game
        bot_actions = session.exec(select(SpaceStationAction).where(SpaceStationAction.sender_id.in_(bot_ids))).all()
        for a in bot_actions:
            session.delete(a)

        # 3. Xóa hồ sơ bot trong các phòng game (SpaceStationPlayer)
        bot_records = session.exec(select(SpaceStationPlayer).where(SpaceStationPlayer.player_id.in_(bot_ids))).all()
        for r in bot_records:
            session.delete(r)

        # 4. Cuối cùng, xóa tận gốc tài khoản bot trong bảng Player
        for b in bots:
            session.delete(b)

        session.commit()
        return {"status": "SUCCESS", "message": f"Đã thanh trừng thành công {len(bots)} bot và toàn bộ rác dữ liệu đi kèm!"}
    except Exception as e:
        return {"error": str(e)}