# --- FILE: backend/game_logic/level.py ---

def safe_increase(current_val: int, multiplier: float) -> int:
    """
    Hàm tăng chỉ số an toàn:
    - current_val: Giá trị hiện tại (VD: 100)
    - multiplier: Hệ số nhân (VD: 1.05 là tăng 5%)
    - Luôn đảm bảo tăng ít nhất 1 điểm để tránh lỗi làm tròn (10 * 1.02 = 10 -> Lỗi)
    """
    if current_val is None: current_val = 0
    
    # Tính giá trị mới
    new_val = int(current_val * multiplier)
    
    # Nếu nhân xong mà vẫn bằng số cũ (do số quá bé), thì cộng thủ công thêm 1
    if new_val <= current_val:
        return current_val + 1
        
    return new_val

def add_exp_to_player(player, amount: int):
    """
    Xử lý logic: Cộng EXP -> Check Level Up -> Tăng Stats theo %
    """
    # 1. Cộng EXP
    player.exp += amount
    is_leveled_up = False
    
    # 2. Vòng lặp thăng cấp (Xử lý trường hợp lên nhiều cấp 1 lúc)
    while player.exp >= player.next_level_exp:
        
        # --- A. XỬ LÝ EXP & LEVEL ---
        player.exp -= player.next_level_exp
        player.level += 1
        is_leveled_up = True
        
        # Tăng độ khó cho cấp sau (+10% EXP yêu cầu)
        player.next_level_exp = int(player.next_level_exp * 1.1)

        # --- B. XỬ LÝ CLASS ---
        user_class = str(player.class_type).strip().upper() if player.class_type else "NOVICE"
        
        # Log server để bạn dễ kiểm soát
        print(f"⚡ Up Level {player.level} | Class: {user_class}")

        # --- C. TĂNG CHỈ SỐ (THEO YÊU CẦU: 5% và 2%) ---
        
        # 1. Tách Item ra để lấy Base Stats
        base_atk = player.atk - (player.item_atk_bonus or 0)
        base_hp = player.hp_max - (player.item_hp_bonus or 0)

        # 2. Nhân % vào Base Stats (Dùng hàm safe_increase của bạn )
        if user_class == "MAGE":
            base_atk = safe_increase(base_atk, 1.05)
            base_hp = safe_increase(base_hp, 1.02)
        elif user_class == "WARRIOR":
            base_hp = safe_increase(base_hp, 1.05)
            base_atk = safe_increase(base_atk, 1.02)
        else:
            base_hp = safe_increase(base_hp, 1.02)
            base_atk = safe_increase(base_atk, 1.02)

        # 3. Cộng lại Item Bonus vào để ra chỉ số tổng mới
        player.atk = base_atk + (player.item_atk_bonus or 0)
        player.hp_max = base_hp + (player.item_hp_bonus or 0)
        
        # Hồi máu
        player.hp = player.hp_max
        
    return is_leveled_up