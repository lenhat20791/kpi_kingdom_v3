import traceback
import os, json, random
import asyncio
import threading
import time
import pytz
from contextlib import asynccontextmanager
from typing import Optional

# --- IMPORT CHUẨN CHO DATETIME ---
# Bỏ cái 'import datetime as dt' đi cho đỡ rối
from datetime import datetime, timedelta 
# --- IMPORT CHUẨN CHO FASTAPI ---
from fastapi import FastAPI, Depends, HTTPException, status, Query, Body, APIRouter, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse

# --- IMPORT CHUẨN CHO SQLMODEL & SQLALCHEMY ---
from sqlmodel import Session, select, update, col, func, or_, and_
from sqlalchemy import func, desc, or_ 

# --- IMPORT FILE CẤU HÌNH & DB ---
import campaign_config as cfg
from pydantic import BaseModel
from database import (
    create_db_and_tables, engine, Player, get_db, Item, Inventory, 
    Title, TowerProgress, Boss, QuestionBank, BossLog, ArenaMatch, 
    ArenaParticipant, SystemStatus, ChatLog, Campaign, CampaignPlayer, 
    MapNode, TroopMovement, Companion, CompanionTemplate, BattleReport, CampaignChat, ScoreLog, CampaignChat
)

# --- IMPORT ROUTES & LOGIC ---
from routes import (
    admin, users, shop, tower, pets, inventory_api, arena_api, 
    auth, skills, market_api, notifications, chat_api, companion
)
from routes.auth import get_password_hash
from game_logic.level import add_exp_to_player
# 2. Viết hàm tạo Admin mặc định (Đây là giải pháp gốc rễ)
def create_default_admin():
    with Session(engine) as session:
        # Kiểm tra xem đã có admin chưa
        admin = session.exec(select(Player).where(Player.username == "admin")).first()
        
        if not admin:
            print("⚡ Đang khởi tạo tài khoản Admin mặc định...")
            
            # 👇 ĐÂY LÀ CHỖ QUAN TRỌNG NHẤT: MÃ HÓA MẬT KHẨU TRƯỚC KHI LƯU
            hashed_pwd = get_password_hash("123456")
            
            admin_user = Player(
                username="admin",
                password_hash=hashed_pwd, # Lưu bản mã hóa cho máy đọc
                plain_password="123456",  # Lưu bản thô cho người đọc (nếu muốn soi)
                full_name="Admin Hệ Thống",
                role="admin",
                hp=9999,    # Admin thì máu trâu tí
                level=100,
                xp=0,
                team_id=0   # Team 0 dành riêng cho ban tổ chức
            )
            
            session.add(admin_user)
            session.commit()
            print("✅ Đã tạo User: admin / Pass: 123456 (Đã mã hóa bảo mật)")
        else:
            print("👌 Tài khoản Admin đã tồn tại. Bỏ qua.")

# 3. Cấu hình sự kiện khởi động (Lifespan)
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("="*50)
    print("🎬 FASTAPI LIFESPAN: Đang khởi động hệ thống...")
    print("="*50)
    
    # 1. Khởi tạo Database cơ bản
    create_db_and_tables() 
    create_default_admin() 
    
    # 2. KÍCH HOẠT BATTLE ENGINE (Chạy ngầm liên tục)
    print("🚀 Khởi động luồng BATTLE ENGINE (asyncio)...")
    engine_task = asyncio.create_task(campaign_game_loop())
    
    # 3. Giao lại quyền điều khiển cho Web Server
    yield 
    
    # ==========================================
    # PHẦN NÀY CHẠY KHI BẠN NHẤN CTRL+C TẮT SERVER
    # ==========================================
    print("🛑 Server shutting down... Đang dọn dẹp tài nguyên...")
    engine_task.cancel() # Ra lệnh dừng vòng lặp hành quân
    try:
        await engine_task # Đợi nó dừng hẳn
    except asyncio.CancelledError:
        print("✅ Đã tắt BATTLE ENGINE an toàn.")

app = FastAPI(
    title="KPI Kingdom V3 API",  # Cấu hình tiêu đề
    lifespan=lifespan            # Cấu hình tự động tạo Admin
)
# --- HÀM PHỤ TRỢ (HELPER): KIỂM TRA & HỒI SINH ---
# Hàm này không cần @app vì nó chỉ được gọi bởi các hàm khác
def check_and_revive_player(player: Player, db: Session):
    """
    Kiểm tra nếu người chơi đang chết mà đã qua thời gian chờ -> Hồi sinh Full HP
    """
    # Logic kiểm tra: Đang chết (HP <= 0) VÀ Có án tử (revive_at)
    if player.hp <= 0 and player.revive_at:
        # Nếu thời gian hiện tại (Now) > Thời gian được hồi sinh (revive_at)
        if datetime.now() > player.revive_at:
            player.hp = player.hp_max # Hồi đầy máu
            player.revive_at = None   # Xóa án tử
            
            db.add(player)
            db.commit()
            db.refresh(player)
            print(f"✨ Đã hồi sinh người chơi {player.username}!")
            
    return player


# --- CẤU HÌNH CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- INCLUDE ROUTERS (Đăng ký các module) ---
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(users.router, prefix="/api/user", tags=["Users"])
app.include_router(shop.router, tags=["Shop"])
app.include_router(tower.router, prefix="/api/tower", tags=["Tower"])
app.include_router(pets.router, prefix="/api/pets", tags=["Pet System"])
app.include_router(inventory_api.router, prefix="/api", tags=["Inventory"])
app.include_router(arena_api.router, prefix="/api", tags=["Arena"])
app.include_router(users.router_public, prefix="/api", tags=["Public Info"])
app.include_router(auth.router, prefix="/api", tags=["Authentication"])
app.include_router(skills.router, prefix="/api/skills", tags=["Skills System"])
app.include_router(market_api.router)
app.include_router(notifications.router, prefix="/api/noti", tags=["Notifications"])
app.include_router(chat_api.router, prefix="/api/chat", tags=["Chat"])
app.include_router(companion.router, prefix="/api", tags=["Companion"])
# --- CẤU HÌNH ĐƯỜNG DẪN FILE (Phiên bản Tuyệt Đối - Chống Lỗi) ---

# 1. Lấy đường dẫn tuyệt đối của file main.py đang chạy
current_file_path = os.path.abspath(__file__)
backend_dir = os.path.dirname(current_file_path)

# 2. Suy ra thư mục project root (Giả sử main.py nằm trong backend/)
# Ta lùi ra 1 cấp để về thư mục gốc của dự án
project_root = os.path.dirname(backend_dir) 

# 3. Tạo đường dẫn đến frontend
frontend_dir = os.path.join(project_root, "frontend")
assets_dir = os.path.join(frontend_dir, "assets")
css_dir = os.path.join(frontend_dir, "css")
backend_path = backend_dir

# 4. MOUNT THƯ MỤC
if os.path.exists(frontend_dir):
    # 👇 QUAN TRỌNG: Dòng này giúp server hiểu đường dẫn bắt đầu bằng /frontend
    app.mount("/frontend", StaticFiles(directory=frontend_dir), name="frontend")
    print(f"✅ Đã mount thư mục Frontend: {frontend_dir}")
else:
    print(f"❌ LỖI: Không tìm thấy thư mục Frontend tại: {frontend_dir}")

assets_dir = os.path.join(frontend_dir, "assets")    
if os.path.exists(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
else:
    print("⚠️ CẢNH BÁO: Không thấy thư mục Assets!")

if os.path.exists(css_dir):
    app.mount("/css", StaticFiles(directory=css_dir), name="css")
    print("✅ Đã mount thành công thư mục CSS!")
else:
    print("❌ LỖI: Không tìm thấy thư mục CSS! Hãy kiểm tra lại tên folder.")
frontend_path = frontend_dir
backend_path = backend_dir
# --- Model dữ liệu gửi lên từ trang Login ---
class LoginRequest(BaseModel):
    username: str
    password: str
# Model nhận dữ liệu
class BaseRequest(BaseModel):
    username: str
class BuyRequest(BaseModel):
    item_id: int # Vì item.id trong model là Int
    username: str
class AttackRequest(BaseModel):
    boss_id: int
    player_id: int = 0         # ID người chơi (Để cộng thưởng chính xác)
    player_name: str           # Tên người chơi (Để ghi log nhanh)
    damage: int = 0            # Frontend gửi lên (nếu = 0 Server sẽ tự tính)
    question_id: int = 0       # ID câu hỏi vừa trả lời (Để check đáp án)
    selected_option: str = ""        # Sát thương gây ra (thường là 50-100 tùy cấu hình)
class MarchByCodeRequest(BaseModel):
    username: str
    target_node_code: str
# 3. API: Người chơi Báo danh / Rút lui
class JoinFactionRequest(BaseModel):
    username: str
    faction: str # "THANH_LONG", "BACH_HO", hoặc "LEAVE"

class SetCommanderRequest(BaseModel):
    username: str
    companion_id: str

# 1. Khai báo khung dữ liệu chat nhận vào
class ChatRequest(BaseModel):
    username: str
    message: str
    channel: str # "ALL" hoặc "ALLY"
# Khai báo form nhận thưởng minigame chien dich
class MinigameRewardRequest(BaseModel):
    username: str
    campaign_id: int

# 2. API Đăng nhập (Chấp nhận password thô từ Excel)
@app.post("/api/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    # Tìm user (chuyển về chữ thường để không phân biệt hoa thường)
    username_clean = data.username.lower().strip()
    statement = select(Player).where(Player.username == username_clean)
    player = db.exec(statement).first()
    
    # Kiểm tra tồn tại
    if not player:
        raise HTTPException(status_code=400, detail="Tên đăng nhập không tồn tại!")
    
    # KIỂM TRA PASSWORD
    # Vì dữ liệu Excel nhập vào là text thô, ta so sánh trực tiếp
    # Sau này nếu muốn bảo mật hơn thì mới bật lại verify_password
    if player.password_hash != data.password:
         raise HTTPException(status_code=400, detail="Mật khẩu không đúng!")

    # Trả về thông tin (để Frontend lưu vào localStorage)
    return {
        "status": "success", 
        "message": "Đăng nhập thành công",
        "user_info": {
            "id": player.id,
            "username": player.username,
            "full_name": player.full_name,
            "class_type": player.class_type,
            "role": getattr(player, "role", "student") # Fallback nếu chưa có cột role
        }
    }

# 3. Trang chủ -> Mở trang Login (index.html)
@app.get("/")
async def read_root():
    # Ưu tiên tìm index.html ngay cạnh main.py (Backend)
    local_index = os.path.join(backend_path, "index.html")
    if os.path.exists(local_index):
        return FileResponse(local_index)
    
    return {"error": "Không tìm thấy file index.html. Hãy tạo file này ngang hàng với main.py"}

# 4. Các trang HTML khác
@app.get("/player_dashboard.html")
async def view_player_dashboard():
    # Tìm ở backend trước (nếu bạn lỡ để ở đó), sau đó tìm ở frontend
    paths_to_check = [
        os.path.join(backend_path, "player_dashboard.html"),
        os.path.join(frontend_path, "player_dashboard.html")
    ]
    for path in paths_to_check:
        if os.path.exists(path):
            return FileResponse(path)
    return {"error": "File player_dashboard.html not found"}

# Trang Admin (HTML)
@app.get("/admin.html")
async def view_admin_dashboard():
    paths_to_check = [
        os.path.join(backend_path, "admin.html"),
        os.path.join(frontend_path, "admin.html")
    ]
    for path in paths_to_check:
        if os.path.exists(path):
            return FileResponse(path)
    return {"error": "File admin.html not found"}

@app.get("/parent.html")
async def view_parent_page():
    # Tìm ở backend trước, sau đó tìm ở frontend theo đúng logic các hàm cũ
    paths_to_check = [
        os.path.join(backend_path, "parent.html"),
        os.path.join(frontend_path, "parent.html")
    ]
    for path in paths_to_check:
        if os.path.exists(path):
            return FileResponse(path)
    return {"error": "File parent.html not found"}

@app.get("/index.html")
async def read_index():
    # Điều hướng về file index.html y hệt như trang chủ
    local_index = os.path.join(backend_path, "index.html")
    if os.path.exists(local_index):
        return FileResponse(local_index)
    return JSONResponse(content={"error": "Chưa tạo file index.html"}, status_code=404)
    
# --- hàm lấy thông tin item  ---
@app.get("/api/shop/items")
def get_shop_items(db: Session = Depends(get_db)):
    try:
        # 1. TRUY VẤN
        # Lấy tất cả item mà is_hidden = False (hoặc None)
        statement = select(Item).where((Item.is_hidden == False) | (Item.is_hidden == 0) | (Item.is_hidden == None))
        results = db.exec(statement).all()
        
        shop_items = []
        for item in results:
            # 2. MAP DỮ LIỆU (Khớp với model của bạn)
            shop_items.append({
                "id": item.id,
                "name": item.name,
                "description": item.description,
                
                # 👇 Sửa đúng tên cột trong model của bạn
                "icon": item.image_url if item.image_url else "default.png", 
                "price": item.price,
                
                # 👇 Sửa đúng tên cột tiền tệ
                "currency": item.currency_type  # tri_thuc, vinh_du, chien_tich
            })
            
        return {"status": "success", "items": shop_items}

    except Exception as e:
        print(f"❌ Lỗi lấy Shop Item: {e}")
        return {"status": "error", "message": "Lỗi Server khi tải Shop"}


@app.post("/api/shop/buy")
def buy_item(data: BuyRequest, db: Session = Depends(get_db)):
    try:
        # 1. TÌM NGƯỜI CHƠI (Dùng username gửi lên thay vì Token)
        # Lưu ý: cần import select ở đầu file (đã có sẵn)
        statement = select(Player).where(Player.username == data.username)
        current_user = db.exec(statement).first()
        
        if not current_user:
            return {"status": "error", "message": "Người chơi không tồn tại!"}

        # 2. TÌM MÓN ĐỒ
        item = db.get(Item, data.item_id)
        if not item:
            return {"status": "error", "message": "Món đồ không tồn tại!"}
        
        # 3. KIỂM TRA TIỀN
        cost = item.price
        currency = item.currency_type # ví dụ: "tri_thuc"
        
        # Lấy số dư hiện tại
        current_balance = getattr(current_user, currency, 0)
        
        if current_balance < cost:
            return {"status": "error", "message": f"Bạn không đủ {currency}!"}

        # 4. TRỪ TIỀN & LƯU
        new_balance = current_balance - cost
        setattr(current_user, currency, new_balance)
        db.add(current_user)

        # 5. THÊM ĐỒ VÀO TÚI (INVENTORY)
        # Kiểm tra xem đã có món này trong túi chưa
        inv_statement = select(Inventory).where(
            Inventory.player_id == current_user.id,
            Inventory.item_id == item.id
        )
        existing_item = db.exec(inv_statement).first()

        if existing_item:
            # Nếu có rồi -> Tăng số lượng
            existing_item.amount += 1
            db.add(existing_item)
        else:
            # Nếu chưa có -> Tạo mới
            new_inv = Inventory(
                player_id=current_user.id,
                item_id=item.id,
                amount=1,
                is_equipped=False
            )
            db.add(new_inv)

        # 6. COMMIT (Chốt đơn)
        db.commit()
        
        return {
            "status": "success", 
            "message": f"Đã mua thành công: {item.name}",
            "new_balance": new_balance 
        }

    except Exception as e:
        print(f"❌ Lỗi Mua Hàng: {e}")
        db.rollback() 
        return {"status": "error", "message": str(e)}
        
# --- API BẢNG VINH DANH (PUBLIC - KHÔNG CẦN LOGIN) ---
@app.get("/api/public/hall-of-fame")
def get_hall_of_fame(db: Session = Depends(get_db)):
    try:
        # 1. Lấy danh sách Danh Hiệu
        titles = db.exec(select(Title).order_by(Title.min_kpi.desc())).all()

        # 2. Lấy Học sinh (Lấy dư ra khoảng 20 người để lọc dần là vừa)
        players = db.exec(
            select(Player)
            .where(Player.kpi > 0)
            .where(Player.username != "admin")
            .order_by(Player.kpi.desc())
            .limit(20) # 👈 Lấy dư ra, vì có thể top 10 chưa chắc đã đủ điểm danh hiệu
        ).all()
        
        leaderboard = []
        
        for p in players:
            # 3. Logic: Tìm danh hiệu
            my_title = None 
            my_color = None 
            
            for t in titles:
                if p.kpi >= t.min_kpi:
                    my_title = t.name
                    my_color = t.color
                    break 
            
            # 👇 --- [THAY ĐỔI QUAN TRỌNG Ở ĐÂY] --- 👇
            # Nếu KHÔNG có danh hiệu (vẫn là None) thì BỎ QUA, không thêm vào list
            if my_title is None:
                continue 

            # Nếu CÓ danh hiệu thì mới thêm
            leaderboard.append({
                "username": p.username,
                "full_name": p.full_name,
                "kpi": p.kpi,
                "title": my_title,
                "color": my_color,
                "avatar": p.class_type if p.class_type else "NOVICE"
            })
            
            # Chỉ lấy đủ Top 10 người có danh hiệu thì dừng
            if len(leaderboard) >= 10:
                break
            
        return leaderboard

    except Exception as e:
        print(f"❌ Lỗi lấy BXH: {e}")
        return []
    
# --- API BXH THÁP THÍ LUYỆN (ĐÃ SỬA THEO DB CỦA BẠN) ---
@app.get("/api/public/tower-ranking")
def get_tower_ranking(db: Session = Depends(get_db)):
    try:
        # 1. Query kết hợp (JOIN) 2 bảng
        # Lấy Top 10 người có max_floor cao nhất
        results = db.exec(
            select(Player, TowerProgress)
            .join(TowerProgress, Player.id == TowerProgress.player_id)
            .where(TowerProgress.max_floor > 0) # Chỉ lấy ai đã leo tháp
            .order_by(TowerProgress.max_floor.desc())
            .limit(10)
        ).all()
        
        ranking = []
        
        # 2. Xử lý kết quả trả về
        # results lúc này là list các cặp [(Player, TowerProgress), (Player, TowerProgress)...]
        for player, progress in results:
            ranking.append({
                "username": player.username,
                "full_name": player.full_name,
                # Lấy dữ liệu tầng cao nhất từ bảng Progress
                "tower_floor": progress.max_floor, 
                "class_type": player.class_type if player.class_type else "Tân Binh"
            })
            
        return ranking

    except Exception as e:
        print(f"❌ Lỗi lấy BXH Tháp: {e}")
        return []    

# --- API BXH boss  ---
# Nhớ import Player ở đầu file nếu chưa có
# from database import Player 

@app.get("/api/public/boss-leaderboard")
def get_boss_leaderboard(db: Session = Depends(get_db)):
    print("👉 [DEBUG] Đang gọi API Leaderboard...") 
    try:
        # 1. TÌM BOSS MỚI NHẤT
        current_boss = db.exec(select(Boss).order_by(Boss.id.desc())).first()

        if not current_boss:
            return {"active": False, "message": "Chưa có dữ liệu Boss", "data": []}

        # 2. TÍNH TỔNG DAMAGE (CÓ JOIN VỚI BẢNG PLAYER)
        # Logic: Join BossLog với Player thông qua username để lấy full_name
        statement_logs = (
            select(
                BossLog.player_name, 
                func.sum(BossLog.dmg_dealt).label("total_damage"),
                Player.full_name  # 👈 LẤY THÊM CỘT NÀY
            )
            .join(Player, BossLog.player_name == Player.username) # 👈 KẾT NỐI 2 BẢNG
            .where(BossLog.boss_id == current_boss.id)
            .group_by(BossLog.player_name, Player.full_name) # Group theo cả tên thật
            .order_by(desc("total_damage"))
            .limit(10)
        )
        
        results = db.exec(statement_logs).all()
        
        # 3. TRẢ VỀ KẾT QUẢ
        leaderboard = []
        for row in results:
            # row[0]: username, row[1]: damage, row[2]: full_name
            
            # Ưu tiên lấy full_name, nếu không có thì lấy username
            display_name = row[2] if row[2] else row[0]

            leaderboard.append({
                "username": row[0],      # Giữ lại username để debug hoặc làm link avatar
                "name": display_name,    # Tên hiển thị (Tiếng Việt)
                "total_damage": row[1] or 0
            })

        print(f"✅ [SUCCESS] Lấy được {len(leaderboard)} người chơi.")

        return {
            "active": True, 
            "boss_name": current_boss.name, 
            "boss_image": current_boss.image_url,
            "status": current_boss.status,
            "data": leaderboard
        }

    except Exception as e:
        import traceback
        traceback.print_exc() 
        print(f"❌ [LỖI NGHIÊM TRỌNG]: {str(e)}")
        return {"active": False, "message": f"Lỗi Code: {str(e)}", "data": []}
    
@app.get("/api/boss/active-info")
def get_active_boss_for_player(db: Session = Depends(get_db)):
    # Tìm con Boss đang có status = "active"
    boss = db.exec(select(Boss).where(Boss.status == "active")).first()
    
    if not boss:
        return {"has_boss": False, "message": "Hiện chưa có Boss nào xuất hiện."}
    
    # Trả về dữ liệu cần thiết để vẽ UI
    return {
        "has_boss": True,
        "id": boss.id,
        "name": boss.name,
        "grade": boss.grade,    # (Nên thêm cái này để hiển thị Lớp mấy)
        "subject": boss.subject, # (Nên thêm cái này để đổi màu hào quang)
        "image_url": boss.image_url,
        "current_hp": boss.current_hp,
        "max_hp": boss.max_hp,
        
        # 👇 QUAN TRỌNG: Thêm 2 dòng này để Animation và VFX hoạt động
        "animation": boss.animation,
        "vfx": boss.vfx,  # <--- BẠN ĐANG THIẾU DÒNG NÀY!

        "time_limit": boss.time_limit,
        "rewards": {
            "kpi": boss.reward_kpi,
            "tri_thuc": boss.reward_tri_thuc,
            "rare_rate": boss.rare_item_rate
        }
    }

@app.post("/api/boss/attack")
def attack_boss(req: AttackRequest, db: Session = Depends(get_db)):
    try:
        # ==================================================================
        # 1. TÌM NGƯỜI CHƠI (Ưu tiên tìm trước để check sống/chết)
        # ==================================================================
        player = None
        if req.player_id > 0:
            player = db.get(Player, req.player_id)
        if not player: # Fallback tìm theo tên
            player = db.exec(select(Player).where(Player.username == req.player_name)).first()
            
        if not player:
            return {"success": False, "message": "Không tìm thấy dữ liệu người chơi!"}

        # ------------------------------------------------------------------
        # [LOGIC MỚI] KIỂM TRA SỐNG / CHẾT & HỒI SINH
        # ------------------------------------------------------------------
        # Gọi hàm phụ trợ để xem đã được hồi sinh chưa
        check_and_revive_player(player, db) 
        
        # Nếu vẫn còn chết (HP <= 0) -> Chặn không cho đánh
        if player.hp <= 0:
            time_left_str = "một lúc nữa"
            if player.revive_at:
                delta = player.revive_at - datetime.now()
                # Tính phút giây còn lại
                total_seconds = int(delta.total_seconds())
                if total_seconds > 0:
                    minutes = total_seconds // 60
                    seconds = total_seconds % 60
                    time_left_str = f"{minutes} phút {seconds} giây"
                else:
                    time_left_str = "vài giây"

            return {
                "success": False, 
                "message": f"💀 Bạn đang trọng thương! Cần nghỉ ngơi thêm {time_left_str}.",
                "is_dead_player": True # Cờ báo hiệu cho Frontend hiện màn hình chết
            }

        # ==================================================================
        # 2. TÌM BOSS
        # ==================================================================
        boss = db.get(Boss, req.boss_id)
        if not boss or boss.status != "active":
            return {"success": False, "message": "Boss không khả dụng!"}

        # ==================================================================
        # 3. KIỂM TRA ĐÁP ÁN (Logic Anti-Cheat & Map Option)
        # ==================================================================
        is_correct = True 
        if req.question_id > 0:
            question = db.get(QuestionBank, req.question_id)
            if question:
                try:
                    # Lấy đáp án đúng từ DB
                    db_correct_val = str(question.correct_answer).strip()
                    # Parse JSON option
                    options_list = json.loads(question.options_json) if isinstance(question.options_json, str) else question.options_json
                    
                    # Tìm Key đúng (a,b,c,d) tương ứng với Value
                    correct_key = "a"
                    if len(options_list) >= 1 and str(options_list[0]).strip() == db_correct_val: correct_key = "a"
                    elif len(options_list) >= 2 and str(options_list[1]).strip() == db_correct_val: correct_key = "b"
                    elif len(options_list) >= 3 and str(options_list[2]).strip() == db_correct_val: correct_key = "c"
                    elif len(options_list) >= 4 and str(options_list[3]).strip() == db_correct_val: correct_key = "d"

                    # So sánh
                    user_key = str(req.selected_option).lower().strip()
                    if user_key != correct_key:
                        is_correct = False
                        
                except Exception as e:
                    print(f"⚠️ Lỗi check đáp án: {e}")
                    # Nếu lỗi hệ thống thì tạm tha cho người chơi
                    is_correct = True
        
        # ==================================================================
        # 4. XỬ LÝ KẾT QUẢ (TRỪ MÁU PLAYER HOẶC TRỪ MÁU BOSS)
        # ==================================================================
        
        # --- TRƯỜNG HỢP A: TRẢ LỜI SAI (NGƯỜI CHƠI MẤT MÁU THẬT) ---
        if not is_correct:
            # 1. Tính damage Boss gây ra (20% Max HP hoặc tối thiểu 10)
            if boss.atk and boss.atk > 0:
                dmg_to_player = boss.atk
            else:
                # Nếu Boss chưa set ATK thì mới dùng công thức cũ (20% máu người chơi)
                dmg_to_player = int(player.hp_max * 0.2)
                if dmg_to_player < 10: dmg_to_player = 10
            
            # 2. Trừ máu và cập nhật DB
            player.hp -= dmg_to_player
            player_died_now = False
            
            # 3. Kiểm tra chết
            if player.hp <= 0:
                player.hp = 0
                player_died_now = True
                # Gán án tử: 30 phút sau mới được chơi
                player.revive_at = datetime.now() + timedelta(minutes=30)
            
            # 4. Lưu ngay lập tức
            db.add(player)
            db.commit()
            
            # Tạo thông báo
            msg = f"❌ Sai rồi! Bạn mất {dmg_to_player} máu."
            if player_died_now:
                msg = "💀 BẠN ĐÃ GỤC NGÃ! Cần 30 phút để hồi phục."

            return {
                "success": False, 
                "correct": False,
                "message": msg,
                "boss_hp": boss.current_hp,
                "player_hp": player.hp,         # Trả về HP mới để Frontend update
                "dmg_taken": dmg_to_player,
                "is_dead_player": player_died_now,
                "revive_at": player.revive_at.isoformat() if player.revive_at else None
            }

        # --- TRƯỜNG HỢP B: TRẢ LỜI ĐÚNG (BOSS MẤT MÁU) ---
        
        # 1. Tính Damage Player gây ra
        final_damage = req.damage
        if final_damage <= 0: # Fallback server tự tính
            base_dmg = 10
            kpi_bonus = (player.kpi or 0) * 0.2
            level_bonus = (player.level or 1) * 10
            final_damage = int(base_dmg + kpi_bonus + level_bonus)
            
        # 2. Trừ máu Boss
        if boss.current_hp is None: boss.current_hp = boss.max_hp
        actual_dmg = min(boss.current_hp, final_damage)
        boss.current_hp -= actual_dmg
        
        # 3. Ghi log
        msg_str = f"{req.player_name} gây {actual_dmg} dmg cho boss!"

        new_log = BossLog(
            boss_id=boss.id,
            player_name=req.player_name,
            action="attack_hit",       # Giữ lại để phân loại nếu cần
            dmg_dealt=actual_dmg,      # Giữ lại để tô màu damage to/nhỏ
            hp_left=boss.current_hp,
            message=msg_str            # 👈 LƯU CÂU THÔNG BÁO VÀO ĐÂY
        )
        db.add(new_log)

        # 4. Check Boss chết
        is_dead = False
        rewards = None
        drop_msg = None
        
        if boss.current_hp <= 0:
            boss.current_hp = 0
            boss.status = "defeated"
            is_dead = True
            
            # 1. Khởi tạo danh sách phần thưởng
            rewards_list_str = [] # Để tạo câu thông báo
            frontend_rewards = { "kpi": 0, "items": [] } # Để gửi về Frontend vẽ hình

            if player:
                # --- A. CỘNG TIỀN TỆ ---
                rw_kpi = boss.reward_kpi or 0
                rw_tri_thuc = boss.reward_tri_thuc or 0
                rw_chien_tich = boss.reward_chien_tich or 0
                rw_vinh_du = boss.reward_vinh_du or 0

                player.kpi = (player.kpi or 0) + rw_kpi
                player.tri_thuc = (player.tri_thuc or 0) + rw_tri_thuc
                player.chien_tich = (player.chien_tich or 0) + rw_chien_tich
                player.vinh_du = (player.vinh_du or 0) + rw_vinh_du
                
                # Ghi vào thông báo
                if rw_kpi > 0: rewards_list_str.append(f"+{rw_kpi} KPI")
                if rw_tri_thuc > 0: rewards_list_str.append(f"+{rw_tri_thuc} Tri thức")
                if rw_chien_tich > 0: rewards_list_str.append(f"+{rw_chien_tich} Chiến tích")
                if rw_vinh_du > 0: rewards_list_str.append(f"+{rw_vinh_du} Vinh dự")

                # --- B. XỬ LÝ DROP POOL (NHIỀU MÓN) ---
                try:
                    # Giải mã JSON: [{"id": "1", "rate": 50}, ...]
                    pool = json.loads(boss.drop_pool) if boss.drop_pool else []
                    
                    for drop_config in pool:
                        d_id = drop_config.get("id")
                        d_rate = float(drop_config.get("rate", 0))
                        
                        # Quay số cho TỪNG MÓN
                        if d_id and random.uniform(0, 100) <= d_rate:
                            item_obj = db.get(Item, int(d_id))
                            if item_obj:
                                # Cộng vào kho
                                inv_item = db.exec(select(Inventory).where(
                                    Inventory.player_id == player.id, 
                                    Inventory.item_id == item_obj.id
                                )).first()

                                if inv_item:
                                    inv_item.amount += 1
                                    db.add(inv_item)
                                else:
                                    new_inv = Inventory(player_id=player.id, item_id=item_obj.id, amount=1)
                                    db.add(new_inv)
                                
                                # Thêm vào danh sách thông báo
                                rewards_list_str.append(f"🎁 {item_obj.name}")
                                frontend_rewards["items"].append({
                                    "name": item_obj.name,
                                    "image": item_obj.image_url
                                })
                except Exception as e:
                    print(f"⚠️ Lỗi Drop Pool: {e}")

                db.add(player)

            # --- C. TẠO THÔNG BÁO HOÀN CHỈNH ---
            full_msg = "🏆 TIÊU DIỆT BOSS THÀNH CÔNG!\n\nBạn nhận được:\n" + "\n".join(rewards_list_str)

            # Lưu Boss
            db.add(boss)
            db.commit()
            db.refresh(boss)

            return {
                "success": True,
                "correct": True,
                "is_dead": is_dead,
                "damage": actual_dmg,
                "boss_hp": 0,
                "message": full_msg, # <--- Frontend chỉ cần alert cái này là đẹp
                "rewards": frontend_rewards
            }
        # --- TRƯỜNG HỢP 2: BOSS CHƯA CHẾT (ĐOẠN NÀY LÚC NÃY BẠN BỊ THIẾU) ---
        else:
            db.add(boss)
            db.commit()
            db.refresh(boss)

            return {
                "success": True,
                "correct": True,
                "is_dead": False,
                "damage": actual_dmg,
                "boss_hp": boss.current_hp,
                "message": f"⚔️ Tấn công chính xác! Gây {actual_dmg} sát thương.",
                "is_dead_player": False
            }
    except Exception as e:
        print(f"❌ LỖI ATTACK: {traceback.format_exc()}")
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.get("/api/boss/get-question")
def get_boss_question(boss_id: int, db: Session = Depends(get_db)):
    try:
        # ==========================================
        # 1. TÌM BOSS VÀ PHÂN LOẠI ĐỘ KHÓ
        # ==========================================
        boss = db.get(Boss, boss_id)
        if not boss:
            return JSONResponse(status_code=404, content={"message": "Không tìm thấy Boss!"})
            
        if boss.atk >= 1000: target_diff = "hell"
        elif boss.atk >= 500: target_diff = "extreme"
        elif boss.atk >= 200: target_diff = "hard"
        else: target_diff = "medium"

        # 2. XÁC ĐỊNH ĐƯỜNG DẪN THƯ MỤC CHUẨN XÁC
        subject_str = boss.subject.lower() 
        
        # Lấy thư mục hiện tại (backend)
        CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
        
        # 🔥 ĐIỂM CHỐT CHẶN: Sử dụng chính xác thư mục "data câu hỏi" của Lãnh chúa
        folder_path = os.path.join(CURRENT_DIR, "..", "data câu hỏi", subject_str)
        
        print(f"👉 [BOSS API] Đang tìm thư mục: {folder_path}")
        
        if not os.path.exists(folder_path):
            print(f"❌ LỖI BOSS: Thư mục không tồn tại: {folder_path}")
            return JSONResponse(status_code=404, content={"message": f"Chưa có thư mục môn: {subject_str}"})

        # 3. TÌM FILE BOSS VÀ ĐỘ KHÓ
        all_files = os.listdir(folder_path)
        
        # Tìm file có đuôi json VÀ có chữ "boss"
        boss_files = [f for f in all_files if "boss" in f.lower() and f.endswith(".json")]
        
        if not boss_files:
            print(f"❌ LỖI BOSS: Thư mục {subject_str} không có file nào chứa chữ 'boss' trong tên!")
            return JSONResponse(status_code=404, content={"message": f"Không có file câu hỏi Boss!"})

        # Cố gắng tìm file khớp độ khó
        diff_files = [f for f in boss_files if target_diff in f.lower()]
        
        # Nếu có file đúng độ khó -> Lấy file đó. Nếu không có -> Lấy bừa 1 file Boss bất kỳ.
        final_files_list = diff_files if diff_files else boss_files
        
        chosen_file = random.choice(final_files_list)
        file_path = os.path.join(folder_path, chosen_file)
        
        print(f"👉 [BOSS API] Đã chọn bốc câu hỏi từ file: {chosen_file}")
        
        # 4. ĐỌC FILE VÀ BỐC CÂU HỎI
        with open(file_path, 'r', encoding='utf-8') as f:
            questions_list = json.load(f)
            
        if not questions_list:
            print(f"❌ LỖI BOSS: File {chosen_file} đang trống rỗng!")
            return JSONResponse(status_code=404, content={"message": f"File {chosen_file} đang trống!"})
            
        q_dict = random.choice(questions_list)

        # 5. TÁCH ĐÁP ÁN
        try:
            options_list = q_dict.get("options", [])
            while len(options_list) < 4:
                options_list.append("---")

            opt_a = options_list[0]
            opt_b = options_list[1]
            opt_c = options_list[2]
            opt_d = options_list[3]

            correct_text = q_dict.get("answer", "")
            correct_char = "a" 
            
            if correct_text == opt_a: correct_char = "a"
            elif correct_text == opt_b: correct_char = "b"
            elif correct_text == opt_c: correct_char = "c"
            elif correct_text == opt_d: correct_char = "d"
            
            print(f"✅ [BOSS API] Bốc thành công 1 câu! (Đáp án: {correct_char.upper()})")

            return {
                "id": random.randint(100000, 999999),
                "content": q_dict.get("question", "Lỗi mất nội dung câu hỏi?"),
                "options": {"a": opt_a, "b": opt_b, "c": opt_c, "d": opt_d},
                "correct_ans": correct_char, 
                "explanation": f"Đáp án đúng là: {correct_text}"
            }

        except Exception as parse_err:
            print(f"❌ LỖI XỬ LÝ JSON BOSS: {parse_err}")
            return {
                "id": 999999,
                "content": q_dict.get("question", "Lỗi dữ liệu câu hỏi"),
                "options": {"a": "Lỗi", "b": "Lỗi", "c": "Lỗi", "d": "Lỗi"},
                "correct_ans": "a",
                "explanation": "Câu hỏi này bị lỗi định dạng JSON."
            }

    except Exception as e:
        print("\n================= 💥 LỖI API BOSS (HỆ THỐNG) 💥 =================")
        traceback.print_exc() 
        print("=================================================================\n")
        return JSONResponse(status_code=500, content={"message": f"Lỗi Server: {str(e)}"})
# --- API LẤY TOÀN BỘ ITEM (DÀNH CHO ADMIN CẤU HÌNH BOSS) ---
@app.get("/api/all-items")
def get_all_items_system(db: Session = Depends(get_db)):
    # Lấy TẤT CẢ (Không lọc is_hidden)
    items = db.exec(select(Item)).all()
    
    # Trả về danh sách gọn nhẹ để Admin chọn
    return [
        {
            "id": i.id, 
            "name": i.name, 
            "type": i.type,
            "price": i.price
        } 
        for i in items
    ]

# API LẤY NHẬT KÝ CHIẾN TRƯỜNG (Dành cho Admin Portal)
@app.get("/api/boss/logs")  # 👈 Sửa thành @app.get và thêm /api
def get_boss_logs(limit: int = 50, db: Session = Depends(get_db)):
    try:
        # Lấy danh sách log mới nhất, sắp xếp giảm dần theo ID
        logs = db.exec(select(BossLog).order_by(BossLog.id.desc()).limit(limit)).all()
        return {"success": True, "logs": logs}
    except Exception as e:
        return {"success": False, "message": str(e), "logs": []}

# --- API TEST: CỘNG EXP & CHECK LEVEL UP ---
@app.post("/api/test/grant-exp")
def grant_exp_to_user(username: str, amount: int, db: Session = Depends(get_db)):
    try:
        # 1. Tìm người chơi theo username
        player = db.exec(select(Player).where(Player.username == username)).first()
        if not player:
            return {"success": False, "message": "Không tìm thấy người chơi này!"}

        # 2. Ghi nhớ chỉ số cũ (để so sánh sự thay đổi)
        old_level = player.level
        old_hp = player.hp_max
        old_atk = player.atk

        # 3. GỌI HÀM LOGIC (Từ file level.py)
        # Hàm này sẽ tự động: Cộng EXP -> Check Level -> Tăng Stats -> Hồi máu
        leveled_up = add_exp_to_player(player, amount)

        # 4. Lưu thay đổi vào Database
        db.add(player)
        db.commit()
        db.refresh(player)

        # 5. Thông báo kết quả
        result_msg = f"Đã cộng {amount} EXP."
        if leveled_up:
            result_msg += f" 🎉 CHÚC MỪNG! Thăng cấp {old_level} -> {player.level}!"

        return {
            "success": True,
            "message": result_msg,
            "leveled_up": leveled_up,
            "changes": {
                "level": f"{old_level} ➔ {player.level}",
                "hp_max": f"{old_hp} ➔ {player.hp_max}",
                "atk": f"{old_atk} ➔ {player.atk}",
                "current_exp": f"{player.exp}/{player.next_level_exp}"
            }
        }

    except Exception as e:
        print(f"Lỗi: {e}")
        return {"success": False, "message": f"Lỗi hệ thống: {str(e)}"}

# --- TÁC VỤ CHẠY NGẦM: Dọn dẹp chat lúc 0h00 ---
async def cleanup_chat_task():
    while True:
        now = datetime.now()
        # Tính thời gian đến 0h00 ngày hôm sau
        tomorrow = datetime(now.year, now.month, now.day) + timedelta(days=1)
        seconds_until_midnight = (tomorrow - now).total_seconds()
        
        print(f"⏳ Còn {int(seconds_until_midnight)} giây nữa đến giờ dọn dẹp Chat...")
        
        # Ngủ cho đến 0h00
        await asyncio.sleep(seconds_until_midnight)
        
        # Đến 0h00 -> Thực hiện xóa
        try:
            print("🧹 Đang dọn dẹp lịch sử Chat...")
            # Tạo session DB thủ công để xóa
            from database import SessionLocal
            db = SessionLocal()
            try:
                # Xóa toàn bộ bảng chatlog
                db.execute(text("DELETE FROM chatlog"))
                db.commit()
                # Gửi thông báo cho mọi người biết (Optional)
                print("✅ Đã xóa sạch lịch sử Chat ngày cũ!")
            finally:
                db.close()
        except Exception as e:
            print(f"❌ Lỗi dọn dẹp: {e}")
            
        # Ngủ thêm 60s để tránh chạy lặp lại ngay lập tức
        await asyncio.sleep(60)

# =====================================================================
# [MODULE CHIẾN DỊCH] 
# =====================================================================
#module đóng băng chiến dịch
def is_campaign_frozen():
    """Kiểm tra xem hiện tại có phải giờ đóng băng hay không (Múi giờ VN)"""
    # 1. Lấy giờ hiện tại theo chuẩn Việt Nam
    vn_tz = pytz.timezone('Asia/Ho_Chi_Minh')
    now_vn = datetime.now(vn_tz)
    current_hour = now_vn.hour
    
    # 2. Kiểm tra dựa trên config: Ví dụ từ 18h đến trước 22h là MỞ
    # Ngoài khung giờ này (nhỏ hơn 18 hoặc lớn hơn/bằng 22) là ĐÓNG BĂNG
    if not (cfg.CAMPAIGN_START_HOUR <= current_hour < cfg.CAMPAIGN_END_HOUR):
        return True
    return False

# =====================================================================
# [MODULE CHIẾN DỊCH] 2. API CHIÊU BINH (Mini-game 1: Trắc nghiệm)
# =====================================================================

@app.post("/api/campaign/minigame/chieu-binh")
def minigame_chieu_binh(req: MinigameRewardRequest, db: Session = Depends(get_db)):
    player = db.exec(select(Player).where(Player.username == req.username)).first()
    if not player: return {"success": False, "message": "Lỗi user"}
    
    c_player = db.exec(select(CampaignPlayer).where(
        CampaignPlayer.campaign_id == req.campaign_id, CampaignPlayer.player_id == player.id
    )).first()
    campaign = db.get(Campaign, req.campaign_id)
    
    if not c_player or not campaign or campaign.status != "ACTIVE":
        return {"success": False, "message": "Chiến dịch chưa mở hoặc đã kết thúc!"}

    max_capacity = getattr(cfg, 'BASE_TROOP_CAPACITY', 100) + (c_player.legion_level - 1) * getattr(cfg, 'CAPACITY_PER_LEVEL', 20)
    current_troops = campaign.tl_troops_vault if c_player.faction == "THANH_LONG" else campaign.bh_troops_vault
    
    if current_troops >= max_capacity:
        return {"success": False, "message": f"Kho lính phe {c_player.faction} đã ĐẦY ({max_capacity}/{max_capacity})!"}

    troops_to_add = getattr(cfg, 'MINIGAME1_TROOPS_REWARD', 100)
    if current_troops + troops_to_add > max_capacity:
        troops_to_add = max_capacity - current_troops 
        
    if c_player.faction == "THANH_LONG": campaign.tl_troops_vault += troops_to_add
    else: campaign.bh_troops_vault += troops_to_add

    c_player.total_troops_farmed += troops_to_add
    c_player.h_hau_phuong = c_player.total_troops_farmed // getattr(cfg, 'TROOPS_FOR_ONE_H_POINT', 1000)

    db.add(campaign)
    db.add(c_player)
    db.commit()
    
    return {"success": True, "message": f"Thu thập thành công {troops_to_add} lính!"}

# 3. CẬP NHẬT API LUYỆN BINH (Nhận username)
@app.post("/api/campaign/minigame/luyen-binh")
def minigame_luyen_binh(req: MinigameRewardRequest, db: Session = Depends(get_db)):
    player = db.exec(select(Player).where(Player.username == req.username)).first()
    if not player: return {"success": False, "message": "Lỗi user"}
    
    c_player = db.exec(select(CampaignPlayer).where(
        CampaignPlayer.campaign_id == req.campaign_id, CampaignPlayer.player_id == player.id
    )).first()
    
    if not c_player: return {"success": False, "message": "Không tìm thấy người chơi!"}
        
    max_lv = getattr(cfg, 'MAX_LEGION_LEVEL', 20)
    if c_player.legion_level >= max_lv:
        return {"success": False, "message": f"Quân đoàn đã đạt cấp độ tối đa (Lv.{max_lv})!"}

    exp_reward = getattr(cfg, 'MINIGAME2_EXP_REWARD', 10)
    c_player.legion_exp += exp_reward
    
    exp_needed = c_player.legion_level * 50 
    leveled_up = False
    
    while c_player.legion_exp >= exp_needed and c_player.legion_level < max_lv:
        c_player.legion_exp -= exp_needed
        c_player.legion_level += 1
        leveled_up = True
        exp_needed = c_player.legion_level * 50 
        
    db.add(c_player)
    db.commit()
    
    msg = f"Đã nhận {exp_reward} EXP."
    if leveled_up:
        new_capacity = getattr(cfg, 'BASE_TROOP_CAPACITY', 100) + (c_player.legion_level - 1) * getattr(cfg, 'CAPACITY_PER_LEVEL', 20)
        msg += f"\n🎉 THĂNG CẤP {c_player.legion_level}! Sức chứa tăng lên {new_capacity} lính!"
        
    return {"success": True, "message": msg}
# 1. API LẤY DANH SÁCH CÁC FILE JSON TRONG THƯ MỤC chien dich
# Hàm công cụ tự động dò đúng đường dẫn thư mục
def get_minigame_folder(game_type: str):
    # Lấy thư mục chứa file main.py (tức là thư mục 'backend')
    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Lùi ra 1 cấp (..), rồi vào 'data câu hỏi' -> 'chien dich'
    return os.path.normpath(os.path.join(current_dir, "..", "data câu hỏi", "chien dich", "chieu binh" if game_type == "chieu-binh" else "luyen binh"))

# 1. API LẤY DANH SÁCH FILE
@app.get("/api/campaign/minigame/files")
def get_minigame_files(game_type: str):
    folder_path = get_minigame_folder(game_type)
    
    if not os.path.exists(folder_path):
        return {"success": False, "data": []}

    files = [f for f in os.listdir(folder_path) if f.endswith('.json')]
    return {"success": True, "data": files}

# 2. API ĐỌC NỘI DUNG FILE
@app.get("/api/campaign/minigame/questions")
def get_minigame_questions(game_type: str, file_name: str):
    folder_path = get_minigame_folder(game_type)
    file_path = os.path.join(folder_path, file_name)
    
    if not os.path.exists(file_path):
        return {"success": False, "message": "Không tìm thấy file!"}

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, list): data = [data]
        return {"success": True, "data": data}
    except Exception as e:
        return {"success": False, "message": f"Lỗi đọc file JSON: {e}"}
# =====================================================================
# [MODULE CHIẾN DỊCH] 5. API XUẤT QUÂN TỪ GIAO DIỆN (Dùng Node Code)
# =====================================================================
# =====================================================================
# [BẢN ĐỒ GIAO THÔNG] ĐỊNH NGHĨA CÁC ĐƯỜNG NỐI & TÌM ĐƯỜNG
# =====================================================================
# Khai báo các đường nối với nhau (Ai đứng cạnh ai)
CAMPAIGN_GRAPH = {
    # Phe Thanh Long
    "TL_BASE": ["TL_TOP_2", "TL_MID_2", "TL_BOT_2"],
    "TL_TOP_2": ["TL_BASE", "TL_TOP_1", "TL_MID_2"], # Cho phép đổi đường (từ Top xuống Mid)
    "TL_TOP_1": ["TL_TOP_2", "BH_TOP_1", "TL_MID_1"],
    "TL_MID_2": ["TL_BASE", "TL_TOP_2", "TL_BOT_2", "TL_MID_1"],
    "TL_MID_1": ["TL_MID_2", "TL_TOP_1", "TL_BOT_1", "BH_MID_1"],
    "TL_BOT_2": ["TL_BASE", "TL_MID_2", "TL_BOT_1"],
    "TL_BOT_1": ["TL_BOT_2", "TL_MID_1", "BH_BOT_1"],
    
    # Phe Bạch Hổ
    "BH_BASE": ["BH_TOP_2", "BH_MID_2", "BH_BOT_2"],
    "BH_TOP_2": ["BH_BASE", "BH_TOP_1", "BH_MID_2"],
    "BH_TOP_1": ["BH_TOP_2", "TL_TOP_1", "BH_MID_1"],
    "BH_MID_2": ["BH_BASE", "BH_TOP_2", "BH_BOT_2", "BH_MID_1"],
    "BH_MID_1": ["BH_MID_2", "BH_TOP_1", "BH_BOT_1", "TL_MID_1"],
    "BH_BOT_2": ["BH_BASE", "BH_MID_2", "BH_BOT_1"],
    "BH_BOT_1": ["BH_BOT_2", "BH_MID_1", "TL_BOT_1"],
}

# Thuật toán đếm số bước chân (BFS - Tìm đường ngắn nhất)
def get_path_distance(start_code: str, target_code: str) -> int:
    if start_code == target_code: return 0
    if start_code not in CAMPAIGN_GRAPH or target_code not in CAMPAIGN_GRAPH:
        return 1 # Fallback mặc định
    
    queue = [(start_code, 0)]
    visited = set([start_code])
    
    while queue:
        current, dist = queue.pop(0)
        if current == target_code:
            return dist
        
        for neighbor in CAMPAIGN_GRAPH.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, dist + 1))
                
    return 1 # Fallback nếu không tìm thấy đường

@app.post("/api/campaign/{campaign_id}/march_by_code")
def march_troops_by_code(campaign_id: int, req: MarchByCodeRequest, db: Session = Depends(get_db)):
    try:
        # 1. TÌM NGƯỜI CHƠI
        player_base = db.exec(select(Player).where(Player.username == req.username)).first()
        if not player_base:
            return {"success": False, "message": "Không tìm thấy người chơi!"}

        player = db.exec(select(CampaignPlayer).where(
            CampaignPlayer.campaign_id == campaign_id, 
            CampaignPlayer.player_id == player_base.id
        )).first()
        
        # 2. TÌM CỨ ĐIỂM ĐÍCH THEO MÃ (VD: TL_MID_1)
        target_node = db.exec(select(MapNode).where(
            MapNode.campaign_id == campaign_id,
            MapNode.node_code == req.target_node_code
        )).first()
        
        if not player or not target_node:
            return {"success": False, "message": "Dữ liệu chiến dịch hoặc cứ điểm không hợp lệ!"}
        
        # =====================================================================
        # BƯỚC 2.5: KIỂM TRA LUẬT ĐẨY ĐƯỜNG (MOBA RULES)
        # =====================================================================
        # Nếu mục tiêu không thuộc phe mình -> Đang đi Tấn công / Xâm lược
        if target_node.owner_faction != player.faction:
            target_code = target_node.node_code
            my_prefix = "TL" if player.faction == "THANH_LONG" else "BH"
            
            # Chỉ áp dụng luật đẩy đường gắt gao khi ĐÁNH SANG PHẦN ĐẤT CỦA ĐỊCH
            if not target_code.startswith(my_prefix):
                # Sổ tay quy tắc: Mục Tiêu -> [Danh sách Cứ Điểm cần phải chiếm trước]
                push_rules = {
                    "BH_TOP_2": ["BH_TOP_1"], "BH_MID_2": ["BH_MID_1"], "BH_BOT_2": ["BH_BOT_1"],
                    "TL_TOP_2": ["TL_TOP_1"], "TL_MID_2": ["TL_MID_1"], "TL_BOT_2": ["TL_BOT_1"],
                    "BH_BASE": ["BH_TOP_2", "BH_MID_2", "BH_BOT_2"],
                    "TL_BASE": ["TL_TOP_2", "TL_MID_2", "TL_BOT_2"]
                }
                
                if target_code in push_rules:
                    req_codes = push_rules[target_code]
                    
                    # Truy vấn xem phe ta đang sở hữu bao nhiêu Cứ Điểm trong điều kiện
                    owned_reqs = db.exec(select(MapNode).where(
                        MapNode.campaign_id == campaign_id,
                        MapNode.node_code.in_(req_codes),
                        MapNode.owner_faction == player.faction
                    )).all()
                    
                    # Nếu phe ta chưa sở hữu Cứ Điểm nào trong danh sách yêu cầu -> Chặn lại
                    if len(owned_reqs) == 0:
                        if "BASE" in target_code:
                            return {"success": False, "message": "🛡️ Cứ Điểm Chính đang được bảo vệ! Phải chiếm ít nhất 1 Cứ Điểm 2 của địch mới có thể mở đường."}
                        else:
                            lane_name = "Đường Trên" if "TOP" in target_code else "Đường Giữa" if "MID" in target_code else "Đường Dưới"
                            return {"success": False, "message": f"🚧 Tuyến đường bị chặn! Bạn phải hạ Cứ Điểm 1 {lane_name} trước khi tiến sâu hơn."}
        # =====================================================================

        # 3. KIỂM TRA ÁN PHẠT TỬ TRẬN (Giữ lại từ code cũ của bạn)
        if player.respawn_at and datetime.now() < player.respawn_at:
            wait_mins = int((player.respawn_at - datetime.now()).total_seconds() / 60)
            return {"success": False, "message": f"💀 Đang trọng thương! Cần nghỉ ngơi {wait_mins} phút nữa."}

        # 4. TÍNH TOÁN LỰC CHIẾN TỪ CHỦ TƯỚNG (Giữ lại chi tiết tên Tướng từ code cũ)
        bonus_percent = 0.0
        commander_name = "Vô Danh"
        
        if player.companion_id:
            commander = db.get(Companion, player.companion_id)
            if commander:
                template = db.get(CompanionTemplate, commander.template_id)
                if template:
                    commander_name = commander.temp_name or template.name
                    
                    # Tính % Bonus theo độ hiếm và cấp sao bằng file config
                    b_rate = {'R': getattr(cfg, 'BONUS_R', 0.02), 'SR': getattr(cfg, 'BONUS_SR', 0.04), 'SSR': getattr(cfg, 'BONUS_SSR', 0.06), 'USR': getattr(cfg, 'BONUS_USR', 0.08)}.get(template.rarity, 0)
                    bonus_percent = b_rate + (commander.star * getattr(cfg, 'BONUS_PER_STAR', 0.01))

        # 5. TÌM QUÂN ĐOÀN HIỆN TẠI (Logic MOBA mới - KHÔNG trừ lính kho nữa)
        my_troop = db.exec(select(TroopMovement).where(
            TroopMovement.campaign_id == campaign_id,
            TroopMovement.player_id == player.player_id
        )).first()

        if not my_troop or my_troop.base_troops <= 0:
            return {"success": False, "message": "Quân đoàn đang trống rỗng! Hãy về Nhà Chính bổ sung quân."}

        if my_troop.status == "MARCHING":
            return {"success": False, "message": "Quân đoàn đang hành quân, không thể bẻ lái giữa đường!"}

        if my_troop.target_node_id == target_node.id:
            return {"success": False, "message": "Tướng quân, chúng ta đang đóng quân tại đây rồi!"}

        # 6. CẬP NHẬT LẠI LỰC CHIẾN 
        # (Phòng hờ người chơi đứng ở Cứ điểm và lén thay Tướng mạnh hơn trước khi đi)
        my_troop.bonus_percent = bonus_percent
        my_troop.real_power = int(my_troop.base_troops + (my_troop.base_troops * bonus_percent))
        # Lấy mã Cứ điểm xuất phát
        current_node = db.get(MapNode, my_troop.target_node_id)
        start_code = current_node.node_code if current_node else f"{player.faction[:2]}_BASE"
        
        # Gọi thuật toán quét bản đồ để đếm khoảng cách
        distance = get_path_distance(start_code, target_node.node_code)

        # 7. TÍNH THỜI GIAN ĐI ĐƯỜNG (Khoảng cách x Thời gian cơ bản)
        if target_node.owner_faction == player.faction and not target_node.is_contested:
            base_minutes = getattr(cfg, 'MARCH_TIME_ALLY_MINUTES', 1)
        else:
            base_minutes = getattr(cfg, 'MARCH_TIME_ENEMY_MINUTES', 2)
             
        # TỐI ƯU: Đảm bảo thời gian đi tối thiểu > 0 để tránh lỗi Javascript
        total_march_minutes = max(base_minutes * distance, 0.1) 
        arrival_time = datetime.now() + timedelta(minutes=total_march_minutes)

        # 8. CẬP NHẬT LỆNH HÀNH QUÂN MỚI 
        my_troop.source_node_code = start_code # Ghi nhớ nơi đi
        my_troop.target_node_id = target_node.id
        my_troop.start_time = datetime.now()
        my_troop.arrival_time = arrival_time
        my_troop.status = "MARCHING"
        
        db.add(my_troop)
        db.commit()

        return {
            "success": True, 
            "message": f"🐎 {commander_name} dẫn {my_troop.base_troops} lính nhổ trại tới {target_node.name}. Khoảng cách: {distance} Trạm. Dự kiến {total_march_minutes} phút!"
        }
        
    except Exception as e:
        print(f"❌ LỖI HÀNH QUÂN:\n{traceback.format_exc()}")
        return {"success": False, "message": "Lỗi hệ thống khi hành quân!"}

# =====================================================================
# [MODULE CHIẾN DỊCH] 6. API RÚT LUI (Hồi Thành Chiến Thuật)
# =====================================================================
@app.post("/api/campaign/{campaign_id}/recall")
def recall_troops(campaign_id: int, req: BaseRequest, db: Session = Depends(get_db)):
    try:
        player_base = db.exec(select(Player).where(Player.username == req.username)).first()
        player = db.exec(select(CampaignPlayer).where(CampaignPlayer.campaign_id == campaign_id, CampaignPlayer.player_id == player_base.id)).first()
        
        base_code = "TL_BASE" if player.faction == "THANH_LONG" else "BH_BASE"
        base_node = db.exec(select(MapNode).where(MapNode.campaign_id == campaign_id, MapNode.node_code == base_code)).first()

        if not base_node: return {"success": False, "message": "Lỗi DB: Bản đồ chưa khởi tạo Nhà Chính!"}

        my_troop = db.exec(select(TroopMovement).where(TroopMovement.campaign_id == campaign_id, TroopMovement.player_id == player.player_id)).first()

        if not my_troop: return {"success": False, "message": "Chưa xuất quân!"}
        
        # 🔥 ĐIỂM CHỐT CHẶN ĐÃ ĐƯỢC GỠ BỎ 🔥
        # Xóa hẳn dòng chặn "MARCHING" để cho phép người chơi bấm lúc đang bị kẹt
        
        # Tinh chỉnh: Chỉ chặn bấm nếu quân đang ở yên tại Nhà Chính và hoàn toàn bình thường
        if my_troop.target_node_id == base_node.id and my_troop.status == "GARRISONED": 
            return {"success": False, "message": "Ngài đang đồn trú ở Bệ Đá Cổ an toàn rồi!"}

        # ⚔️ THI THIẾT QUÂN LUẬT: BẤT CHẤP LÀ ĐANG LÀM GÌ, TỐNG HẾT VỀ NHÀ VÀ RESET TRẠNG THÁI
        my_troop.target_node_id = base_node.id
        my_troop.source_node_code = None # Xóa dấu vết đường đi cũ để chống kẹt radar
        my_troop.start_time = datetime.now()
        my_troop.arrival_time = datetime.now() # Đặt mốc thời gian là 'Đến nơi ngay lập tức'
        my_troop.status = "GARRISONED" # Reset về trạng thái an toàn: Đang đồn trú

        db.add(my_troop)
        db.commit()

        # Thông báo rõ ràng cho user biết họ đã được gỡ bug
        return {"success": True, "message": "✨ Giải cứu thành công! Toàn quân đã Dịch chuyển tức thời về Bệ Đá Cổ."}

    except Exception as e:
        print(f"❌ LỖI RECALL:\n{traceback.format_exc()}")
        return {"success": False, "message": "Lỗi hệ thống khi biến về!"}
# =====================================================================
# [MODULE CHIẾN DỊCH] 7. API TÍNH TOÁN GIAO TRANH & CHIẾM THÀNH
# =====================================================================
@app.post("/api/campaign/{campaign_id}/node/{node_id}/resolve")
def resolve_node_combat(campaign_id: int, node_id: int, db: Session = Depends(get_db)):
    node = db.get(MapNode, node_id)
    if not node:
        return {"success": False, "message": "Cứ điểm không tồn tại"}

    now = datetime.now()

    # BƯỚC 1: ĐỔI TRẠNG THÁI "ĐANG ĐI" -> "ĐẾN NƠI (ĐÓNG QUÂN)"
    arrived_troops = db.exec(select(TroopMovement).where(
        TroopMovement.target_node_id == node_id,
        TroopMovement.status == "MARCHING",
        TroopMovement.arrival_time <= now
    )).all()
    
    for t in arrived_troops:
        t.status = "GARRISONED"
    db.commit()

    # BƯỚC 2: GOM QUÂN 2 PHE (Đang đóng quân tại Node này) ĐỂ CHUẨN BỊ XẾP HÀNG
    # Lấy lính Thanh Long
    tl_troops = db.exec(
        select(TroopMovement, CampaignPlayer)
        .join(CampaignPlayer, TroopMovement.player_id == CampaignPlayer.player_id)
        .where(TroopMovement.target_node_id == node_id, TroopMovement.status == "GARRISONED", CampaignPlayer.faction == "THANH_LONG")
        .order_by(TroopMovement.arrival_time) # Ai đến trước xếp trước
    ).all()

    # Lấy lính Bạch Hổ
    bh_troops = db.exec(
        select(TroopMovement, CampaignPlayer)
        .join(CampaignPlayer, TroopMovement.player_id == CampaignPlayer.player_id)
        .where(TroopMovement.target_node_id == node_id, TroopMovement.status == "GARRISONED", CampaignPlayer.faction == "BACH_HO")
        .order_by(TroopMovement.arrival_time)
    ).all()

    # Chuyển thành list (mảng) để dễ pop (rút) người đứng đầu ra đánh
    tl_queue = [{"troop": t, "player": p} for t, p in tl_troops if t.real_power > 0]
    bh_queue = [{"troop": t, "player": p} for t, p in bh_troops if t.real_power > 0]

    combat_logs = [] # Lưu lịch sử chém nhau để báo cáo cho người dùng

    # BƯỚC 3: VÒNG LẶP GIAO TRANH TIÊN PHONG (1 vs 1)
    while tl_queue and bh_queue:
        tl_front = tl_queue[0]
        bh_front = bh_queue[0]

        tl_power = tl_front["troop"].real_power
        bh_power = bh_front["troop"].real_power

        if tl_power > bh_power:
            # Thanh Long Thắng, Bạch Hổ Chết
            tl_front["troop"].real_power -= bh_power
            tl_front["player"].k_kills += 1  # Ăn mạng
            
            bh_front["troop"].real_power = 0
            bh_front["troop"].status = "DEFEATED"
            bh_front["player"].t_deaths += 1 # Bị giết
            bh_front["player"].respawn_at = now + timedelta(minutes=cfg.RESPAWN_PENALTY_MINUTES)
            # 👇 CHÈN GỌI HÀM VÀO ĐÂY (Thanh Long giết Bạch Hổ) 👇
            killer_name = db.get(Player, tl_front["player"].player_id).username
            victim_name = db.get(Player, bh_front["player"].player_id).username
            process_kill_streak(db, campaign, tl_front["player"], bh_front["player"], killer_name, victim_name)
            # 👆 KẾT THÚC CHÈN 👆
            combat_logs.append(f"⚔️ {tl_front['player'].player_id} đánh bại {bh_front['player'].player_id}.")
            bh_queue.pop(0) # Loại Bạch Hổ khỏi hàng đợi

        elif bh_power > tl_power:
            # Bạch Hổ Thắng, Thanh Long Chết
            bh_front["troop"].real_power -= tl_power
            bh_front["player"].k_kills += 1
            
            tl_front["troop"].real_power = 0
            tl_front["troop"].status = "DEFEATED"
            tl_front["player"].t_deaths += 1
            tl_front["player"].respawn_at = now + timedelta(minutes=cfg.RESPAWN_PENALTY_MINUTES)
            # 👇 CHÈN GỌI HÀM VÀO ĐÂY (Bạch Hổ giết Thanh Long) 👇
            killer_name = db.get(Player, bh_front["player"].player_id).username
            victim_name = db.get(Player, tl_front["player"].player_id).username
            process_kill_streak(db, campaign, bh_front["player"], tl_front["player"], killer_name, victim_name)
            # 👆 KẾT THÚC CHÈN 👆
            combat_logs.append(f"⚔️ {bh_front['player'].player_id} đánh bại {tl_front['player'].player_id}.")
            tl_queue.pop(0) # Loại Thanh Long khỏi hàng đợi
            
        else:
            # Hòa (Chết cả 2)
            tl_front["troop"].real_power = 0
            tl_front["troop"].status = "DEFEATED"
            tl_front["player"].t_deaths += 1
            tl_front["player"].respawn_at = now + timedelta(minutes=cfg.RESPAWN_PENALTY_MINUTES)
            
            bh_front["troop"].real_power = 0
            bh_front["troop"].status = "DEFEATED"
            bh_front["player"].t_deaths += 1
            bh_front["player"].respawn_at = now + timedelta(minutes=cfg.RESPAWN_PENALTY_MINUTES)
            
            combat_logs.append(f"⚔️ {tl_front['player'].player_id} và {bh_front['player'].player_id} đồng quy ư tận.")
            tl_queue.pop(0)
            bh_queue.pop(0)

    # BƯỚC 4: LƯU TRẠNG THÁI LÍNH VÀ PLAYER VÀO DATABASE SAU KHI ĐÁNH XONG
    for item in tl_troops + bh_troops:
        db.add(item[0]) # Troop
        db.add(item[1]) # Player

    # BƯỚC 5: XỬ LÝ QUYỀN SỞ HỮU & CHIẾM THÀNH (60 PHÚT)
    # Tìm xem phe nào còn sống (còn GARRISONED)
    tl_survivors = len(tl_queue) > 0
    bh_survivors = len(bh_queue) > 0

    if tl_survivors and not bh_survivors:
        occupying_faction = "THANH_LONG"
    elif bh_survivors and not tl_survivors:
        occupying_faction = "BACH_HO"
    else:
        occupying_faction = None # Không còn ai sống sót ở cái thành này

    # A. Nếu kẻ đang chiếm đóng KHÁC với chủ sở hữu hiện tại -> Kích hoạt tranh chấp
    if occupying_faction and occupying_faction != node.owner_faction:
        if not node.is_contested:
            # Bắt đầu đếm ngược cắm cờ 60 phút
            node.is_contested = True
            node.capture_start_time = now
            combat_logs.append(f"🚩 Phe {occupying_faction} đã dọn sạch phòng thủ! Bắt đầu đếm ngược chiếm cứ điểm.")
        else:
            # Nếu Đang tranh chấp rồi, kiểm tra xem đã đủ 60 phút chưa?
            time_held = (now - node.capture_start_time).total_seconds() / 60
            if time_held >= cfg.DEFEND_TO_CAPTURE_MINUTES:
                # 🎊 ĐỔI CHỦ THÀNH CÔNG!
                node.owner_faction = occupying_faction
                node.is_contested = False
                node.capture_start_time = None
                combat_logs.append(f"🏰 CHIẾM THÀNH CÔNG! Cứ điểm nay thuộc về phe {occupying_faction}.")
                
    # B. Nếu chủ sở hữu hiện tại lấy lại được quyền kiểm soát (Đánh đuổi được kẻ tấn công)
    elif occupying_faction == node.owner_faction and node.is_contested:
        # Hủy bỏ quá trình tranh chấp
        node.is_contested = False
        node.capture_start_time = None
        combat_logs.append(f"🛡️ Phe {node.owner_faction} đã bảo vệ thành công Cứ điểm!")

    db.add(node)
    db.commit()

    return {
        "success": True,
        "logs": combat_logs,
        "current_owner": node.owner_faction,
        "is_contested": node.is_contested,
        "capture_start_time": node.capture_start_time.isoformat() if node.capture_start_time else None
    }

# =====================================================================
# [MODULE CHIẾN DỊCH] 8. API LẤY TRẠNG THÁI BẢN ĐỒ (Dành cho Frontend)
# =====================================================================

@app.get("/api/campaign/state")
def get_campaign_state(username: str, db: Session = Depends(get_db)):
    try:
        try:
            import campaign_config as cfg
        except ImportError:
            import sys, os
            # Tự động trỏ vào thư mục hiện tại nếu Python không tìm thấy
            sys.path.append(os.path.dirname(os.path.abspath(__file__)))
            import campaign_config as cfg
            
        player = db.exec(select(Player).where(Player.username == username)).first()
        if not player: return {"success": False, "message": "Không tìm thấy người chơi"}

        # 🔥 SỬA BUG 1: Dạy API tìm cả chiến dịch đang Báo danh (REGISTERING) và Khai chiến (ACTIVE)
        campaign = db.exec(
            select(Campaign)
            .where(Campaign.status.in_(["REGISTERING", "ACTIVE"]))
        ).first()
        if not campaign: return {"success": False, "message": "Hiện không có chiến dịch nào đang diễn ra!"}

        # Lấy thông tin người chơi (Có thể c_player = None nếu họ chưa bấm nút Báo danh)
        c_player = db.exec(select(CampaignPlayer).where(
            CampaignPlayer.campaign_id == campaign.id, CampaignPlayer.player_id == player.id
        )).first()

        # 1. Lấy thông tin Chủ Tướng (Chỉ lấy khi ĐÃ BÁO DANH)
        commander_info = None
        if c_player and c_player.companion_id:
            comp = db.get(Companion, c_player.companion_id)
            template = db.get(CompanionTemplate, comp.template_id) if comp else None
            if comp and template:
                base = {'R': getattr(cfg, 'BONUS_R', 0.02), 'SR': getattr(cfg, 'BONUS_SR', 0.04), 'SSR': getattr(cfg, 'BONUS_SSR', 0.06), 'USR': getattr(cfg, 'BONUS_USR', 0.08)}.get(template.rarity, 0)
                commander_info = {
                    "name": comp.temp_name or template.name, "image_url": template.image_path,
                    "rarity": template.rarity, "stars": comp.star, "total_bonus": int(round((base + (comp.star * getattr(cfg, 'BONUS_PER_STAR', 0.01))) * 100))
                }

        # 2. Xử lý thông tin CỦA BẢN THÂN (Bọc bằng if c_player để bảo vệ)
        my_current_troops = 0
        my_location = None
        
        if c_player:
            my_troop = db.exec(select(TroopMovement).where(TroopMovement.campaign_id == campaign.id, TroopMovement.player_id == player.id)).first()
            if my_troop:
                if my_troop.real_power > 0:
                    my_current_troops = my_troop.base_troops
                
                if my_troop.status == "GARRISONED":
                    loc_node = db.get(MapNode, my_troop.target_node_id)
                    if loc_node: my_location = loc_node.node_code

        # 3. Lấy DANH SÁCH TÊN NGƯỜI CHƠI TRÊN SA BÀN (Cứ điểm)
        garrisoned_troops = db.exec(
            select(TroopMovement.target_node_id, Player.username)
            .join(Player, TroopMovement.player_id == Player.id) 
            .where(
                TroopMovement.campaign_id == campaign.id, 
                TroopMovement.status == "GARRISONED", 
                TroopMovement.real_power > 0
            )
        ).all()
        
        players_in_nodes = {}
        for node_id, uname in garrisoned_troops:
            if node_id not in players_in_nodes:
                players_in_nodes[node_id] = []
            players_in_nodes[node_id].append(uname)

        # 4. Quét toàn bộ Cứ Điểm
        nodes = db.exec(select(MapNode).where(MapNode.campaign_id == campaign.id)).all()
        node_data = {}
        for n in nodes:
            defenders_sum = db.exec(select(func.sum(TroopMovement.real_power)).where(
                TroopMovement.target_node_id == n.id, TroopMovement.status == "GARRISONED"
            )).first()
            
            capture_end = None
            if n.is_contested and n.capture_start_time:
                defend_time = getattr(cfg, 'DEFEND_TO_CAPTURE_MINUTES', 60)
                capture_end = (n.capture_start_time + timedelta(minutes=defend_time)).isoformat()

            node_data[n.node_code] = {
                "owner": n.owner_faction,
                "troops": int(defenders_sum) if defenders_sum else 0,
                "is_contested": n.is_contested,
                "contesting_faction": n.contesting_faction,
                "capture_end_time": capture_end,
                "players": players_in_nodes.get(n.id, []) 
            }

        # 5. Quét Radar lấy các đạo quân đang chạy
        active_movements = db.exec(select(TroopMovement).where(TroopMovement.campaign_id == campaign.id, TroopMovement.status == "MARCHING")).all()
        movements_data = []
        for m in active_movements:
            m_player = db.exec(select(CampaignPlayer).where(CampaignPlayer.player_id == m.player_id, CampaignPlayer.campaign_id == campaign.id)).first()
            target_node = db.get(MapNode, m.target_node_id)
            if m_player and target_node:
                movements_data.append({
                    "id": m.id, "faction": m_player.faction,
                    "start_code": m.source_node_code, "target_code": target_node.node_code,
                    "start_time": m.start_time.isoformat(), "arrival_time": m.arrival_time.isoformat()
                })

        # 6. Lấy danh sách tên người đã báo danh cho Sảnh Lobby
        registered_players = db.exec(
            select(CampaignPlayer.faction, Player.username)
            .join(Player, CampaignPlayer.player_id == Player.id)
            .where(CampaignPlayer.campaign_id == campaign.id)
        ).all()
        
        lobby_players = {"THANH_LONG": [], "BACH_HO": []}
        for faction, uname in registered_players:
            if faction in lobby_players:
                lobby_players[faction].append(uname)
                
        # Tính số lượng thay vì phải query SQL thêm lần nữa (tối ưu tốc độ)
        tl_count = len(lobby_players["THANH_LONG"])
        bh_count = len(lobby_players["BACH_HO"])
        # 🔴 1. TÍNH TOÁN GIỚI HẠN KHO CHO 2 PHE
        try:
            import campaign_config as cfg
        except ImportError:
            import sys, os
            sys.path.append(os.path.dirname(os.path.abspath(__file__)))
            import campaign_config as cfg

        base_cap = getattr(cfg, 'BASE_TROOP_CAPACITY', 100)
        per_level = getattr(cfg, 'CAPACITY_PER_LEVEL', 20)

        # Gom tất cả người chơi phe Thanh Long và Bạch Hổ lại
        tl_players = db.exec(select(CampaignPlayer).where(CampaignPlayer.campaign_id == campaign.id, CampaignPlayer.faction == "THANH_LONG")).all()
        bh_players = db.exec(select(CampaignPlayer).where(CampaignPlayer.campaign_id == campaign.id, CampaignPlayer.faction == "BACH_HO")).all()

        # =================================================================
        # 🔥 CODE ĐÃ SỬA CHUẨN XÁC: HÀM TÍNH SỨC CHỨA CÓ BONUS
        # =================================================================
        def get_capacity_with_bonus(player):
            # 1. Tính sức chứa cơ bản
            base_capacity = base_cap + (player.legion_level - 1) * per_level
            bonus_percent = 0
            
            # 2. Tính bonus từ Chủ Tướng (Copy y chang logic commander_info của bạn)
            if getattr(player, 'companion_id', None):
                comp = db.get(Companion, player.companion_id)
                template = db.get(CompanionTemplate, comp.template_id) if comp else None
                
                if comp and template:
                    base = {'R': getattr(cfg, 'BONUS_R', 0.02), 'SR': getattr(cfg, 'BONUS_SR', 0.04), 'SSR': getattr(cfg, 'BONUS_SSR', 0.06), 'USR': getattr(cfg, 'BONUS_USR', 0.08)}.get(template.rarity, 0)
                    # Tính ra con số phần trăm nguyên (ví dụ 10)
                    bonus_percent = int(round((base + (comp.star * getattr(cfg, 'BONUS_PER_STAR', 0.01))) * 100))
            
            # 3. Tính tổng sức chứa (Cộng phần trăm và Làm tròn xuống)
            import math
            return math.floor(base_capacity * (1 + (bonus_percent / 100.0)))

        # Cộng dồn sức chứa (Đã áp dụng bonus) của từng người cho 2 phe
        tl_max_vault = sum([get_capacity_with_bonus(p) for p in tl_players]) if tl_players else 0
        bh_max_vault = sum([get_capacity_with_bonus(p) for p in bh_players]) if bh_players else 0
        # =================================================================
        # =================================================================
        # 🔥 SỬA BUG 3: Bọc c_player lại bằng lệnh if c_player else ... để không bị sập Server
        return {
            "success": True, 
            "is_frozen": is_campaign_frozen(),
            "status": campaign.status, 
            "campaign_id": campaign.id, 
            "end_time": campaign.end_time.isoformat() if campaign.end_time else None,
            "tl_max_vault": tl_max_vault, 
            "bh_max_vault": bh_max_vault, 
            "lobby_counts": {"THANH_LONG": tl_count, "BACH_HO": bh_count},
            "lobby_players": lobby_players, # 🚨 ĐÃ BỔ SUNG: Dòng này quan trọng nhất để Frontend có danh sách tên!
            "my_faction": c_player.faction if c_player else None, 
            "my_level": c_player.legion_level if c_player else 1,
            "scores": {
                "THANH_LONG": round(campaign.tl_victory_points, 1),
                "BACH_HO": round(campaign.bh_victory_points, 1)
            },
            "my_commander": commander_info, 
            "my_legion_troops": my_current_troops, 
            "my_location": my_location,
            "k_kills": c_player.k_kills if c_player else 0, 
            "t_deaths": c_player.t_deaths if c_player else 0, 
            "h_hau_phuong": c_player.h_hau_phuong if c_player else 0,
            "vaults": {"THANH_LONG": campaign.tl_troops_vault, "BACH_HO": campaign.bh_troops_vault},
            "respawn_at": c_player.respawn_at.isoformat() if c_player and c_player.respawn_at else None,
            "nodes": node_data, "movements": movements_data
        }
    except Exception as e:
        import traceback
        print(f"❌ LỖI LOAD MAP:\n{traceback.format_exc()}")
        return {"success": False, "message": "Lỗi hệ thống khi tải bản đồ!"}
# =====================================================================
# [MODULE CHIẾN DỊCH] QUẢN LÝ MÙA GIẢI & PHÒNG CHỜ BÁO DANH
# =====================================================================

# 1. API ADMIN: Mở Chiến Dịch Mùa Mới
@app.post("/api/admin/campaign/create")
def admin_create_campaign(db: Session = Depends(get_db)):
    # Kiểm tra xem có chiến dịch nào đang chạy hoặc đang báo danh không
    existing = db.exec(select(Campaign).where(Campaign.status.in_(["ACTIVE", "REGISTERING"]))).first()
    if existing:
        return {"success": False, "message": f"Đang có chiến dịch Mùa {existing.id} ở trạng thái {existing.status}!"}

    # Đếm số lượng chiến dịch để tự động tăng số Mùa (Mùa 1, Mùa 2...)
    total_campaigns = len(db.exec(select(Campaign)).all())
    next_season = total_campaigns + 1

    new_campaign = Campaign(
        name=f"Mùa {next_season}: Quần Anh Tranh Tài",
        status="REGISTERING", # Trạng thái BÁO DANH (Chưa đánh được)
        tl_troops_vault=0,
        bh_troops_vault=0
    )
    db.add(new_campaign)
    db.commit()
    return {"success": True, "message": f"Loa loa! Đã mở báo danh Chiến dịch Mùa {next_season}!"}

# 2. API: Lấy thông tin Phòng Chờ (Lobby)
@app.get("/api/campaign/lobby")
def get_campaign_lobby(db: Session = Depends(get_db)):
    campaign = db.exec(select(Campaign).where(Campaign.status == "REGISTERING")).first()
    if not campaign:
        return {"success": False, "message": "Hiện không có phòng chờ báo danh nào."}

    # Lấy danh sách người chơi đã báo danh
    players = db.exec(select(CampaignPlayer, Player).join(Player, CampaignPlayer.player_id == Player.id).where(CampaignPlayer.campaign_id == campaign.id)).all()
    
    tl_players = [p.Player.username for p in players if p.CampaignPlayer.faction == "THANH_LONG"]
    bh_players = [p.Player.username for p in players if p.CampaignPlayer.faction == "BACH_HO"]

    return {
        "success": True,
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "tl_players": tl_players,
        "bh_players": bh_players
    }

# 5. API ADMIN: Kết Thúc Mùa Giải Hiện Tại
@app.post("/api/admin/campaign/close")
def admin_close_campaign(db: Session = Depends(get_db)):
    try:
        # Tìm chiến dịch đang chạy hoặc đang báo danh
        active_campaign = db.exec(select(Campaign).where(Campaign.status.in_(["ACTIVE", "REGISTERING"]))).first()
        
        if not active_campaign:
            return {"success": False, "message": "Không có mùa giải nào đang diễn ra để kết thúc!"}

        # Đổi trạng thái thành ENDED và chốt thời gian
        active_campaign.status = "ENDED"
        active_campaign.end_time = datetime.now()
        
        db.add(active_campaign)
        db.commit()

        return {"success": True, "message": f"🛑 Đã kết thúc {active_campaign.name} thành công! Hãy mở mùa giải mới."}
        
    except Exception as e:
        print(f"❌ LỖI ĐÓNG MÙA GIẢI: {e}")
        return {"success": False, "message": "Lỗi hệ thống khi đóng mùa giải!"}

@app.post("/api/campaign/join")
def join_campaign(req: JoinFactionRequest, db: Session = Depends(get_db)):
    campaign = db.exec(select(Campaign).where(Campaign.status == "REGISTERING")).first()
    if not campaign:
        return {"success": False, "message": "Đã hết hạn báo danh, chiến dịch đang diễn ra!"}

    player = db.exec(select(Player).where(Player.username == req.username)).first()
    if not player:
        return {"success": False, "message": "Lỗi: Không tìm thấy tài khoản!"}

    c_player = db.exec(select(CampaignPlayer).where(CampaignPlayer.campaign_id == campaign.id, CampaignPlayer.player_id == player.id)).first()

    # Xử lý Rút lui
    if req.faction == "LEAVE":
        if c_player:
            db.delete(c_player)
            db.commit()
        return {"success": True, "message": "Đã rút lui khỏi chiến dịch!"}

    # Xử lý Báo danh
    if c_player:
        c_player.faction = req.faction # Đổi phe
    else:
        c_player = CampaignPlayer(
            campaign_id=campaign.id,
            player_id=player.id,
            faction=req.faction,
            legion_level=1,
            merit_points=0
        )
        db.add(c_player)
        
    db.commit()
    faction_name = "Thanh Long" if req.faction == "THANH_LONG" else "Bạch Hổ"
    return {"success": True, "message": f"Đã ghi danh vào phe {faction_name}!"}

# 4. API ADMIN: Bắt Đầu Chiến Dịch
@app.post("/api/admin/campaign/start")
def admin_start_campaign(db: Session = Depends(get_db)):
    campaign = db.exec(select(Campaign).where(Campaign.status == "REGISTERING")).first()
    if not campaign:
        return {"success": False, "message": "Không có chiến dịch nào đang trong giai đoạn báo danh!"}

    # ==========================================
    # 🔥 THÊM LOGIC TÍNH TOÁN THỜI GIAN MÙA GIẢI
    # ==========================================
    from datetime import datetime, timedelta
    try:
        import campaign_config as cfg
    except ImportError:
        import sys, os
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        import campaign_config as cfg

    now = datetime.now()
    # Lấy số giờ giới hạn từ config, nếu quên chưa set thì mặc định là 48h
    duration_hours = getattr(cfg, 'CAMPAIGN_DURATION_HOURS', 48) 

    # Ghi nhận giờ khai chiến và giờ kết thúc vào Database
    campaign.start_time = now
    campaign.end_time = now + timedelta(hours=duration_hours)
    # ==========================================

    # Chuyển trạng thái sang ACTIVE (Bản đồ sẽ mở)
    campaign.status = "ACTIVE"
    
    # Sinh ra 14 Cứ điểm trên bản đồ (Gồm 2 Nhà Chính + 12 Cứ điểm)
    # Format: (Mã, Tên Cứ Điểm, Phe, VP mỗi giờ)
    nodes_data = [
        # --- NHÀ CHÍNH (Không sinh điểm VP) ---
        ("TL_BASE", "Bệ Đá Cổ (Thanh Long)", "THANH_LONG", 0),
        ("BH_BASE", "Bệ Đá Cổ (Bạch Hổ)", "BACH_HO", 0),
        
        # --- 12 Cứ điểm (Sinh 1 điểm VP/giờ) ---
        ("TL_TOP_2", "Cứ điểm 2 Sơn Lâm (TL)", "THANH_LONG", 1), ("TL_TOP_1", "Cứ điểm 1 Sơn Lâm (TL)", "THANH_LONG", 1),
        ("BH_TOP_1", "Cứ điểm 1 Sơn Lâm (BH)", "BACH_HO", 1), ("BH_TOP_2", "Cứ điểm 2 Sơn Lâm (BH)", "BACH_HO", 1),
        ("TL_MID_2", "Cứ điểm 2 Đồng Bằng (TL)", "THANH_LONG", 1), ("TL_MID_1", "Cứ điểm 1 Đồng Bằng (TL)", "THANH_LONG", 1),
        ("BH_MID_1", "Cứ điểm 1 Đồng Bằng (BH)", "BACH_HO", 1), ("BH_MID_2", "Cứ điểm 2 Đồng Bằng (BH)", "BACH_HO", 1),
        ("TL_BOT_2", "Cứ điểm 2 Duyên Hải (TL)", "THANH_LONG", 1), ("TL_BOT_1", "Cứ điểm 1 Duyên Hải (TL)", "THANH_LONG", 1),
        ("BH_BOT_1", "Cứ điểm 1 Duyên Hải (BH)", "BACH_HO", 1), ("BH_BOT_2", "Cứ điểm 2 Duyên Hải (BH)", "BACH_HO", 1),
    ]
    
    for code, name, faction, vp in nodes_data:
        node = MapNode(
            campaign_id=campaign.id, 
            node_code=code, 
            name=name, 
            owner_faction=faction, 
            is_contested=False,
            vp_per_hour=vp
        )
        db.add(node)
        
    db.commit()
    return {"success": True, "message": f"🔥 CHIẾN DỊCH {campaign.name} CHÍNH THỨC BẮT ĐẦU!"}

# =====================================================================
# [MODULE CHIẾN DỊCH] TRÁI TIM HỆ THỐNG: ENGINE XỬ LÝ CHIẾN ĐẤU
# =====================================================================
engine_run_count = 0 

def process_campaign_battles(db):
    try:
        import campaign_config as cfg
    except ImportError:
        import sys, os
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        import campaign_config as cfg
        
    penalty_mins = getattr(cfg, 'RESPAWN_PENALTY_MINUTES', 1) # Lấy cấu hình phạt thời gian
    now = datetime.now()
    arrived_movements = db.exec(select(TroopMovement).where(
        TroopMovement.status == "MARCHING", TroopMovement.arrival_time <= now
    ).order_by(TroopMovement.arrival_time)).all()

    if not arrived_movements: return

    for movement in arrived_movements:
        # ĐƯA VIỆC TÌM CAMPAIGN VÀ BỆ ĐÁ CỔ VÀO TRONG VÒNG LẶP
        campaign = db.get(Campaign, movement.campaign_id)
        if not campaign: continue

        tl_base = db.exec(select(MapNode).where(MapNode.campaign_id == campaign.id, MapNode.node_code == "TL_BASE")).first()
        bh_base = db.exec(select(MapNode).where(MapNode.campaign_id == campaign.id, MapNode.node_code == "BH_BASE")).first()

        target_node = db.get(MapNode, movement.target_node_id)
        
        c_player = db.exec(select(CampaignPlayer).where(
            CampaignPlayer.player_id == movement.player_id, CampaignPlayer.campaign_id == campaign.id
        )).first()

        if not c_player or not target_node: continue
        player_faction = c_player.faction
        
        defenders = db.exec(select(TroopMovement).where(
            TroopMovement.target_node_id == target_node.id, TroopMovement.status == "GARRISONED"
        ).order_by(TroopMovement.id)).all()

        total_defense = sum(d.real_power for d in defenders)
        attack_power = movement.real_power

        defender_faction = target_node.owner_faction
        if target_node.is_contested and target_node.contesting_faction:
            defender_faction = target_node.contesting_faction

        # 1. TIẾP VIỆN ĐỒNG MINH
        if player_faction == defender_faction:
            movement.status = "GARRISONED"
            db.add(movement)
            c_player.h_hau_phuong += 1
            db.add(c_player)
            continue

        # CHUẨN BỊ DỮ LIỆU TÊN CHO CHIẾN BÁO
        attacker_p = db.get(Player, movement.player_id)
        attacker_name = attacker_p.username if attacker_p else "Vô danh"
        attacker_faction_tag = "(TL)" if player_faction == "THANH_LONG" else "(BH)"

        enemy_names = []
        for d in defenders:
            enemy_p = db.get(Player, d.player_id)
            if enemy_p and enemy_p.username not in enemy_names:
                enemy_names.append(enemy_p.username)
        
        # 🔥 SỬA LỖI 1: Nếu Cứ điểm không có lính thủ, vinh danh tên Phe đang sở hữu thay vì gọi là Phiến quân
        if enemy_names:
            enemy_str = ", ".join(enemy_names)
        else:
            if defender_faction == "THANH_LONG": enemy_str = "Phe Thanh Long"
            elif defender_faction == "BACH_HO": enemy_str = "Phe Bạch Hổ"
            else: enemy_str = "Phiến quân"

        target_faction_tag = ""
        if defender_faction == "THANH_LONG": target_faction_tag = "(TL)"
        elif defender_faction == "BACH_HO": target_faction_tag = "(BH)"
        full_target_name = f"{target_node.name} {target_faction_tag}".strip()


        # 2. ĐÁNH NHAU
        if attack_power > total_defense:
            # TẤN CÔNG THẮNG (Phe thủ chết sạch)
            for d in defenders:
                c_player.k_kills += 1 
                def_player = db.exec(select(CampaignPlayer).where(
                    CampaignPlayer.player_id == d.player_id, CampaignPlayer.campaign_id == campaign.id
                )).first()
                
                if def_player:
                    def_player.t_deaths += 1 
                    def_player.respawn_at = now + timedelta(minutes=penalty_mins)
                    db.add(def_player)
                    # vòng lặp giết từng người)👇
                    victim_name = db.get(Player, def_player.player_id).username
                    # 🔥 SỬA LỖI 2: Đổi chữ killer_name (vô nghĩa) thành attacker_name (biến chuẩn)
                    process_kill_streak(db, campaign, c_player, def_player, attacker_name, victim_name)
                    # 🔥 Kéo xác phe THỦ về Nhà Chính
                    base_node = tl_base if def_player.faction == "THANH_LONG" else bh_base
                    if base_node: d.target_node_id = base_node.id
                    
            db.add(c_player) 
            
            remaining_real_power = attack_power - total_defense
            remaining_troops = int(remaining_real_power / (1 + movement.bonus_percent))
            
            new_report = BattleReport(
                campaign_id=campaign.id, player_id=movement.player_id, faction=player_faction,
                type="PERSONAL", title="⚔️ ĐẠI THẮNG",
                content=f"Bạn đã đánh bại quân đoàn địch [{enemy_str}] tại {full_target_name}.\n📈 Thiệt hại: -{movement.base_troops - remaining_troops} lính.\n📉 Quân số còn lại: {remaining_troops}."
            )
            db.add(new_report)

            ally_report = BattleReport(
                campaign_id=campaign.id, player_id=0, faction=player_faction,
                type="ALLY", title="🛡️ TIẾP BÁO",
                content=f"Đồng đội [{attacker_name}] vừa bảo vệ/đánh chiếm thành công {full_target_name} từ tay [{enemy_str}]!"
            )
            db.add(ally_report)
            
            movement.real_power = remaining_real_power
            movement.base_troops = remaining_troops 
            movement.status = "GARRISONED" 
            db.add(movement)

            # --- LOGIC CỜ VÀNG ---
            if target_node.owner_faction == player_faction:
                target_node.is_contested = False
                target_node.contesting_faction = None
                target_node.capture_start_time = None
            else:
                target_node.is_contested = True
                target_node.contesting_faction = player_faction
                target_node.capture_start_time = now
            db.add(target_node)
            
            # Cập nhật trạng thái những kẻ thủ thành bại trận thành "Đang GARRISONED ở Nhà Chính với 0 lính"
            for d in defenders:
                d.status = "GARRISONED" 
                d.real_power = 0
                d.base_troops = 0 
                db.add(d)
            
        else:
            # TẤN CÔNG THUA (Phe công chết sạch)
            c_player.t_deaths += 1
            c_player.respawn_at = now + timedelta(minutes=penalty_mins)
            db.add(c_player)
            
            # 🔥 Kéo xác phe CÔNG về Nhà Chính
            base_node = tl_base if player_faction == "THANH_LONG" else bh_base
            if base_node: movement.target_node_id = base_node.id
            
            lose_report = BattleReport(
                campaign_id=campaign.id, player_id=movement.player_id, faction=player_faction,
                type="PERSONAL", title="💀 THẢM BẠI",
                content=f"Quân đoàn của bạn đã bị [{enemy_str}] tiêu diệt tại {full_target_name}.\n📈 Thiệt hại: -{movement.base_troops} lính.\n📉 Quân số còn lại: 0."
            )
            db.add(lose_report)
            
            # Gán trạng thái cho kẻ Tấn công
            movement.status = "GARRISONED"
            movement.real_power = 0
            movement.base_troops = 0
            db.add(movement)

            remaining_damage = attack_power
            for d in defenders:
                if remaining_damage <= 0: break
                
                def_player = db.exec(select(CampaignPlayer).where(
                    CampaignPlayer.player_id == d.player_id, CampaignPlayer.campaign_id == campaign.id
                )).first()
                
                if d.real_power <= remaining_damage:
                    remaining_damage -= d.real_power
                    
                    if def_player:
                        def_player.t_deaths += 1
                        def_player.respawn_at = now + timedelta(minutes=penalty_mins)
                        db.add(def_player)
                        # 🔥 Kéo xác những người THỦ chết chùm về Nhà Chính
                        base_node = tl_base if def_player.faction == "THANH_LONG" else bh_base
                        if base_node: d.target_node_id = base_node.id
                        
                    c_player.k_kills += 1 
                    db.add(c_player)
                    
                    # Gán trạng thái cho kẻ Thủ bị kéo theo
                    d.status = "GARRISONED"
                    d.real_power = 0
                    d.base_troops = 0
                else:
                    d.real_power -= remaining_damage
                    d.base_troops = int(d.real_power / (1 + d.bonus_percent)) 
                    remaining_damage = 0
                    
                    if def_player:
                        def_player.k_kills += 1
                        db.add(def_player)
                        # 🔥 SỬA LỖI 3: Bổ sung gọi hàm Liên Sát để vinh danh người Phòng Thủ
                        def_killer_name = db.get(Player, def_player.player_id).username
                        process_kill_streak(db, campaign, def_player, c_player, def_killer_name, attacker_name)
                        
                db.add(d)
                
    db.commit()

# API Bổ Sung Quân (Hồi máu ở Bệ Đá Cổ)
@app.post("/api/campaign/{campaign_id}/replenish")
def replenish_troops(campaign_id: int, req: BaseRequest, db: Session = Depends(get_db)):
    try:
        player_base = db.exec(select(Player).where(Player.username == req.username)).first()
        player = db.exec(select(CampaignPlayer).where(CampaignPlayer.campaign_id == campaign_id, CampaignPlayer.player_id == player_base.id)).first()
        campaign = db.get(Campaign, campaign_id)
        
        if not player or not campaign: return {"success": False, "message": "Dữ liệu không hợp lệ!"}

        if player.respawn_at and datetime.now() < player.respawn_at:
            wait_mins = int((player.respawn_at - datetime.now()).total_seconds() / 60)
            return {"success": False, "message": f"💀 Đang trọng thương! Chờ {wait_mins} phút."}

        # Tìm đúng mã Nhà Chính
        base_code = "TL_BASE" if player.faction == "THANH_LONG" else "BH_BASE"
        base_node = db.exec(select(MapNode).where(MapNode.campaign_id == campaign_id, MapNode.node_code == base_code)).first()

        if not base_node: return {"success": False, "message": "❌ Lỗi DB: Bản đồ chưa khởi tạo Nhà Chính!"}

        my_troop = db.exec(select(TroopMovement).where(TroopMovement.campaign_id == campaign_id, TroopMovement.player_id == player.player_id)).first()

        # Nếu chưa xuất quân lần nào -> Tạo thẳng ở Base
        if not my_troop:
            my_troop = TroopMovement(
                campaign_id=campaign_id, player_id=player.player_id,
                target_node_id=base_node.id, base_troops=0, bonus_percent=0.0, real_power=0,
                start_time=datetime.now(), arrival_time=datetime.now(), status="GARRISONED"
            )
            db.add(my_troop)
            db.commit()
            db.refresh(my_troop)

        if my_troop.status == "MARCHING": return {"success": False, "message": "Quân đoàn đang di chuyển, không thể tiếp tế!"}
        if my_troop.target_node_id != base_node.id: return {"success": False, "message": "Bạn phải Rút Lui về Bệ Đá Cổ mới có thể bổ sung binh lực!"}

        # =====================================================================
        # BƯỚC 1: LẤY % BONUS CỦA CHỦ TƯỚNG (Đưa lên trên cùng)
        # =====================================================================
        bonus_percent = 0.0
        if player.companion_id:
            comp = db.get(Companion, player.companion_id)
            if comp:
                template = db.get(CompanionTemplate, comp.template_id)
                if template:
                    b_rate = {'R': getattr(cfg, 'BONUS_R', 0.02), 'SR': getattr(cfg, 'BONUS_SR', 0.04), 'SSR': getattr(cfg, 'BONUS_SSR', 0.06), 'USR': getattr(cfg, 'BONUS_USR', 0.08)}.get(template.rarity, 0)
                    bonus_percent = b_rate + (comp.star * getattr(cfg, 'BONUS_PER_STAR', 0.01))

        # =====================================================================
        # BƯỚC 2: TÍNH MAX_CAPACITY (ĐÃ CỘNG BONUS) VÀ KIỂM TRA SỨC CHỨA
        # =====================================================================
        import math
        base_capacity = getattr(cfg, 'BASE_TROOP_CAPACITY', 100) + (player.legion_level - 1) * getattr(cfg, 'CAPACITY_PER_LEVEL', 20)
        max_capacity = math.floor(base_capacity * (1 + bonus_percent))
        
        troops_needed = max_capacity - my_troop.base_troops

        if troops_needed <= 0: return {"success": False, "message": "Quân đoàn đã đầy sức chứa!"}

        # =====================================================================
        # BƯỚC 3: RÚT LÍNH TỪ KHO PHE VÀ CỘNG CHO PLAYER
        # =====================================================================
        faction_vault = campaign.tl_troops_vault if player.faction == "THANH_LONG" else campaign.bh_troops_vault
        if faction_vault <= 0: return {"success": False, "message": "Kho dự trữ đã cạn kiệt!"}

        troops_to_take = min(troops_needed, faction_vault)
        if player.faction == "THANH_LONG": 
            campaign.tl_troops_vault -= troops_to_take
        else: 
            campaign.bh_troops_vault -= troops_to_take

        my_troop.base_troops += troops_to_take
        my_troop.bonus_percent = bonus_percent
        # Lưu ý: Sức mạnh thực chiến (real_power) sẽ được tính buff lên thêm dựa trên số lính base * bonus_percent
        my_troop.real_power = int(my_troop.base_troops + (my_troop.base_troops * bonus_percent))
        my_troop.status = "GARRISONED" 

        db.add(campaign)
        db.add(my_troop)
        db.commit()

        return {"success": True, "message": f"💊 Đã bổ sung {troops_to_take} lính vào Quân đoàn!"}

    except Exception as e:
        import traceback
        print(f"❌ LỖI REPLENISH:\n{traceback.format_exc()}")
        return {"success": False, "message": "Lỗi hệ thống khi nạp quân!"}

# =========================================================
# VÒNG LẶP ENGINE CHIẾN ĐẤU (DÙNG ĐA LUỒNG - THREADING)
# =========================================================
engine_run_count = 0

def campaign_engine_worker():
    global engine_run_count
    print("\n" + "="*50)
    print("🚀 BATTLE ENGINE (THREADING): Đã khởi động luồng độc lập!")
    print("="*50 + "\n")
    
    while True:
        time.sleep(5)  # Nghỉ 5 giây (Dùng time.sleep chuẩn của Python)
        engine_run_count += 1
        
        try:
            # Lấy Session DB
            db_gen = get_db()
            db = next(db_gen)
            try:
                process_campaign_battles(db)
                
                # In log mỗi 60 giây (12 vòng x 5s)
                if engine_run_count % 12 == 0:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚔️ Thread Engine vẫn đang soi sa bàn... (Vòng {engine_run_count})")
            finally:
                try:
                    next(db_gen) # Đóng kết nối DB
                except StopIteration:
                    pass
        except Exception as e:
            print(f"❌ LỖI TRONG THREAD COMBAT: {e}")


@app.post("/api/campaign/set-commander")
def set_campaign_commander(req: SetCommanderRequest, db: Session = Depends(get_db)):
    try:
        player = db.exec(select(Player).where(Player.username == req.username)).first()
        campaign = db.exec(select(Campaign).where(Campaign.status == "ACTIVE")).first()
        
        if not player or not campaign:
            return {"success": False, "message": "Không tìm thấy dữ liệu người chơi hoặc chiến dịch đang mở!"}

        c_player = db.exec(select(CampaignPlayer).where(
            CampaignPlayer.campaign_id == campaign.id,
            CampaignPlayer.player_id == player.id
        )).first()

        if not c_player:
            return {"success": False, "message": "Bạn chưa báo danh tham gia mùa giải này!"}

        # Lấy thông tin Đồng hành
        companion = db.get(Companion, req.companion_id)
        if not companion or companion.player_id != player.id:
            return {"success": False, "message": "Đồng hành không hợp lệ hoặc không thuộc quyền sở hữu của bạn!"}

        # LẤY TÊN TỪ BẢNG TEMPLATE
        template = db.get(CompanionTemplate, companion.template_id)
        display_name = companion.temp_name or (template.name if template else "Vô Danh")

        c_player.companion_id = req.companion_id
        db.add(c_player)
        db.commit()

        return {
            "success": True, 
            "message": f"🚩 Đã bổ nhiệm {display_name} làm Chủ Tướng dẫn quân!"
        }
    except Exception as e:
        print(f"❌ Lỗi Set Commander: {e}")
        return {"success": False, "message": "Lỗi hệ thống khi thiết lập Chủ Tướng"}

@app.get("/api/companions/my-list")
def get_my_companions(username: str, db: Session = Depends(get_db)):
    # 1. Tìm người chơi
    player = db.exec(select(Player).where(Player.username == username)).first()
    if not player:
        return {"success": False, "companions": [], "message": "Không tìm thấy người chơi"}

    # 2. Truy vấn gộp (JOIN) giữa thẻ thực tế và phôi thẻ
    statement = select(Companion, CompanionTemplate).join(
        CompanionTemplate, Companion.template_id == CompanionTemplate.template_id
    ).where(Companion.player_id == player.id)
    
    results = db.exec(statement).all()

    if not results:
        return {"success": True, "companions": [], "message": "Bạn chưa sở hữu đồng hành nào"}

    # 3. Lấy dữ liệu chính xác từ từng bảng và TỰ ĐỘNG TÍNH BONUS
    companions_data = []
    for comp, template in results:
        # Lấy Bonus gốc từ campaign_config (cfg)
        base = 0.0
        if template.rarity == 'R': base = cfg.BONUS_R
        elif template.rarity == 'SR': base = cfg.BONUS_SR
        elif template.rarity == 'SSR': base = cfg.BONUS_SSR
        elif template.rarity == 'USR': base = cfg.BONUS_USR
        
        star_bonus = comp.star * cfg.BONUS_PER_STAR
        total_bonus_pct = int(round((base + star_bonus) * 100))

        companions_data.append({
            "id": comp.id, 
            "name": comp.temp_name or template.name, 
            "rarity": template.rarity, 
            "stars": comp.star,        
            "image_url": template.image_path,
            "total_bonus": total_bonus_pct # <--- Tính xong gửi thẳng ra Frontend!
        })

    return {
        "success": True,
        "companions": companions_data
    }
# =========================================================
# API KIỂM TRA TRẠNG THÁI (ĐỂ BẠN YÊN TÂM)
# =========================================================
@app.get("/api/campaign/engine-status")
def check_engine_status():
    global engine_run_count
    if engine_thread.is_alive():
        return {"success": True, "message": f"✅ HOÀN HẢO! Thread Engine đang hoạt động cực mạnh. Đã quét {engine_run_count} vòng."}
    return {"success": False, "message": "❌ THREAD ĐÃ CHẾT!"}

# =====================================================================
# [GAME LOOP] XỬ LÝ TRANH CHẤP Cứ điểm VÀ ĐIỂM CHIẾN DỊCH (CHẠY MỖI PHÚT)
# =====================================================================
async def campaign_game_loop():
    print("🚀 BATTLE ENGINE: Đã khởi động hệ thống điều hành tập trung!")
    
    while True:
        await asyncio.sleep(5) # Chạy mỗi 5 giây
        
        # 🔥 BƯỚC 1: KIỂM TRA GIỜ ĐÓNG BĂNG (MÚI GIỜ VN)
        # Nếu đang trong giờ đóng băng, bỏ qua toàn bộ logic bên dưới
        if is_campaign_frozen():
            # Chỉ in log một lần mỗi khi đóng băng để tránh rác console
            if not hasattr(campaign_game_loop, "frozen_logged"):
                print("❄️ [HỆ THỐNG] Chiến trường đã đóng băng. Tạm dừng mọi hoạt động chém giết và cộng điểm.")
                campaign_game_loop.frozen_logged = True
            continue 
        
        # Nếu không đóng băng thì reset lại flag log để lần sau in tiếp
        campaign_game_loop.frozen_logged = False

        try:
            with Session(engine) as db:
                # 1. XỬ LÝ TRẬN ĐÁNH (Sẽ bị dừng nếu ở trên continue)
                process_campaign_battles(db)
                
                # 2. KIỂM TRA CHIẾM ĐÓNG & CỘNG ĐIỂM (Chạy mỗi 30s)
                if not hasattr(campaign_game_loop, "counter"): campaign_game_loop.counter = 0
                campaign_game_loop.counter += 5
                
                if campaign_game_loop.counter >= 30:
                    campaign_game_loop.counter = 0
                    
                    campaign = db.exec(select(Campaign).where(Campaign.status == "ACTIVE")).first()
                    if campaign:
                        now = datetime.now()
                        nodes = db.exec(select(MapNode).where(MapNode.campaign_id == campaign.id)).all()
                        
                        is_game_over = False
                        winner_faction = ""
                        
                        for node in nodes:
                            # 1. Kiểm tra hết giờ tranh chấp
                            if node.is_contested and node.capture_start_time:
                                defend_time = getattr(cfg, 'DEFEND_TO_CAPTURE_MINUTES', 60)
                                if now >= node.capture_start_time + timedelta(minutes=defend_time):
                                    node.owner_faction = node.contesting_faction
                                    node.is_contested = False
                                    node.contesting_faction = None
                                    node.capture_start_time = None
                                    db.add(node)
                            
                            # 2. CỘNG ĐIỂM (VP) - Phần này sẽ dừng sinh điểm khi đóng băng do lệnh continue ở trên
                            if not node.is_contested and "BASE" not in node.node_code and node.owner_faction:
                                vp_reward = (node.vp_per_hour or 1) / 120.0
                                if node.owner_faction == "THANH_LONG":
                                    campaign.tl_victory_points += float(vp_reward)
                                elif node.owner_faction == "BACH_HO":
                                    campaign.bh_victory_points += float(vp_reward)

                            # 3. KIỂM TRA ĐIỀU KIỆN CHIẾN THẮNG TUYỆT ĐỐI
                            if node.node_code == "BH_BASE" and node.owner_faction == "THANH_LONG":
                                is_game_over = True
                                winner_faction = "THANH_LONG"
                            elif node.node_code == "TL_BASE" and node.owner_faction == "BACH_HO":
                                is_game_over = True
                                winner_faction = "BACH_HO"
                        
                        db.add(campaign)
                        
                        # ======================================================
                        # 4. LOGIC KẾT THÚC GAME & PHÁT THƯỞNG (DÙNG BIẾN CONFIG)
                        # ======================================================
                        if is_game_over:
                            winner_display_name = "Thanh Long" if winner_faction == "THANH_LONG" else "Bạch Hổ"
                            print(f"🏆 KẾT THÚC MÙA GIẢI: PHE {winner_display_name.upper()} ĐÃ GIÀNH CHIẾN THẮNG!")
                            
                            campaign.status = "FINISHED"
                            campaign.end_time = now # Ghi nhận thời gian kết thúc
                            
                            # Bắn chiến báo hệ thống
                            victory_report = BattleReport(
                                campaign_id=campaign.id,
                                player_id=0,
                                faction="ALL",
                                type="SYSTEM",
                                title="🏆 ĐẠI THẮNG MÙA GIẢI",
                                content=f"Vang dội đất trời! Quân đoàn {winner_display_name} đã xuất sắc đập tan Nhà Chính địch, giành vị trí Độc Tôn!\nPhần thưởng đã được gửi vào kho đồ các Lãnh chúa."
                            )
                            db.add(victory_report)
                            
                            # Quét danh sách người tham gia để phát thưởng
                            participants = db.exec(select(CampaignPlayer).where(CampaignPlayer.campaign_id == campaign.id)).all()
                            
                            for p_record in participants:
                                actual_player = db.get(Player, p_record.player_id)
                                if not actual_player: continue
                                
                                # SỬ DỤNG ĐÚNG TÊN BIẾN TRONG FILE CONFIG CỦA BẠN
                                if p_record.faction == winner_faction:
                                    reward_kpi = getattr(cfg, 'WIN_REWARD_KPI', 20)
                                    reward_tri_thuc = getattr(cfg, 'WIN_REWARD_TRI_THUC', 50)
                                    reward_chien_tich = getattr(cfg, 'WIN_REWARD_CHIEN_TICH', 10)
                                    status_text = "Chiến thắng"
                                else:
                                    reward_kpi = getattr(cfg, 'LOSE_REWARD_KPI', 10)
                                    reward_tri_thuc = getattr(cfg, 'LOSE_REWARD_TRI_THUC', 10)
                                    reward_chien_tich = getattr(cfg, 'LOSE_REWARD_CHIEN_TICH', 3)
                                    status_text = "Tham gia"
                                
                                # Cộng tài nguyên cho người chơi
                                actual_player.kpi = (actual_player.kpi or 0) + reward_kpi
                                actual_player.tri_thuc = (actual_player.tri_thuc or 0) + reward_tri_thuc
                                actual_player.chien_tich = (actual_player.chien_tich or 0) + reward_chien_tich
                                db.add(actual_player)
                                from database import ScoreLog
                                # Ghi log nhận thưởng để user dễ theo dõi trong hồ sơ
                                log = ScoreLog(
                                    target_id=actual_player.id,
                                    target_name=actual_player.username,
                                    sender_id=0,
                                    sender_name="Hệ Thống",
                                    category="TÀI NGUYÊN",
                                    description=f"Thưởng {status_text} chiến dịch mùa này: +{reward_kpi} KPI, +{reward_tri_thuc} Tri Thức, +{reward_chien_tich} Chiến Tích.",
                                    value_change=reward_kpi
                                )
                                db.add(log)
                                
                            print(f"🎁 Đã phát thưởng thành công cho {len(participants)} lãnh chúa tham gia!")

                db.commit() # Một lệnh Commit duy nhất cho tất cả thay đổi
                
        except Exception as e:
            import traceback
            print(f"❌ LỖI ENGINE TỔNG HỢP: {traceback.format_exc()}")

@app.get("/api/campaign/reports")
def get_battle_reports(username: str, db: Session = Depends(get_db)):
    try:
        player = db.exec(select(Player).where(Player.username == username)).first()
        campaign = db.exec(select(Campaign).where(Campaign.status == "ACTIVE")).first()
        if not player or not campaign: return {"success": False, "data": []}

        c_player = db.exec(select(CampaignPlayer).where(
            CampaignPlayer.player_id == player.id,
            CampaignPlayer.campaign_id == campaign.id
        )).first()
  
        # 🔥 CHIA NHÁNH: XỬ LÝ RIÊNG CHO KHÁN GIẢ VÀ NGƯỜI CHƠI
        if not c_player:
            # 1. NẾU LÀ KHÁN GIẢ: Lấy tin Hệ thống + Tin chiến sự (ALLY) của CẢ 2 PHE
            reports = db.exec(
                select(BattleReport).where(
                    BattleReport.campaign_id == campaign.id,
                    BattleReport.type.in_(["SYSTEM", "ALLY"]) 
                ).order_by(BattleReport.timestamp.desc()).limit(30)
            ).all()
        else:
            # 2. NẾU LÀ NGƯỜI CHƠI BÁO DANH: Lấy tin như bình thường
            reports = db.exec(
                select(BattleReport).where(
                    BattleReport.campaign_id == campaign.id,
                    or_(
                        BattleReport.player_id == player.id,  
                        (BattleReport.type == "ALLY") & (BattleReport.faction == c_player.faction), 
                        BattleReport.type == "SYSTEM"         
                    )
                ).order_by(BattleReport.timestamp.desc()).limit(30)
            ).all()

        data = []
        for r in reports:
            # 🔥 TỐI ƯU HIỂN THỊ CHO KHÁN GIẢ TRUNG LẬP
            rpt_type = r.type
            rpt_title = r.title
            rpt_content = r.content

            if not c_player and rpt_type == "ALLY":
                # Biến tin Đồng minh thành tin Hệ thống (Màu đỏ) để khán giả dễ nhìn
                rpt_type = "SYSTEM" 
                # Thêm tên phe vào Tiêu đề
                faction_str = "Thanh Long" if r.faction == "THANH_LONG" else "Bạch Hổ"
                rpt_title = f"[{faction_str}] {r.title}"
                # Đổi nhân xưng
                rpt_content = r.content.replace("Đồng đội", "Quân Đoàn")

            data.append({
                "id": r.id,
                "type": rpt_type,
                "title": rpt_title,
                "content": rpt_content,
                "time": r.timestamp.strftime('%H:%M')
            })
            
        return {"success": True, "data": data}
        
    except Exception as e:
        import traceback
        print(f"❌ LỖI LẤY CHIẾN BÁO: {traceback.format_exc()}")
        return {"success": False, "data": []}

@app.get("/api/campaign/last-result")
def get_campaign_last_result(db: Session = Depends(get_db)):
    try:
        # 1. Tìm chiến dịch vừa mới FINISHED gần nhất
        last_campaign = db.exec(
            select(Campaign)
            .where(Campaign.status == "FINISHED")
            .order_by(Campaign.end_time.desc())
        ).first()
        
        if not last_campaign:
            return {"success": False, "message": "Chưa có chiến dịch nào."}
            
        # ==========================================
        # 🔥 ĐỊNH ĐOẠT PHE CHIẾN THẮNG THEO LUẬT CHƠI
        # ==========================================
        winner = "DRAW" # Mặc định là hòa
        
        # 🚨 BẮT BUỘC: Phải lọc theo campaign_id để không lấy nhầm Nhà Chính mùa trước
        tl_base = db.exec(
            select(MapNode)
            .where(MapNode.campaign_id == last_campaign.id)
            .where(MapNode.node_code == "TL_BASE")
        ).first()
        
        bh_base = db.exec(
            select(MapNode)
            .where(MapNode.campaign_id == last_campaign.id)
            .where(MapNode.node_code == "BH_BASE")
        ).first()
        
        # ĐIỀU KIỆN 1: Chiếm được Nhà Chính của địch (Kiểm tra xem owner_faction đã bị đổi chưa)
        if tl_base and tl_base.owner_faction == "BACH_HO":
            winner = "BACH_HO"
        elif bh_base and bh_base.owner_faction == "THANH_LONG":
            winner = "THANH_LONG"
        else:
            # ĐIỀU KIỆN 2: Không ai mất Nhà Chính -> Xét theo Điểm Chiến Dịch (Victory Points)
            if last_campaign.tl_victory_points > last_campaign.bh_victory_points:
                winner = "THANH_LONG"
            elif last_campaign.bh_victory_points > last_campaign.tl_victory_points:
                winner = "BACH_HO"

        # ==========================================
        # LẤY DỮ LIỆU NGƯỜI CHƠI & PHONG THẦN
        # ==========================================
        players = db.exec(
            select(CampaignPlayer, Player.username)
            .join(Player, CampaignPlayer.player_id == Player.id)
            .where(CampaignPlayer.campaign_id == last_campaign.id)
        ).all()
        
        thanh_long = []
        bach_ho = []
        
        # 3. Tìm các kỷ lục K, T, H
        max_k, max_h = 0, 0
        min_t = 999999
        
        for cp, _ in players:
            if cp.k_kills > max_k: max_k = cp.k_kills
            if cp.h_hau_phuong > max_h: max_h = cp.h_hau_phuong
            if cp.t_deaths < min_t: min_t = cp.t_deaths
            
        if min_t == 999999: min_t = 0 # Tránh lỗi nếu chưa ai chết
            
        # 4. Trao danh hiệu & Phân loại phe
        for cp, username in players:
            titles = []
            if cp.k_kills == max_k and max_k > 0: titles.append("👑 Chiến Thần")
            if cp.h_hau_phuong == max_h and max_h > 0: titles.append("🛡️ Hậu Phương Thép")
            if cp.t_deaths == min_t: titles.append("🏃 Kẻ Sinh Tồn")
            
            p_data = {
                "username": username,
                "k": cp.k_kills,
                "t": cp.t_deaths,
                "h": cp.h_hau_phuong,
                "titles": titles
            }
            
            if cp.faction == "THANH_LONG": thanh_long.append(p_data)
            else: bach_ho.append(p_data)
                
        # Sắp xếp danh sách theo Kills giảm dần
        thanh_long.sort(key=lambda x: x['k'], reverse=True)
        bach_ho.sort(key=lambda x: x['k'], reverse=True)
        
        return {
            "success": True,
            "campaign_name": last_campaign.name,
            "winner": winner,  # Trả về kết quả phe thắng/thua/hòa
            "tl_score": round(last_campaign.tl_victory_points, 1), # Gửi điểm về giao diện chờ
            "bh_score": round(last_campaign.bh_victory_points, 1),
            "thanh_long": thanh_long,
            "bach_ho": bach_ho
        }
    except Exception as e:
        import traceback
        print(f"❌ LỖI LẤY KẾT QUẢ: {traceback.format_exc()}")
        return {"success": False}

@app.get("/api/dev/reset-map")
def force_reset_campaign(db: Session = Depends(get_db)):
    """API bí mật dành cho Dev để dọn dẹp các chiến dịch bị kẹt"""
    try:
        # 1. Ép tất cả các chiến dịch đang kẹt về trạng thái FINISHED
        stuck_campaigns = db.exec(select(Campaign).where(Campaign.status != "FINISHED")).all()
        for c in stuck_campaigns:
            c.status = "FINISHED"
            db.add(c)
            
        # 2. Quét sạch toàn bộ lính đang kẹt trên bản đồ
        all_movements = db.exec(select(TroopMovement)).all()
        for mov in all_movements:
            db.delete(mov)
            
        # 3. Trả toàn bộ Cứ điểm về trạng thái trung lập ban đầu
        nodes = db.exec(select(MapNode)).all()
        for node in nodes:
            node.is_contested = False
            node.contesting_faction = None
            node.capture_start_time = None
            if "TL_" in node.node_code:
                node.owner_faction = "THANH_LONG"
            elif "BH_" in node.node_code:
                node.owner_faction = "BACH_HO"
            else:
                node.owner_faction = None
            db.add(node)
            
        db.commit()
        return {"success": True, "message": "🧹 Đã dọn dẹp sạch sẽ toàn bộ rác sa bàn! Bạn có thể báo danh lại."}
        
    except Exception as e:
        db.rollback()
        return {"success": False, "message": str(e)}

# 2. API GỬI TIN NHẮN CHAT
@app.post("/api/campaign/chat")
def send_chat_message(req: ChatRequest, db: Session = Depends(get_db)):
    try:
        player = db.exec(select(Player).where(Player.username == req.username)).first()
        campaign = db.exec(select(Campaign).where(Campaign.status == "ACTIVE")).first()
        if not player or not campaign: return {"success": False, "message": "Chiến dịch chưa mở!"}

        c_player = db.exec(select(CampaignPlayer).where(
            CampaignPlayer.campaign_id == campaign.id,
            CampaignPlayer.player_id == player.id
        )).first()
        if not c_player: return {"success": False, "message": "Bạn chưa báo danh!"}

        if not req.message.strip(): return {"success": False, "message": "Tin nhắn trống!"}

        # Lưu vào Database
        new_chat = CampaignChat(
            campaign_id=campaign.id,
            sender_name=player.username,
            faction=c_player.faction,
            message=req.message[:255], # Giới hạn 255 ký tự chống spam
            channel=req.channel
        )
        db.add(new_chat)
        db.commit()
        return {"success": True}
    except Exception as e:
        print(f"Lỗi gửi Chat: {e}")
        return {"success": False, "message": "Lỗi hệ thống!"}

# 3. API LẤY DANH SÁCH TIN NHẮN
@app.get("/api/campaign/chat")
def get_chat_messages(username: str, db: Session = Depends(get_db)):
    try:
        player = db.exec(select(Player).where(Player.username == username)).first()
        campaign = db.exec(select(Campaign).where(Campaign.status == "ACTIVE")).first()
        if not player or not campaign: return {"success": False, "data": []}

        c_player = db.exec(select(CampaignPlayer).where(
            CampaignPlayer.campaign_id == campaign.id,
            CampaignPlayer.player_id == player.id
        )).first()
        if not c_player: return {"success": False, "data": []}

        # Lọc tin nhắn: Lấy kênh "TẤT CẢ" HOẶC (kênh "ĐỒNG MINH" + đúng phe của mình)
        chats = db.exec(
            select(CampaignChat)
            .where(
                CampaignChat.campaign_id == campaign.id,
                or_(
                    CampaignChat.channel == "ALL",
                    and_(CampaignChat.channel == "ALLY", CampaignChat.faction == c_player.faction)
                )
            )
            .order_by(CampaignChat.timestamp.desc())
            .limit(50) # Lấy 50 tin mới nhất
        ).all()

        data = []
        # Đảo ngược mảng để tin mới nhất nằm ở dưới cùng khung chat
        for c in reversed(chats): 
            data.append({
                "id": c.id,
                "sender": c.sender_name,
                "faction": c.faction,
                "message": c.message,
                "channel": c.channel,
                "time": c.timestamp.strftime('%H:%M')
            })
        
        return {"success": True, "data": data}
    except Exception as e:
        print(f"Lỗi lấy Chat: {e}")
        return {"success": False, "data": []}

#hàm check để gọi danh hiệu liên sát
def process_kill_streak(db, campaign, killer_player, victim_player, killer_name: str, victim_name: str):
    """ Hàm tính toán và sinh ra thông báo Chuỗi Hạ Gục """
    now = datetime.now()
    announcement_msg = None

    # 1. Nạn nhân bị giết -> Reset chuỗi về 0
    victim_player.current_kill_streak = 0

    # 2. Kiểm tra chuỗi của Kẻ Tồn Tại (Thời gian 60 phút)
    if killer_player.last_kill_time and (now - killer_player.last_kill_time) <= timedelta(minutes=60):
        killer_player.current_kill_streak += 1
    else:
        # Nếu quá 60 phút mới giết mạng tiếp theo -> Tính lại từ 1
        killer_player.current_kill_streak = 1
        
    killer_player.last_kill_time = now

    # 3. Phán xét danh hiệu
    if not campaign.first_blood_claimed:
        campaign.first_blood_claimed = True
        announcement_msg = f"🩸 <b>{killer_name}</b> đã hạ gục <b>{victim_name}</b> - đạt được <span class='text-red-500'>ĐẦU DANH TRẠNG!</span>"
    elif killer_player.current_kill_streak == 2:
        announcement_msg = f"⚔️ <b>{killer_name}</b> đã hạ gục <b>{victim_name}</b> - đạt được <span class='text-yellow-400'>SONG SÁT!</span>"
    elif killer_player.current_kill_streak >= 3:
        announcement_msg = f"🔥 <b>{killer_name}</b> đã hạ gục <b>{victim_name}</b> - Đạt được liên sát và trở thành <span class='text-purple-500 font-black'>SÁT THẦN!</span>"

    # 4. Phát loa thông báo toàn bản đồ (Mượn bảng Chat để lưu thông báo)
    if announcement_msg:
        sys_msg = CampaignChat(
            campaign_id=campaign.id,
            sender_name="SYSTEM_KILL_ANNOUNCEMENT", # Phải là sender_name
            faction="SYSTEM",                       # Phải có faction
            channel="ALL",
            message=announcement_msg,               # Phải là message
            timestamp=now
        )
        db.add(sys_msg)
        
    db.commit()



# 👇 ĐOẠN CODE KHỞI ĐỘNG SERVER (PHẢI CÓ Ở CUỐI FILE)
if __name__ == "__main__":
    import uvicorn
    # Chạy server ở cổng 8000
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

