import os
import traceback
import random
import json
from fastapi import FastAPI, Depends, HTTPException, status, Query, Body, APIRouter,Request
#from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select, update, func, col 
from datetime import datetime, timedelta
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from typing import Optional
from database import create_db_and_tables, engine, Player, get_db, Item, Inventory, Title, TowerProgress, Boss, QuestionBank, BossLog, ArenaMatch, ArenaParticipant, SystemStatus 
#from auth import verify_password, create_access_token, get_current_user, ACCESS_TOKEN_EXPIRE_MINUTES
from routes import admin, users, shop, tower, pets, inventory_api, arena_api, auth, skills, market_api
from pydantic import BaseModel
from sqlalchemy import func, desc, or_
from game_logic.level import add_exp_to_player
from contextlib import asynccontextmanager
from routes.auth import get_password_hash
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
    # Khi Server bật lên:
    create_db_and_tables() # 1. Tạo bảng trống
    create_default_admin() # 2. Điền ngay ông Admin vào
    yield
    # Khi Server tắt đi:
    print("Server shutting down...")

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

# 1. API CHỌN CLASS (Dùng username thay vì Token)
@app.post("/player/choose-class")
def choose_class(
    class_name: str = Query(...), 
    username: str = Query(...), # <--- THAY ĐỔI: Nhận thẳng username
    db: Session = Depends(get_db)
):
    # Tìm user
    user = db.exec(select(Player).where(Player.username == username)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Không tìm thấy người chơi")

    # Validate Class
    valid_classes = ["WARRIOR", "MAGE"]
    if class_name not in valid_classes:
        raise HTTPException(status_code=400, detail="Class không hợp lệ")

    # Lưu vào DB
    user.class_type = class_name
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return {"status": "success", "message": f"Bạn đã trở thành {class_name}!"}

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
        statement = select(Item).where(Item.is_hidden == False)
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

class BuyRequest(BaseModel):
    item_id: int # Vì item.id trong model là Int
    username: str
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


class AttackRequest(BaseModel):
    boss_id: int
    player_id: int = 0         # ID người chơi (Để cộng thưởng chính xác)
    player_name: str           # Tên người chơi (Để ghi log nhanh)
    damage: int = 0            # Frontend gửi lên (nếu = 0 Server sẽ tự tính)
    question_id: int = 0       # ID câu hỏi vừa trả lời (Để check đáp án)
    selected_option: str = ""        # Sát thương gây ra (thường là 50-100 tùy cấu hình)

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
def get_boss_question(db: Session = Depends(get_db)):
    try:
        # 1. Lấy 1 câu hỏi ngẫu nhiên từ QuestionBank
        statement = select(QuestionBank).order_by(func.random()).limit(1)
        q = db.exec(statement).first()
        
        if not q:
            return JSONResponse(status_code=404, content={"message": "Kho câu hỏi trống!"})

        # 2. XỬ LÝ ĐÁP ÁN (QUAN TRỌNG)
        # QuestionBank lưu đáp án kiểu: '["Màu Đỏ", "Màu Xanh", "Màu Vàng", "Màu Tím"]'
        try:
            # Giải nén chuỗi JSON thành List Python
            options_list = json.loads(q.options_json)
            
            # Đảm bảo danh sách luôn có đủ 4 phần tử (nếu thiếu thì điền dấu "-")
            while len(options_list) < 4:
                options_list.append("---")

            # Gán vào 4 biến
            opt_a = options_list[0]
            opt_b = options_list[1]
            opt_c = options_list[2]
            opt_d = options_list[3]

            # 3. TÌM ĐÁP ÁN ĐÚNG LÀ A, B, C HAY D
            # QuestionBank lưu đáp án đúng là TEXT (VD: "Màu Xanh")
            # Ta phải tìm xem "Màu Xanh" nằm ở vị trí nào để trả về 'a', 'b', 'c' hay 'd'
            correct_char = "a" # Mặc định
            
            # So sánh nội dung để tìm ra key
            if q.correct_answer == opt_a: correct_char = "a"
            elif q.correct_answer == opt_b: correct_char = "b"
            elif q.correct_answer == opt_c: correct_char = "c"
            elif q.correct_answer == opt_d: correct_char = "d"
            
            # 4. Trả về Frontend
            return {
                "id": q.id,
                "content": q.content,
                "options": {
                    "a": opt_a,
                    "b": opt_b,
                    "c": opt_c,
                    "d": opt_d
                },
                "correct_ans": correct_char, 
                "explanation": getattr(q, "explanation", f"Đáp án đúng là: {q.correct_answer}")
            }

        except Exception as parse_err:
            print(f"Lỗi giải nén đáp án (ID {q.id}): {parse_err}")
            # Fallback nếu dữ liệu lỗi để không sập game
            return {
                "id": q.id,
                "content": q.content,
                "options": {"a": "Lỗi dữ liệu", "b": "Lỗi dữ liệu", "c": "Lỗi dữ liệu", "d": "Lỗi dữ liệu"},
                "correct_ans": "a",
                "explanation": "Câu hỏi này bị lỗi định dạng đáp án."
            }

    except Exception as e:
        print(f"❌ Server Error: {str(e)}")
        return JSONResponse(status_code=500, content={"message": str(e)})

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

@app.middleware("http")
async def check_maintenance_mode(request: Request, call_next):
    # 1. Danh sách các đường dẫn ĐƯỢC PHÉP truy cập khi bảo trì
    # (Bao gồm: trang admin, api login, file tĩnh, và chính api kiểm tra bảo trì)
    allowed_paths = [
        "/admin",           # Admin vẫn phải vào được để tắt bảo trì
        "/api/login",       # Cho phép login (để check role admin)
        "/static",          # Cho phép tải file css/js/ảnh
        "/docs",            # Cho phép xem tài liệu API
        "/openapi.json",
        "/api/data/maintenance-status", # Cho phép lấy trạng thái để hiển thị thông báo
        "/api/data/maintenance-update"  # Cho phép Admin tắt bảo trì
    ]

    # 2. Nếu đường dẫn hiện tại nằm trong danh sách cho phép -> Cho qua luôn
    # (Logic: Nếu path bắt đầu bằng 1 trong các allowed_paths)
    if any(request.url.path.startswith(path) for path in allowed_paths):
        return await call_next(request)

    # 3. Kiểm tra trong Database xem có đang bảo trì không
    # (Mở session thủ công vì Middleware không dùng Depends được)
    with Session(engine) as session:
        system_status = session.get(SystemStatus, 1)
        
        # Nếu đang bảo trì -> CHẶN LẠI NGAY ⛔
        if system_status and system_status.is_maintenance:
            return JSONResponse(
                status_code=503, # Mã lỗi "Service Unavailable"
                content={
                    "detail": "MAINTENANCE_MODE", # Keyword để Frontend bắt
                    "message": system_status.message or "Hệ thống đang bảo trì. Vui lòng quay lại sau!"
                }
            )

    # 4. Nếu không bảo trì -> Cho qua
    return await call_next(request)


# 👇 ĐOẠN CODE KHỞI ĐỘNG SERVER (PHẢI CÓ Ở CUỐI FILE)
if __name__ == "__main__":
    import uvicorn
    # Chạy server ở cổng 8000
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

