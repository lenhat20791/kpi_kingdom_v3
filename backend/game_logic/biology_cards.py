"""Biology card definitions for Study Spire."""


def _card(card_id, name, rarity, mana_cost, card_type, filename, description, effects, tags, tooltips=()):
    image_url = f"/assets/Deck/deck%20sinh%20hoc/{filename}"
    return {
        "card_id": card_id,
        "id": card_id,
        "name": name,
        "subject": "sinh",
        "rarity": rarity,
        "mana_cost": mana_cost,
        "cost": mana_cost,
        "card_type": card_type,
        "type": card_type,
        "tags": ["sinh_hoc", *tags],
        "description": description,
        "image_url": image_url,
        "art_path": image_url,
        "effects": effects,
        "effect_tooltips": list(tooltips),
    }


BIOLOGY_CARDS = [
    _card(
        "biology_01_photosynthesis", "Quang hợp", "rare", 1, "defense", "quang_hop.png",
        "Hồi phục 5 máu ngay lập tức và nhận 4 Khiên.",
        [{"op": "heal", "value": 5}, {"op": "gain_shield", "value": 4}], ["heal"],
        ["Hồi máu tức thì: Hồi phục một lượng máu ngay khi lá bài được đánh ra, không vượt quá máu tối đa."],
    ),
    _card(
        "biology_02_water_absorption", "Rễ cây hút nước", "rare", 1, "attack", "re_cay_hut_nuoc.png",
        "Gây 6 sát thương. Hồi máu bằng 50% lượng sát thương thực tế gây vào máu của đối thủ.",
        [{"op": "attack", "value": 6, "lifesteal_ratio": 0.5}], ["heal", "lifesteal"],
        ["Hút máu: Hồi phục dựa trên sát thương thực tế trừ vào HP đối thủ; sát thương bị Khiên chặn không được tính."],
    ),
    _card(
        "biology_03_cell_division", "Tế bào phân chia", "rare", 2, "defense", "te_bao_phan_chia.png",
        "Nhận 6 Khiên. Bắt đầu Tái tạo: hồi 3 máu cuối lượt trong 3 lượt. Gọi Mô phân sinh từ tệp bài lên tay.",
        [
            {"op": "gain_shield", "value": 6},
            {"op": "apply_regeneration", "value": 3, "turns": 3},
            {"op": "tutor", "card_id": "biology_04_meristem", "from": "draw_pile"},
        ], ["heal", "regen", "combo_tutor"],
        [
            "Tái tạo (Regen): Hồi máu dần ở cuối mỗi lượt trong số lượt hiệu lực.",
            "Triệu hồi: Rút chính xác lá bài chỉ định từ tệp bài đưa lên tay người chơi.",
        ],
    ),
    _card(
        "biology_04_meristem", "Mô phân sinh", "rare", 1, "attack", "mo_phan_sinh.png",
        "Gây 5 sát thương. Nếu bản thân đang có Tái tạo, tăng thời gian duy trì thêm 2 lượt.",
        [{"op": "attack", "value": 5}, {"op": "extend_regeneration", "turns": 2}], ["regen"],
        ["Tái tạo (Regen): Hiệu ứng hồi phục máu dần ở cuối mỗi lượt.", "Khai thác trạng thái: Gia tăng thời gian hiệu lực của trạng thái đang có trên người chơi."],
    ),
    _card(
        "biology_05_organic_nutrients", "Dinh dưỡng hữu cơ", "rare", 2, "defense", "dinh_duong_huu_co.png",
        "Nhận 8 Khiên. Tăng 2 lượng máu hồi phục mỗi lần Tái tạo kích hoạt trong trận. Gọi Thoát hơi nước lên tay.",
        [
            {"op": "gain_shield", "value": 8},
            {"op": "increase_regeneration_power", "value": 2},
            {"op": "tutor", "card_id": "biology_06_transpiration", "from": "draw_pile"},
        ], ["heal", "regen", "combo_tutor"],
        [
            "Tái tạo: Hồi 3 máu ở cuối mỗi lượt, kéo dài trong 3 lượt.",
            "Cường hóa Tái tạo: Tăng lượng máu nhận được mỗi khi Tái tạo kích hoạt trong trận.",
            "Triệu hồi: Rút chính xác lá bài chỉ định từ tệp bài đưa lên tay người chơi.",
        ],
    ),
    _card(
        "biology_06_transpiration", "Thoát hơi nước", "rare", 1, "defense", "thoat_hoi_nuoc.png",
        "Nhận 8 Khiên. Giảm 1 Trí Tuệ tiêu thụ của 1 lá mang nhãn Hồi Máu ngẫu nhiên trên tay trong lượt này.",
        [{"op": "gain_shield", "value": 8}, {"op": "modify_random_cost_by_tag", "tag": "heal", "delta": -1, "minimum": 0}], ["heal"],
        ["Giảm Tiêu Thụ: Giảm điểm Trí Tuệ của một lá mang nhãn Hồi Máu trên tay trong lượt hiện tại, tối thiểu 0."],
    ),
    _card(
        "biology_07_epiphyte", "Hút bám biểu sinh", "rare", 2, "attack", "hut_bam_bieu_sinh.png",
        "Gây 7 sát thương. Nếu người chơi đang có Khiên, hồi phục 4 máu ngay lập tức.",
        [{"op": "attack", "value": 7}, {"op": "heal_if_player_has_shield", "value": 4}], ["heal"],
        ["Hồi máu tức thì: Hồi phục máu ngay khi lá bài được đánh ra."],
    ),
    _card(
        "biology_08_vegetative_reproduction", "Sinh sản sinh dưỡng", "rare", 1, "spell", "ss_sinh_duong.png",
        "Bỏ 2 lá bài ngẫu nhiên trên tay vào mộ bài, rút 3 lá bài mới từ tệp bài.",
        [{"op": "discard_random_hand", "count": 2}, {"op": "draw", "count": 3}], [],
        ["Lọc bài (Cycle): Đưa bài thừa trên tay vào mộ để tái tạo và rút bài mới từ tệp bài."],
    ),
    _card(
        "biology_09_blood_circulation", "Tuần hoàn máu", "rare", 1, "defense", "tuan_hoan_mau.png",
        "Nhận 6 Khiên. Nếu máu hiện tại đang đầy, nhận thêm 6 Khiên.",
        [{"op": "gain_shield", "value": 6}, {"op": "gain_shield_if_full_hp", "value": 6}], [],
        ["Đầy máu (Full HP): Kích hoạt hiệu ứng thưởng nếu người chơi chưa mất máu khi đánh lá bài."],
    ),
    _card(
        "biology_10_ecosystem", "Hệ sinh thái tự nhiên", "rare", 1, "defense", "he_sinh_thai.png",
        "Nhận 5 Khiên. Giảm 1 Trí Tuệ tiêu thụ cho các lá Sinh Học được rút trong lượt này.",
        [{"op": "gain_shield", "value": 5}, {"op": "set_draw_cost_aura_by_tag", "tag": "sinh_hoc", "delta": -1, "minimum": 0}], [],
        ["Hào quang hệ (Aura): Giảm chi phí các lá Sinh Học được rút trong lượt, tối thiểu 0."],
    ),
    _card(
        "biology_11_seed_dormancy", "Trạng thái ngủ nghỉ của hạt", "rare", 2, "defense", "ngu_nghi_hat.png",
        "Nhận 4 Khiên. Nếu đã hồi máu trong lượt này, giữ toàn bộ Khiên sang lượt sau.",
        [{"op": "gain_shield", "value": 4}, {"op": "retain_shield_if_healed"}], ["heal", "retain_shield"],
        ["Bảo Toàn Khiên (Retain Shield): Khiên không bị đặt về 0 khi bắt đầu lượt mới nếu điều kiện được thỏa mãn."],
    ),
    _card(
        "biology_12_gene_mutation", "Đột biến gen", "rare", 0, "spell", "dot_bien_gen.png",
        "Mất 4 máu của bản thân. Nhận thêm 2 điểm Trí Tuệ tạm thời trong lượt này.",
        [{"op": "self_damage", "value": 4}, {"op": "gain_mana", "value": 2, "increase_temporary_max": True}], [],
        ["Hy sinh máu: Trừ máu trực tiếp, bỏ qua Khiên, để nhận Trí Tuệ vượt giới hạn."],
    ),
    _card(
        "biology_13_food_chain", "Chuỗi thức ăn", "ultra_rare", 2, "attack", "chuoi_thuc_an.png",
        "Gây 8 sát thương. Hồi máu bằng toàn bộ sát thương thực tế đòn này gây vào máu đối thủ.",
        [{"op": "attack", "value": 8, "lifesteal_ratio": 1.0}], ["heal", "lifesteal"],
        ["Hút máu: Hồi phục bằng sát thương thực tế trừ vào HP đối thủ; sát thương bị Khiên chặn không được tính."],
    ),
    _card(
        "biology_14_tissue_regeneration", "Tái sinh mô sống", "ultra_rare", 3, "spell", "tai_sinh_mo.png",
        "Trong 2 lượt kế tiếp, toàn bộ lượng máu hồi phục từ mọi nguồn được nhân đôi.",
        [{"op": "set_healing_multiplier", "multiplier": 2, "turns": 2}], ["heal"],
        ["Nhân đôi Hồi Phục: Nhân đôi hồi máu tức thì, Tái tạo và Hút máu trong thời gian hiệu lực."],
    ),
    _card(
        "biology_15_biodiversity", "Đa dạng sinh học", "ultra_rare", 2, "spell", "da_dang_sh.png",
        "Đưa 2 lá mang hiệu ứng Hồi Máu từ tệp bài lên tay. Giảm chi phí của chúng về 0 trong lượt này.",
        [
            {"op": "tutor_by_tag", "tag": "heal", "count": 2, "from": "draw_pile"},
            {"op": "set_cost_for_last_drawn", "cost": 0},
        ], ["heal", "combo_tutor"],
        ["Tìm Kiếm Có Điều Kiện: Rút 2 lá mang nhãn Hồi Máu từ tệp bài và giảm chi phí về 0 trong lượt."],
    ),
    _card(
        "biology_16_homeostasis", "Cân bằng nội môi", "ultra_rare", 2, "spell", "can_bang_noi_moi.png",
        "Tiêu thụ 50% Khiên để hồi máu tương đương. Hóa giải toàn bộ hiệu ứng bất lợi trên người.",
        [
            {"op": "consume_shield_ratio", "ratio": 0.5},
            {"op": "heal_from_consumed_shield"},
            {"op": "cleanse", "target": "player", "category": "debuff"},
        ], ["heal"],
        ["Chuyển hóa Khiên thành Máu: Đổi nửa Khiên đang có thành hồi máu tức thời.", "Thanh lọc: Xóa sạch các hiệu ứng bất lợi đang mắc phải."],
    ),
    _card(
        "biology_17_cellular_respiration", "Hô hấp tế bào", "ultra_rare", 3, "attack", "ho_hap_te_bao.png",
        "Gây 10 sát thương. Nếu máu hiện tại dưới 50%, đòn này gây thêm 8 sát thương và hồi 6 máu.",
        [{"op": "attack", "value": 10, "bonus_if_player_hp_below_ratio": 0.5, "bonus_damage": 8, "bonus_heal": 6}], ["heal"],
        ["Ngưỡng máu nguy hiểm: Tăng sát thương và hồi máu khẩn cấp khi còn dưới nửa máu tối đa."],
    ),
]

for biology_card in BIOLOGY_CARDS:
    biology_card["art_path"] = biology_card["image_url"]