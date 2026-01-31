import os
import json
from sqlmodel import SQLModel, Field, create_engine, Session, select, Column, TEXT
from typing import Optional
from unidecode import unidecode 
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "game.db")
sqlite_url = f"sqlite:///{DB_PATH}"
connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, echo=True, connect_args=connect_args)

# . Hàm khởi tạo Database
def create_db_and_tables():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    SQLModel.metadata.create_all(engine)

# Hàm cấp phát session chuẩn cho FastAPI 
def get_db():
    with Session(engine) as session:
        yield session


# 1. Hàm tiện ích: Chuẩn hóa tên
def generate_username(full_name: str) -> str:
    if not full_name: return "user"
    clean_name = unidecode(full_name).lower().replace(" ", "")
    return clean_name
# 2. Định nghĩa các bảng (Models)
class Player(SQLModel, table=True):
    # --- 1. ĐỊNH DANH ---
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    password_hash: str
    plain_password: Optional[str] = Field(default=None)
    full_name: str
    role: str = Field(default="student") # admin / student
    
    # --- 2. CHỈ SỐ SỨC MẠNH (LEVEL UP SYSTEM) ---
    level: int = Field(default=1)
    
    # EXP: Hiện tại / Cần thiết (Mặc định 100 theo yêu cầu)
    exp: int = Field(default=0)
    next_level_exp: int = Field(default=100) 
    
    # Chỉ số chiến đấu (Sẽ tăng khi lên cấp)
    hp: int = Field(default=100)      # Máu hiện tại (Biến động trong trận)
    hp_max: int = Field(default=100)  # Máu tối đa (Tăng khi Warrior lên cấp)
    atk: int = Field(default=10)      # 👈 [MỚI] Sức tấn công (Tăng khi Mage lên cấp)

    # Hệ thống Class & Skill
    class_type: str = Field(default="NOVICE") # WARRIOR / MAGE
    skill_points: int = Field(default=0)
    equipped_skill: Optional[str] = Field(default=None)
    skills_data: str = Field(default="{}")    # Lưu danh sách skill đã học (JSON)

    # --- 3. HỆ THỐNG KPI & HỌC TẬP ---
    kpi: float = Field(default=0.0) # Điểm KPI
    
    diem_vi_pham: int = Field(default=0)
    diem_phat_bieu: int = Field(default=0)
    diem_tx: float = Field(default=0.0)       # Kiểm tra thường xuyên
    diem_hk: float = Field(default=0.0)       # Kiểm tra học kỳ
    diem_san_pham: float = Field(default=0.0) # Điểm sản phẩm

    # --- 4. KINH TẾ ---
    tri_thuc: int = Field(default=0)   # Vàng (Gold)
    chien_tich: int = Field(default=0) # Ruby
    vinh_du: int = Field(default=0)    # Badge

    # --- 5. THÔNG TIN KHÁC (Metadata) ---
    team_id: int = Field(default=0)
    stats_json: str = Field(default="{}") 
    titles_json: str = Field(default="[]")
    
    # --- 6. HỆ THỐNG THÁP & TRANG BỊ ---
    tower_floor: int = Field(default=1)       # Tầng tháp cao nhất
    revive_at: Optional[datetime] = Field(default=None) # Thời điểm hồi sinh
    
    # Slot trang bị (Charm/Items)
    equip_slot_1: Optional[int] = Field(default=None)
    equip_slot_2: Optional[int] = Field(default=None)
    equip_slot_3: Optional[int] = Field(default=None)
    equip_slot_4: Optional[int] = Field(default=None)
# 4
class Inventory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id")
    item_id: int = Field(foreign_key="item.id")
    
    # Số lượng (Thống nhất dùng 'amount' để khớp với item_processor)
    amount: int = Field(default=1) 
    
    is_equipped: bool = Field(default=False) # (Deprecated - Giờ dùng slot bên Player, nhưng giữ lại để backup)
    metadata_json: str = Field(default="{}") # Lưu độ bền, ngày hết hạn...
# 5
class ActiveEffect(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id")
    effect_json: str
    expire_time: float
# 6
class Question(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    subject: str
    content: str
    options_json: str
    correct_answer: str
    difficulty: int = 1
# 7. Bảng Quản lý Boss (Lưu cấu hình)
class Boss(SQLModel, table=True):
    __tablename__ = "bosses" # Quy ước số nhiều

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)                 # Tên Boss
    
    # Mục tiêu & Chỉ số
    grade: int                                    # Khối lớp (6,7,8,9)
    subject: str                                  # Môn học (toan, ly, hoa...)
    max_hp: int                                   # Máu tổng
    current_hp: int                               # Máu hiện tại (Real-time)
    atk: int                                      # Sát thương Boss gây ra
    time_limit: int = Field(default=15)           # Thời gian suy nghĩ (giây)
    
    # Hình ảnh & Hiệu ứng
    image_url: str
    animation: str = Field(default="stand")       # breathe, float, shake...
    vfx: Optional[str] = Field(default=None)      # fire, snow...
    
    # Phần thưởng (Drop List) - 4 loại tiền tệ
    reward_kpi: int = Field(default=0)
    reward_tri_thuc: int = Field(default=0)
    reward_chien_tich: int = Field(default=0)
    reward_vinh_du: int = Field(default=0)
    drop_pool: str = Field(default="[]")
    # Vật phẩm hiếm (Rare Drop)
    rare_item_id: Optional[str] = Field(default=None)
    rare_item_rate: int = Field(default=0)        # Tỷ lệ phần trăm (0-100)
    
    status: str = Field(default="inactive")       # active (đang đánh), inactive (chờ), defeated (đã chết)
# 8. Bảng Nhật ký Chiến đấu (Lưu lịch sử đấm nhau)
class BossLog(SQLModel, table=True):
    __tablename__ = "boss_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    boss_id: int = Field(foreign_key="bosses.id")
    
    player_name: str                              # Lưu tên HS tại thời điểm đánh
    action: str                                   # "attack_hit" (trúng), "attack_miss" (trượt/sai)
    dmg_dealt: int                                # Sát thương gây ra
    hp_left: int                                  # Máu Boss còn lại lúc đó
    created_at: datetime = Field(default_factory=datetime.now)
# 9. Khai báo bảng Item (Định nghĩa vật phẩm)
class Item(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    image_url: str
    description: Optional[str] = Field(default="Vật phẩm bí ẩn")
    
    # --- PHÂN LOẠI & LOGIC ---
    # type: charm (bùa), consumable (dùng), chest (rương), material (rác)
    type: str = Field(default="consumable") 
    can_equip: bool = Field(default=False)  # True nếu là Charm đeo được
    
    # Config Logic (JSON): {"action": "heal", "value": 50}
    config: str = Field(default="{}")

    # --- SHOP & KINH TẾ ---
    currency_type: str = Field(default="tri_thuc") # tri_thuc, chien_tich, vinh_du
    price: int = Field(default=0)
    
    # --- QUẢN LÝ SHOP ---
    is_hidden: bool = Field(default=False) # True = Ẩn khỏi Shop
    limit_type: int = Field(default=0)     # 0: KGH, 1: 1 lần/acc, 2: Theo tuần...    
# 10. Khai báo bảng ShopHistory (Theo dõi lịch sử mua)
class ShopHistory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int
    item_id: int
    purchase_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    amount: int = 1
#11--- THÁP THÍ LUYỆN ---
class TowerQuestion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    subject: str  # Toán, Lý, Hóa, Anh, Văn
    difficulty: str  # Medium, Hard, Extreme, Hell
    content: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_ans: str  # a, b, c, d
    explanation: Optional[str] = None # Lời giải từ AI
#12 lưu tiến trình leo tháp
class TowerProgress(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id")
    current_floor: int = Field(default=1) 
    max_floor: int = Field(default=1)
    last_played: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
#13 Bảng lưu cấu hình Tổng quát (Ảnh + Quà)
class TowerSetting(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    config_data: str = Field(default="{}", sa_column=Column(TEXT))
#14 quản lý trạng thái hệ thống, bảo trì
class SystemStatus(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    is_maintenance: bool = Field(default=False)
    message: str = Field(default="Hệ thống đang bảo trì để nâng cấp phó bản, vui lòng quay lại sau!")
    updated_at: str = Field(default="")
#15. Bảng PlayerPet (Thú cưng người chơi sở hữu)
class PlayerPet(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id")
    
    # ID của loại Pet (Link tới bảng Item để lấy tên, ảnh, config buff)
    item_id: int = Field(foreign_key="item.id") 
    
    # Chỉ số riêng của Pet này
    star_level: int = Field(default=1)     # Số sao (Mặc định 1 sao)
    level: int = Field(default=1)          # Cấp độ
    exp: int = Field(default=0)            # Kinh nghiệm hiện tại
    
    # Trạng thái Aura
    is_active: bool = Field(default=False) # True = Đang bay theo chủ
    active_start_time: Optional[datetime] = None # Thời gian bắt đầu kích hoạt
#16 [MỚI] BẢNG CHỢ ĐEN (MARKET) ---
class MarketListing(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    seller_id: int = Field(foreign_key="player.id") # Người bán
    item_id: int = Field(foreign_key="item.id")     # Vật phẩm
    
    amount: int = Field(default=1) # Số lượng bán
    price: int = Field(default=0)  # Giá bán
    currency: str = Field(default="tri_thuc") # Loại tiền muốn nhận
    
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    description: str = Field(default="") # Lời nhắn người bán
# bảng kỹ năng
class SkillTemplate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    skill_id: str = Field(index=True, unique=True) # Ví dụ: MAGE_FIRE_01
    name: str
    description: Optional[str] = None
    class_type: str # WARRIOR / MAGE
    skill_type: str # ACTIVE / PASSIVE
    min_level: int = Field(default=1)  # Cấp độ tối thiểu để học
    
    prerequisite_id: Optional[str] = Field(default=None) # ID skill cha (để tạo cây)
    # Lưu toàn bộ logic chiến đấu và nâng cấp vào JSON để linh hoạt
    # Cấu trúc: {"base_mult": 1.5, "vfx": "fx-meteor", "currency": "TRI_THUC", "base_cost": 100, "scaling": 1.2}
    config_data: str = Field(default="{}")
# BẢNG MỚI: LƯU KỸ NĂNG CỦA NGƯỜI CHƠI
class PlayerSkill(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: int = Field(foreign_key="player.id", index=True)
    
    skill_id: str = Field(index=True) # Link với skill_id bên trên
    
    level: int = Field(default=1)     # Cấp độ hiện tại của skill
    is_equipped: bool = Field(default=False) # True = Đang lắp để dùng
# =========================================================
# 🏛️ HỆ THỐNG LÔI ĐÀI (ARENA SYSTEM)
# =========================================================
class QuestionBank(SQLModel, table=True):
    """Ngân hàng câu hỏi trắc nghiệm"""
    id: Optional[int] = Field(default=None, primary_key=True)
    subject: str = Field(index=True)      # Môn học (Toan, Ly, Hoa...)
    difficulty: str = Field(index=True)   # Do kho (hard, super_hard, hell)
    content: str                          # Nội dung câu hỏi
    options_json: str                     # Lưu List 4 đáp án dạng JSON string: '["A", "B", "C", "D"]'
    correct_answer: str                   # Đáp án đúng (A, B, C, hoặc D)
    explanation: str = Field(default="")

class ArenaMatch(SQLModel, table=True):
    """Quản lý thông tin trận đấu"""
    id: Optional[int] = Field(default=None, primary_key=True)
    mode: str = Field(default="1vs1")     # 1vs1, 2vs2
    difficulty: str                       # hard, super_hard, hell
    bet_amount: int = Field(default=0)    # Mức cược KPI
    
    # Trạng thái: pending (chờ nhận), active (đang đấu), completed (xong), cancelled (hủy/hết hạn)
    status: str = Field(default="pending", index=True) 
    
    created_by: str                       # Username người tạo
    created_at: datetime = Field(default_factory=datetime.now)
    expires_at: datetime                  # Thời hạn 24h (tính từ lúc tạo hoặc lúc start)
    
    winner_team: Optional[str] = None     # 'A' hoặc 'B' hoặc 'Draw'
    logs: Optional[str] = None            # Ghi lại diễn biến trận đấu (JSON)

class ArenaParticipant(SQLModel, table=True):
    """Danh sách người tham gia từng trận"""
    id: Optional[int] = Field(default=None, primary_key=True)
    match_id: int = Field(foreign_key="arenamatch.id")
    username: str = Field(index=True)
    team: str                             # 'A' (Đội thách đấu) hoặc 'B' (Đội bị thách đấu)
    
    # Trạng thái người chơi: pending (chờ xác nhận), accepted (đã vào), submitted (đã nộp bài)
    status: str = Field(default="pending") 
    
    score: int = Field(default=0)         # Số câu đúng
    quiz_data_json: Optional[str] = None  # Lưu bộ đề riêng của người này (tránh lộ đề)
    submitted_at: Optional[datetime] = None

# hệ thống danh hiệu #
class Title(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str  # Tên danh hiệu (Vd: Tân Binh, Chiến Thần)
    min_kpi: int = Field(default=0) # Điểm KPI tối thiểu để đạt được
    color: str = Field(default="#fbbf24") # Màu sắc hiển thị (Hex code, mặc định là vàng)

#nhật ký nhập điểm
class ScoreLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    sender_name: str     # Người nhập (Tổ trưởng)
    target_name: str     # Người được nhập (Thành viên)
    category: str        # "academic" (Học tập) hoặc "violation" (Vi phạm)
    description: str     # Chi tiết (VD: Phát biểu, Đi trễ...)
    value_change: float  # Số điểm cộng/trừ (VD: +1, -3)
    created_at: datetime = Field(default_factory=datetime.utcnow) # Thời gian ghi nhận
    sender_id: int 
    target_id: int
if __name__ == "__main__":
    create_db_and_tables()
    print(f"✅ Đã khởi tạo thành công Database tại: {DB_PATH}")

