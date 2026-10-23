"""Chemistry card definitions for Study Spire."""


def _card(card_id, name, rarity, mana_cost, card_type, filename, description, effects, tags, tooltips=()):
    image_url = f"/assets/Deck/deck%20hoa%20hoc/{filename}"
    return {
        "card_id": card_id,
        "id": card_id,
        "name": name,
        "subject": "hoa",
        "rarity": rarity,
        "mana_cost": mana_cost,
        "cost": mana_cost,
        "card_type": card_type,
        "type": card_type,
        "tags": ["hoa_hoc", *tags],
        "description": description,
        "image_url": image_url,
        "art_path": image_url,
        "effects": effects,
        "effect_tooltips": list(tooltips),
    }


CHEMISTRY_CARDS = [
    _card(
        "chemistry_01_acid_properties", "Tính chất hóa học của Axit", "rare", 1, "attack", "tchh_axit.png",
        "Gây 6 sát thương và áp dụng 3 tầng Độc lên đối thủ.",
        [{"op": "attack", "value": 6}, {"op": "apply_poison", "stacks": 3, "pierce_shield": True}],
        ["poison"],
        ["Độc: Cuối mỗi lượt, mục tiêu nhận sát thương bằng số stack Độc hiện tại (trừ thẳng vào HP, Khiên không chặn được), sau đó giảm 1 tầng."],
    ),
    _card(
        "chemistry_02_exothermic_reaction", "Phản ứng tỏa nhiệt", "rare", 1, "defense", "pu_toa_nhiet.png",
        "Nhận 6 Khiên. Nếu đối thủ đang dính Độc, gây sát thương bằng số tầng Độc hiện có lên đối thủ.",
        [{"op": "gain_shield", "value": 6}, {"op": "damage_from_enemy_poison"}],
        ["poison"],
    ),
    _card(
        "chemistry_03_base_indicator", "Dung dịch Bazơ và Chất chỉ thị", "rare", 2, "defense", "bazo_chi_thi.png",
        "Nhận 8 Khiên. Tăng thêm 2 tầng Độc nếu đối thủ đang dính Độc. Gọi lá Phản ứng trung hòa từ tệp bài lên tay.",
        [
            {"op": "gain_shield", "value": 8},
            {"op": "apply_poison_if_enemy_poisoned", "stacks": 2, "pierce_shield": True},
            {"op": "tutor", "card_id": "chemistry_04_neutralization", "from": "draw_pile"},
        ],
        ["poison", "combo_tutor"],
        [
            "Độc: Gây sát thương thẳng vào HP cuối lượt.",
            "Triệu hồi: Rút chính xác lá bài chỉ định từ tệp bài đưa lên tay người chơi.",
        ],
    ),
    _card(
        "chemistry_04_neutralization", "Phản ứng trung hòa", "rare", 1, "attack", "pu_trung_hoa.png",
        "Gây 5 sát thương. Nếu đã sử dụng lá Dung dịch Bazơ và Chất chỉ thị trước đó trong lượt, áp dụng thêm 4 tầng Độc lên đối thủ.",
        [
            {"op": "attack", "value": 5},
            {"op": "apply_poison_if_card_played", "card_id": "chemistry_03_base_indicator", "stacks": 4, "pierce_shield": True},
        ],
        ["poison", "combo_tutor"],
    ),
    _card(
        "chemistry_05_chlorine_gas", "Phi kim: Khí Clo", "rare", 2, "spell", "khi_clo.png",
        "Áp dụng 5 tầng Độc lên đối thủ. Gọi lá Muối NaCl và Hợp chất từ tệp bài lên tay.",
        [
            {"op": "apply_poison", "stacks": 5, "pierce_shield": True},
            {"op": "tutor", "card_id": "chemistry_06_nacl_compound", "from": "draw_pile"},
        ],
        ["poison", "combo_tutor"],
        [
            "Độc: Trừ thẳng vào HP cuối mỗi lượt.",
            "Triệu hồi: Rút chính xác lá bài chỉ định từ tệp bài đưa lên tay.",
        ],
    ),
    _card(
        "chemistry_06_nacl_compound", "Muối NaCl và Hợp chất", "rare", 1, "defense", "muoi_nacl.png",
        "Nhận 10 Khiên. Giảm 1 Trí Tuệ tiêu thụ của 1 lá bài mang nhãn Độc ngẫu nhiên trên tay trong lượt này.",
        [{"op": "gain_shield", "value": 10}, {"op": "modify_random_cost_by_tag", "tag": "poison", "delta": -1, "minimum": 0}],
        ["poison"],
    ),
    _card(
        "chemistry_07_solution_exchange", "Phản ứng trao đổi trong dung dịch", "rare", 2, "defense", "pu_trao_doi.png",
        "Nhận 7 Khiên. Chuyển hóa toàn bộ số tầng Độc của đối thủ thành Khiên bổ sung cho bản thân, sau đó Độc trở về 0.",
        [{"op": "gain_shield", "value": 7}, {"op": "convert_enemy_poison_to_shield"}],
        ["poison"],
    ),
    _card(
        "chemistry_08_solution_concentration", "Nồng độ dung dịch", "rare", 1, "spell", "nong_do_dd.png",
        "Tăng số tầng Độc hiện có của đối thủ thêm 50%, làm tròn xuống. Nếu đối thủ chưa dính Độc, áp dụng 3 tầng Độc.",
        [{"op": "amplify_enemy_poison", "multiplier": 1.5, "fallback_stacks": 3, "pierce_shield": True}],
        ["poison"],
    ),
    _card(
        "chemistry_09_distillation", "Tách chất và Chưng cất", "rare", 1, "spell", "chung_cat.png",
        "Bỏ 2 lá bài ngẫu nhiên trên tay vào mộ bài, rút 3 lá bài mới từ tệp bài.",
        [{"op": "discard_random_hand", "count": 2}, {"op": "draw", "count": 3}],
        [],
    ),
    _card(
        "chemistry_10_covalent_bond", "Liên kết cộng hóa trị", "rare", 1, "defense", "lk_cong_hoa_tri.png",
        "Nhận 5 Khiên. Giảm 1 Trí Tuệ tiêu thụ cho tất cả các lá bài thuộc hệ Hóa Học rút ra trong lượt này.",
        [{"op": "gain_shield", "value": 5}, {"op": "set_draw_cost_aura_by_tag", "tag": "hoa_hoc", "delta": -1, "minimum": 0}],
        [],
    ),
    _card(
        "chemistry_11_mass_conservation", "Định luật bảo toàn khối lượng", "rare", 2, "defense", "bt_khoi_luong.png",
        "Nhận 4 Khiên. Nếu đối thủ đang bị nhiễm Độc, giữ lại toàn bộ số Khiên hiện có sang lượt sau.",
        [{"op": "gain_shield", "value": 4}, {"op": "retain_shield_if_enemy_poisoned"}],
        ["poison", "retain_shield"],
    ),
    _card(
        "chemistry_12_chemical_transformation", "Sự biến đổi hóa học", "rare", 0, "spell", "bd_hoa_hoc.png",
        "Mất 4 HP của bản thân. Nhận thêm 2 điểm Trí Tuệ tạm thời trong lượt này.",
        [{"op": "self_damage", "value": 4}, {"op": "gain_mana", "value": 2, "increase_temporary_max": True}],
        [],
    ),
    _card(
        "chemistry_13_catalyst_detonation", "Tốc độ phản ứng và Chất xúc tác", "ultra_rare", 2, "attack", "xuc_tac.png",
        "Tiêu thụ toàn bộ số tầng Độc của đối thủ và gây sát thương nổ thẳng vào HP bằng 150% số tầng Độc vừa tiêu thụ.",
        [{"op": "consume_enemy_poison_burst", "multiplier": 1.5}],
        ["poison"],
        ["Kích Nổ Độc: Xóa toàn bộ Độc để giải phóng sát thương tức thì trực tiếp vào HP, bỏ qua Khiên."],
    ),
    _card(
        "chemistry_14_chain_reaction", "Phản ứng dây chuyền", "ultra_rare", 3, "spell", "day_chuyen.png",
        "Trong 2 lượt kế tiếp, Độc không giảm ở cuối mỗi lượt mà tự động nhân đôi.",
        [{"op": "set_poison_doubling", "turns": 2}],
        ["poison"],
        ["Chuỗi nhân đôi: Độc gây sát thương xuyên Khiên xong sẽ tự nhân đôi số stack thay vì giảm 1 trong thời gian hiệu lực."],
    ),
    _card(
        "chemistry_15_periodic_table", "Bảng tuần hoàn các nguyên tố hóa học", "ultra_rare", 2, "spell", "bang_tuan_hoan.png",
        "Chọn 2 lá bài mang hiệu ứng Độc trong tệp bài đưa lên tay. Giảm lượng Trí Tuệ cần dùng của 2 lá đó về 0 trong lượt này.",
        [
            {"op": "tutor_by_tag", "tag": "poison", "count": 2, "from": "draw_pile"},
            {"op": "set_cost_for_last_drawn", "cost": 0},
        ],
        ["poison", "combo_tutor"],
        ["Triệu hồi: Rút chính xác các lá bài phù hợp từ tệp bài đưa lên tay."],
    ),
    _card(
        "chemistry_16_nitric_acid_corrosion", "Axit Nitric và Ăn mòn kim loại", "ultra_rare", 3, "attack", "hno3_an_mon.png",
        "Gây 10 sát thương trực tiếp vào HP, bỏ qua Khiên. Nếu đối thủ có từ 10 tầng Độc trở lên, làm Choáng đối thủ trong 1 lượt.",
        [
            {"op": "direct_damage", "value": 10},
            {"op": "stun_if_enemy_poison_at_least", "stacks": 10, "turns": 1},
        ],
        ["poison"],
        ["Choáng: Đối thủ mất hoàn toàn lượt hành động kế tiếp."],
    ),
    _card(
        "chemistry_17_heavy_metal_toxicity", "Nhiễm độc kim loại nặng", "ultra_rare", 2, "spell", "doc_kim_loai_nang.png",
        "Áp dụng ngay 12 tầng Độc lên đối thủ. Xóa bỏ toàn bộ Khiên và các trạng thái có lợi trên người đối thủ.",
        [
            {"op": "apply_poison", "stacks": 12, "pierce_shield": True},
            {"op": "purge_enemy_buffs"},
        ],
        ["poison"],
        ["Thanh Tẩy: Phá hủy toàn bộ Khiên và các hiệu ứng tăng sức mạnh của đối thủ."],
    ),
]

for chemistry_card in CHEMISTRY_CARDS:
    chemistry_card["art_path"] = chemistry_card["image_url"]