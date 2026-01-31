import json
import random
from datetime import datetime
from sqlmodel import Session, select
from database import Inventory, Item, Player

# =====================================================
# HÀM HỖ TRỢ TÍNH TOÁN
# =====================================================
def calculate_max_hp_limit(player):
    """Tính giới hạn máu"""
    base_hp = max(10, player.kpi or 0)
    bonus = 0
    if player.class_type == "WARRIOR":
        bonus = 300
    elif player.class_type == "MAGE":
        bonus = 100
    return base_hp + bonus

# =====================================================
# BỘ XỬ LÝ TRUNG TÂM (CORE PROCESSOR)
# =====================================================
def apply_item_effects(player: Player, item: Item, db: Session):
    try:
        # 1. Parse JSON Config
        if not item.config:
            return False, "Vật phẩm chưa được cấu hình!", {}
            
        try:
            config = json.loads(item.config)
        except json.JSONDecodeError:
            config = {"action": item.config.strip()}

        # Lấy action (Hỗ trợ cả 'type' do Admin JS mới gửi lên)
        action = config.get("action") or config.get("type")
        value = config.get("value", 0)

        # -----------------------------------------------------
        # CASE 1: HỒI MÁU (HP) [ĐÃ FIX LỖI TỤT MÁU]
        # -----------------------------------------------------
        if action == "heal" or action == "Hồi máu (HP)":
            # Lấy lượng máu hồi phục
            if not value: value = config.get("hp_restore", 100)
            heal_amount = int(value)
            
            # ❌ BỎ CODE CŨ: max_hp = calculate_max_hp_limit(player)
            
            # ✅ CODE MỚI: Lấy Max HP chuẩn từ Database (do Level Up tính)
            real_max_hp = player.hp_max
            
            # Fallback an toàn (Đề phòng DB lỗi ra 0)
            if real_max_hp < 100: real_max_hp = 100
            
            # Lấy máu hiện tại
            current_hp = player.hp if player.hp else 0

            # Kiểm tra: Nếu máu đã đầy thì không cho dùng (để đỡ phí bình)
            if current_hp >= real_max_hp:
                 return False, "Máu đã đầy, không cần dùng thêm!", {}

            # Tính toán máu mới
            new_hp = current_hp + heal_amount
            
            # Nếu vượt quá giới hạn thì cắt về Max
            if new_hp > real_max_hp:
                new_hp = real_max_hp
            
            # Cập nhật vào Player
            player.hp = new_hp 
            db.add(player)
            # (Lưu ý: db.commit() sẽ được gọi ở hàm cha bên ngoài inventory_api)
            
            return True, f"Đã hồi {heal_amount} HP. Máu hiện tại: {new_hp}/{real_max_hp}", {"hp": new_hp, "max_hp": real_max_hp}

        # -----------------------------------------------------
        # CASE 2: NHẬN TIỀN TỆ / KPI
        # -----------------------------------------------------
        elif action == "add_currency" or action == "Nhận tiền tệ/KPI":
            currency_type = config.get("target_currency") or config.get("type", "tri_thuc")
            amount = int(value)
            
            msg = ""
            if currency_type == "tri_thuc":
                player.tri_thuc = (player.tri_thuc or 0) + amount
                msg = f"Nhận được {amount} Tri Thức!"
            elif currency_type == "chien_tich":
                player.chien_tich = (player.chien_tich or 0) + amount
                msg = f"Nhận được {amount} Chiến Tích!"
            elif currency_type == "vinh_du":
                player.vinh_du = (player.vinh_du or 0) + amount
                msg = f"Nhận được {amount} Vinh Dự!"
            elif currency_type == "kpi":
                player.kpi = (player.kpi or 0) + amount
                msg = f"KPI tăng thêm {amount} điểm!"
            else:
                return False, f"Loại tiền tệ '{currency_type}' không hợp lệ", {}
                
            db.add(player)
            return True, msg, {"currency": currency_type, "amount": amount}

        # -----------------------------------------------------
        # CASE 3: XÓA THỜI GIAN CHỜ HỒI SINH
        # -----------------------------------------------------
        elif action == "reset_revive" or action == "reset_cooldown":
            if not player.revive_at:
                return False, "Bạn đang sống khỏe mạnh, không cần dùng!", {}
            
            player.revive_at = None
            player.hp = calculate_max_hp_limit(player)
            db.add(player)
            return True, "Hồi sinh thành công! Sẵn sàng chiến đấu.", {"hp": player.hp}

        # -----------------------------------------------------
        # CASE 4: RƯƠNG GACHA (SỬA LỖI RƯƠNG RỖNG) 🎁
        # -----------------------------------------------------
        elif action == "gacha_open" or action == "Rương Gacha (Quay vật phẩm)":
            
            # 👇 QUAN TRỌNG: Thêm 'pool' vào danh sách tìm kiếm
            drops = (config.get("gacha_items") or 
                     config.get("drops") or 
                     config.get("pool") or  # <--- THỦ PHẠM NẰM Ở ĐÂY
                     config.get("loot_table") or [])
            
            if not drops:
                return False, "Rương này rỗng (Lỗi config: Không tìm thấy danh sách item)!", {}

            # --- Thuật toán Quay thưởng ---
            population = [] # ID vật phẩm
            weights = []    # Tỷ lệ

            for d in drops:
                # Lấy ID (chấp nhận cả string lẫn int)
                raw_id = d.get("item_id") or d.get("id")
                # Lấy tỷ lệ
                raw_rate = d.get("rate", 0)
                
                if raw_id and float(raw_rate) > 0:
                    try:
                        population.append(int(raw_id)) # Ép kiểu về số nguyên
                        weights.append(float(raw_rate))
                    except:
                        pass

            if not population:
                return False, "Cấu hình rương bị lỗi (ID vật phẩm không hợp lệ).", {}

            # Quay số (Chọn 1 món)
            won_item_id = random.choices(population, weights=weights, k=1)[0]
            qty = 1 

            # --- Cộng đồ vào kho ---
            inv_item = db.exec(select(Inventory).where(
                Inventory.player_id == player.id,
                Inventory.item_id == won_item_id
            )).first()

            if inv_item:
                inv_item.amount += qty
                db.add(inv_item)
            else:
                new_inv = Inventory(player_id=player.id, item_id=won_item_id, amount=qty)
                db.add(new_inv)
            
            # Lấy thông tin hiển thị
            won_item_obj = db.get(Item, won_item_id)
            
            # Commit luôn ở đây để đảm bảo lưu giao dịch
            # (Lưu ý: Nếu hàm cha bên ngoài có commit rồi thì dòng này có thể thừa, 
            # nhưng thêm vào cho chắc chắn trong trường hợp này)
            # db.commit() 
            
            if not won_item_obj:
                return True, f"Mở thành công item ID {won_item_id} (nhưng item này đã bị xóa tên)", {}

            return True, f"Mở rương thành công! Bạn nhận được: {won_item_obj.name}", {
                "reward_name": won_item_obj.name,
                "reward_image": won_item_obj.image_url,
                "received": [f"{won_item_obj.name} x{qty}"]
            }

        # -----------------------------------------------------
        # CASE 5: THÔNG ĐIỆP
        # -----------------------------------------------------
        elif action == "send_message":
            msg_content = config.get("content", "Không có nội dung.")
            return True, f"Thông điệp: {msg_content}", {}

        else:
            return False, f"Chức năng '{action}' chưa được hỗ trợ", {}

    except Exception as e:
        print(f"❌ ITEM ERROR: {e}")
        return False, f"Lỗi hệ thống: {str(e)}", {}