import random
import json
from typing import List, Dict, Any

# 1. TẬP GIÁ TRỊ PHỔ THÔNG (Đảm bảo luôn xuất hiện trên >= 3 người)
COMMON_POOLS = {
    "hair_type": ["Tóc ngắn thẳng", "Tóc ngắn xoăn", "Tóc dài thẳng", "Tóc dài xoăn"],
    "eye_color": ["Mắt nâu", "Mắt xanh dương", "Mắt hổ phách (vàng)"],
    "face_trait": ["Nốt ruồi dưới mắt", "Vết sẹo lông mày", "Tàn nhang hai má", "Nốt ruồi khóe môi", "Không có tì vết"],
    "left_arm_trait": ["Nốt ruồi cổ tay trái", "Vết sẹo cẳng tay trái", "Hình xăm vạch số", "Không có tì vết"],
    "right_arm_trait": ["Nốt ruồi bắp tay phải", "Vết sẹo mu bàn tay phải", "Đeo vòng định danh", "Không có tì vết"],
    "left_leg_trait": ["Vết bớt đầu gối trái", "Vết sẹo ống đồng trái", "Không có tì vết"],
    "right_leg_trait": ["Vết sẹo mắt cá phải", "Nốt ruồi đùi phải", "Không có tì vết"]
}

# 2. TẬP ĐẶC ĐIỂM ĐỘC NHẤT (UNIQUE POOL - Mỗi người đúng 1 cái không trùng lặp)
UNIQUE_TRAITS_POOL = [
    ("face_trait", "Vết sẹo hình chữ X ở cằm"),
    ("face_trait", "Nốt ruồi son giữa trán"),
    ("face_trait", "Vết bớt màu đỏ nửa mặt"),
    ("hair_type", "Tóc vuốt dựng nhuộm bạc"),
    ("eye_color", "Mắt hai màu dị sắc (Heterochromia)"),
    ("left_arm_trait", "Vết sẹo hình ngôi sao cẳng tay trái"),
    ("left_arm_trait", "Nốt ruồi tam giác cổ tay trái"),
    ("left_arm_trait", "Dấu vết phỏng nhiệt cánh tay trái"),
    ("right_arm_trait", "Nốt ruồi kép mu bàn tay phải"),
    ("right_arm_trait", "Vết sẹo vết cắt dài cánh tay phải"),
    ("right_arm_trait", "Khớp tay kim loại nhân tạo phải"),
    ("left_leg_trait", "Vết bớt hình ngọn lửa bắp chân trái"),
    ("left_leg_trait", "Nốt ruồi thẳng hàng đầu gối trái"),
    ("right_leg_trait", "Vết sẹo mảnh ghép đùi phải"),
    ("right_leg_trait", "Nốt ruồi lớn mắt cá trong chân phải"),
    ("face_trait", "Sẹo rạch ngang gò má trái"),
    ("face_trait", "Nốt ruồi đỉnh mũi"),
    ("left_arm_trait", "Vết xăm mã vạch phát sáng tay trái"),
    ("right_arm_trait", "Nốt ruồi đỏ mu ngón tay trỏ phải"),
    ("left_leg_trait", "Vết rạn năng lượng cẳng chân trái"),
    ("right_leg_trait", "Dấu ấn biểu tượng sao Hỏa mờ đùi phải"),
    ("hair_type", "Tóc tết lọn dài kiểu viễn chinh"),
    ("face_trait", "Vết sẹo tia chớp chân mày phải"),
    ("left_arm_trait", "Sẹo ghép nối khớp tay trái"),
    ("right_arm_trait", "Nốt ruồi ở cùi chỏ phải"),
    ("left_leg_trait", "Vết sẹo lồi khớp gối trái"),
    ("right_leg_trait", "Nốt ruồi ở gót chân phải"),
    ("face_trait", "Hai nốt ruồi song song đuôi mắt phải"),
    ("left_arm_trait", "Vết bớt hình thoi cánh tay trái"),
    ("right_arm_trait", "Vết sẹo móng vuốt cẳng tay phải"),
    ("left_leg_trait", "Sẹo phẫu thuật xương chân trái"),
    ("right_leg_trait", "Vết bớt bán nguyệt mắt cá phải"),
    ("hair_type", "Tóc cạo sát hai bên phủ đỉnh"),
    ("face_trait", "Nốt ruồi phong thủy nhân trung"),
    ("left_arm_trait", "Sẹo bỏng lạnh mu bàn tay trái"),
    ("right_arm_trait", "Vết bớt màu chàm bắp tay phải")
]


def generate_biometrics_for_crew(player_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """
    Tạo hồ sơ sinh trắc học cho toàn bộ danh sách người chơi (30-35 người).
    Đảm bảo:
      - Mỗi người có đúng 1 đặc điểm Unique.
      - Các đặc điểm còn lại thuộc Common Pool (trùng lặp >= 3 người).
    """
    num_players = len(player_ids)
    if num_players > len(UNIQUE_TRAITS_POOL):
        raise ValueError("Số lượng người chơi vượt quá kho đặc điểm Unique sẵn có!")

    # 1. Chuẩn bị danh sách đặc điểm Unique không trùng nhau
    selected_uniques = random.sample(UNIQUE_TRAITS_POOL, num_players)
    random.shuffle(selected_uniques)

    crew_biometrics = {}

    for idx, p_id in enumerate(player_ids):
        unique_slot, unique_value = selected_uniques[idx]

        # Khởi tạo giá trị phổ thông ngẫu nhiên từ Common Pool
        profile = {
            "hair_type": {"value": random.choice(COMMON_POOLS["hair_type"]), "is_unique": False},
            "eye_color": {"value": random.choice(COMMON_POOLS["eye_color"]), "is_unique": False},
            "face_trait": {"value": random.choice(COMMON_POOLS["face_trait"]), "is_unique": False},
            "left_arm_trait": {"value": random.choice(COMMON_POOLS["left_arm_trait"]), "is_unique": False},
            "right_arm_trait": {"value": random.choice(COMMON_POOLS["right_arm_trait"]), "is_unique": False},
            "left_leg_trait": {"value": random.choice(COMMON_POOLS["left_leg_trait"]), "is_unique": False},
            "right_leg_trait": {"value": random.choice(COMMON_POOLS["right_leg_trait"]), "is_unique": False},
        }

        # Ghi đè đúng 1 slot bằng đặc điểm Unique
        profile[unique_slot] = {
            "value": unique_value,
            "is_unique": True
        }

        # Lưu lại vị trí slot unique để hệ thống tra cứu nhanh
        profile["_unique_slot_key"] = unique_slot
        crew_biometrics[p_id] = profile

    return crew_biometrics


def get_random_clue_from_profile(profile_json_str: str, allow_unique: bool = False) -> str:
    """
    Hàm tiện ích: Rút trích ngẫu nhiên 1 manh mối nhân diện từ hồ sơ.
    Ưu tiên tuyệt đối các module phổ thông (is_unique == False).
    """
    profile = json.loads(profile_json_str) if isinstance(profile_json_str, str) else profile_json_str
    
    # Lấy danh sách các slot thuộc tính có thể trích xuất
    trait_keys = [k for k in profile.keys() if not k.startswith("_")]

    # Phân loại module phổ thông và unique
    common_clues = [profile[k]["value"] for k in trait_keys if not profile[k]["is_unique"]]
    unique_clues = [profile[k]["value"] for k in trait_keys if profile[k]["is_unique"]]

    # Ưu tiên trả về đặc điểm phổ thông trước
    if common_clues:
        return random.choice(common_clues)
    elif allow_unique and unique_clues:
        return unique_clues[0]
    return "Không thu thập được dấu vết rõ ràng"