import json
from sqlmodel import Session, select
from database import Player, PlayerItem, Item, Companion

def recalculate_player_stats(db: Session, player: Player, heal_mode: str = "MAINTAIN_PERCENT"):
    """
    Tính lại toàn bộ chỉ số nhân vật dựa trên trang bị.
    
    Tham số heal_mode:
    - "MAINTAIN_PERCENT" (Mặc định): Giữ nguyên % máu (Dùng khi Mặc/Tháo đồ).
    - "HEAL_BONUS": Hồi phục đúng lượng Max HP vừa tăng thêm (Dùng khi Cường hóa).
    - "FULL_HEAL": Hồi đầy 100% máu (Dùng khi Lên cấp).
    """
    
    # [QUAN TRỌNG] Lưu lại chỉ số Máu cũ để tính toán tỷ lệ
    old_max_hp = player.hp_max
    old_current_hp = player.hp

    # 1. Lấy tất cả đồ đang mặc
    equipped_items = db.exec(
        select(PlayerItem)
        .where(PlayerItem.player_id == player.id)
        .where(PlayerItem.is_equipped == True)
    ).all()
    # Lấy Thẻ Đồng Hành (MỚI)
    equipped_companions = db.exec(
        select(Companion)
        .where(Companion.player_id == player.id)
        .where(Companion.is_equipped == True)
    ).all()
    # 2. TÍNH TỔNG BONUS MỚI
    new_atk_bonus = 0 
    new_hp_bonus = 0
    # A. Cộng từ Charm
    for item in equipped_items:
        if item.stats_data:
            try:
                stats = json.loads(item.stats_data)
                new_atk_bonus += int(stats.get("atk", 0))
                new_hp_bonus += int(stats.get("hp", 0))
            except: pass
    # B. Cộng từ Thẻ Đồng Hành (MỚI)
    for comp in equipped_companions:
        new_atk_bonus += comp.atk
        new_hp_bonus += comp.hp
        
    # 3. Lấy lại chỉ số gốc (Base Stats)
    # Logic: Base = Tổng hiện tại - Bonus cũ đang lưu trong DB
    current_base_atk = player.atk - (player.item_atk_bonus or 0)
    current_base_hp = player.hp_max - (player.item_hp_bonus or 0) 

    # 4. Áp dụng Bonus mới
    # Logic: Tổng mới = Base + Bonus mới
    player.atk = current_base_atk + new_atk_bonus
    player.hp_max = current_base_hp + new_hp_bonus
    
    # Cập nhật thông tin bonus vào DB
    player.item_atk_bonus = new_atk_bonus
    player.item_hp_bonus = new_hp_bonus

    # ==========================================================
    # 5. XỬ LÝ MÁU HIỆN TẠI (LOGIC MỚI - HYBRID)
    # ==========================================================
    
    # Trường hợp 1: Lên cấp -> Hồi đầy máu
    if heal_mode == "FULL_HEAL":
        player.hp = player.hp_max
        
    # Trường hợp 2: Cường hóa -> Tăng bao nhiêu Max thì hồi bấy nhiêu máu
    elif heal_mode == "HEAL_BONUS":
        hp_diff = player.hp_max - old_max_hp
        if hp_diff > 0:
            player.hp = old_current_hp + hp_diff
        else:
            player.hp = old_current_hp # Nếu ko tăng hoặc giảm thì giữ nguyên số cũ

    # Trường hợp 3: Mặc/Tháo đồ -> Giữ nguyên % (Chống hack máu)
    else: # "MAINTAIN_PERCENT"
        if old_max_hp > 0:
            # Tính % máu cũ (Ví dụ: 50/100 = 0.5)
            percent = old_current_hp / old_max_hp
            # Áp dụng % đó cho Max HP mới (Ví dụ: 200 * 0.5 = 100)
            new_current_hp = int(player.hp_max * percent)
            player.hp = new_current_hp
        
        # Đảm bảo tối thiểu 1 HP để ko bị chết oan khi tháo đồ
        if player.hp < 1: player.hp = 1

    # Chốt chặn cuối cùng: Không được vượt quá Max HP mới
    if player.hp > player.hp_max:
        player.hp = player.hp_max

    # 6. Lưu vào DB
    db.add(player)
    db.commit()
    db.refresh(player)
    
    print(f"🔄 Recalculate ({heal_mode}): HP {old_current_hp}/{old_max_hp} -> {player.hp}/{player.hp_max}")