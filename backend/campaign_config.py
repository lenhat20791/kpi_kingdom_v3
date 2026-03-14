# ==========================================
# CẤU HÌNH CHIẾN DỊCH THANH LONG - BẠCH HỔ
# ==========================================

# 1. Thời gian hoạt động
CAMPAIGN_START_HOUR = 6
CAMPAIGN_END_HOUR = 22
CAMPAIGN_DURATION_HOURS = 168
MARCH_TIME_ALLY_MINUTES = 3
MARCH_TIME_ENEMY_MINUTES = 5
DEFEND_TO_CAPTURE_MINUTES = 20
RESPAWN_PENALTY_MINUTES = 5

# 2. Mini-game & Lính
MINIGAME1_TROOPS_REWARD = 150  # Số lính nhận được mỗi lần Chiêu binh
MINIGAME2_EXP_REWARD = 30      # Số EXP nhận được mỗi lần Luyện binh
TROOPS_FOR_ONE_H_POINT = 1000  # Cứ cày 1000 lính = 1 điểm Hậu Phương (H)

# 3. Quân đoàn (Level & Sức chứa)
BASE_TROOP_CAPACITY = 100      # Sức chứa lính ở Level 1
CAPACITY_PER_LEVEL = 20        # Mỗi lần lên cấp nới rộng thêm bao nhiêu lính
MAX_LEGION_LEVEL = 20          # Cấp tối đa của Quân đoàn

# 4. Thẻ Đồng Hành (Bonus Lực chiến)
BONUS_R = 0.02
BONUS_SR = 0.04
BONUS_SSR = 0.06
BONUS_USR = 0.08
BONUS_PER_STAR = 0.01

# 5. Phần thưởng cuối mùa giải
WIN_REWARD_CHIEN_TICH = 20
WIN_REWARD_TRI_THUC = 50
WIN_REWARD_KPI = 50
LOSE_REWARD_CHIEN_TICH = 10
LOSE_REWARD_TRI_THUC = 10
LOSE_REWARD_KPI = 10