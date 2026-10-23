"""Turn-based player-versus-player card combat for Study Spire rooms."""

from __future__ import annotations

import random
from copy import deepcopy
from typing import Any

from game_logic.study_spire import (
    SUDDEN_DEATH_DAMAGE_MULTIPLIER,
    _apply_draw_cost_auras,
    _trigger_relic_emergency_heal,
    _tick_effects,
    apply_relic_battle_start,
    apply_relic_turn_end,
    apply_relic_turn_start,
    draw_cards,
    play_card,
    reduce_relic_poison,
)


def _new_seat(
    player_id: int,
    username: str,
    name: str,
    card_rows: list[dict[str, Any]],
    relic_ids: list[str],
    rng: random.Random,
) -> dict[str, Any]:
    deck = [card["instance_id"] for card in card_rows]
    rng.shuffle(deck)
    draw_pile, discard_pile, hand = draw_cards(deck, [], [], 4, rng=rng)
    stats = {
        "hp": 80,
        "hp_max": 80,
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
        "poison_doubling_turns": 0,
        "stunned_turns": 0,
    }
    extra_draw = apply_relic_battle_start(stats, relic_ids)
    draw_pile, discard_pile, hand = draw_cards(
        draw_pile, discard_pile, hand, extra_draw, rng=rng,
    )
    return {
        "player_id": player_id,
        "username": username,
        "name": name,
        "relic_ids": list(stats["relic_ids"]),
        "stats": stats,
        "draw_pile": draw_pile,
        "discard_pile": discard_pile,
        "exhaust_pile": [],
        "hand": hand,
        "turn_history": [],
        "cost_modifiers": {},
        "draw_cost_auras": [],
    }


def create_pvp_battle_state(
    host_id: int,
    host_username: str,
    host_name: str,
    host_cards: list[dict[str, Any]],
    guest_id: int,
    guest_username: str,
    guest_name: str,
    guest_cards: list[dict[str, Any]],
    seed: int,
    host_relic_ids: list[str] | None = None,
    guest_relic_ids: list[str] | None = None,
) -> dict[str, Any]:
    rng = random.Random(seed)
    card_rows = host_cards + guest_cards
    return {
        "seed": seed,
        "turn_number": 1,
        "active_player_id": host_id,
        "winner_player_id": None,
        "sudden_death": False,
        "log": [],
        "players": {
            str(host_id): _new_seat(host_id, host_username, host_name, host_cards, host_relic_ids or [], rng),
            str(guest_id): _new_seat(guest_id, guest_username, guest_name, guest_cards, guest_relic_ids or [], rng),
        },
        "cards": {
            card["instance_id"]: {key: deepcopy(value) for key, value in card.items() if key != "instance_id"}
            for card in card_rows
        },
        "card_metadata": {
            card["instance_id"]: {
                "card_id": card["card_id"],
                "type": card["card_type"],
                "tags": list(card.get("tags", [])),
                "cost": int(card["mana_cost"]),
            }
            for card in card_rows
        },
    }


def _battle_adapter(state: dict[str, Any], player_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    active = state["players"][str(player_id)]
    opponent_id = next(candidate for candidate in state["players"] if int(candidate) != player_id)
    opponent = state["players"][opponent_id]
    battle = {
        "seed": state["seed"],
        "phase": "PLAYER_TURN",
        "turn_number": state["turn_number"],
        "sudden_death": bool(state.get("sudden_death", False)),
        "player": deepcopy(active["stats"]),
        "enemy": deepcopy(opponent["stats"]),
        "draw_pile": list(active["draw_pile"]),
        "hand": list(active["hand"]),
        "discard_pile": list(active["discard_pile"]),
        "exhaust_pile": list(active["exhaust_pile"]),
        "draw_events": [],
        "turn_history": deepcopy(active["turn_history"]),
        "relic_ids": list(active["stats"].get("relic_ids", [])),
        "relic_usage": deepcopy(active["stats"].get("relic_usage", {})),
        "card_metadata": state["card_metadata"],
        "cost_modifiers": deepcopy(active["cost_modifiers"]),
        "draw_cost_auras": deepcopy(active["draw_cost_auras"]),
        "next_intent": {"type": "attack", "damage": 0},
    }
    return battle, opponent


def play_pvp_card(state: dict[str, Any], player_id: int, instance_id: str) -> dict[str, Any]:
    if int(state["active_player_id"]) != player_id:
        raise ValueError("Chưa đến lượt của bạn.")
    _activate_sudden_death_if_due(state)
    active = state["players"][str(player_id)]
    card = state["cards"].get(instance_id)
    if not card:
        raise ValueError("Không tìm thấy lá bài trong deck PvP.")

    battle, opponent = _battle_adapter(state, player_id)
    updated = play_card(
        battle,
        instance_id,
        {
            "card_id": card["card_id"],
            "mana_cost": card["mana_cost"],
            "card_type": card["card_type"],
            "tags": card.get("tags", []),
            "effects": card.get("effects", []),
            "exhaust": card.get("exhaust", False),
        },
    )
    active["stats"] = updated["player"]
    active["draw_pile"] = updated["draw_pile"]
    active["hand"] = updated["hand"]
    active["discard_pile"] = updated["discard_pile"]
    active["exhaust_pile"] = updated["exhaust_pile"]
    active["turn_history"] = updated["turn_history"]
    active["stats"]["relic_ids"] = updated["player"].get("relic_ids", [])
    active["stats"]["relic_usage"] = updated["player"].get("relic_usage", {})
    active["cost_modifiers"] = updated["cost_modifiers"]
    active["draw_cost_auras"] = updated.get("draw_cost_auras", [])
    opponent["stats"] = updated["enemy"]
    state["log"].append({
        "type": "card_played",
        "player_id": player_id,
        "card_id": card["card_id"],
        "card_name": card["name"],
        "turn_number": state["turn_number"],
    })
    if updated["player"]["hp"] <= 0:
        opponent_id = next(candidate for candidate in state["players"] if int(candidate) != player_id)
        state["winner_player_id"] = int(opponent_id)
    elif updated["enemy"]["hp"] <= 0:
        state["winner_player_id"] = player_id
    return state


def _finish_seat_turn(state: dict[str, Any], player_id: int, opponent_id: int) -> bool:
    seat = state["players"][str(player_id)]
    opponent = state["players"][str(opponent_id)]
    stats = seat["stats"]
    seat["discard_pile"].extend(seat["hand"])
    seat["hand"] = []

    _tick_effects(stats, "regeneration")
    if stats.get("healing_multiplier_turns", 0) > 0:
        stats["healing_multiplier_turns"] -= 1
        if stats["healing_multiplier_turns"] == 0:
            stats["healing_multiplier"] = 1
    if stats["hp"] <= 0:
        state["winner_player_id"] = opponent_id
        return False

    opponent_stats = opponent["stats"]
    poison_damage_multiplier = (
        SUDDEN_DEATH_DAMAGE_MULTIPLIER if state.get("sudden_death") else 1
    )
    reduce_relic_poison(opponent_stats)
    poison_doubles = opponent_stats.get("poison_doubling_turns", 0) > 0
    _tick_effects(
        opponent_stats,
        "poison",
        poison_doubles=poison_doubles,
        damage_multiplier=poison_damage_multiplier,
    )
    if poison_doubles:
        opponent_stats["poison_doubling_turns"] -= 1
    _trigger_relic_emergency_heal(opponent_stats)
    _trigger_relic_emergency_heal(stats)
    if opponent_stats["hp"] <= 0:
        state["winner_player_id"] = player_id
        return False

    if not stats.get("retain_shield", False):
        stats["shield"] = 0
    stats["retain_shield"] = False
    apply_relic_turn_end(stats)
    stats["attack_repeat_aura"] = 0
    stats["healed_this_turn"] = 0
    seat["cost_modifiers"] = {}
    seat["draw_cost_auras"] = []
    seat["turn_history"] = []
    extra_draw = apply_relic_turn_start(stats)

    state["turn_number"] += 1
    _activate_sudden_death_if_due(state)
    rng = random.Random(state["seed"] + state["turn_number"] + player_id)
    seat["draw_pile"], seat["discard_pile"], seat["hand"] = draw_cards(
        seat["draw_pile"], seat["discard_pile"], seat["hand"], 4 + extra_draw, rng=rng,
    )
    return True


def _activate_sudden_death_if_due(state: dict[str, Any]) -> None:
    if state.get("sudden_death") or int(state.get("turn_number", 1)) <= 20:
        return
    state["sudden_death"] = True
    state["log"].append({
        "type": "sudden_death_started",
        "turn_number": int(state["turn_number"]),
    })


def end_pvp_turn(state: dict[str, Any], player_id: int) -> dict[str, Any]:
    if int(state["active_player_id"]) != player_id:
        raise ValueError("Chưa đến lượt của bạn.")
    _activate_sudden_death_if_due(state)
    opponent_id = next(candidate for candidate in state["players"] if int(candidate) != player_id)
    opponent = state["players"][opponent_id]
    if not _finish_seat_turn(state, player_id, int(opponent_id)):
        return state

    if opponent["stats"].get("stunned_turns", 0) > 0:
        opponent["stats"]["stunned_turns"] -= 1
        state["log"].append({"type": "turn_skipped", "player_id": int(opponent_id), "turn_number": state["turn_number"]})
        if not _finish_seat_turn(state, int(opponent_id), player_id):
            return state
        state["active_player_id"] = player_id
    else:
        state["active_player_id"] = int(opponent_id)
    return state