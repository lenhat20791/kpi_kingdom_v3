import json
import random
from sqlmodel import Session, select
from database import Inventory, Item, Player

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
                    
                    # --- CỘNG VÀO KHO (AN TOÀN) ---
                    inv_item = db.exec(select(Inventory).where(
                        Inventory.player_id == player.id,
                        Inventory.item_id == target_id
                    )).first()

                    if inv_item:
                        # Ép kiểu int để chống crash
                        current_amt = int(inv_item.amount)
                        inv_item.amount = current_amt + qty
                        db.add(inv_item)
                    else:
                        new_item = Inventory(player_id=player.id, item_id=target_id, amount=qty)
                        db.add(new_item)
                    
                    # --- LẤY TÊN VÀ XỬ LÝ KÝ TỰ LẠ ---
                    item_obj = db.get(Item, target_id)
                    raw_name = item_obj.name if item_obj else f"Item {target_id}"
                    # Xóa ký tự \xa0 gây lỗi Frontend
                    clean_name = raw_name.replace("\xa0", " ").strip()
                    
                    # Cộng dồn vào danh sách hiển thị
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
        # MẶC ĐỊNH
        # =====================================================
        return False, "Vật phẩm chưa được hỗ trợ.", {}

    except Exception as e:
        print(f"❌ LỖI ITEM PROCESSOR: {e}")
        # In chi tiết lỗi ra console server để debug nếu cần
        import traceback
        traceback.print_exc()
        return False, "Lỗi hệ thống xử lý vật phẩm.", {}