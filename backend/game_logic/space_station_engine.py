import json
import random
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlmodel import Session, select

from database import (
    SpaceStationMatch,
    SpaceStationPlayer,
    SpaceStationAction,
    SpaceStationLog,
    Player
)
from game_logic.space_station_biometrics import get_random_clue_from_profile

def resolve_night_phase(match_id: int, db: Session) -> Dict[str, Any]:
    """
    Pipeline giải quyết toàn bộ sự kiện ngày/đêm lúc 22h00.
    Trả về báo cáo tóm tắt các sự kiện đã diễn ra.
    """
    match = db.get(SpaceStationMatch, match_id)
    if not match or match.status != "RUNNING":
        return {"error": "Trận đấu không tồn tại hoặc chưa bắt đầu"}

    # 1. Lấy toàn bộ người chơi và các hành động PENDING trong ngày
    players: List[SpaceStationPlayer] = db.exec(
        select(SpaceStationPlayer).where(SpaceStationPlayer.match_id == match_id)
    ).all()
    
    player_dict: Dict[int, SpaceStationPlayer] = {p.id: p for p in players}
    alive_players = [p for p in players if p.is_alive]

    actions: List[SpaceStationAction] = db.exec(
        select(SpaceStationAction)
        .where(
            SpaceStationAction.match_id == match_id,
            SpaceStationAction.day_number == match.current_day,
            SpaceStationAction.status == "PENDING"
        )
    ).all()

    morning_reports = []  # Lưu các thông báo công khai lúc 06:00
    private_logs = []     # Lưu các thông báo mật cho từng cá nhân
    
    # ----------------------------------------------------
    # BƯỚC 1: XỬ LÝ BIỂU QUYẾT XỬ TỬ BAN NGÀY (DAY VOTE)
    # ----------------------------------------------------
    vote_actions = [a for a in actions if a.action_type == "VOTE_DAY" and a.target_id_1]
    vote_counts: Dict[int, int] = {}
    for v in vote_actions:
        vote_counts[v.target_id_1] = vote_counts.get(v.target_id_1, 0) + 1

    voted_out_player: Optional[SpaceStationPlayer] = None
    
    # Kiểm tra người bị vote cao nhất
    if vote_counts:
        sorted_votes = sorted(vote_counts.items(), key=lambda x: x[1], reverse=True)
        top_target_id, top_votes = sorted_votes[0]
        
        # Kiểm tra hòa phiếu
        is_tie = len(sorted_votes) > 1 and sorted_votes[1][1] == top_votes
        
        if not is_tie and top_target_id in player_dict and player_dict[top_target_id].is_alive:
            voted_out_player = player_dict[top_target_id]
            voted_out_player.is_alive = False
            voted_out_player.death_reason = "VOTE"
            voted_out_player.death_day = match.current_day
            
            p_info = db.get(Player, voted_out_player.player_id)
            morning_reports.append(
                f"Nghị quyết Trạm: Thành viên [{p_info.full_name}] nhận số phiếu biểu quyết cao nhất và đã được đưa vào buồng ngủ đông vĩnh viễn."
            )
            # Reset hình phạt hòa phiếu
            match.skip_vote_penalty = 0
        else:
            # Hòa phiếu hoặc bỏ phiếu trắng chiếm đa số
            match.skip_vote_penalty += 1
            morning_reports.append(
                "Biểu quyết bất thành do hòa phiếu/bỏ phiếu trắng. Hệ thống an ninh suy yếu: Alien được cắn thêm mục tiêu vào đêm nay!"
            )
    else:
        match.skip_vote_penalty += 1
        morning_reports.append(
            "Không có biểu quyết nào được thực hiện. Hệ thống an ninh suy yếu: Alien được cắn thêm mục tiêu vào đêm nay!"
        )

    # ----------------------------------------------------
    # BƯỚC 2: KIỂM TRA ĐIỀU KIỆN THẮNG 1 CỦA GIÁN ĐIỆP
    # ----------------------------------------------------
    spy_players = [p for p in players if p.actual_role == "MARS_SPY"]
    spies_voted_out = [p for p in spy_players if p.death_reason == "VOTE"]
    spies_dead_other = [p for p in spy_players if not p.is_alive and p.death_reason != "VOTE"]

    # ĐK1: Bị vote toàn bộ HOẶC có ít nhất 2 Gián điệp bị vote và những người còn lại chết do nguyên nhân khác
    total_spies = len(spy_players)
    if total_spies > 0:
        cond1_met = False
        if len(spies_voted_out) == total_spies:
            cond1_met = True
        elif len(spies_voted_out) >= 2 and (len(spies_voted_out) + len(spies_dead_other) == total_spies):
            cond1_met = True
            
        if cond1_met:
            match.status = "ENDED"
            match.winner_faction = "MARS_SPY_COND1"
            match.ended_at = datetime.utcnow()
            morning_reports.append("CẢNH BÁO KHẨN CẤP: Toàn bộ nhân sự Sao Hỏa bị thanh trừng! Hạm đội Sao Hỏa đã khai hỏa tấn công. GIÁN ĐIỆP SAO HỎA CHIẾN THẮNG!")
            _save_logs_and_flush(db, match, morning_reports, private_logs, actions)
            return {"status": "GAME_OVER", "winner": "MARS_SPY_COND1"}

    # ----------------------------------------------------
    # BƯỚC 3: XỬ LÝ VỆ BINH QUỐC GIA (KHIÊN BẢO VỆ)
    # ----------------------------------------------------
    protected_ids = set()
    guard_actions = [a for a in actions if a.action_type == "PROTECT" and a.target_id_1]
    for g in guard_actions:
        guard_player = player_dict.get(g.sender_id)
        if guard_player and guard_player.is_alive:
            protected_ids.add(g.target_id_1)

    # ----------------------------------------------------
    # BƯỚC 4: XỬ LÝ SÚNG HÌNH SỰ & THUỐC ĐỘC KHOA HỌC GIA
    # ----------------------------------------------------
    # 4.1. Hình sự ngầm nổ súng
    cop_actions = [a for a in actions if a.action_type == "SHOOT" and a.target_id_1]
    for ca in cop_actions:
        cop = player_dict.get(ca.sender_id)
        target = player_dict.get(ca.target_id_1)
        if cop and cop.is_alive and target and target.is_alive:
            # Bắn trúng Alien hoặc Gián Điệp
            if target.actual_role in ["ALIEN", "MARS_SPY"]:
                target.is_alive = False
                target.death_reason = "GUN"
                target.death_day = match.current_day
                t_info = db.get(Player, target.player_id)
                morning_reports.append(f"An ninh trạm: Phát hiện thi thể [{t_info.full_name}] bị hạ gục bởi đạn năng lượng tầm gần.")
            else:
                # Bắn nhầm Phi hành gia: Hình sự tự tử, nạn nhân an toàn[cite: 8]
                cop.is_alive = False
                cop.death_reason = "SUICIDE"
                cop.death_day = match.current_day
                cop_info = db.get(Player, cop.player_id)
                morning_reports.append(f"Kỷ luật an ninh: Thành viên an ninh ngầm [{cop_info.full_name}] đã tử vong do vi phạm quy tắc nổ súng.")

    # 4.2. Khoa học gia dùng độc
    poison_actions = [a for a in actions if a.action_type == "POISON" and a.target_id_1]
    for pa in poison_actions:
        sci = player_dict.get(pa.sender_id)
        target = player_dict.get(pa.target_id_1)
        if sci and target and target.is_alive:
            target.is_alive = False
            target.death_reason = "POISON"
            target.death_day = match.current_day
            t_info = db.get(Player, target.player_id)
            morning_reports.append(f"Báo cáo y tế: Thành viên [{t_info.full_name}] đã ngưng thở do nhiễm độc tố hóa học lạ.")

    # ----------------------------------------------------
    # BƯỚC 5: XỬ LÝ ALIEN CẮN NGƯỜI & THUỐC CỨU
    # ----------------------------------------------------
    alien_alive = [p for p in players if p.actual_role == "ALIEN" and p.is_alive]
    alien_bites_count = 2 if len(alien_alive) > 1 else (1 if len(alien_alive) == 1 else 0)
    alien_bites_count += match.skip_vote_penalty  # Cộng dồn penalty nếu có[cite: 8]

    alien_vote_actions = [a for a in actions if a.action_type == "ALIEN_BITE"]
    alien_target_votes: Dict[int, int] = {}
    for aa in alien_vote_actions:
        if aa.target_id_1:
            alien_target_votes[aa.target_id_1] = alien_target_votes.get(aa.target_id_1, 0) + 1
        if aa.target_id_2:
            alien_target_votes[aa.target_id_2] = alien_target_votes.get(aa.target_id_2, 0) + 1

    # Tìm ra danh sách nạn nhân Alien muốn cắn
    chosen_victims = []
    if alien_target_votes:
        sorted_alien_targets = sorted(alien_target_votes.items(), key=lambda x: x[1], reverse=True)
        chosen_victims = [t_id for t_id, _ in sorted_alien_targets[:alien_bites_count]]

    # Khoa học gia dùng thuốc cứu
    revive_actions = [a for a in actions if a.action_type == "REVIVE" and a.target_id_1]
    revived_ids = {ra.target_id_1 for ra in revive_actions if player_dict.get(ra.sender_id, None) and player_dict[ra.sender_id].is_alive}

    for vic_id in chosen_victims:
        vic = player_dict.get(vic_id)
        if vic and vic.is_alive:
            if vic_id in protected_ids:
                # Được Vệ binh bảo vệ thành công[cite: 8]
                continue
            elif vic_id in revived_ids:
                # Được Khoa học gia cứu sống kịp thời[cite: 8]
                continue
            else:
                vic.is_alive = False
                vic.death_reason = "ALIEN_BITE"
                vic.death_day = match.current_day
                v_info = db.get(Player, vic.player_id)
                morning_reports.append(f"Cảnh báo sinh học: Phát hiện khoang ngủ đông của [{v_info.full_name}] có dấu vết sinh vật lạ xâm nhập.")

    # ----------------------------------------------------
    # BƯỚC 6: XỬ LÝ THU THẬP THÔNG TIN (ĐIỀU TRA VIÊN & NGOẠI CẢM)
    # ----------------------------------------------------
    # 6.1. Điều tra viên
    inv_actions = [a for a in actions if a.action_type == "INVESTIGATE"]
    for ia in inv_actions:
        inv = player_dict.get(ia.sender_id)
        if inv and inv.is_alive:
            target_ids = json.loads(ia.target_ids_json) if ia.target_ids_json else []
            target_players = [player_dict[tid] for tid in target_ids if tid in player_dict]
            
            has_alien = any(tp.actual_role == "ALIEN" for tp in target_players)
            spy_in_group = [tp for tp in target_players if tp.actual_role == "MARS_SPY"]
            
            if spy_in_group:
                chosen_spy = random.choice(spy_in_group)
                clue = get_random_clue_from_profile(chosen_spy.biometrics_json)
                private_logs.append((inv.id, f"[Điều Tra]: Nhóm 4 người có dấu hiệu gián điệp. Manh mối nhận diện: [{clue}]."))
            elif has_alien:
                private_logs.append((inv.id, "[Điều Tra]: Nhóm 4 người xuất hiện phản ứng sinh học bất thường (Nghi vấn Alien)."))
            else:
                private_logs.append((inv.id, "[Điều Tra]: Nhóm 4 người hoàn toàn bình thường, không phát hiện dấu vết."))

    # 6.2. Nhà ngoại cảm (Mỗi 2 đêm 1 lần)[cite: 8]
    if match.current_day % 2 == 1:
        psychics = [p for p in players if p.actual_role == "PSYCHIC" and p.is_alive]
        enemies = [p for p in players if p.actual_role in ["ALIEN", "MARS_SPY"] and p.is_alive]
        for psy in psychics:
            if enemies:
                target_enemy = random.choice(enemies)
                clue = get_random_clue_from_profile(target_enemy.biometrics_json)
                private_logs.append((psy.id, f"[Giấc Mơ Tâm Linh]: Bạn thoáng thấy hình ảnh một kẻ khả nghi mang đặc điểm: [{clue}]."))

    # ----------------------------------------------------
    # BƯỚC 7: XỬ LÝ THƯ CHIÊU MỘ GIÁN ĐIỆP & NGƯỜI 2 MẶT
    # ----------------------------------------------------
    spy_letters = [a for a in actions if a.action_type == "SPY_LETTER" and a.target_id_1]
    for sla in spy_letters:
        target = player_dict.get(sla.target_id_1)
        if target and target.is_alive and target.actual_role not in ["ALIEN", "MARS_SPY"]:
            # Tạo thư nặc danh gửi vào hòm thư mục tiêu
            private_logs.append((
                target.id,
                "[Thư Nặc Danh Sao Hỏa]: Chúng tôi muốn mời bạn tham gia giải phóng Trạm Không Gian. Hãy lựa chọn: Đồng ý hoặc Từ chối."
            ))

    # ----------------------------------------------------
    # BƯỚC 8: KIỂM TRA ĐIỀU KIỆN THẮNG CHUNG CUỘC
    # ----------------------------------------------------
    alive_now = [p for p in players if p.is_alive]
    n_alive = len(alive_now)
    a_alive = len([p for p in alive_now if p.actual_role == "ALIEN"])
    s_alive = len([p for p in alive_now if p.actual_role == "MARS_SPY"])

    # Điều kiện thắng Alien: Alien >= 1/2 số người còn lại (không tính Alien) -> A >= (N - A) / 2[cite: 8]
    if a_alive > 0 and a_alive >= (n_alive - a_alive) / 2:
        match.status = "ENDED"
        match.winner_faction = "ALIEN"
        match.ended_at = datetime.utcnow()
        morning_reports.append("TRẠM ĐÃ THẤT THỦ: Sinh vật ngoài hành tinh đã chiếm quyền kiểm soát toàn bộ trạm! ALIEN CHIẾN THẮNG!")
    
    # Điều kiện thắng Gián Điệp 2: Gián điệp >= 1/2 số người còn lại (không tính Gián điệp)[cite: 8]
    elif s_alive > 0 and s_alive >= (n_alive - s_alive) / 2:
        match.status = "ENDED"
        match.winner_faction = "MARS_SPY_COND2"
        match.ended_at = datetime.utcnow()
        morning_reports.append("CHIẾM QUYỀN TÀU: Gián điệp Sao Hỏa đã chiếm quyền điều khiển khoang chỉ huy! GIÁN ĐIỆP SAO HỎA CHIẾN THẮNG!")
    
    # Điều kiện thắng Phi Hành Đoàn: Tiêu diệt cả Alien và Gián Điệp[cite: 8]
    elif a_alive == 0 and s_alive == 0:
        match.status = "ENDED"
        match.winner_faction = "ASTRONAUT"
        match.ended_at = datetime.utcnow()
        morning_reports.append("KHỞI HOÀN: Tất cả hiểm họa Alien và Gián điệp đã bị thanh trừng. PHI HÀNH ĐOÀN CHIẾN THẮNG!")
    
    else:
        # Chuyển sang ngày tiếp theo
        match.current_day += 1

    # Lưu lại toàn bộ dữ liệu & Logs
    _save_logs_and_flush(db, match, morning_reports, private_logs, actions)
    return {"status": "SUCCESS", "current_day": match.current_day, "reports": morning_reports}


def _save_logs_and_flush(db: Session, match: SpaceStationMatch, morning_reports: List[str], private_logs: List[tuple], actions: List[SpaceStationAction]):
    """Ghi nhận nhật ký và đóng trạng thái lệnh"""
    # 1. Ghi log công khai
    if morning_reports:
        public_content = "<br>• " + "<br>• ".join(morning_reports)
        log_pub = SpaceStationLog(
            match_id=match.id,
            day_number=match.current_day,
            log_type="MORNING_REPORT_PUBLIC",
            receiver_id=None,
            content_text=public_content
        )
        db.add(log_pub)

    # 2. Ghi log riêng tư
    for recv_id, msg in private_logs:
        log_priv = SpaceStationLog(
            match_id=match.id,
            day_number=match.current_day,
            log_type="PRIVATE_CLUE",
            receiver_id=recv_id,
            content_text=msg
        )
        db.add(log_priv)

    # 3. Đánh dấu các lệnh đã hoàn tất
    for a in actions:
        a.status = "EXECUTED"
        db.add(a)

    db.add(match)
    db.commit()