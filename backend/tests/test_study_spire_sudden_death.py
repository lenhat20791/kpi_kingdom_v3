import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game_logic.study_spire_pvp import create_pvp_battle_state, end_pvp_turn, play_pvp_card


def _card(instance_id, card_type, effects):
    return {
        "instance_id": instance_id,
        "card_id": instance_id,
        "name": instance_id,
        "mana_cost": 0,
        "card_type": card_type,
        "tags": [],
        "effects": effects,
        "exhaust": False,
    }


def _battle(host_cards, guest_cards, *, guest_relics=()):
    return create_pvp_battle_state(
        1, "host", "Host", host_cards,
        2, "guest", "Guest", guest_cards,
        11, [], list(guest_relics),
    )


class StudySpireSuddenDeathTests(unittest.TestCase):
    def test_sudden_death_starts_after_twenty_completed_turns_once(self):
        battle = _battle([_card("h", "spell", [])], [_card("g", "spell", [])])

        for _ in range(20):
            battle = end_pvp_turn(battle, int(battle["active_player_id"]))

        self.assertEqual(battle["turn_number"], 21)
        self.assertTrue(battle["sudden_death"])
        started_events = [entry for entry in battle["log"] if entry["type"] == "sudden_death_started"]
        self.assertEqual(len(started_events), 1)
        self.assertEqual(started_events[0]["turn_number"], 21)

        battle = end_pvp_turn(battle, int(battle["active_player_id"]))
        self.assertEqual(
            sum(entry["type"] == "sudden_death_started" for entry in battle["log"]),
            1,
        )

    def test_sudden_death_doubles_attacks_and_opponent_damage_effects(self):
        host_cards = [
            _card("strike", "attack", [{"op": "attack", "value": 8}]),
            _card("poison_burst", "spell", [
                {"op": "damage_from_enemy_poison"},
                {"op": "direct_damage", "value": 4},
                {"op": "consume_enemy_poison_burst", "multiplier": 1.5},
            ]),
        ]
        guest_cards = [_card("guard", "spell", [])]
        battle = _battle(host_cards, guest_cards, guest_relics=["relic_06"])
        battle["sudden_death"] = True
        battle["players"]["1"]["hand"] = ["strike", "poison_burst"]
        battle["players"]["2"]["stats"]["active_effects"] = [
            {"type": "poison", "stacks": 3, "pierce_shield": True},
        ]

        battle = play_pvp_card(battle, 1, "strike")
        self.assertEqual(battle["players"]["2"]["stats"]["hp"], 64)
        self.assertEqual(battle["players"]["1"]["stats"]["hp"], 76)

        battle["players"]["1"]["stats"]["mana"] = 3
        battle = play_pvp_card(battle, 1, "poison_burst")
        self.assertEqual(battle["players"]["2"]["stats"]["hp"], 41)
        self.assertFalse(battle["players"]["2"]["stats"]["active_effects"])

    def test_sudden_death_doubles_poison_tick_damage(self):
        battle = _battle([_card("h", "spell", [])], [_card("g", "spell", [])])
        battle["sudden_death"] = True
        battle["players"]["2"]["stats"]["active_effects"] = [
            {"type": "poison", "stacks": 3, "pierce_shield": True},
        ]

        battle = end_pvp_turn(battle, 1)

        self.assertEqual(battle["players"]["2"]["stats"]["hp"], 74)
        self.assertEqual(battle["players"]["2"]["stats"]["active_effects"][0]["stacks"], 2)


if __name__ == "__main__":
    unittest.main()
