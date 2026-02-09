import json
import random
import os
import datetime
from sqlmodel import Session, select
from database import Inventory, Item, Player, PlayerItem, SystemConfig, ChatLog
# =====================================================
# CẤU HÌNH MẶC ĐỊNH (FALLBACK)
# =====================================================
# =====================================================
# CẤU HÌNH ĐƯỜNG DẪN ẢNH (ĐÃ SỬA CHO CẤU TRÚC BACKEND/FRONTEND)
# =====================================================

# 1. Lấy vị trí file item_processor.py (đang ở: backend/game_logic)
CURRENT_FILE_DIR = os.path.dirname(os.path.abspath(__file__))

# 2. Lấy thư mục Backend (cha của game_logic)
BACKEND_DIR = os.path.dirname(CURRENT_FILE_DIR)

# 3. Lấy thư mục Gốc Dự Án (cha của Backend) - Nơi chứa cả folder backend và frontend
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)

# 4. Tạo đường dẫn đến thư mục ảnh trong Frontend
CHARM_DISK_PATH = os.path.join(PROJECT_ROOT, "frontend", "assets", "items", "charms")

# Đường dẫn URL hiển thị trên web (Giữ nguyên)
CHARM_URL_PREFIX = "/assets/items/charms/"

DEFAULT_CHARM_CONFIG = {
    "MAGIC": {"lines": 1, "atk_range": [1, 15], "hp_range": [10, 50]},
    "EPIC":  {"lines": 2, "atk_range": [15, 50], "hp_range": [50, 150]},
    "LEGEND":{"lines": 2, "atk_range": [50, 100], "hp_range": [150, 250]}
}

DEFAULT_FORGE_CONFIG = {
    "group_1": {"min": 0, "max": 3, "rate": 80, "stone": 1, "bonus_pct": 10}, # +1 -> +3
    "group_2": {"min": 3, "max": 7, "rate": 60,  "stone": 2, "bonus_pct": 20}, # +4 -> +7
    "group_3": {"min": 7, "max": 10,"rate": 25,  "stone": 5, "bonus_pct": 50}  # +8 -> +10
}


# =====================================================
# HÀM HỖ TRỢ
# =====================================================
def calculate_max_hp_limit(player):
    """Tính giới hạn máu an toàn, trả về số nguyên"""
    real_max = player.hp_max if player.hp_max and player.hp_max > 0 else 100
    return int(real_max)

# =====================================================
# BỘ XỬ LÝ ITEM (BẢN ĐẦY ĐỦ: GACHA + TIỀN TỆ + HỒI SINH)
# =====================================================
def apply_item_effects(player: Player, item: Item, db: Session):
    try:
        # 1. Parse Config an toàn
        if not item.config: return False, "Item lỗi config", {}
        
        try:
            config = json.loads(item.config)
        except:
            config = {"action": item.config.strip()}

        action = config.get("action") or config.get("type")
        value = config.get("value", 0)

        # =====================================================
        # CASE 1: RƯƠNG GACHA (ĐÃ NÂNG CẤP & GỘP ĐỒ)
        # =====================================================
        if action == "gacha_open" or action == "Rương Gacha (Quay vật phẩm)":
            # Hỗ trợ mọi kiểu key mà admin có thể nhập
            drops = (config.get("gacha_items") or config.get("drops") or config.get("pool") or config.get("loot_table") or [])           
            if not drops: return False, "Rương rỗng!", {}
            received_map = {} # Dùng để gộp đồ: {"Bình máu": 2}
            
            # --- QUAY THƯỞNG ---
            for drop in drops:
                rate = int(drop.get("rate", 0))
                # Random tỷ lệ rơi
                if random.randint(1, 100) <= rate:
                    target_id = int(drop.get("item_id") or drop.get("id"))
                    
                    # Random số lượng min-max
                    min_q = int(drop.get("min", 1))
                    max_q = int(drop.get("max", 1))
                    qty = random.randint(min_q, max_q)
                    
                    # --- ĐOẠN KIỂM TRA CHARM MỚI ---
                    item_obj = db.get(Item, target_id)
                    if not item_obj: continue

                    # Đọc config của item vừa quay trúng
                    item_config = {}
                    try:
                        item_config = json.loads(item_obj.config) if item_obj.config else {}
                    except: pass
                    
                    item_action = item_config.get("action")

                    # Nếu là Phôi Charm (Ma thuật, Sử thi, Huyền thoại)
                    if item_action in ["charm_gen_magic", "charm_gen_epic", "charm_gen_legend"]:
                        rarity_map = {
                            "charm_gen_magic": "MAGIC",
                            "charm_gen_epic": "EPIC",
                            "charm_gen_legend": "LEGEND"
                        }
                        rarity_type = rarity_map.get(item_action)

                        # Chạy dây chuyền sản xuất Charm theo số lượng qty
                        for _ in range(qty):
                            new_charm = generate_charm(db, player.id, rarity_type)
                            # Lấy tên tiếng Việt của Charm vừa đúc xong để hiện thông báo
                            clean_name = f"{new_charm.name} ({rarity_type})"
                            received_map[clean_name] = received_map.get(clean_name, 0) + 1
                        # 👇 THÊM ĐOẠN NÀY ĐỂ LOA THÔNG BÁO 👇
                            if rarity_type == "LEGEND":
                                
                                now = datetime.datetime.now().strftime("%H:%M")
                                
                                # Tạo nội dung tin nhắn có chứa hiệu ứng "con rắn"
                                announcement_content = (
                                    f"📢 Chúc mừng <b>{player.username}</b> đã may mắn mở rương được "
                                    f"Charm Huyền Thoại: <span class='name-admin-wrapper'><span class='name-admin'>{new_charm.name}</span></span>!"
                                )
                                
                                # Tạo bản ghi tin nhắn mới vào bảng Chat của bạn
                                # (Lưu ý: Bạn hãy kiểm tra tên bảng Chat của mình là 'Chat' hay 'ChatMessage' nhé)
                                system_msg = ChatLog(
                                    player_name="HỆ THỐNG",
                                    content=announcement_content,
                                    role="SYSTEM",
                                    time=now
                                )
                                db.add(system_msg)
                        continue 
                    # --- KẾT THÚC ĐOẠN KIỂM TRA CHARM ---

                    # --- CỘNG VÀO KHO (AN TOÀN) - Chỉ chạy cho Item thường ---
                    inv_item = db.exec(select(Inventory).where(
                        Inventory.player_id == player.id,
                        Inventory.item_id == target_id
                    )).first()

                    if inv_item:
                        current_amt = int(inv_item.amount)
                        inv_item.amount = current_amt + qty
                        db.add(inv_item)
                    else:
                        new_item = Inventory(player_id=player.id, item_id=target_id, amount=qty)
                        db.add(new_item)
                    
                    # Xử lý tên cho Item thường để hiện thông báo
                    raw_name = item_obj.name if item_obj else f"Item {target_id}"
                    clean_name = raw_name.replace("\xa0", " ").strip()
                    
                    if clean_name in received_map:
                        received_map[clean_name] += qty
                    else:
                        received_map[clean_name] = qty

            db.commit() # Lưu ngay

            if received_map:
                # Tạo thông báo gộp: "2x Bình máu, 1x Kiếm"
                msg_parts = [f"{qty}x {name}" for name, qty in received_map.items()]
                full_msg = "Bạn nhận được: " + ", ".join(msg_parts)
                
                # Trả về data đầy đủ để Frontend update thanh máu/mana nếu cần
                return True, full_msg, {
                    "received": msg_parts,
                    "hp": int(player.hp),
                    "mp": 100
                }
            else:
                return True, "Rương trống rỗng (Chúc bạn may mắn lần sau)!", {}

        # =====================================================
        # CASE 2: HỒI MÁU (HP)
        # =====================================================
        elif action == "heal" or action == "Hồi máu (HP)":
            if not value: value = config.get("hp_restore", 100)
            heal = int(value)
            
            p_max = calculate_max_hp_limit(player)
            p_cur = int(player.hp or 0)
            
            if p_cur >= p_max:
                 return False, "Máu đã đầy!", {}

            new_hp = min(p_cur + heal, p_max)
            player.hp = new_hp
            db.add(player)
            
            return True, f"Hồi {heal} HP. (Máu: {new_hp}/{p_max})", {"hp": new_hp}

        # =====================================================
        # CASE 3: NHẬN TIỀN TỆ / KPI (ĐÃ KHÔI PHỤC)
        # =====================================================
        elif action == "add_currency" or action == "Nhận tiền tệ/KPI":
            currency_type = config.get("target_currency") or config.get("type", "tri_thuc")
            amount = int(value)
            
            msg = ""
            if currency_type == "tri_thuc":
                player.tri_thuc = (player.tri_thuc or 0) + amount
                msg = f"+{amount} Tri Thức"
            elif currency_type == "chien_tich":
                player.chien_tich = (player.chien_tich or 0) + amount
                msg = f"+{amount} Chiến Tích"
            elif currency_type == "vinh_du":
                player.vinh_du = (player.vinh_du or 0) + amount
                msg = f"+{amount} Vinh Dự"
            elif currency_type == "kpi":
                player.kpi = (player.kpi or 0) + amount
                msg = f"+{amount} KPI"
            else:
                return False, f"Loại tiền tệ '{currency_type}' không hợp lệ", {}
            
            db.add(player)
            return True, msg, {"currency": currency_type, "amount": amount}

        # =====================================================
        # CASE 4: XÓA THỜI GIAN CHỜ HỒI SINH (ĐÃ KHÔI PHỤC)
        # =====================================================
        elif action == "reset_revive" or action == "reset_cooldown":
            if not player.revive_at:
                return False, "Bạn đang sống khỏe mạnh!", {}
            
            player.revive_at = None
            player.hp = calculate_max_hp_limit(player)
            db.add(player)
            return True, "Hồi sinh thành công!", {"hp": player.hp}


        # =====================================================
        # CASE 5: ĐÁ CƯỜNG HÓA (CHẶN DÙNG TRỰC TIẾP)
        # =====================================================
        elif action == "enhance_stone" or action == "Nguyên liệu: Đá Cường Hóa":
            # Trả về True để hiển thị thông báo nhưng không làm mất item (trừ khi bạn muốn)
            # Ở đây ta trả về False ở tham số đầu tiên của tuple logic game để không trừ item ở Inventory API
            # Nhưng trả về message hướng dẫn
            return False, "Vật phẩm này chỉ dùng được trong Lò Rèn (Tab Trang Bị)!", {}

        # =====================================================
        # MẶC ĐỊNH
        # =====================================================
        return False, "Vật phẩm chưa được hỗ trợ.", {}

    except Exception as e:
        print(f"❌ LỖI ITEM PROCESSOR: {e}")
        # In chi tiết lỗi ra console server để debug nếu cần
        import traceback
        traceback.print_exc()
        return False, "Lỗi hệ thống xử lý vật phẩm.", {}
    
def get_charm_config(db: Session):
    """Lấy cấu hình Charm từ DB hoặc dùng mặc định"""
    record = db.exec(select(SystemConfig).where(SystemConfig.key == "charm_setup")).first()
    return json.loads(record.value) if record else DEFAULT_CHARM_CONFIG

def get_forge_config(db: Session):
    """Lấy cấu hình Lò rèn từ DB hoặc dùng mặc định"""
    record = db.exec(select(SystemConfig).where(SystemConfig.key == "forge_setup")).first()
    return json.loads(record.value) if record else DEFAULT_FORGE_CONFIG

# ==========================================================
# 🏭 PHẦN 1: NHÀ MÁY SẢN XUẤT CHARM (GENERATOR) - [MỚI]
# ==========================================================
def generate_charm(db: Session, player_id: int, rarity: str = "MAGIC"):
    """
    Tạo charm mới và bỏ thẳng vào túi người chơi.
    rarity: 'MAGIC', 'EPIC', 'LEGEND'
    """
    # 1. Lấy cấu hình & Chuẩn bị
    config = get_charm_config(db)
    target_config = config.get(rarity, config["MAGIC"]) # Fallback về Magic nếu lỗi

    # 2. Bốc ảnh ngẫu nhiên
    img_name = "default.png"
    try:
        if os.path.exists(CHARM_DISK_PATH):
            # Lấy tất cả file ảnh (png, jpg, jpeg)
            valid_exts = ('.png', '.jpg', '.jpeg', '.webp')
            files = [f for f in os.listdir(CHARM_DISK_PATH) if f.lower().endswith(valid_exts)]
            
            if files: 
                img_name = random.choice(files)
            else:
                print(f"⚠️ Thư mục {CHARM_DISK_PATH} có tồn tại nhưng KHÔNG CÓ ẢNH nào!")
        else:
            print(f"⚠️ Không tìm thấy thư mục ảnh tại: {CHARM_DISK_PATH}")
            # In ra để debug xem nó đang tìm ở đâu
            print(f"ℹ️ (Gợi ý: Kiểm tra xem folder 'frontend' có nằm ngang hàng với folder 'backend' không)")
    except Exception as e:
        print(f"⚠️ Lỗi quét ảnh Charm: {e}")
    
    # Tạo URL chuẩn cho Frontend
    full_img_url = f"{CHARM_URL_PREFIX}{img_name}"

    # 3. Roll chỉ số (Stats)
    stats = {}
    
    # Logic: Ma thuật (MAGIC) chỉ có 1 dòng (ATK hoặc HP)
    if rarity == "MAGIC":
        stat_type = random.choice(["atk", "hp"]) # Random 1 trong 2
        min_val, max_val = target_config.get(f"{stat_type}_range", [10, 50])
        stats[stat_type] = random.randint(min_val, max_val)
    
    # Logic: Sử Thi/Huyền Thoại có đủ 2 dòng
    else: 
        atk_min, atk_max = target_config.get("atk_range", [10, 50])
        hp_min, hp_max = target_config.get("hp_range", [100, 500])
        stats["atk"] = random.randint(atk_min, atk_max)
        stats["hp"] = random.randint(hp_min, hp_max)

    # 4. Đặt tên tiếng Việt
    vn_name = "CHARM"
    if rarity == "MAGIC": vn_name = "Charm Ma Thuật"
    elif rarity == "EPIC": vn_name = "Charm Sử Thi"
    elif rarity == "LEGEND": vn_name = "Charm Huyền Thoại"

    # 5. Lưu vào DB
    new_item = PlayerItem(
        player_id=player_id,
        image_url=full_img_url,
        rarity=rarity,
        name=vn_name,
        stats_data=json.dumps(stats),
        enhance_level=0,
        is_equipped=False,
        slot_index=0
    )
    
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    
    return new_item

# ==========================================================
# 🔥 PHẦN 2: LÒ RÈN (FORGE SYSTEM) - [MỚI]
# ==========================================================
def forge_item(db: Session, item_id: int, player_id: int, stone_item_id: int = None):
    """
    Cường hóa Charm.
    - item_id: ID của Charm trong túi (PlayerItem)
    - stone_item_id: (Tùy chọn) Nếu để None, hệ thống sẽ tự quét túi để tìm đá.
    """
    # 1. Kiểm tra Item Charm
    charm = db.exec(select(PlayerItem).where(PlayerItem.id == item_id, PlayerItem.player_id == player_id)).first()
    if not charm: return {"status": "error", "message": "Không tìm thấy vật phẩm!"}
    
    if charm.enhance_level >= 10:
        return {"status": "error", "message": "Vật phẩm đã đạt cấp tối đa (+10)!"}

    # 2. Lấy cấu hình Forge & Xác định nhóm
    forge_config = get_forge_config(db)
    current_cfg = forge_config["group_3"] # Mặc định khó nhất
    
    for group in forge_config.values():
        if group["min"] <= charm.enhance_level < group["max"]:
            current_cfg = group
            break

    # =========================================================
    # 3. TỰ ĐỘNG TÌM ĐÁ CƯỜNG HÓA TRONG TÚI
    # =========================================================
    stone_inv = None
    
    # Cách 1: Nếu API có truyền ID đá cụ thể (Ưu tiên tìm theo ID đó trước)
    if stone_item_id:
        stone_inv = db.exec(select(Inventory).where(
            Inventory.player_id == player_id, 
            Inventory.item_id == stone_item_id
        )).first()

    # Cách 2: Nếu không truyền ID hoặc tìm không thấy -> Quét toàn bộ túi
    if not stone_inv:
        # Lấy tất cả item đang có trong túi
        inventory_list = db.exec(
            select(Inventory, Item)
            .join(Item)
            .where(Inventory.player_id == player_id)
            .where(Inventory.amount > 0)
        ).all()

        for inv, item_def in inventory_list:
            try:
                # Đọc config của từng món đồ
                cfg = json.loads(item_def.config)
                
                # Kiểm tra xem có phải là Đá Cường Hóa không?
                # (Logic này khớp với cái else-if bạn vừa thêm ở Admin)
                if cfg.get("action") == "enhance_stone" or cfg.get("type") == "enhance_stone":
                    stone_inv = inv
                    break # Tìm thấy rồi thì dừng lại
            except: 
                pass

    # Xác định giá đá
    cost = current_cfg["stone"]
    
    # Kiểm tra lần cuối
    if not stone_inv or stone_inv.amount < cost:
        return {"status": "error", "message": f"Không đủ Đá Cường Hóa! Cần {cost} viên."}

    # 4. Trừ đá (Luôn trừ dù thành công hay thất bại)
    stone_inv.amount -= cost
    if stone_inv.amount <= 0:
        db.delete(stone_inv) # Xóa nếu hết sạch
    else:
        db.add(stone_inv)

    # 5. Roll nhân phẩm (Giữ nguyên)
    success_rate = current_cfg["rate"]
    roll = random.randint(1, 100)
    is_success = roll <= success_rate

    result_data = {
        "consumed_stones": cost,
        "old_level": charm.enhance_level,
        "new_level": charm.enhance_level
    }

    if is_success:
        # --- THÀNH CÔNG ---
        charm.enhance_level += 1
        
        # Tăng chỉ số (Bonus %)
        try:
            stats = json.loads(charm.stats_data)
            bonus_multiplier = 1 + (current_cfg["bonus_pct"] / 100)
            
            for key in stats:
                stats[key] = int(stats[key] * bonus_multiplier)
                
            charm.stats_data = json.dumps(stats)
        except: pass
        
        result_data["status"] = "success"
        result_data["message"] = f"Thành công! {charm.name} đã lên +{charm.enhance_level}"
        result_data["new_level"] = charm.enhance_level
    else:
        # --- THẤT BẠI ---
        result_data["status"] = "fail"
        result_data["message"] = "Cường hóa thất bại! Bạn bị mất nguyên liệu."

    db.add(charm)
    db.commit()
    db.refresh(charm) # Refresh để đảm bảo dữ liệu mới nhất
    
    return result_data