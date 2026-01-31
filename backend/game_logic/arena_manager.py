import json
import random
from datetime import datetime, timedelta
from sqlmodel import Session, select, col, text
from database import Player, ArenaMatch, ArenaParticipant, QuestionBank
from sqlalchemy import text

class ArenaManager:
    def __init__(self, db: Session):
        self.db = db

    # =========================================================================
    # 1. TẠO & THAM GIA TRẬN ĐẤU
    # =========================================================================

    def create_match(self, username: str, mode: str, difficulty: str, bet_amount: int, opponent_name: str = None):
        """
        Người chơi tạo thách đấu.
        - Trừ tiền ngay lập tức (Cơ chế Tạm giữ).
        - Tạo Match và Participant (Creator).
        - Nếu 1vs1: Tạo sẵn slot cho đối thủ (Pending).
        """
        # 1. Kiểm tra tiền cược
        creator = self.db.exec(select(Player).where(Player.username == username)).first()
        if not creator or (creator.kpi or 0) < bet_amount:
            return {"success": False, "message": "Bạn không đủ KPI để cược lôi đài!"}

        # 2. Trừ tiền cọc (Escrow)
        creator.kpi = (creator.kpi or 0) - bet_amount
        self.db.add(creator)

        # 3. Tạo Match
        # Thời hạn tạm thời là 24h kể từ lúc tạo (để chờ accept), 
        # khi active sẽ reset lại 24h cho trận đấu
        new_match = ArenaMatch(
            mode=mode,
            difficulty=difficulty,
            bet_amount=bet_amount,
            status="pending",
            created_by=username,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(hours=24) 
        )
        self.db.add(new_match)
        self.db.commit()
        self.db.refresh(new_match)

        # 4. Thêm Creator vào trận (Team A)
        p1 = ArenaParticipant(
            match_id=new_match.id,
            username=username,
            team="A",
            status="accepted", # Chủ phòng auto accept
            score=0
        )
        self.db.add(p1)

        # 5. Nếu là 1vs1, thêm đối thủ vào (Team B) - Status Pending
        if mode == "1vs1" and opponent_name:
            p2 = ArenaParticipant(
                match_id=new_match.id,
                username=opponent_name,
                team="B",
                status="pending", # Chờ đối thủ đồng ý
                score=0
            )
            self.db.add(p2)

        self.db.commit()
        return {"success": True, "match_id": new_match.id, "message": "Đã gửi thư khiêu chiến!"}

    def accept_match_1vs1(self, match_id: int, username: str):
        """
        Đối thủ chấp nhận kèo 1vs1.
        Đã nâng cấp: 
        - Fix lỗi click đúp (Re-join).
        - Tự động tạo slot nếu là kèo mở.
        - Trừ tiền và kích hoạt trận đấu.
        """
        # 1. Lấy thông tin trận đấu
        match = self.db.get(ArenaMatch, match_id)
        if not match:
            return {"success": False, "message": "Trận đấu không tồn tại."}

        # -----------------------------------------------------------
        # 🔥 FIX LỖI 400: XỬ LÝ KHI TRẬN ĐẤU ĐÃ ACTIVE (RE-JOIN)
        # -----------------------------------------------------------
        if match.status == "active":
            # Kiểm tra xem người này có phải là đối thủ đã nhận kèo trước đó không
            participant = self.db.exec(select(ArenaParticipant).where(
                ArenaParticipant.match_id == match_id, 
                ArenaParticipant.username == username
            )).first()

            if participant and participant.status == "accepted":
                # Nếu đúng là người trong cuộc -> Cho vào luôn
                return {"success": True, "message": "Đang vào lại trận đấu...", "data": {"status": "active"}}
            else:
                # Nếu là người lạ -> Báo đã có người khác nhanh tay hơn
                return {"success": False, "message": "Trận đấu này đã có người khác nhận kèo!"}

        # -----------------------------------------------------------
        # KIỂM TRA ĐIỀU KIỆN CHẤP NHẬN (KHI STATUS = PENDING)
        # -----------------------------------------------------------
        if match.status != "pending":
            return {"success": False, "message": "Trận đấu đã hết hạn hoặc bị hủy."}

        # Chặn tự đánh với chính mình
        if match.created_by == username:
            return {"success": False, "message": "Bạn không thể tự chấp nhận kèo của chính mình."}

        # 2. Kiểm tra tiền của người chấp nhận (Accepter)
        accepter = self.db.exec(select(Player).where(Player.username == username)).first()
        if not accepter:
            return {"success": False, "message": "Không tìm thấy thông tin người chơi."}
            
        if (accepter.kpi or 0) < match.bet_amount:
            return {"success": False, "message": f"Bạn cần {match.bet_amount} KPI để nhận kèo này!"}

        # 3. Trừ tiền cọc ngay lập tức
        accepter.kpi = (accepter.kpi or 0) - match.bet_amount
        self.db.add(accepter)

        # 4. Xử lý Participant (Người tham gia)
        # Tìm xem đã có slot sẵn chưa (Trường hợp thách đấu chỉ định)
        participant = self.db.exec(select(ArenaParticipant).where(
            ArenaParticipant.match_id == match_id, 
            ArenaParticipant.username == username
        )).first()
        
        if participant:
            # Case A: Đã có slot (Thách đấu chỉ định) -> Update status
            participant.status = "accepted"
            self.db.add(participant)
        else:
            # Case B: Chưa có slot (Thách đấu mở - Ai vào cũng được) -> Tạo mới
            # Kiểm tra xem phòng đã đầy chưa (1vs1 chỉ cho phép tối đa 2 người: 1 chủ, 1 khách)
            count = self.db.exec(select(func.count(ArenaParticipant.id)).where(ArenaParticipant.match_id == match_id)).one()
            if count >= 2:
                 return {"success": False, "message": "Trận đấu đã đủ người!"}

            new_participant = ArenaParticipant(
                match_id=match_id,
                username=username,
                team="B",          # 👈 Thêm dòng này (Vì chủ phòng là A, khách phải là B)
                status="accepted",
                score=0            # 👈 Thêm dòng này (Khởi tạo điểm bằng 0)
            )
            self.db.add(new_participant)

        # 5. Kích hoạt trận đấu
        match.status = "active"
        
        # Reset thời gian hết hạn (Cho thêm 24h để thi đấu tính từ lúc nhận kèo)
        match.expires_at = datetime.now() + timedelta(hours=24) 
        self.db.add(match)
        
        # 6. Lưu tất cả thay đổi
        self.db.commit()
        
        return {"success": True, "message": "Chấp nhận thành công! Vào trận ngay.", "data": {"status": "active"}}

    def join_lobby_2vs2(self, match_id: int, username: str, team: str):
        """
        Người lạ tham gia phòng chờ 2vs2.
        """
        match = self.db.get(ArenaMatch, match_id)
        if not match or match.status != "pending":
            return {"success": False, "message": "Phòng không khả dụng."}

        # Check xem đã tham gia chưa
        existing = self.db.exec(select(ArenaParticipant).where(
            ArenaParticipant.match_id == match_id,
            ArenaParticipant.username == username
        )).first()
        if existing:
            return {"success": False, "message": "Bạn đã ở trong phòng này rồi."}

        # Check số lượng thành viên team đó (Max 2)
        team_count = self.db.exec(select(ArenaParticipant).where(
            ArenaParticipant.match_id == match_id,
            ArenaParticipant.team == team
        )).all()
        if len(team_count) >= 2:
            return {"success": False, "message": f"Team {team} đã đủ người."}

        # Check tiền
        joiner = self.db.exec(select(Player).where(Player.username == username)).first()
        if (joiner.kpi or 0) < match.bet_amount:
            return {"success": False, "message": "Bạn không đủ KPI để cược lôi đài!."}

        # Trừ tiền & Thêm vào phòng
        joiner.kpi -= match.bet_amount
        self.db.add(joiner)

        new_p = ArenaParticipant(
            match_id=match_id,
            username=username,
            team=team,
            status="accepted",
            score=0
        )
        self.db.add(new_p)
        self.db.commit()

        # Kiểm tra nếu đủ 4 người -> Start game
        total_p = self.db.exec(select(ArenaParticipant).where(ArenaParticipant.match_id == match_id)).all()
        if len(total_p) == 4:
            match.status = "active"
            match.expires_at = datetime.now() + timedelta(hours=24)
            self.db.add(match)
            self.db.commit()
            return {"success": True, "message": "Đã tham gia. Phòng đủ người, trận đấu BẮT ĐẦU!"}
        
        return {"success": True, "message": f"Đã tham gia Team {team}. Chờ đủ người..."}

    # =========================================================================
    # 2. XỬ LÝ GAMEPLAY (LÀM BÀI & TÍNH ĐIỂM)
    # =========================================================================

    def get_quiz_questions(self, match_id: int, username: str):
        """
        Lấy đề thi cho user.
        - Mỗi trận đấu nên dùng chung 1 bộ đề (Fair play).
        - Nếu chưa có đề -> Random tạo và lưu lại.
        - Nếu có rồi -> Trả về.
        """
        match = self.db.get(ArenaMatch, match_id)
        if not match or match.status != "active":
            return None # Hoặc raise Error

        # Kiểm tra xem trận này đã có đề chưa (Lưu trong field match.logs tạm thời hoặc 1 bảng riêng)
        # Để đơn giản, ta sẽ random mỗi lần (nhưng tốt nhất là lưu lại ID câu hỏi vào match.logs)
        
        # Logic đơn giản: Random 5 câu theo độ khó
        questions = self.db.exec(select(QuestionBank).where(
            QuestionBank.difficulty == match.difficulty
        )).all()
        
        if len(questions) < 5:
            # Fallback nếu thiếu câu hỏi
            selected_qs = questions
        else:
            selected_qs = random.sample(questions, 5)

        # Format dữ liệu trả về Frontend (Ẩn đáp án đúng)
        quiz_data = []
        for q in selected_qs:
            quiz_data.append({
                "id": q.id,
                "subject": q.subject,
                "content": q.content,
                "options": json.loads(q.options_json), # String -> List
                # KHÔNG TRẢ VỀ correct_answer
            })
            
        return quiz_data

    def submit_quiz_answer(self, match_id: int, username: str, user_answers: list):
        """
        Chấm điểm bài thi.
        Đã nâng cấp: Chỉ gọi trọng tài khi người cuối cùng nộp bài.
        """
        # 1. Kiểm tra người chơi
        participant = self.db.exec(select(ArenaParticipant).where(
            ArenaParticipant.match_id == match_id,
            ArenaParticipant.username == username
        )).first()

        if not participant or participant.status == "submitted":
            return {"success": False, "message": "Bạn không thuộc trận này hoặc đã nộp bài rồi."}

        # 2. Chấm điểm
        score = 0
        for ans in user_answers:
            q_id = ans.get("id")
            user_choice = ans.get("answer")
            
            question = self.db.get(QuestionBank, q_id)
            if question and question.correct_answer == user_choice:
                score += 1

        # 3. Lưu điểm số và Commit (LƯU Ý: Phải commit ngay để DB cập nhật)
        participant.score = score
        participant.status = "submitted"
        participant.submitted_at = datetime.now()
        self.db.add(participant)
        self.db.commit() # <--- Commit điểm số của người này trước

        # =======================================================
        # 4. KIỂM TRA ĐỂ GỌI TRỌNG TÀI (Đoạn quan trọng nhất)
        # =======================================================
        print(f"📝 {username} đã nộp bài. Điểm: {score}. Đang kiểm tra xem đủ người chưa...")
        
        # Lấy danh sách tất cả người chơi trong trận
        all_participants = self.db.exec(select(ArenaParticipant).where(
            ArenaParticipant.match_id == match_id
        )).all()
        
        # Kiểm tra xem có ai chưa nộp không? (status khác 'submitted')
        # Lưu ý: Người vừa nộp đã được set 'submitted' ở bước 3 rồi.
        not_finished_count = sum(1 for p in all_participants if p.status != "submitted")
        
        if not_finished_count == 0:
            print("🚀 Đây là người cuối cùng! Gọi trọng tài ngay lập tức.")
            # Gọi hàm check_match_end "Bất Tử" (dùng SQL) mà tôi gửi ở tin nhắn trước
            self.check_match_end(match_id)
        else:
            print(f"⏳ Vẫn còn {not_finished_count} người chưa nộp. Chưa gọi trọng tài.")

        return {"success": True, "score": score}

    # =========================================================================
    # 3. TRỌNG TÀI & PHÂN ĐỊNH THẮNG THUA
    # =========================================================================

    def check_match_end(self, match_id: int):
        """
        Phiên bản CHUẨN (Production):
        - Dùng ORM thay vì SQL thô (Code sạch).
        - Đồng bộ logic cộng thưởng với arena_api.py.
        - Dùng để xử lý các trận HẾT GIỜ (Expired) hoặc Treo.
        """
        print(f"\n⚡ [MANAGER] Đang kiểm tra Match ID: {match_id}")
        
        # 1. Lấy dữ liệu
        match = self.db.get(ArenaMatch, match_id)
        if not match: return

        # Nếu trận đã xong thì bỏ qua ngay
        if match.status in ["finished", "completed", "cancelled"]:
            return 

        participants = self.db.exec(select(ArenaParticipant).where(
            ArenaParticipant.match_id == match_id
        )).all()

        # 2. Kiểm tra điều kiện: Chỉ xử lý khi HẾT GIỜ hoặc ĐÃ NỘP ĐỦ
        # (Thường API đã lo vụ nộp đủ, hàm này chủ yếu lo vụ Hết Giờ)
        is_expired = datetime.now() > match.expires_at
        all_submitted = all(p.status == "submitted" for p in participants)
        
        if not (all_submitted or is_expired):
            return # Chưa xong thì thôi

        # 3. Tính điểm
        score_a = sum(p.score for p in participants if p.team == "A")
        score_b = sum(p.score for p in participants if p.team == "B")
        
        winner_team = "Draw"
        if score_a > score_b: winner_team = "A"
        elif score_b > score_a: winner_team = "B"
        
        print(f"   📊 Kết quả: A({score_a}) - B({score_b}) => Winner: {winner_team}")

        # 4. TRẢ THƯỞNG (Logic chuẩn ORM)
        total_pot = match.bet_amount * len(participants)
        
        # --- Trường hợp HÒA ---
        if winner_team == "Draw":
            for p in participants:
                player = self.db.get(Player, p.username)
                if player:
                    # Hoàn tiền
                    player.kpi = (player.kpi or 0) + match.bet_amount
                    self.db.add(player)
                    print(f"   Draw -> Hoàn tiền cho {p.username}")

        # --- Trường hợp CÓ NGƯỜI THẮNG ---
        else:
            winners = [p for p in participants if p.team == winner_team]
            if winners:
                reward = int(total_pot / len(winners))
                for w in winners:
                    player = self.db.get(Player, w.username)
                    if player:
                        # 1. Cộng KPI
                        player.kpi = (player.kpi or 0) + reward
                        
                        # 2. Cộng Chiến Tích (Đã đồng bộ với API)
                        player.chien_tich = (player.chien_tich or 0) + 1
                        
                        self.db.add(player)
                        print(f"   🏆 Thắng -> {w.username} (+{reward} KPI, +1 Chiến Tích)")

        # 5. CẬP NHẬT TRẠNG THÁI & LOGS
        match.status = "finished"
        
        # Xác định tên người thắng (Username) để lưu vào DB cho khớp Frontend
        final_winner_name = "Draw"
        if winner_team == "A":
            p_a = next((p for p in participants if p.team == "A"), None)
            if p_a: final_winner_name = p_a.username
        elif winner_team == "B":
            p_b = next((p for p in participants if p.team == "B"), None)
            if p_b: final_winner_name = p_b.username
            
        match.winner_team = final_winner_name
        
        # Lưu Log JSON đầy đủ
        log_data = {
            "winner": winner_team,
            "winner_name": final_winner_name,
            "score": f"{score_a}-{score_b}",
            "reason": "expired" if is_expired else "submitted", # Ghi chú lý do kết thúc
            "time": str(datetime.now())
        }
        match.logs = json.dumps(log_data)
        
        self.db.add(match)
        self.db.commit()
        print(f"✅ [MANAGER] Đã chốt sổ trận đấu thành công!")
    # =========================================================================
    # 4. TIỆN ÍCH KHÁC (HỦY, TIMEOUT)
    # =========================================================================

    def cancel_match(self, match_id: int, request_username: str):
        """
        Hủy trận đấu (Khi đang pending).
        - Chỉ người tạo mới được hủy.
        - Hoàn tiền lại cho người tạo.
        """
        match = self.db.get(ArenaMatch, match_id)
        if not match or match.status != "pending":
            return {"success": False, "message": "Không thể hủy trận này."}

        if match.created_by != request_username:
            return {"success": False, "message": "Bạn không phải chủ phòng."}

        # Hoàn tiền cho tất cả những ai đã đặt cọc (Creator + Joiners trong 2vs2)
        participants = self.db.exec(select(ArenaParticipant).where(
            ArenaParticipant.match_id == match_id
        )).all()

        for p in participants:
            # Chỉ hoàn tiền nếu họ đã bị trừ (status accepted hoặc creator)
            # Với 1vs1: Opponent status='pending' chưa bị trừ tiền -> Ko cần hoàn
            # Với Creator: status='accepted' -> Hoàn
            if p.status == "accepted":
                player = self.db.exec(select(Player).where(Player.username == p.username)).first()
                if player:
                    player.kpi = (player.kpi or 0) + match.bet_amount
                    self.db.add(player)

        match.status = "cancelled"
        self.db.add(match)
        self.db.commit()
        return {"success": True, "message": "Đã hủy trận và hoàn tiền."}

    def process_lazy_timeouts(self):
        """
        Hàm này cần được gọi mỗi khi User vào trang Lôi Đài.
        Nó quét các trận 'active' hoặc 'pending' đã quá hạn để xử lý.
        """
        # 1. Xử lý các trận đang đấu (active) mà hết giờ -> Gọi trọng tài xử thua
        expired_active_matches = self.db.exec(select(ArenaMatch).where(
            ArenaMatch.status == "active",
            ArenaMatch.expires_at < datetime.now()
        )).all()

        for match in expired_active_matches:
            self.check_match_end(match.id)

        # 2. Xử lý các lời mời (pending) quá hạn -> Hủy và hoàn tiền
        expired_pending_matches = self.db.exec(select(ArenaMatch).where(
            ArenaMatch.status == "pending",
            ArenaMatch.expires_at < datetime.now()
        )).all()

        for match in expired_pending_matches:
            # Tái sử dụng logic hủy trận (nhưng cho phép system hủy)
            # Copy logic hoàn tiền ở trên xuống đây để tránh circular dependency phức tạp
            participants = self.db.exec(select(ArenaParticipant).where(ArenaParticipant.match_id == match.id)).all()
            for p in participants:
                if p.status == "accepted":
                    player = self.db.exec(select(Player).where(Player.username == p.username)).first()
                    if player:
                        player.kpi = (player.kpi or 0) + match.bet_amount
                        self.db.add(player)
            
            match.status = "cancelled"
            match.logs = json.dumps({"reason": "Expired (24h no response)"})
            self.db.add(match)
        
        self.db.commit()

