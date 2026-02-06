from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc, delete, text
from database import get_db, ChatLog, Player, ChatBan, ChatKeyword, ChatWarningLog
from datetime import datetime, timedelta
import json
import jwt 
from routes.auth import SECRET_KEY, ALGORITHM 

router = APIRouter()

# --- 1. QUẢN LÝ KẾT NỐI ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[int, WebSocket] = {}

    async def connect(self, websocket: WebSocket, player_id: int):
        await websocket.accept()
        self.active_connections[player_id] = websocket

    def disconnect(self, player_id: int):
        if player_id in self.active_connections:
            del self.active_connections[player_id]

    async def broadcast(self, message_dict: dict):
        msg_json = json.dumps(message_dict)
        disconnected_ids = []
        for pid, ws in self.active_connections.items():
            try:
                await ws.send_text(msg_json)
            except:
                disconnected_ids.append(pid)
        for pid in disconnected_ids:
            self.disconnect(pid)

manager = ConnectionManager()

# --- 2. HỆ THỐNG CHỐNG SPAM & CHECK BAN ---
spam_tracker = {}

# Hàm lấy giờ VN
def get_vn_time():
    return (datetime.utcnow() + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S")

def check_ban_and_spam(player_id: int, db: Session) -> tuple[bool, str]:
    now = datetime.now()
    
    # 1. Kiểm tra trong Database xem có bị Admin cấm không
    ban_info = db.get(ChatBan, player_id)
    if ban_info:
        ban_end = datetime.strptime(ban_info.banned_until, "%Y-%m-%d %H:%M:%S")
        if now < ban_end:
            remain = int((ban_end - now).total_seconds() / 60)
            return False, f"BẠN ĐANG BỊ CẤM CHAT! Lý do: {ban_info.reason}. Còn {remain} phút."
        else:
            # Hết hạn cấm -> Xóa khỏi DB
            db.delete(ban_info)
            db.commit()

    # 2. Kiểm tra Spam (giữ nguyên logic cũ)
    tracker = spam_tracker.get(player_id, {'last_msg': now, 'count': 0, 'banned_until': None})
    if tracker['banned_until'] and now < tracker['banned_until']:
        return False, "Spam quá nhiều! Bị tạm khóa 5 phút."

    time_diff = (now - tracker['last_msg']).total_seconds()
    if time_diff < 1.0: tracker['count'] += 1
    else: tracker['count'] = 1
    
    tracker['last_msg'] = now
    if tracker['count'] > 5:
        tracker['banned_until'] = now + timedelta(minutes=5)
        tracker['count'] = 0
        spam_tracker[player_id] = tracker
        return False, "Bạn chat quá nhanh! Đã bị CẤM CHAT 5 PHÚT."
        
    spam_tracker[player_id] = tracker
    return True, ""

# --- 3. API WEBSOCKET CHÍNH ---
@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...), db: Session = Depends(get_db)):
    # A. Xác thực
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        player = db.query(Player).filter(Player.username == username).first()
        if not player:
            await websocket.close(code=1008)
            return
    except:
        await websocket.close(code=1008)
        return

    await manager.connect(websocket, player.id)
    
    try:
        while True:
            raw_text = await websocket.receive_text()
            
            # 1. Kiểm tra Cấm & Spam
            is_valid, err_msg = check_ban_and_spam(player.id, db)
            if not is_valid:
                await websocket.send_text(json.dumps({"type": "error", "content": err_msg}))
                continue

            content = raw_text.strip()
            if not content: continue

            # 2. KIỂM TRA TỪ KHÓA CẤM (Keyword Filter)
            keywords = db.query(ChatKeyword).all()
            violation_detected = False
            for k in keywords:
                if k.word.lower() in content.lower():
                    violation_detected = True
                    break
            
            # Chuẩn bị tin nhắn
            msg_data = {
                "type": "chat",
                "player_id": player.id,
                "player_name": player.full_name,
                "role": player.role,
                "content": content,
                "time": datetime.now().strftime("%H:%M %d/%m")
            }

            # Gửi tin nhắn đi (kể cả có vi phạm, vẫn gửi nhưng kèm cảnh báo sau đó)
            await manager.broadcast(msg_data)
            
            # Lưu tin nhắn chính
            db.add(ChatLog(player_id=player.id, player_name=player.full_name, role=player.role, content=content, created_at=get_vn_time()))
            
            # 3. XỬ LÝ NẾU VI PHẠM
            if violation_detected:
                # A. Gửi cảnh báo hệ thống công khai
                warning_msg = {
                    "type": "chat",
                    "player_id": 0, # ID 0 là System
                    "player_name": "⚠️ HỆ THỐNG",
                    "role": "SYSTEM",
                    "content": f"[{player.full_name}] đã có ngôn từ không chuẩn mực, xin chú ý! Nếu tái phạm sẽ bị cấm chat 12h.",
                    "time": datetime.now().strftime("%H:%M")
                }
                await manager.broadcast(warning_msg)

                # B. Lưu vào Log bí mật cho Admin
                log_entry = ChatWarningLog(
                    player_id=player.id,
                    player_name=player.full_name,
                    content=content,
                    created_at=get_vn_time()
                )
                db.add(log_entry)

            db.commit()

    except WebSocketDisconnect:
        manager.disconnect(player.id)

# --- 4. CÁC API QUẢN TRỊ (ADMIN ONLY) ---

# API Admin Lấy danh sách Log Vi Phạm
@router.get("/admin/warnings")
def get_warnings(db: Session = Depends(get_db)):
    return db.query(ChatWarningLog).order_by(desc(ChatWarningLog.id)).limit(100).all()

# API Admin Thêm từ khóa cấm
@router.post("/admin/keyword")
def add_keyword(word: str, db: Session = Depends(get_db)):
    if not db.query(ChatKeyword).filter(ChatKeyword.word == word).first():
        db.add(ChatKeyword(word=word))
        db.commit()
    return {"success": True}

# API Admin Ban người chơi
@router.post("/admin/ban")
def ban_player(target_id: int, hours: int, reason: str, db: Session = Depends(get_db)):
    target = db.get(Player, target_id)
    if not target: return {"success": False}
    
    until = (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    
    # Kiểm tra xem đã bị ban chưa, nếu rồi thì cập nhật
    existing_ban = db.get(ChatBan, target_id)
    if existing_ban:
        existing_ban.banned_until = until
        existing_ban.reason = reason
    else:
        new_ban = ChatBan(player_id=target_id, player_name=target.full_name, banned_until=until, reason=reason)
        db.add(new_ban)
    
    db.commit()
    return {"success": True, "message": f"Đã cấm chat {target.full_name} trong {hours}h"}

# API Lấy lịch sử (Giữ nguyên)
@router.get("/history")
def get_chat_history(db: Session = Depends(get_db)):
    msgs = db.query(ChatLog).order_by(desc(ChatLog.id)).limit(50).all()
    results = []
    for msg in reversed(msgs):
        results.append({
            "type": "chat",
            "player_id": msg.player_id,
            "player_name": msg.player_name,
            "role": msg.role,
            "content": msg.content,
            "time": datetime.strptime(msg.created_at, "%Y-%m-%d %H:%M:%S").strftime("%H:%M %d/%m") if msg.created_at else ""
        })
    return results
# API dành cho Admin để lấy danh sách tất cả học sinh để chọn cấm chat
@router.get("/admin/all-players")
def get_all_players_for_admin(db: Session = Depends(get_db)):
    # Chỉ lấy id và full_name để dropdown nhẹ nhàng
    players = db.query(Player.id, Player.full_name).order_by(Player.full_name).all()
    # Chuyển đổi kết quả query thành danh sách dict
    return [{"id": p.id, "full_name": p.full_name} for p in players]
# API dành cho Admin lấy danh sách toàn bộ từ khóa đang bị cấm
@router.get("/admin/keywords_list")
def get_keywords_list(db: Session = Depends(get_db)):
    return db.query(ChatKeyword).all()