from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlmodel import Session, select, func, or_
from database import get_db, Player, ArenaMatch, ArenaParticipant, QuestionBank
from game_logic.arena_manager import ArenaManager
from typing import Optional, Dict, List
from pydantic import BaseModel
import random
import json
import ast
router = APIRouter(prefix="/arena", tags=["Arena"])

# --- DATA MODELS (Schema cho dữ liệu gửi lên) ---
class ChallengeRequest(BaseModel):
    mode: str          # 1vs1, 2vs2
    difficulty: str    # hard, super_hard, hell
    bet_amount: int
    opponent_name: Optional[str] = None

class AcceptMatchRequest(BaseModel):
    match_id: int
    username: str

class AnswerItem(BaseModel):
    id: int
    answer: str

class SubmitAnswer(BaseModel):
    match_id: int
    username: str
    answers: Dict[str, str]

# --- API ENDPOINTS ---

@router.post("/create")
def create_challenge(
    req: ChallengeRequest, 
    username: str = Query(...), 
    db: Session = Depends(get_db)
):
    manager = ArenaManager(db)
    result = manager.create_match(
        username=username,
        mode=req.mode,
        difficulty=req.difficulty,
        bet_amount=req.bet_amount,
        opponent_name=req.opponent_name
    )
    
    if not result["success"]:
        # Manager sẽ trả về message lỗi nếu không đủ tiền
        raise HTTPException(status_code=400, detail=result["message"])
        
    return result

@router.get("/list-my-matches")
def list_my_matches(username: str = Query(...), db: Session = Depends(get_db)):
    from sqlmodel import or_ 
    manager = ArenaManager(db)
    manager.process_lazy_timeouts()
    
    # 1. Incoming (Lời mời ĐẾN) -> CHỈ LẤY PENDING HOẶC ACTIVE (Chưa xong)
    incoming_query = db.exec(
        select(ArenaParticipant, ArenaMatch)
        .join(ArenaMatch)
        .where(ArenaParticipant.username == username)
        .where(or_(ArenaMatch.status == "pending", ArenaMatch.status == "active")) # <--- Bỏ finished
        .order_by(ArenaMatch.created_at.desc())
    ).all()
    
    incoming_data = []
    for p, m in incoming_query:
        incoming_data.append({
            "match_id": m.id,
            "creator": m.created_by,
            "bet": m.bet_amount,
            "mode": m.mode,
            "difficulty": m.difficulty,
            "status": m.status,
            "logs": m.logs,
            "my_status": p.status
        })

    # 2. Outgoing (Lời mời ĐI) -> CHỈ LẤY PENDING HOẶC ACTIVE (Chưa xong)
    outgoing_query = db.exec(
        select(ArenaMatch)
        .where(ArenaMatch.created_by == username)
        .where(or_(ArenaMatch.status == "pending", ArenaMatch.status == "active")) # <--- Bỏ finished
        .order_by(ArenaMatch.created_at.desc())
    ).all()
    
    outgoing_data = []
    for m in outgoing_query:
        outgoing_data.append({
            "match_id": m.id,
            "created_at": m.created_at,
            "bet": m.bet_amount,
            "mode": m.mode,
            "difficulty": m.difficulty,
            "status": m.status,
            "logs": m.logs,
            "player_1": m.created_by,
            "player_2": getattr(m, "player_2", "???") 
        })

    # 3. History (Lịch sử) -> CHỈ LẤY TRẬN ĐÃ KẾT THÚC (FINISHED)
    # Lấy cả trận mình tạo VÀ trận mình tham gia
    history_query = db.exec(
        select(ArenaMatch)
        .join(ArenaParticipant, isouter=True) # Join để tìm trận mình tham gia
        .where(or_(
            ArenaMatch.created_by == username,      # Mình tạo
            ArenaParticipant.username == username   # Hoặc mình tham gia
        ))
        .where(ArenaMatch.status == "finished")     # Chỉ lấy trận đã xong
        .order_by(ArenaMatch.created_at.desc())
        .limit(5) # Chỉ lấy 20 trận gần nhất cho đỡ lag
    ).all()
    
    # Lọc trùng (Do join có thể ra trùng nếu logic phức tạp, set cho chắc)
    history_unique = {m.id: m for m in history_query}.values()
    
    history_data = []
    for m in history_unique:
         history_data.append({
            "match_id": m.id,
            "created_at": m.created_at,
            "bet": m.bet_amount,
            "mode": m.mode,
            "winner_team": m.winner_team,
            "logs": m.logs,
            "created_by": m.created_by # Để biết mình là chủ hay khách
        })

    return {
        "incoming": incoming_data,
        "outgoing": outgoing_data,
        "history": history_data # <--- Key mới
    }

@router.post("/accept")
def accept_match(
    payload: AcceptMatchRequest, 
    db: Session = Depends(get_db)
):
    # Khởi tạo Manager
    manager = ArenaManager(db)
    
    # Gọi hàm xử lý từ Manager
    # Hàm này sẽ làm các việc:
    # 1. Kiểm tra User B có đủ tiền không?
    # 2. Trừ tiền User B (nếu có cược).
    # 3. Chuyển trạng thái trận đấu sang 'active'.
    result = manager.accept_match_1vs1(
        match_id=payload.match_id,
        username=payload.username
    )
    
    # Nếu có lỗi (ví dụ: không đủ tiền, trận đấu đã hết hạn...) -> Báo lỗi ngay
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
        
    return result

@router.post("/cancel")
def cancel_match(match_id: int = Body(..., embed=True), username: str = Body(..., embed=True), db: Session = Depends(get_db)):
    manager = ArenaManager(db)
    result = manager.cancel_match(match_id, username)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result

# --- PHẦN 2VS2 & LOBBY ---

@router.get("/lobby")
def get_lobby(db: Session = Depends(get_db)):
    """Lấy danh sách các phòng 2vs2 đang chờ (Pending)"""
    manager = ArenaManager(db)
    manager.process_lazy_timeouts()
    
    matches = db.exec(select(ArenaMatch).where(ArenaMatch.mode == "2vs2", ArenaMatch.status == "pending")).all()
    
    lobby_data = []
    for m in matches:
        # Lấy danh sách thành viên hiện tại
        participants = db.exec(select(ArenaParticipant).where(ArenaParticipant.match_id == m.id)).all()
        team_a = [p.username for p in participants if p.team == 'A']
        team_b = [p.username for p in participants if p.team == 'B']
        
        lobby_data.append({
            "id": m.id,
            "bet": m.bet_amount,
            "difficulty": m.difficulty,
            "team_a": team_a,
            "team_b": team_b,
            "count": len(participants)
        })
    return lobby_data

@router.post("/join-lobby")
def join_lobby(match_id: int = Body(...), username: str = Body(...), team: str = Body(...), db: Session = Depends(get_db)):
    manager = ArenaManager(db)
    result = manager.join_lobby_2vs2(match_id, username, team)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result

# --- PHẦN LÀM BÀI THI ---

@router.get("/quiz")
def get_arena_quiz(
    match_id: int, 
    username: str, 
    db: Session = Depends(get_db)
):
    print(f"⚡ [DEBUG] Lấy đề cho Match {match_id}")

    # Lấy tất cả câu hỏi
    all_questions = db.exec(select(QuestionBank)).all()
    
    if len(all_questions) < 5:
        raise HTTPException(status_code=400, detail="Kho câu hỏi không đủ 5 câu!")

    # Chọn ngẫu nhiên 5 câu
    selected_questions = random.sample(all_questions, 5)
    
    quiz_data = []
    for q in selected_questions:
        try:
            # --- XỬ LÝ OPTIONS (Vạn năng) ---
            raw_data = q.options_json
            
            if isinstance(raw_data, list):
                options = raw_data
            elif isinstance(raw_data, str):
                raw_str = raw_data.strip()
                if "'" in raw_str: raw_str = raw_str.replace("'", '"')
                try:
                    options = json.loads(raw_str)
                except:
                    try:
                        options = ast.literal_eval(raw_str)
                    except:
                        options = ["Lỗi data", "Lỗi data", "Lỗi data", "Lỗi data"]
            else:
                 options = ["Lỗi data", "Lỗi data", "Lỗi data", "Lỗi data"]

            if not isinstance(options, list):
                options = ["Lỗi format", "Lỗi format", "Lỗi format", "Lỗi format"]

        except Exception as e:
            print(f"❌ LỖI OPTIONS CÂU {q.id}: {e}")
            options = ["Lỗi hiển thị", "Lỗi hiển thị", "Lỗi hiển thị", "Lỗi hiển thị"]

        # --- TẠO DỮ LIỆU TRẢ VỀ ---
        # Chú ý: Các dòng dưới đây phải có dấu phẩy ở cuối
        quiz_data.append({
            "id": q.id,
            "content": q.content,
            "options": options,
            "subject": q.subject,
            "difficulty": q.difficulty,          # <--- Đã có dấu phẩy
            "correct_answer": q.correct_answer,  # <--- Đã có dấu phẩy
            "explanation": q.explanation         # <--- Dòng cuối không bắt buộc phẩy nhưng có cũng không sao
        })

    print("✅ Đã tạo đề thi thành công.")
    return {
        "match_id": match_id,
        "questions": quiz_data
    }
# ==================================================================
# 4. API NỘP BÀI (SUBMIT) - THÊM ĐOẠN NÀY VÀO CUỐI FILE
# ==================================================================
class SubmitAnswer(BaseModel): # Khai báo mô hình dữ liệu (Nhớ import BaseModel nếu thiếu)
    match_id: int
    username: str
    answers: dict


# 2. API NỘP BÀI (FULL LOGIC PvP)
@router.post("/submit")
def submit_arena_quiz(
    payload: SubmitAnswer, 
    db: Session = Depends(get_db)
):
    print(f"📝 [DEBUG] Nhận bài từ {payload.username} - Match {payload.match_id}")
    
    # --- BƯỚC 1: TÌM TRẬN ĐẤU ---
    match = db.get(ArenaMatch, payload.match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Không tìm thấy trận đấu")

    # --- BƯỚC 2: CHẤM ĐIỂM (Code của bạn) ---
    current_score = 0
    correct_count = 0
    
    for q_id, user_ans in payload.answers.items():
        try:
            question = db.get(QuestionBank, int(q_id))
            if question:
                # So sánh đáp án (chuyển về chữ thường, bỏ khoảng trắng)
                db_correct = str(question.correct_answer).strip().lower()
                user_choice = str(user_ans).strip().lower()
                
                if db_correct == user_choice:
                    current_score += 10 
                    correct_count += 1
        except:
            continue

    # --- BƯỚC 3: LƯU ĐIỂM VÀO DATABASE (Quan trọng!) ---
    # Lấy logs cũ ra
    try:
        match_logs = json.loads(match.logs) if match.logs else {}
    except:
        match_logs = {}
    
    # Ghi điểm người chơi này vào logs
    match_logs[payload.username] = current_score
    
    # Lưu ngược lại vào DB
    match.logs = json.dumps(match_logs)
    db.add(match)
    db.commit() # <--- Lệnh này giúp lưu điểm vĩnh viễn
       
        # 4. KIỂM TRA ĐỦ NGƯỜI CHƯA
    required_players = 2
    if match.mode == "2vs2": required_players = 4
    elif match.mode == "3vs3": required_players = 6

    if len(match_logs) >= required_players:
        
        # --- LOGIC TÍNH ĐIỂM TEAM (CHUẨN CHO MỌI CHẾ ĐỘ) ---
        
        # 1. Lấy danh sách người tham gia để biết ai phe nào
        participants = db.exec(
            select(ArenaParticipant).where(ArenaParticipant.match_id == match.id)
        ).all()
        
        score_team_A = 0
        score_team_B = 0
        
        # 2. Cộng điểm từng người vào phe tương ứng
        for p in participants:
            # Lấy điểm từ logs (nếu chưa có thì là 0)
            user_score = match_logs.get(p.username, 0)
            
            if p.team == 'A':
                score_team_A += user_score
            elif p.team == 'B':
                score_team_B += user_score

        print(f"🧮 [KẾT QUẢ] Team A: {score_team_A} - Team B: {score_team_B}")

        # 3. So sánh tổng điểm
        winner = "Draw"
        if score_team_A > score_team_B:
            # Với 1vs1 thì Team A chính là username của người tạo
            # Với 2vs2 thì winner là tên Team ("Team A")
            winner = match.created_by if match.mode == "1vs1" else "Team A"
            
        elif score_team_B > score_team_A:
            # Tìm tên người đại diện team B (cho 1vs1)
            # Lấy ai đó trong team B làm đại diện hoặc trả về "Team B"
            player_b_rep = next((p.username for p in participants if p.team == 'B'), "Team B")
            winner = player_b_rep if match.mode == "1vs1" else "Team B"
            
        else:
            winner = "Draw"

        # 4. Cập nhật DB
        match.status = "finished"
        match.winner_team = winner 
        if match.bet_amount > 0:
            # Lấy danh sách người chơi để cộng tiền
            # (Lưu ý: biến 'participants' đã được bạn query ở đoạn tính điểm Team rồi, dùng lại luôn)
            for p in participants:
                p_wallet = db.exec(select(Player).where(Player.username == p.username)).first()
                if not p_wallet: continue

                # -- TRƯỜNG HỢP HÒA (Trả lại tiền) --
                if winner == "Draw" or winner == "Hòa":
                    p_wallet.kpi += match.bet_amount
                
                # -- TRƯỜNG HỢP CÓ NGƯỜI THẮNG --
                else:
                    is_winner = False
                    # Check thắng 1vs1
                    if match.mode == "1vs1" and winner == p.username:
                        is_winner = True
                
                    # Check thắng Team (2vs2, 3vs3)
                    elif str(winner) == f"Team {p.team}" or str(winner) == p.team: 
                        is_winner = True
                    
                    # Nếu thắng -> Ăn gấp đôi tiền + 1 Chiến Tích
                    if is_winner:
                        # 1. Cộng KPI (Tiền)
                        p_wallet.kpi += (match.bet_amount * 2)
                        
                        # 👇 2. CỘNG CHIẾN TÍCH (Thêm dòng này vào) 👇
                        p_wallet.chien_tich = (p_wallet.chien_tich or 0) + 1
                        
                        print(f"✅ Đã cộng tiền và chiến tích cho {p.username}")

                db.add(p_wallet)
            
            print(f"💰 [ECONOMY] Đã phân định tiền thưởng cho Match {match.id}")
        db.add(match)
        db.commit()

        # Thông báo kết quả
        result_msg = ""
        if match.mode == "1vs1":
            result_msg = f"🏆 Người thắng: {winner}"
        else:
            result_msg = f"🏆 Đội thắng: {winner} ({score_team_A} - {score_team_B})"

        return {
            "status": "finished",
            "my_score": current_score,
            "correct_count": correct_count,
            "message": f"🏁 TRẬN ĐẤU KẾT THÚC!\nBạn được {current_score} điểm.\n{result_msg}"
        }

    else:
        # CHƯA ĐỦ NGƯỜI
        return {
            "status": "waiting",
            "my_score": current_score,
            "correct_count": correct_count,
            "message": f"⏳ ĐÃ NỘP BÀI!\nĐã có {len(match_logs)}/{required_players} người hoàn thành.\nĐang tính điểm..."
        }
@router.get("/opponents")
def get_arena_opponents(
    current_user: str = Query(...), 
    db: Session = Depends(get_db)
):
    # 👇 LOG DEBUG 1: Xác nhận API đã được gọi
    print(f"🐍 [DEBUG-BE] API Opponents được gọi bởi user: '{current_user}'")
    
    try:
        # Tìm tất cả player có username KHÁC current_user
        players = db.exec(
            select(Player)
            .where(Player.username != current_user)  # Không lấy chính mình
            .where(Player.username != "admin")       # Không lấy Admin
        ).all()
        
        # 👇 LOG DEBUG 2: Xem tìm được bao nhiêu người trong DB
        print(f"🐍 [DEBUG-BE] Tìm thấy {len(players)} người chơi khác trong DB.")
        
        result = []
        for p in players:
            kpi_safe = p.kpi if p.kpi is not None else 0
            result.append({
                "username": p.username,
                "full_name": p.full_name if p.full_name else p.username,
                "class_type": p.class_type if p.class_type else "Novice",
                "kpi": kpi_safe
            })
        
        return result

    except Exception as e:
        # 👇 LOG DEBUG 3: Nếu code Python bị crash
        print(f"❌ [DEBUG-BE] Lỗi code Python: {e}")
        import traceback
        traceback.print_exc()
        raise e
    
# ==================================================================
# API LẤY CHI TIẾT TRẬN ĐẤU (Để xem kết quả)
# ==================================================================
@router.get("/match/{match_id}")
def get_match_detail(match_id: int, db: Session = Depends(get_db)):
    match = db.get(ArenaMatch, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Không tìm thấy trận đấu")
    return match