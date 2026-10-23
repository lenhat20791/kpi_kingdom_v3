import random
import math
import unicodedata
from copy import deepcopy
from typing import Any

from game_logic.study_spire_relics import RELIC_BY_ID


SUDDEN_DEATH_DAMAGE_MULTIPLIER = 2


ROOM_TYPES = ("monster", "chest", "inn", "elite", "event")
ROOM_TYPE_WEIGHTS = (40, 10, 15, 10, 25)
DIRECTIONS = ("left", "straight", "right")


BASE_STAGE_FLOORS = 10
MAX_STAGE_FLOORS = 15
STAGE_POWER_STEP = 0.25


def stage_floor_count(stage: int) -> int:
    return min(MAX_STAGE_FLOORS, BASE_STAGE_FLOORS + max(0, int(stage) - 1))


def stage_power_multiplier(stage: int) -> float:
    return 1 + STAGE_POWER_STEP * max(0, int(stage) - 1)


def generate_map_graph(seed: int, stage: int = 1) -> dict[str, Any]:
    rng = random.Random(seed)
    stage = max(1, int(stage))
    final_floor = stage_floor_count(stage)
    boss_id = f"f{final_floor}_boss"
    nodes: dict[str, dict[str, Any]] = {
        "f1_node_1": {"node_id": "f1_node_1", "floor": 1, "room_type": "monster"}
    }

    for floor in range(2, final_floor):
        for index in range(1, 4):
            node_id = f"f{floor}_node_{index}"
            nodes[node_id] = {
                "node_id": node_id,
                "floor": floor,
                "room_type": rng.choices(ROOM_TYPES, weights=ROOM_TYPE_WEIGHTS, k=1)[0],
            }

    nodes[boss_id] = {"node_id": boss_id, "floor": final_floor, "room_type": "boss"}

    edges: list[dict[str, str]] = []
    for floor in range(1, final_floor - 1):
        source_ids = [node_id for node_id, node in nodes.items() if node["floor"] == floor]
        target_ids = [node_id for node_id, node in nodes.items() if node["floor"] == floor + 1]
        for source_id in source_ids:
            for direction, target_id in zip(DIRECTIONS, target_ids):
                edges.append({"from_node_id": source_id, "target_node_id": target_id, "direction": direction})

    pre_boss_ids = [node_id for node_id, node in nodes.items() if node["floor"] == final_floor - 1]
    for source_id in pre_boss_ids:
        edges.append({"from_node_id": source_id, "target_node_id": boss_id, "direction": "forward"})

    return {"seed": seed, "stage": stage, "final_floor": final_floor, "nodes": nodes, "edges": edges}


def get_route_options(graph: dict[str, Any], current_node_id: str) -> list[dict[str, str]]:
    return [
        {"target_node_id": edge["target_node_id"], "direction": edge["direction"]}
        for edge in graph["edges"]
        if edge["from_node_id"] == current_node_id
    ]


def calculate_damage(health: int, shield: int, incoming_damage: int) -> dict[str, int]:
    remaining_damage = max(0, int(incoming_damage))
    current_shield = max(0, int(shield))
    absorbed_damage = min(current_shield, remaining_damage)
    return {
        "hp": max(0, int(health) - (remaining_damage - absorbed_damage)),
        "shield": current_shield - absorbed_damage,
    }


def draw_cards(
    draw_pile: list[str],
    discard_pile: list[str],
    hand: list[str],
    count: int,
    *,
    max_hand: int = 10,
    rng: random.Random | None = None,
) -> tuple[list[str], list[str], list[str]]:
    rng = rng or random.Random()
    draw = list(draw_pile)
    discard = list(discard_pile)
    current_hand = list(hand)

    for _ in range(max(0, count)):
        if len(current_hand) >= max_hand:
            break
        if not draw and discard:
            draw = rng.sample(discard, len(discard))
            discard = []
        if not draw:
            break
        current_hand.append(draw.pop(0))

    return draw, discard, current_hand


def _relic_effects(entity: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        RELIC_BY_ID[relic_id]["effect"]
        for relic_id in entity.get("relic_ids", [])
        if relic_id in RELIC_BY_ID
    ]


def _relic_usage(entity: dict[str, Any]) -> dict[str, Any]:
    usage = entity.setdefault("relic_usage", {})
    usage.setdefault("cards_this_turn", 0)
    usage.setdefault("attacks_this_turn", 0)
    return usage


def apply_relic_battle_start(entity: dict[str, Any], relic_ids: list[str]) -> int:
    entity["relic_ids"] = sorted({relic_id for relic_id in relic_ids if relic_id in RELIC_BY_ID})
    entity["relic_usage"] = {"cards_this_turn": 0, "attacks_this_turn": 0}
    opening_draw = 0
    opening_mana = 0
    for effect in _relic_effects(entity):
        bonus_hp = int(effect.get("bonus_hp", 0))
        entity["hp_max"] = int(entity["hp_max"]) + bonus_hp
        entity["hp"] = min(int(entity["hp_max"]), int(entity["hp"]) + bonus_hp)
        entity["shield"] = int(entity.get("shield", 0)) + int(effect.get("opening_shield", 0))
        opening_mana += int(effect.get("opening_mana", 0))
        opening_draw += int(effect.get("opening_draw", 0))
    extra_draw = apply_relic_turn_start(entity)
    entity["mana"] += opening_mana
    return opening_draw + extra_draw


def apply_relic_turn_start(entity: dict[str, Any]) -> int:
    usage = _relic_usage(entity)
    emergency_used = bool(usage.get("emergency_heal_used"))
    usage.clear()
    usage.update({
        "cards_this_turn": 0,
        "attacks_this_turn": 0,
        "emergency_heal_used": emergency_used,
    })
    turn_mana = 0
    extra_draw = 0
    for effect in _relic_effects(entity):
        entity["shield"] = int(entity.get("shield", 0)) + int(effect.get("turn_shield", 0))
        entity["hp"] = min(
            int(entity.get("hp_max", entity["hp"])),
            int(entity["hp"]) + int(effect.get("turn_heal", 0)),
        )
        turn_mana += int(effect.get("turn_mana", 0))
        extra_draw += int(effect.get("turn_draw", 0))
    entity["mana_max"] = 3 + turn_mana
    entity["mana"] = entity["mana_max"]
    return extra_draw


def apply_relic_turn_end(entity: dict[str, Any]) -> None:
    unused_mana_shield = sum(int(effect.get("unused_mana_shield", 0)) for effect in _relic_effects(entity))
    if unused_mana_shield:
        entity["shield"] = int(entity.get("shield", 0)) + min(6, int(entity.get("mana", 0)) * unused_mana_shield)


def reduce_relic_poison(entity: dict[str, Any]) -> None:
    reduction = sum(int(effect.get("poison_reduction", 0)) for effect in _relic_effects(entity))
    if reduction <= 0:
        return
    effects = []
    for active_effect in entity.get("active_effects", []):
        current = deepcopy(active_effect)
        if current.get("type") == "poison":
            current["stacks"] = max(0, int(current.get("stacks", 0)) - reduction)
            if current["stacks"] == 0:
                continue
        effects.append(current)
    entity["active_effects"] = effects


def _draw_relic_cards(state: dict[str, Any], count: int, seed_offset: int) -> None:
    if count <= 0:
        return
    hand_count = len(state["hand"])
    reshuffled = not state["draw_pile"] and bool(state["discard_pile"])
    state["draw_pile"], state["discard_pile"], state["hand"] = draw_cards(
        state["draw_pile"],
        state["discard_pile"],
        state["hand"],
        count,
        rng=random.Random(int(state["seed"]) + int(state["turn_number"]) + seed_offset),
    )
    drawn = state["hand"][hand_count:]
    if drawn:
        state.setdefault("draw_events", []).append({
            "cause": "relic",
            "card_instance_ids": drawn,
            "reshuffled": reshuffled,
        })


def normalize_study_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", str(value)).casefold()
    return " ".join(normalized.split())


def typing_accuracy(submitted_text: str, expected_text: str) -> float:
    submitted = normalize_study_text(submitted_text)
    expected = normalize_study_text(expected_text)
    if not expected:
        return 0.0
    if submitted == expected:
        return 1.0

    if len(submitted) < len(expected):
        submitted, expected = expected, submitted

    previous_row = list(range(len(expected) + 1))
    for submitted_index, submitted_char in enumerate(submitted, start=1):
        current_row = [submitted_index]
        for expected_index, expected_char in enumerate(expected, start=1):
            insertion = current_row[expected_index - 1] + 1
            deletion = previous_row[expected_index] + 1
            substitution = previous_row[expected_index - 1] + (submitted_char != expected_char)
            current_row.append(min(insertion, deletion, substitution))
        previous_row = current_row

    distance = previous_row[-1]
    return max(0.0, 1.0 - distance / max(len(submitted), len(expected)))


def create_battle_state(
    deck_card_ids: list[str],
    enemy: dict[str, Any],
    *,
    player_hp: int,
    player_hp_max: int,
    seed: int,
    card_metadata: dict[str, dict[str, Any]] | None = None,
    relic_ids: list[str] | None = None,
) -> dict[str, Any]:
    if not deck_card_ids:
        raise ValueError("Bộ bài phải có ít nhất một lá.")

    rng = random.Random(seed)
    draw_pile = list(deck_card_ids)
    rng.shuffle(draw_pile)
    player = {
        "hp": max(0, player_hp),
        "hp_max": max(1, player_hp_max),
        "mana": 3,
        "mana_max": 3,
        "shield": 0,
        "strength": 0,
        "active_effects": [],
        "retain_shield": False,
        "attack_repeat_aura": 0,
        "attack_damage_modifiers": [],
        "healed_this_turn": 0,
        "healing_multiplier": 1,
        "healing_multiplier_turns": 0,
        "regen_power": 0,
    }
    enemy_state = {
        "name": str(enemy.get("name", "Đối thủ")),
        "sprite_set": str(enemy.get("sprite_set", "Rat")),
        "image_url": str(enemy.get("image_url", "")),
        "arena_background": str(enemy.get("arena_background", "")),
        "hp": max(0, int(enemy["hp"])),
        "max_hp": max(1, int(enemy.get("max_hp", enemy["hp"]))),
        "attack": max(0, int(enemy.get("attack", 0))),
        "shield": max(0, int(enemy.get("shield", 0))),
        "strength": max(0, int(enemy.get("strength", 0))),
        "active_effects": deepcopy(enemy.get("active_effects", [])),
        "poison_doubling_turns": 0,
        "strength": max(0, int(enemy.get("strength", 0))),
        "active_effects": deepcopy(enemy.get("active_effects", [])),
        "poison_doubling_turns": 0,
        "stunned_turns": 0,
    }
    draw_pile, discard_pile, hand = draw_cards(draw_pile, [], [], 4, rng=rng)
    relic_draw = apply_relic_battle_start(player, relic_ids or [])
    battle_draw_state = {
        "seed": seed,
        "turn_number": 1,
        "draw_pile": draw_pile,
        "discard_pile": discard_pile,
        "hand": hand,
        "draw_events": [],
    }
    _draw_relic_cards(battle_draw_state, relic_draw, 401)
    draw_pile, discard_pile, hand = (
        battle_draw_state["draw_pile"],
        battle_draw_state["discard_pile"],
        battle_draw_state["hand"],
    )

    return {
        "seed": seed,
        "phase": "PLAYER_TURN",
        "turn_number": 1,
        "player": player,
        "enemy": enemy_state,
        "draw_pile": draw_pile,
        "hand": hand,
        "discard_pile": discard_pile,
        "exhaust_pile": [],
        "draw_events": ([{"cause": "opening_hand", "card_instance_ids": list(hand[:4]), "reshuffled": False}] if hand else []) + battle_draw_state["draw_events"],
        "turn_history": [],
        "card_metadata": deepcopy(card_metadata or {}),
        "cost_modifiers": {},
        "next_intent": {"type": "attack", "damage": enemy_state["attack"]},
    }


def _ensure_battle_fields(state: dict[str, Any]) -> None:
    player = state["player"]
    player.setdefault("mana_max", 3)
    player.setdefault("retain_shield", False)
    player.setdefault("attack_repeat_aura", 0)
    player.setdefault("attack_damage_modifiers", [])
    player.setdefault("healed_this_turn", 0)
    player.setdefault("healing_multiplier", 1)
    player.setdefault("healing_multiplier_turns", 0)
    player.setdefault("regen_power", 0)
    player.setdefault("relic_ids", [])
    player.setdefault("relic_usage", {"cards_this_turn": 0, "attacks_this_turn": 0})
    state.setdefault("turn_history", [])
    state.setdefault("card_metadata", {})
    state.setdefault("cost_modifiers", {})
    state.setdefault("draw_cost_auras", [])
    state["enemy"].setdefault("poison_doubling_turns", 0)
    state["enemy"].setdefault("stunned_turns", 0)


def _card_cost(state: dict[str, Any], card_instance_id: str, base_cost: int) -> int:
    modifier = state.get("cost_modifiers", {}).get(card_instance_id, {})
    if "cost" in modifier:
        return max(0, int(modifier["cost"]))
    multiplier = float(modifier.get("multiplier", 1))
    delta = int(modifier.get("delta", 0))
    minimum = int(modifier.get("minimum", 0))
    return max(minimum, math.floor(base_cost * multiplier) + delta)


def _apply_draw_cost_auras(state: dict[str, Any], instance_ids: list[str]) -> None:
    for instance_id in instance_ids:
        tags = state.get("card_metadata", {}).get(instance_id, {}).get("tags", [])
        for aura in state.get("draw_cost_auras", []):
            if aura["tag"] not in tags:
                continue
            modifier = state["cost_modifiers"].setdefault(instance_id, {})
            modifier["delta"] = int(modifier.get("delta", 0)) + int(aura.get("delta", 0))
            modifier["minimum"] = max(int(modifier.get("minimum", 0)), int(aura.get("minimum", 0)))


def _apply_damage(state: dict[str, Any], target_name: str, damage: int, *, consume_vulnerable: bool = True) -> int:
    target = state[target_name]
    previous_hp = int(target["hp"])
    if not consume_vulnerable:
        target.update(calculate_damage(target["hp"], target["shield"], max(0, damage)))
        return previous_hp - int(target["hp"])
    remaining_effects = []
    vulnerable_stacks = 0
    for active_effect in target.get("active_effects", []):
        if active_effect.get("type") == "vulnerable":
            vulnerable_stacks += max(0, int(active_effect.get("stacks", 0)))
        else:
            remaining_effects.append(active_effect)
    target["active_effects"] = remaining_effects
    target.update(calculate_damage(target["hp"], target["shield"], max(0, damage) + vulnerable_stacks))
    return previous_hp - int(target["hp"])


def _poison_stacks(entity: dict[str, Any]) -> int:
    return sum(
        max(0, int(effect.get("stacks", 0)))
        for effect in entity.get("active_effects", [])
        if effect.get("type") == "poison"
    )


def _apply_poison(entity: dict[str, Any], stacks: int, *, pierce_shield: bool = False) -> None:
    if stacks <= 0:
        return
    existing = next((effect for effect in entity.setdefault("active_effects", []) if effect.get("type") == "poison"), None)
    if existing:
        existing["stacks"] = max(0, int(existing.get("stacks", 0))) + stacks
        existing["pierce_shield"] = bool(existing.get("pierce_shield", False) or pierce_shield)
    else:
        entity["active_effects"].append({"type": "poison", "stacks": stacks, "pierce_shield": pierce_shield})


def _heal_entity(entity: dict[str, Any], amount: int) -> int:
    multiplier = max(0.0, float(entity.get("healing_multiplier", 1)))
    requested = math.floor(max(0, int(amount)) * multiplier)
    previous_hp = int(entity["hp"])
    entity["hp"] = min(int(entity["hp_max"]), previous_hp + requested)
    actual_healing = int(entity["hp"]) - previous_hp
    if "healed_this_turn" in entity:
        entity["healed_this_turn"] += actual_healing
    return actual_healing


def _apply_effect(state: dict[str, Any], effect: dict[str, Any], context: dict[str, Any]) -> None:
    operation = effect.get("op", effect.get("type"))
    value = max(0, int(effect.get("value", effect.get("amount", 0))))
    damage_multiplier = float(context.get("damage_multiplier", 1))
    target_name = effect.get("target", "player" if operation in {"shield", "gain_shield", "gain_shield_if_card_played", "heal", "regeneration", "apply_regeneration", "strength", "gain_strength"} else "enemy")
    target = state.get(target_name)

    if operation in {"attack", "attack_from_shield", "attack_bonus_per_prior_tag"}:
        low_health_bonus = (
            effect.get("bonus_if_player_hp_below_ratio") is not None
            and state["player"]["hp"] < state["player"]["hp_max"] * float(effect["bonus_if_player_hp_below_ratio"])
        )
        if operation == "attack_from_shield":
            base_damage = math.floor(state["player"].get("shield", 0) * float(effect.get("ratio", 0.5)))
        elif operation == "attack_bonus_per_prior_tag":
            tag = effect.get("tag")
            prior_count = sum(tag in entry.get("tags", []) for entry in context["prior_history"])
            base_damage = value * prior_count
        else:
            base_damage = value
            bonus = effect.get("bonus_per_prior_tag")
            if bonus:
                prior_count = sum(bonus.get("tag") in entry.get("tags", []) for entry in context["prior_history"])
                base_damage += int(bonus.get("value", 0)) * prior_count
        if low_health_bonus:
            base_damage += max(0, int(effect.get("bonus_damage", 0)))
        damage = base_damage + int(state["player"].get("strength", 0))
        damage = max(0, math.floor(damage * context.get("attack_multiplier", 1) * damage_multiplier))
        actual_hp_damage = _apply_damage(state, "enemy", damage, consume_vulnerable=context.get("card_type") == "attack")
        lifesteal_ratio = max(0.0, float(effect.get("lifesteal_ratio", 0)))
        if lifesteal_ratio:
            _heal_entity(state["player"], math.floor(actual_hp_damage * lifesteal_ratio))
        if low_health_bonus:
            _heal_entity(state["player"], max(0, int(effect.get("bonus_heal", 0))))
    elif operation in {"shield", "gain_shield"}:
        if target is None:
            raise ValueError("Mục tiêu hiệu ứng không hợp lệ.")
        target["shield"] += value
    elif operation == "gain_shield_if_card_played":
        required_card_id = effect.get("card_id")
        if any(entry.get("card_id") == required_card_id for entry in context["prior_history"]):
            state["player"]["shield"] += value
    elif operation == "damage_from_enemy_poison":
        poison_stacks = _poison_stacks(state["enemy"])
        if poison_stacks:
            _apply_damage(state, "enemy", math.floor(poison_stacks * damage_multiplier), consume_vulnerable=False)
    elif operation in {"strength", "gain_strength"}:
        if target is None:
            raise ValueError("Mục tiêu hiệu ứng không hợp lệ.")
        target["strength"] += value
    elif operation in {"poison", "apply_poison", "apply_status"}:
        if target is None:
            raise ValueError("Mục tiêu hiệu ứng không hợp lệ.")
        status = effect.get("status", "poison" if operation != "apply_status" else "")
        stacks = max(0, int(effect.get("stacks", value)))
        if status not in {"poison", "vulnerable"}:
            raise ValueError("Trạng thái chưa được hỗ trợ.")
        if status == "poison":
            _apply_poison(target, stacks, pierce_shield=bool(effect.get("pierce_shield", False)))
        else:
            existing = next((item for item in target.setdefault("active_effects", []) if item.get("type") == status), None)
            if existing:
                existing["stacks"] = int(existing.get("stacks", 0)) + stacks
            elif stacks:
                target["active_effects"].append({"type": status, "stacks": stacks})
    elif operation in {"heal", "apply_regeneration", "regeneration"}:
        if target is None:
            raise ValueError("Mục tiêu hiệu ứng không hợp lệ.")
        if operation == "heal":
            _heal_entity(target, value)
        else:
            turns = max(0, int(effect.get("turns", 0)))
            if value and turns:
                target.setdefault("active_effects", []).append({"type": "regeneration", "amount": value, "turns_left": turns})
    elif operation == "draw":
        hand_before = len(state["hand"])
        actual_count = min(int(effect.get("count", 0)), max(0, 10 - hand_before))
        reshuffled = actual_count > len(state["draw_pile"]) and bool(state["discard_pile"])
        state["draw_pile"], state["discard_pile"], state["hand"] = draw_cards(
            state["draw_pile"], state["discard_pile"], state["hand"], int(effect.get("count", 0)),
            rng=random.Random(state["seed"] + state["turn_number"] + len(state["turn_history"])),
        )
        drawn_ids = state["hand"][hand_before:]
        if drawn_ids or reshuffled:
            state.setdefault("draw_events", []).append({"cause": effect.get("cause", "card_effect"), "card_instance_ids": drawn_ids, "reshuffled": reshuffled})
        _apply_draw_cost_auras(state, drawn_ids)
    elif operation == "discard_hand":
        state["discard_pile"].extend(state["hand"])
        state["hand"] = []
    elif operation == "self_damage":
        state["player"]["hp"] = max(0, int(state["player"]["hp"]) - value)
    elif operation == "gain_mana":
        player = state["player"]
        player["mana"] += value
        if effect.get("increase_temporary_max"):
            player["mana_max"] += value
    elif operation == "tutor":
        card_id = effect.get("card_id")
        metadata = state["card_metadata"]
        match = next((instance_id for instance_id in state["draw_pile"] if metadata.get(instance_id, {}).get("card_id") == card_id), None)
        if match is not None and len(state["hand"]) < 10:
            state["draw_pile"].remove(match)
            state["hand"].append(match)
            state.setdefault("last_drawn_card_ids", []).append(match)
            state.setdefault("draw_events", []).append({"cause": "tutor", "card_instance_ids": [match], "reshuffled": False})
            _apply_draw_cost_auras(state, [match])
    elif operation == "set_cost_modifier":
        target_card_id = effect.get("target_card_id")
        for instance_id in state["hand"]:
            if state["card_metadata"].get(instance_id, {}).get("card_id") == target_card_id:
                state["cost_modifiers"][instance_id] = {"cost": max(0, int(effect.get("cost", 0)))}
    elif operation == "modify_cost_by_tag":
        tag = effect.get("tag")
        for instance_id in state["hand"]:
            metadata = state["card_metadata"].get(instance_id, {})
            if tag in metadata.get("tags", []):
                current = state["cost_modifiers"].get(instance_id, {})
                current["delta"] = int(current.get("delta", 0)) + int(effect.get("delta", 0))
                current["minimum"] = int(effect.get("minimum", 0))
                state["cost_modifiers"][instance_id] = current
    elif operation == "draw_random_by_type":
        eligible = [
            instance_id for instance_id in state["draw_pile"]
            if state["card_metadata"].get(instance_id, {}).get("type") == effect.get("card_type")
        ]
        rng = random.Random(state["seed"] + state["turn_number"] + len(state["turn_history"]))
        rng.shuffle(eligible)
        drawn = eligible[:min(int(effect.get("count", 0)), 10 - len(state["hand"]))]
        for instance_id in drawn:
            state["draw_pile"].remove(instance_id)
            state["hand"].append(instance_id)
        state["last_drawn_card_ids"] = drawn
        if drawn:
            state.setdefault("draw_events", []).append({"cause": "filtered_draw", "card_instance_ids": drawn, "reshuffled": False})
        _apply_draw_cost_auras(state, drawn)
    elif operation == "modify_cost_for_drawn_cards":
        for instance_id in state.pop("last_drawn_card_ids", []):
            current_cost = _card_cost(state, instance_id, int(state["card_metadata"].get(instance_id, {}).get("cost", 0)))
            state["cost_modifiers"][instance_id] = {
                "cost": max(int(effect.get("minimum", 0)), math.floor(current_cost * float(effect.get("multiplier", 1))))
            }
    elif operation == "set_retain_shield":
        state["player"]["retain_shield"] = bool(effect.get("value", True))
    elif operation == "retain_shield_if_no_type_played":
        card_type = effect.get("type")
        if not any(entry.get("type") == card_type for entry in state["turn_history"]):
            state["player"]["retain_shield"] = True
    elif operation == "consume_shield_ratio":
        player = state["player"]
        previous_shield = int(player.get("shield", 0))
        player["_shield_before_consume"] = previous_shield
        consumed = math.floor(previous_shield * float(effect.get("ratio", 0)))
        player["_shield_consumed"] = consumed
        player["shield"] = max(0, previous_shield - consumed)
    elif operation == "consume_all_shield":
        state["player"]["shield"] = 0
    elif operation == "set_attack_damage_modifier":
        player = state["player"]
        shield_before_consume = int(player.pop("_shield_before_consume", player.get("shield", 0)))
        multiplier = float(effect.get("multiplier_with_shield", 2)) if shield_before_consume else float(effect.get("multiplier_without_shield", 1.5))
        player["attack_damage_modifiers"].append({"charges": int(effect.get("charges", 1)), "multiplier": multiplier})
    elif operation == "set_attack_repeat_aura":
        state["player"]["attack_repeat_aura"] = max(0, int(effect.get("count", 1)))
    elif operation == "set_draw_cost_aura_by_tag":
        state.setdefault("draw_cost_auras", []).append({
            "tag": effect["tag"],
            "delta": int(effect.get("delta", 0)),
            "minimum": int(effect.get("minimum", 0)),
        })
        _apply_draw_cost_auras(state, list(state["hand"]))
    elif operation == "apply_poison_if_enemy_poisoned":
        if _poison_stacks(state["enemy"]) > 0:
            _apply_poison(
                state["enemy"],
                max(0, int(effect.get("stacks", 0))),
                pierce_shield=bool(effect.get("pierce_shield", False)),
            )
    elif operation == "apply_poison_if_card_played":
        if any(entry.get("card_id") == effect.get("card_id") for entry in context["prior_history"]):
            _apply_poison(
                state["enemy"],
                max(0, int(effect.get("stacks", 0))),
                pierce_shield=bool(effect.get("pierce_shield", False)),
            )
    elif operation == "modify_random_cost_by_tag":
        eligible = [
            instance_id for instance_id in state["hand"]
            if effect.get("tag") in state["card_metadata"].get(instance_id, {}).get("tags", [])
        ]
        if eligible:
            rng = random.Random(state["seed"] + state["turn_number"] + len(state["turn_history"]))
            selected_id = rng.choice(eligible)
            modifier = state["cost_modifiers"].setdefault(selected_id, {})
            modifier["delta"] = int(modifier.get("delta", 0)) + int(effect.get("delta", 0))
            modifier["minimum"] = max(int(modifier.get("minimum", 0)), int(effect.get("minimum", 0)))
    elif operation == "convert_enemy_poison_to_shield":
        state["player"]["shield"] += _poison_stacks(state["enemy"])
        state["enemy"]["active_effects"] = [
            active for active in state["enemy"].get("active_effects", [])
            if active.get("type") != "poison"
        ]
    elif operation == "amplify_enemy_poison":
        enemy = state["enemy"]
        poison_effects = [active for active in enemy.get("active_effects", []) if active.get("type") == "poison"]
        poison_stacks = _poison_stacks(enemy)
        if poison_stacks:
            first_poison = poison_effects[0]
            first_poison["stacks"] = math.floor(poison_stacks * float(effect.get("multiplier", 1)))
            first_poison["pierce_shield"] = bool(
                effect.get("pierce_shield", False)
                or any(active.get("pierce_shield", False) for active in poison_effects)
            )
            enemy["active_effects"] = [
                active for active in enemy.get("active_effects", [])
                if active.get("type") != "poison" or active is first_poison
            ]
        else:
            _apply_poison(
                enemy,
                max(0, int(effect.get("fallback_stacks", 0))),
                pierce_shield=bool(effect.get("pierce_shield", False)),
            )
    elif operation == "discard_random_hand":
        discard_count = min(max(0, int(effect.get("count", 0))), len(state["hand"]))
        rng = random.Random(state["seed"] + state["turn_number"] + len(state["turn_history"]))
        discarded = rng.sample(state["hand"], discard_count)
        for instance_id in discarded:
            state["hand"].remove(instance_id)
        state["discard_pile"].extend(discarded)
    elif operation == "retain_shield_if_enemy_poisoned":
        if _poison_stacks(state["enemy"]) > 0:
            state["player"]["retain_shield"] = True
    elif operation == "consume_enemy_poison_burst":
        enemy = state["enemy"]
        poison_stacks = _poison_stacks(enemy)
        enemy["active_effects"] = [
            active for active in enemy.get("active_effects", [])
            if active.get("type") != "poison"
        ]
        burst_damage = math.floor(poison_stacks * float(effect.get("multiplier", 1.5)) * damage_multiplier)
        enemy["hp"] = max(0, int(enemy["hp"]) - burst_damage)
    elif operation == "set_poison_doubling":
        state["enemy"]["poison_doubling_turns"] = max(0, int(effect.get("turns", 0)))
    elif operation == "direct_damage":
        if target is None:
            raise ValueError("Mục tiêu hiệu ứng không hợp lệ.")
        damage = math.floor(value * damage_multiplier) if target_name == "enemy" else value
        target["hp"] = max(0, int(target["hp"]) - damage)
    elif operation == "stun_if_enemy_poison_at_least":
        if _poison_stacks(state["enemy"]) >= max(0, int(effect.get("stacks", 0))):
            state["enemy"]["stunned_turns"] = max(0, int(effect.get("turns", 1)))
    elif operation == "tutor_by_tag":
        tag = effect.get("tag")
        eligible = [
            instance_id for instance_id in state["draw_pile"]
            if tag in state["card_metadata"].get(instance_id, {}).get("tags", [])
        ]
        rng = random.Random(state["seed"] + state["turn_number"] + len(state["turn_history"]))
        rng.shuffle(eligible)
        drawn = eligible[:min(max(0, int(effect.get("count", 0))), max(0, 10 - len(state["hand"]))) ]
        for instance_id in drawn:
            state["draw_pile"].remove(instance_id)
            state["hand"].append(instance_id)
        state["last_drawn_card_ids"] = drawn
        if drawn:
            state.setdefault("draw_events", []).append({"cause": "filtered_tutor", "card_instance_ids": drawn, "reshuffled": False})
            _apply_draw_cost_auras(state, drawn)
    elif operation == "set_cost_for_last_drawn":
        for instance_id in state.pop("last_drawn_card_ids", []):
            state["cost_modifiers"][instance_id] = {"cost": max(0, int(effect.get("cost", 0)))}
    elif operation == "extend_regeneration":
        extra_turns = max(0, int(effect.get("turns", 0)))
        for active in state["player"].get("active_effects", []):
            if active.get("type") == "regeneration":
                active["turns_left"] = max(0, int(active.get("turns_left", 0))) + extra_turns
    elif operation == "increase_regeneration_power":
        state["player"]["regen_power"] += max(0, int(effect.get("value", 0)))
    elif operation == "heal_if_player_has_shield":
        if state["player"].get("shield", 0) > 0:
            _heal_entity(state["player"], value)
    elif operation == "gain_shield_if_full_hp":
        player = state["player"]
        if player["hp"] >= player["hp_max"]:
            player["shield"] += value
    elif operation == "retain_shield_if_healed":
        if state["player"].get("healed_this_turn", 0) > 0:
            state["player"]["retain_shield"] = True
    elif operation == "set_healing_multiplier":
        player = state["player"]
        player["healing_multiplier"] = max(
            float(player.get("healing_multiplier", 1)),
            float(effect.get("multiplier", 1)),
        )
        player["healing_multiplier_turns"] = max(
            int(player.get("healing_multiplier_turns", 0)),
            max(0, int(effect.get("turns", 0))),
        )
    elif operation == "heal_from_consumed_shield":
        player = state["player"]
        consumed = max(0, int(player.pop("_shield_consumed", 0)))
        player.pop("_shield_before_consume", None)
        _heal_entity(player, consumed)
    elif operation == "purge_enemy_buffs":
        enemy = state["enemy"]
        enemy["shield"] = 0
        enemy["strength"] = 0
        beneficial_types = {"strength", "regeneration", "regen", "empower", "might", "fortify"}
        enemy["active_effects"] = [
            active for active in enemy.get("active_effects", [])
            if active.get("category") != "buff" and active.get("type") not in beneficial_types
        ]
    elif operation == "cleanse":
        if target is None:
            raise ValueError("Mục tiêu hiệu ứng không hợp lệ.")
        bad_statuses = {"poison", "vulnerable", "weakness", "weak"}
        target["active_effects"] = [
            active for active in target.get("active_effects", [])
            if active.get("category") != effect.get("category") and active.get("type") not in bad_statuses
        ]
    else:
        raise ValueError("Loại hiệu ứng chưa được hỗ trợ.")


def _trigger_relic_emergency_heal(entity: dict[str, Any]) -> None:
    usage = _relic_usage(entity)
    if usage.get("emergency_heal_used"):
        return
    heal = sum(int(effect.get("emergency_heal", 0)) for effect in _relic_effects(entity))
    if heal and int(entity["hp"]) * 2 <= int(entity.get("hp_max", entity["hp"])):
        entity["hp"] = min(int(entity.get("hp_max", entity["hp"])), int(entity["hp"]) + heal)
        usage["emergency_heal_used"] = True


def _relic_receive_damage(
    target: dict[str, Any],
    attacker: dict[str, Any],
    damage_taken: int,
    hp_lost: int,
    *,
    damage_multiplier: float = 1,
) -> None:
    usage = _relic_usage(target)
    effects = _relic_effects(target)
    if damage_taken > 0:
        reflect = sum(int(effect.get("reflect_damage", 0)) for effect in effects)
        if reflect and not usage.get("reflect_used"):
            attacker["hp"] = max(0, int(attacker["hp"]) - math.floor(reflect * damage_multiplier))
            usage["reflect_used"] = True
    if hp_lost > 0 and not usage.get("damage_reduction_used"):
        reduction = sum(int(effect.get("damage_reduction", 0)) for effect in effects)
        if reduction:
            target["hp"] = min(int(target.get("hp_max", target["hp"])), int(target["hp"]) + min(reduction, hp_lost))
            usage["damage_reduction_used"] = True
    _trigger_relic_emergency_heal(target)


def play_card(
    battle_state: dict[str, Any],
    card_instance_id: str,
    card_template: dict[str, Any],
) -> dict[str, Any]:
    state = deepcopy(battle_state)
    _ensure_battle_fields(state)
    state["draw_events"] = []
    if state["phase"] != "PLAYER_TURN":
        raise ValueError("Hiện không phải lượt người chơi.")
    if card_instance_id not in state["hand"]:
        raise ValueError("Lá bài không có trên tay.")

    legacy_effect = card_template.get("effect", {})
    card_type = card_template.get("card_type", card_template.get("type"))
    if not card_type:
        card_type = "attack" if legacy_effect.get("type") == "attack" else "spell"
    tags = list(card_template.get("tags", []))
    cost = _card_cost(state, card_instance_id, int(card_template.get("mana_cost", 0)))
    if state["player"]["mana"] < cost:
        raise ValueError("Không đủ mana.")

    player = state["player"]
    enemy = state["enemy"]
    usage = _relic_usage(player)
    card_number = int(usage["cards_this_turn"]) + 1
    relic_multiplier = 1.0
    if card_type == "attack":
        for effect in _relic_effects(player):
            if effect.get("first_attack_multiplier") and int(usage["attacks_this_turn"]) == 0:
                relic_multiplier *= float(effect["first_attack_multiplier"])
            if (
                effect.get("low_health_attack_multiplier")
                and int(usage["attacks_this_turn"]) == 0
                and int(player["hp"]) * 2 <= int(player.get("hp_max", player["hp"]))
            ):
                relic_multiplier *= float(effect["low_health_attack_multiplier"])
            if effect.get("third_card_attack_multiplier") and usage.get("boost_next_attack"):
                relic_multiplier *= float(effect["third_card_attack_multiplier"])
    enemy_hp_before = int(enemy["hp"])
    enemy_shield_before = int(enemy.get("shield", 0))
    poison_before = _poison_stacks(enemy)
    state["player"]["mana"] -= cost
    state["hand"].remove(card_instance_id)
    prior_history = deepcopy(state["turn_history"])
    state["turn_history"].append({
        "card_id": card_template.get("card_id", state["card_metadata"].get(card_instance_id, {}).get("card_id", card_instance_id)),
        "instance_id": card_instance_id,
        "type": card_type,
        "tags": tags or state["card_metadata"].get(card_instance_id, {}).get("tags", []),
    })

    effects = card_template.get("effects")
    if effects is None:
        effect_type = legacy_effect.get("type")
        legacy_mapping = {"attack": "attack", "shield": "gain_shield", "strength": "gain_strength", "poison": "apply_poison", "heal": "heal", "regeneration": "apply_regeneration"}
        effects = []
        if effect_type in legacy_mapping:
            effects = [{**{key: value for key, value in legacy_effect.items() if key != "type"}, "op": legacy_mapping[effect_type]}]

    attack_multiplier = 1.0
    if card_type == "attack" and state["player"]["attack_damage_modifiers"]:
        modifier = state["player"]["attack_damage_modifiers"][0]
        attack_multiplier = float(modifier["multiplier"]) * relic_multiplier
        modifier["charges"] -= 1
        if modifier["charges"] <= 0:
            state["player"]["attack_damage_modifiers"].pop(0)
    elif card_type == "attack":
        attack_multiplier = relic_multiplier
    damage_multiplier = SUDDEN_DEATH_DAMAGE_MULTIPLIER if state.get("sudden_death") else 1
    context = {
        "prior_history": prior_history,
        "attack_multiplier": attack_multiplier,
        "card_type": card_type,
        "damage_multiplier": damage_multiplier,
    }
    repeat_count = 1 + (1 if card_type == "attack" and state["player"]["attack_repeat_aura"] else 0)
    for _ in range(repeat_count):
        for effect in effects:
            _apply_effect(state, effect, context)

    target_pile = "exhaust_pile" if card_template.get("exhaust") else "discard_pile"
    state[target_pile].append(card_instance_id)

    updated_player = state["player"]
    updated_enemy = state["enemy"]
    updated_usage = _relic_usage(updated_player)
    updated_usage["cards_this_turn"] = card_number
    if card_type == "attack":
        updated_usage["attacks_this_turn"] = int(updated_usage["attacks_this_turn"]) + 1
        if updated_usage.get("boost_next_attack"):
            updated_usage["boost_next_attack"] = False

        extra_draw = sum(int(effect.get("attack_draw", 0)) for effect in _relic_effects(updated_player))
        if extra_draw and not updated_usage.get("attack_draw_used"):
            _draw_relic_cards(state, extra_draw, 419 + card_number)
            updated_usage["attack_draw_used"] = True
    if card_number % 3 == 0 and any(
        effect.get("third_card_attack_multiplier") for effect in _relic_effects(updated_player)
    ):
        updated_usage["boost_next_attack"] = True

    spell_shield = sum(int(effect.get("spell_shield", 0)) for effect in _relic_effects(updated_player))
    if card_type != "attack" and spell_shield and not updated_usage.get("spell_shield_used"):
        updated_player["shield"] = int(updated_player.get("shield", 0)) + spell_shield
        updated_usage["spell_shield_used"] = True

    poison_bonus = sum(int(effect.get("poison_bonus", 0)) for effect in _relic_effects(updated_player))
    if poison_bonus and _poison_stacks(updated_enemy) > poison_before and not updated_usage.get("poison_bonus_used"):
        poison_effect = next(effect for effect in updated_enemy.get("active_effects", []) if effect.get("type") == "poison")
        poison_effect["stacks"] += poison_bonus
        updated_usage["poison_bonus_used"] = True

    damage_taken = max(0, enemy_hp_before + enemy_shield_before - int(updated_enemy["hp"]) - int(updated_enemy.get("shield", 0)))
    _relic_receive_damage(
        updated_enemy,
        updated_player,
        damage_taken,
        max(0, enemy_hp_before - int(updated_enemy["hp"])),
        damage_multiplier=damage_multiplier,
    )
    _trigger_relic_emergency_heal(updated_player)

    state.pop("last_drawn_card_ids", None)
    if state["enemy"]["hp"] <= 0 or state["player"]["hp"] <= 0:
        state["phase"] = "RESOLVING"
    elif state["phase"] == "RESOLVING":
        state["phase"] = "PLAYER_TURN"
    return state


def _tick_effects(
    entity: dict[str, Any],
    effect_type: str,
    *,
    poison_doubles: bool = False,
    damage_multiplier: float = 1,
) -> None:
    remaining_effects = []
    for effect in entity["active_effects"]:
        current = deepcopy(effect)
        if current["type"] != effect_type:
            remaining_effects.append(current)
            continue

        if effect_type == "poison":
            stacks = max(0, int(current.get("stacks", 0)))
            damage = max(0, math.floor(stacks * damage_multiplier))
            if current.get("pierce_shield"):
                entity["hp"] = max(0, int(entity["hp"]) - damage)
            else:
                entity.update(calculate_damage(entity["hp"], entity["shield"], damage))
            current["stacks"] = stacks * 2 if poison_doubles else max(0, stacks - 1)
            if current["stacks"]:
                remaining_effects.append(current)
        elif effect_type == "regeneration":
            amount = max(0, int(current.get("amount", 0))) + max(0, int(entity.get("regen_power", 0)))
            turns_left = max(0, int(current.get("turns_left", 0)))
            _heal_entity(entity, amount)
            current["turns_left"] = max(0, turns_left - 1)
            if current["turns_left"]:
                remaining_effects.append(current)

    entity["active_effects"] = remaining_effects


def end_player_turn(battle_state: dict[str, Any]) -> dict[str, Any]:
    state = deepcopy(battle_state)
    _ensure_battle_fields(state)
    state["draw_events"] = []
    if state["phase"] != "PLAYER_TURN":
        raise ValueError("Hiện không phải lượt người chơi.")

    apply_relic_turn_end(state["player"])
    state["discard_pile"].extend(state["hand"])
    state["hand"] = []
    _tick_effects(state["player"], "regeneration")
    if state["player"]["healing_multiplier_turns"] > 0:
        state["player"]["healing_multiplier_turns"] -= 1
        if state["player"]["healing_multiplier_turns"] == 0:
            state["player"]["healing_multiplier"] = 1

    if state["player"]["hp"] <= 0:
        state["phase"] = "RESOLVING"
        return state

    intent = state["next_intent"]
    if intent["type"] == "attack":
        if state["enemy"].get("stunned_turns", 0) > 0:
            state["enemy"]["stunned_turns"] -= 1
        else:
            incoming = int(intent["damage"]) + int(state["enemy"].get("strength", 0))
            total_before = int(state["player"]["hp"]) + int(state["player"].get("shield", 0))
            hp_before = int(state["player"]["hp"])
            _apply_damage(state, "player", incoming)
            total_after = int(state["player"]["hp"]) + int(state["player"].get("shield", 0))
            _relic_receive_damage(
                state["player"],
                state["enemy"],
                max(0, total_before - total_after),
                max(0, hp_before - int(state["player"]["hp"])),
            )
    else:
        raise ValueError("Ý định của quái chưa được hỗ trợ.")

    _tick_effects(state["enemy"], "regeneration")
    poison_doubles = state["enemy"].get("poison_doubling_turns", 0) > 0
    _tick_effects(state["enemy"], "poison", poison_doubles=poison_doubles)
    if poison_doubles:
        state["enemy"]["poison_doubling_turns"] -= 1
    reduce_relic_poison(state["player"])
    _tick_effects(state["player"], "poison")
    _trigger_relic_emergency_heal(state["player"])

    if state["player"]["hp"] <= 0 or state["enemy"]["hp"] <= 0:
        state["phase"] = "RESOLVING"
        return state

    if not state["player"].get("retain_shield", False):
        state["player"]["shield"] = 0
    state["player"]["retain_shield"] = False
    state["player"]["mana_max"] = 3
    state["player"]["mana"] = 3
    state["player"]["attack_repeat_aura"] = 0
    state["cost_modifiers"] = {}
    state["draw_cost_auras"] = []
    state["player"]["healed_this_turn"] = 0
    state["turn_history"] = []
    state["turn_number"] += 1
    relic_draw = apply_relic_turn_start(state["player"])
    reshuffled = not state["draw_pile"] and bool(state["discard_pile"])
    state["draw_pile"], state["discard_pile"], state["hand"] = draw_cards(
        state["draw_pile"], state["discard_pile"], state["hand"], 4,
        rng=random.Random(state["seed"] + state["turn_number"]),
    )
    if state["hand"]:
        state["draw_events"].append({"cause": "turn_start", "card_instance_ids": list(state["hand"]), "reshuffled": reshuffled})
    _draw_relic_cards(state, relic_draw, 431)
    state["next_intent"] = {
        "type": "attack",
        "damage": state["enemy"]["attack"],
    }
    return state