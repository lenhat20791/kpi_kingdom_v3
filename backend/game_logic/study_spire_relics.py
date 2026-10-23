"""Study Spire relic catalog and collection helpers."""

from __future__ import annotations

import json
import random
from typing import Any

from sqlmodel import Session, select

from database import StudyPlayerRelic, StudyPvpRelicLoadout


RELIC_CATALOG: tuple[dict[str, Any], ...] = (
    {"id": "relic_01", "name": "Hộ Tâm Thạch", "image": "screenshot_1769737577.png", "description": "Bắt đầu mỗi trận với 8 Khiên.", "effect": {"opening_shield": 8}},
    {"id": "relic_02", "name": "Mạch Sống", "image": "screenshot_1769737595.png", "description": "Tăng 8 HP tối đa khi bắt đầu trận.", "effect": {"bonus_hp": 8}},
    {"id": "relic_03", "name": "Ngọc Khí", "image": "screenshot_1769737604.png", "description": "Nhận thêm 1 Mana trong lượt đầu tiên.", "effect": {"opening_mana": 1}},
    {"id": "relic_04", "name": "Tinh Văn", "image": "screenshot_1769737611.png", "description": "Rút thêm 1 lá khi bắt đầu trận.", "effect": {"opening_draw": 1}},
    {"id": "relic_05", "name": "Long Nha", "image": "screenshot_1769737623.png", "description": "Đòn đánh đầu tiên mỗi lượt gây thêm 25% sát thương.", "effect": {"first_attack_multiplier": 1.25}},
    {"id": "relic_06", "name": "Gai Phản Chấn", "image": "screenshot_1769737631.png", "description": "Một lần mỗi lượt, phản lại 2 sát thương khi bị đánh trúng.", "effect": {"reflect_damage": 2}},
    {"id": "relic_07", "name": "Nọc Độc", "image": "screenshot_1769737641.png", "description": "Lần đầu gây Độc mỗi lượt cộng thêm 1 tầng.", "effect": {"poison_bonus": 1}},
    {"id": "relic_08", "name": "Khiên Hồi Lưu", "image": "screenshot_1769737651.png", "description": "Nhận 2 Khiên khi bắt đầu mỗi lượt.", "effect": {"turn_shield": 2}},
    {"id": "relic_09", "name": "Mắt Bão", "image": "screenshot_1769737659.png", "description": "Rút thêm 1 lá khi bắt đầu mỗi lượt.", "effect": {"turn_draw": 1}},
    {"id": "relic_10", "name": "Tâm Pháp", "image": "screenshot_1769737667.png", "description": "Nhận thêm 1 Mana ở mỗi lượt.", "effect": {"turn_mana": 1}},
    {"id": "relic_11", "name": "Sinh Mộc", "image": "screenshot_1769737675.png", "description": "Hồi 2 HP khi bắt đầu mỗi lượt.", "effect": {"turn_heal": 2}},
    {"id": "relic_12", "name": "Hồi Nguyên", "image": "screenshot_1769737681.png", "description": "Một lần mỗi trận, khi HP còn tối đa một nửa, hồi 10 HP.", "effect": {"emergency_heal": 10}},
    {"id": "relic_13", "name": "Hỏa Ấn", "image": "screenshot_1769737687.png", "description": "Lá không phải đòn đánh đầu tiên mỗi lượt cho thêm 5 Khiên.", "effect": {"spell_shield": 5}},
    {"id": "relic_14", "name": "Ảnh Bộ", "image": "screenshot_1769737693.png", "description": "Đòn đánh đầu tiên mỗi lượt giúp rút thêm 1 lá.", "effect": {"attack_draw": 1}},
    {"id": "relic_15", "name": "Linh Tê", "image": "screenshot_1769737699.png", "description": "Cuối lượt, mỗi Mana chưa dùng đổi thành 2 Khiên, tối đa 6.", "effect": {"unused_mana_shield": 2}},
    {"id": "relic_16", "name": "Thiết Bì", "image": "screenshot_1769737706.png", "description": "Một lần mỗi lượt, giảm 1 sát thương HP nhận từ một lá đối thủ.", "effect": {"damage_reduction": 1}},
    {"id": "relic_17", "name": "Phá Quân", "image": "screenshot_1769737715.png", "description": "Khi HP còn tối đa một nửa, đòn đánh đầu mỗi lượt mạnh hơn 35%.", "effect": {"low_health_attack_multiplier": 1.35}},
    {"id": "relic_18", "name": "Tĩnh Tâm", "image": "screenshot_1769737723.png", "description": "Giảm 1 sát thương Độc nhận vào mỗi lượt.", "effect": {"poison_reduction": 1}},
    {"id": "relic_19", "name": "Tinh Tú", "image": "default.png", "description": "Cứ lá thứ ba được đánh ra trong lượt, đòn đánh kế tiếp mạnh hơn 40%.", "effect": {"third_card_attack_multiplier": 1.4}},
)

RELIC_BY_ID = {relic["id"]: relic for relic in RELIC_CATALOG}
RELIC_IDS = set(RELIC_BY_ID)


def owned_relic_ids(db: Session, player_id: int) -> list[str]:
    rows = db.exec(
        select(StudyPlayerRelic).where(StudyPlayerRelic.player_id == player_id)
    ).all()
    owned = {row.relic_id for row in rows if row.relic_id in RELIC_IDS}
    unclaimed = [relic["id"] for relic in RELIC_CATALOG if relic["id"] not in owned]
    changed = False
    for row in rows:
        if row.relic_id in RELIC_IDS:
            continue
        if unclaimed:
            row.relic_id = unclaimed.pop(0)
            owned.add(row.relic_id)
        else:
            db.delete(row)
        changed = True
    if changed:
        db.flush()
    return sorted(owned)


def pvp_loadout_ids(db: Session, player_id: int) -> list[str]:
    loadout = db.get(StudyPvpRelicLoadout, player_id)
    if loadout is None:
        return []
    try:
        selected = json.loads(loadout.relic_ids_json)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("Loadout relic PvP đã lưu không hợp lệ.") from error
    if not isinstance(selected, list):
        raise ValueError("Loadout relic PvP đã lưu không hợp lệ.")
    owned = set(owned_relic_ids(db, player_id))
    return sorted({relic_id for relic_id in selected if relic_id in owned})


def next_unowned_relic_id(db: Session, player_id: int, rng: random.Random) -> str | None:
    unowned = sorted(RELIC_IDS - set(owned_relic_ids(db, player_id)))
    return rng.choice(unowned) if unowned else None
