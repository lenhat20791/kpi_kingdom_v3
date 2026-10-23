import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game_logic.biology_cards import BIOLOGY_CARDS
from game_logic.chemistry_cards import CHEMISTRY_CARDS
from game_logic.study_spire import create_battle_state, end_player_turn, play_card
from game_logic.study_spire_pvp import create_pvp_battle_state, end_pvp_turn, play_pvp_card
from game_logic.study_spire_relics import RELIC_CATALOG


def _card(instance_id, card_type, effects, *, cost=0, card_id=None):
    return {
        "instance_id": instance_id,
        "card_id": card_id or instance_id,
        "name": instance_id,
        "mana_cost": cost,
        "card_type": card_type,
        "tags": [],
        "effects": effects,
        "exhaust": False,
    }


def _pve_battle(relic_ids=(), *, hp=80, hp_max=80, enemy_hp=200, deck_size=16):
    return create_battle_state(
        [f"c{index}" for index in range(deck_size)],
        {"name": "Target", "hp": enemy_hp, "max_hp": enemy_hp, "attack": 0, "shield": 0},
        player_hp=hp,
        player_hp_max=hp_max,
        seed=17,
        relic_ids=list(relic_ids),
    )


def _pvp_battle(host_cards, guest_cards, *, host_relics=(), guest_relics=()):
    return create_pvp_battle_state(
        1, "host", "Host", host_cards,
        2, "guest", "Guest", guest_cards,
        29, list(host_relics), list(guest_relics),
    )


class StudySpireRelicCombatTests(unittest.TestCase):
    def test_catalog_has_19_unique_relics(self):
        self.assertEqual(len(RELIC_CATALOG), 19)
        self.assertEqual(len({relic["id"] for relic in RELIC_CATALOG}), 19)

    def test_full_relic_loadout_stacks_opening_effects(self):
        relic_ids = [relic["id"] for relic in RELIC_CATALOG]
        battle = _pve_battle(relic_ids)
        player = battle["player"]
        self.assertEqual((player["hp"], player["hp_max"]), (88, 88))
        self.assertEqual(player["shield"], 10)
        self.assertEqual(player["mana"], 5)
        self.assertEqual(len(battle["hand"]), 6)

    def test_relic_01_grants_opening_shield(self):
        self.assertEqual(_pve_battle(["relic_01"])["player"]["shield"], 8)

    def test_relic_02_increases_current_and_max_hp(self):
        battle = _pve_battle(["relic_02"], hp=70, hp_max=80)
        self.assertEqual((battle["player"]["hp"], battle["player"]["hp_max"]), (78, 88))

    def test_relic_03_grants_one_opening_mana(self):
        self.assertEqual(_pve_battle(["relic_03"])["player"]["mana"], 4)

    def test_relic_04_draws_one_opening_card(self):
        self.assertEqual(len(_pve_battle(["relic_04"])["hand"]), 5)

    def test_relic_05_boosts_only_the_first_attack_each_turn(self):
        battle = _pve_battle(["relic_05"])
        battle["hand"] = ["c0", "c1"]
        attack = {"mana_cost": 0, "card_type": "attack", "effects": [{"op": "attack", "value": 8}]}
        battle = play_card(battle, "c0", attack)
        battle = play_card(battle, "c1", attack)
        self.assertEqual(battle["enemy"]["hp"], 182)

    def test_relic_06_reflects_damage_only_once_per_turn_in_pvp(self):
        host_cards = [_card("h1", "attack", [{"op": "attack", "value": 5}]), _card("h2", "attack", [{"op": "attack", "value": 5}])]
        guest_cards = [_card("g1", "spell", [])]
        battle = _pvp_battle(host_cards, guest_cards, guest_relics=["relic_06"])
        battle["players"]["1"]["hand"] = ["h1", "h2"]
        battle = play_pvp_card(battle, 1, "h1")
        battle = play_pvp_card(battle, 1, "h2")
        self.assertEqual(battle["players"]["1"]["stats"]["hp"], 78)

    def test_relic_07_adds_poison_to_a_real_chemistry_card(self):
        card = next(card for card in CHEMISTRY_CARDS if card["card_id"] == "chemistry_01_acid_properties")
        battle = _pve_battle(["relic_07"])
        battle["hand"] = ["acid"]
        battle = play_card(battle, "acid", {
            "card_id": card["card_id"],
            "mana_cost": card["mana_cost"],
            "card_type": card["card_type"],
            "effects": card["effects"],
        })
        poison = next(effect for effect in battle["enemy"]["active_effects"] if effect["type"] == "poison")
        self.assertEqual(poison["stacks"], 4)

    def test_relic_08_grants_shield_at_each_turn_start(self):
        battle = _pve_battle(["relic_08"])
        self.assertEqual(battle["player"]["shield"], 2)
        battle = end_player_turn(battle)
        self.assertEqual(battle["player"]["shield"], 2)

    def test_relic_09_draws_one_card_each_turn(self):
        battle = end_player_turn(_pve_battle(["relic_09"]))
        self.assertEqual(len(battle["hand"]), 5)

    def test_relic_10_grants_one_mana_each_turn(self):
        battle = end_player_turn(_pve_battle(["relic_10"]))
        self.assertEqual(battle["player"]["mana"], 4)

    def test_relic_11_heals_at_turn_start(self):
        battle = _pve_battle(["relic_11"], hp=70)
        battle["player"]["hp"] = 70
        battle = end_player_turn(battle)
        self.assertEqual(battle["player"]["hp"], 72)

    def test_relic_12_heals_once_at_half_health(self):
        battle = end_player_turn(_pve_battle(["relic_12"], hp=40))
        self.assertEqual(battle["player"]["hp"], 50)
        battle["player"]["hp"] = 40
        battle = end_player_turn(battle)
        self.assertEqual(battle["player"]["hp"], 40)

    def test_relic_13_grants_spell_shield_once_per_turn(self):
        battle = _pve_battle(["relic_13"])
        battle["hand"] = ["s1", "s2"]
        spell = {"mana_cost": 0, "card_type": "spell", "effects": []}
        battle = play_card(battle, "s1", spell)
        battle = play_card(battle, "s2", spell)
        self.assertEqual(battle["player"]["shield"], 5)

    def test_relic_14_draws_after_the_first_attack_each_turn(self):
        battle = _pve_battle(["relic_14"])
        battle["hand"] = ["a1", "a2", "s1", "s2"]
        attack = {"mana_cost": 0, "card_type": "attack", "effects": [{"op": "attack", "value": 1}]}
        battle = play_card(battle, "a1", attack)
        self.assertEqual(len(battle["hand"]), 4)
        battle = play_card(battle, "a2", attack)
        self.assertEqual(len(battle["hand"]), 3)

    def test_relic_15_converts_unused_mana_to_next_turn_shield_in_pvp(self):
        host_cards = [_card("h1", "spell", [])]
        guest_cards = [_card("g1", "spell", [])]
        battle = _pvp_battle(host_cards, guest_cards, host_relics=["relic_15"])
        battle["players"]["1"]["stats"]["shield"] = 5
        battle = end_pvp_turn(battle, 1)
        self.assertEqual(battle["players"]["1"]["stats"]["shield"], 6)

    def test_relic_16_reduces_hp_damage_once_per_turn_in_pvp(self):
        host_cards = [_card("h1", "attack", [{"op": "attack", "value": 5}]), _card("h2", "attack", [{"op": "attack", "value": 5}])]
        guest_cards = [_card("g1", "spell", [])]
        battle = _pvp_battle(host_cards, guest_cards, guest_relics=["relic_16"])
        battle["players"]["1"]["hand"] = ["h1", "h2"]
        battle = play_pvp_card(battle, 1, "h1")
        battle = play_pvp_card(battle, 1, "h2")
        self.assertEqual(battle["players"]["2"]["stats"]["hp"], 71)

    def test_relic_17_boosts_first_attack_when_health_is_at_half(self):
        battle = _pve_battle(["relic_17"], hp=40)
        battle["hand"] = ["c0"]
        battle = play_card(battle, "c0", {
            "mana_cost": 0,
            "card_type": "attack",
            "effects": [{"op": "attack", "value": 20}],
        })
        self.assertEqual(battle["enemy"]["hp"], 173)

    def test_relic_18_reduces_poison_damage_by_one(self):
        battle = _pve_battle(["relic_18"])
        battle["player"]["active_effects"] = [{"type": "poison", "stacks": 4}]
        battle = end_player_turn(battle)
        self.assertEqual(battle["player"]["hp"], 77)

    def test_relic_19_buffs_the_attack_after_each_third_card(self):
        battle = _pve_battle(["relic_19"])
        battle["hand"] = ["s1", "s2", "a1", "a2"]
        spell = {"mana_cost": 0, "card_type": "spell", "effects": []}
        attack = {"mana_cost": 0, "card_type": "attack", "effects": [{"op": "attack", "value": 10}]}
        battle = play_card(battle, "s1", spell)
        battle = play_card(battle, "s2", spell)
        battle = play_card(battle, "a1", attack)
        self.assertEqual(battle["enemy"]["hp"], 190)
        battle = play_card(battle, "a2", attack)
        self.assertEqual(battle["enemy"]["hp"], 176)

    def test_real_biology_healing_card_combines_with_defensive_relics(self):
        card = next(card for card in BIOLOGY_CARDS if card["card_id"] == "biology_01_photosynthesis")
        battle = _pve_battle(["relic_08", "relic_11"], hp=60)
        battle["player"]["hp"] = 60
        battle["hand"] = ["photosynthesis"]
        battle = play_card(battle, "photosynthesis", {
            "card_id": card["card_id"],
            "mana_cost": card["mana_cost"],
            "card_type": card["card_type"],
            "effects": card["effects"],
        })
        self.assertEqual(battle["player"]["hp"], 65)
        self.assertEqual(battle["player"]["shield"], 6)


if __name__ == "__main__":
    unittest.main()
