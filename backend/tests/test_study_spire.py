import random
import sys
import unittest
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel, Session, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game_logic.study_spire import (
    ROOM_TYPES,
    ROOM_TYPE_WEIGHTS,
    create_battle_state,
    calculate_damage,
    draw_cards,
    generate_map_graph,
    get_route_options,
    end_player_turn,
    play_card,
    typing_accuracy,
)
from game_logic.physics_cards import PHYSICS_CARDS
from game_logic.chemistry_cards import CHEMISTRY_CARDS
from game_logic.biology_cards import BIOLOGY_CARDS
from database import (
    Player,
    StudyActiveRun,
    StudyActionLedger,
    StudyBattle,
    StudyBattleResolution,
    StudyCardInstance,
    StudyCardTemplate,
    StudyDeck,
    StudyDeckCard,
    StudyPackTemplate,
    StudyPassage,
    StudyPlayerPack,
    StudyPlayerRelic,
    StudyPvpRelicLoadout,
    StudyRunHistory,
    migrate_study_spire_schema,
)


class StudySpireDomainTests(unittest.TestCase):
    def test_additive_study_schema_upgrade_adds_missing_versions(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE studydeck (id INTEGER PRIMARY KEY, player_id INTEGER, name TEXT, updated_at TEXT)")
            connection.exec_driver_sql("CREATE TABLE studyplayerpack (id INTEGER PRIMARY KEY, player_id INTEGER, pack_id TEXT, quantity INTEGER)")
            connection.exec_driver_sql("CREATE TABLE studycardtemplate (card_id TEXT PRIMARY KEY, name TEXT, subject TEXT, rarity TEXT, mana_cost INTEGER, description TEXT, image_url TEXT, effect_json TEXT)")
            connection.exec_driver_sql("CREATE TABLE studybattleresolution (id INTEGER PRIMARY KEY, idempotency_key TEXT UNIQUE, run_id TEXT, battle_id TEXT, result_json TEXT, committed_at TEXT)")
            connection.exec_driver_sql("CREATE TABLE studyactionledger (id INTEGER PRIMARY KEY, idempotency_key TEXT UNIQUE, run_id TEXT, action_type TEXT, result_json TEXT, committed_at TEXT)")

        migrate_study_spire_schema(engine)
        inspector = inspect(engine)
        deck_columns = {column["name"] for column in inspector.get_columns("studydeck")}
        pack_columns = {column["name"] for column in inspector.get_columns("studyplayerpack")}
        card_columns = {column["name"] for column in inspector.get_columns("studycardtemplate")}
        self.assertIn("state_version", deck_columns)
        self.assertIn("state_version", pack_columns)
        self.assertIn("player_id", {column["name"] for column in inspector.get_columns("studybattleresolution")})
        self.assertIn("player_id", {column["name"] for column in inspector.get_columns("studyactionledger")})
        self.assertTrue({"card_type", "tags_json", "effects_json", "exhaust", "is_active"} <= card_columns)
        engine.dispose()

    def test_battle_draws_four_cards_and_card_effects_are_server_deterministic(self):
        battle = create_battle_state(
            [f"card-{index}" for index in range(12)],
            {"name": "Hang quái", "image_url": "/assets/background/hg1.png", "hp": 40, "max_hp": 40, "attack": 6, "shield": 0},
            player_hp=80,
            player_hp_max=80,
            seed=42,
        )
        self.assertEqual(battle["player"]["mana"], 3)
        self.assertEqual(len(battle["hand"]), 4)
        self.assertEqual(battle["next_intent"]["damage"], 6)
        self.assertEqual(battle["enemy"]["name"], "Hang quái")
        self.assertEqual(battle["enemy"]["image_url"], "/assets/background/hg1.png")

        card_id = battle["hand"][0]
        battle = play_card(battle, card_id, {"mana_cost": 1, "effect": {"type": "attack", "value": 7}})
        self.assertEqual(battle["enemy"]["hp"], 33)
        self.assertEqual(battle["player"]["mana"], 2)
        self.assertIn(card_id, battle["discard_pile"])

    def test_relics_apply_to_battle_stats_draw_and_attacks(self):
        battle = create_battle_state(
            [f"card-{index}" for index in range(12)],
            {"name": "Hang quái", "hp": 40, "max_hp": 40, "attack": 0, "shield": 0},
            player_hp=80,
            player_hp_max=80,
            seed=42,
            relic_ids=["relic_01", "relic_02", "relic_03", "relic_04", "relic_08", "relic_09", "relic_10"],
        )
        self.assertEqual(battle["player"]["hp"], 88)
        self.assertEqual(battle["player"]["hp_max"], 88)
        self.assertEqual(battle["player"]["shield"], 10)
        self.assertEqual(battle["player"]["mana"], 5)
        self.assertEqual(len(battle["hand"]), 6)

        attack_battle = create_battle_state(
            [f"card-{index}" for index in range(12)],
            {"hp": 40, "max_hp": 40, "attack": 0, "shield": 0},
            player_hp=80,
            player_hp_max=80,
            seed=42,
            relic_ids=["relic_05"],
        )
        attack_id = attack_battle["hand"][0]
        attack_battle = play_card(
            attack_battle,
            attack_id,
            {"mana_cost": 0, "card_type": "attack", "effect": {"type": "attack", "value": 8}},
        )
        self.assertEqual(attack_battle["enemy"]["hp"], 30)

    def test_relic_reduces_poison_damage_at_turn_end(self):
        battle = create_battle_state(
            [f"card-{index}" for index in range(12)],
            {"hp": 40, "max_hp": 40, "attack": 0, "shield": 0},
            player_hp=80,
            player_hp_max=80,
            seed=9,
            relic_ids=["relic_18"],
        )
        battle["player"]["active_effects"] = [{"type": "poison", "stacks": 4}]
        battle = end_player_turn(battle)
        self.assertEqual(battle["player"]["hp"], 77)

    def test_end_turn_ticks_independent_regeneration_and_resets_shield(self):
        battle = create_battle_state(
            [f"card-{index}" for index in range(12)],
            {"hp": 40, "max_hp": 40, "attack": 5, "shield": 0},
            player_hp=60,
            player_hp_max=80,
            seed=9,
        )
        battle["player"]["shield"] = 7
        battle["player"]["active_effects"] = [
            {"type": "regeneration", "amount": 3, "turns_left": 2},
            {"type": "regeneration", "amount": 6, "turns_left": 3},
        ]

        battle = end_player_turn(battle)
        self.assertEqual(battle["player"]["hp"], 69)
        self.assertEqual(battle["player"]["shield"], 0)
        self.assertEqual(battle["player"]["mana"], 3)
        self.assertEqual(battle["turn_number"], 2)
        self.assertEqual(len(battle["hand"]), 4)
        self.assertEqual([effect["turns_left"] for effect in battle["player"]["active_effects"]], [1, 2])

    def test_poison_ticks_and_decays_without_crossing_zero_health(self):
        battle = create_battle_state(
            [f"card-{index}" for index in range(12)],
            {"hp": 2, "max_hp": 40, "attack": 5, "shield": 0, "active_effects": [{"type": "poison", "stacks": 3}]},
            player_hp=80,
            player_hp_max=80,
            seed=9,
        )

        battle = end_player_turn(battle)
        self.assertEqual(battle["enemy"]["hp"], 0)
        self.assertEqual(battle["phase"], "RESOLVING")
        self.assertEqual(battle["player"]["hp"], 75)

    def test_study_schema_is_isolated_and_ledgers_are_unique(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        tables = [
            Player.__table__,
            StudyCardTemplate.__table__,
            StudyCardInstance.__table__,
            StudyDeck.__table__,
            StudyDeckCard.__table__,
            StudyPackTemplate.__table__,
            StudyPlayerPack.__table__,
            StudyPassage.__table__,
            StudyActiveRun.__table__,
            StudyBattle.__table__,
            StudyBattleResolution.__table__,
            StudyActionLedger.__table__,
            StudyRunHistory.__table__,
            StudyPlayerRelic.__table__,
            StudyPvpRelicLoadout.__table__,
        ]
        SQLModel.metadata.create_all(engine, tables=tables)
        table_names = set(inspect(engine).get_table_names())
        self.assertIn("player", table_names)
        self.assertIn("studyactiverun", table_names)
        self.assertIn("studybattleresolution", table_names)
        self.assertNotIn("inventory", table_names)
        self.assertNotIn("arenamatch", table_names)

        with Session(engine) as session:
            player = Player(username="ledger_owner", password_hash="hash", full_name="Ledger Owner")
            session.add(player)
            session.flush()
            session.add(StudyBattleResolution(
                idempotency_key="run-a_battle-a",
                player_id=player.id,
                run_id="run-a",
                battle_id="battle-a",
                result_json="{}",
            ))
            session.commit()
            session.add(StudyBattleResolution(
                idempotency_key="run-a_battle-a",
                player_id=player.id,
                run_id="run-a",
                battle_id="battle-a",
                result_json="{}",
            ))
            with self.assertRaises(IntegrityError):
                session.commit()
            session.rollback()
        engine.dispose()

    def test_map_is_deterministic_and_has_ten_connected_floors(self):
        graph = generate_map_graph(1729)
        self.assertEqual(graph, generate_map_graph(1729))

        nodes = graph["nodes"]
        self.assertEqual({node["floor"] for node in nodes.values()}, set(range(1, 11)))
        self.assertEqual(len([node for node in nodes.values() if node["floor"] == 1]), 1)
        self.assertEqual(len([node for node in nodes.values() if node["floor"] == 10]), 1)
        self.assertEqual(next(node for node in nodes.values() if node["floor"] == 1)["room_type"], "monster")
        self.assertEqual(next(node for node in nodes.values() if node["floor"] == 10)["room_type"], "boss")

        boss_id = next(node_id for node_id, node in nodes.items() if node["floor"] == 10)
        for node_id, node in nodes.items():
            if node["floor"] < 9:
                self.assertEqual(len(get_route_options(graph, node_id)), 3)
            elif node["floor"] == 9:
                self.assertEqual(get_route_options(graph, node_id), [{"target_node_id": boss_id, "direction": "forward"}])

        reachable = {next(node_id for node_id, node in nodes.items() if node["floor"] == 1)}
        for floor in range(1, 10):
            reachable = {
                option["target_node_id"]
                for node_id in reachable
                for option in get_route_options(graph, node_id)
            }
            self.assertTrue(reachable)
            self.assertTrue(all(nodes[node_id]["floor"] == floor + 1 for node_id in reachable))
        self.assertIn(boss_id, reachable)

    def test_later_stages_have_more_floors_and_stronger_monsters(self):
        from game_logic.study_spire import stage_floor_count, stage_power_multiplier

        self.assertEqual([stage_floor_count(stage) for stage in (1, 2, 5, 6, 20)], [10, 11, 14, 15, 15])
        self.assertGreater(stage_power_multiplier(3), stage_power_multiplier(2))
        for stage in (1, 3, 6):
            graph = generate_map_graph(99, stage)
            final_floor = stage_floor_count(stage)
            self.assertEqual(graph["final_floor"], final_floor)
            self.assertEqual({node["floor"] for node in graph["nodes"].values()}, set(range(1, final_floor + 1)))
            self.assertEqual(graph["nodes"][f"f{final_floor}_boss"]["room_type"], "boss")
            for node_id, node in graph["nodes"].items():
                if 2 <= node["floor"] < final_floor:
                    self.assertEqual(len(get_route_options(graph, node_id)), 3 if node["floor"] < final_floor - 1 else 1)

    def test_map_room_types_follow_requested_route_probabilities(self):
        self.assertEqual(dict(zip(ROOM_TYPES, ROOM_TYPE_WEIGHTS)), {
            "monster": 40,
            "chest": 10,
            "inn": 15,
            "elite": 10,
            "event": 25,
        })
        counts = {room_type: 0 for room_type in ROOM_TYPES}
        sample_count = 0
        for seed in range(1000):
            graph = generate_map_graph(seed)
            for node in graph["nodes"].values():
                if 2 <= node["floor"] <= 9:
                    counts[node["room_type"]] += 1
                    sample_count += 1

        for room_type, weight in zip(ROOM_TYPES, ROOM_TYPE_WEIGHTS):
            expected_count = sample_count * weight / 100
            self.assertLess(abs(counts[room_type] - expected_count), sample_count * 0.015)

    def test_damage_consumes_shield_before_health(self):
        self.assertEqual(calculate_damage(80, 7, 10), {"hp": 77, "shield": 0})
        self.assertEqual(calculate_damage(80, 7, 3), {"hp": 80, "shield": 4})
        self.assertEqual(calculate_damage(0, 0, 99), {"hp": 0, "shield": 0})

    def test_draw_cards_shuffles_discard_and_respects_hand_limit(self):
        draw_pile, discard_pile, hand = draw_cards(
            draw_pile=["c1"],
            discard_pile=["c2", "c3"],
            hand=["c4"] * 9,
            count=4,
            rng=random.Random(4),
        )
        self.assertEqual(len(hand), 10)
        self.assertEqual(draw_pile, [])
        self.assertEqual(set(discard_pile), {"c2", "c3"})

    def test_physics_card_catalog_has_seventeen_contiguous_ids_and_vietnamese_fields(self):
        self.assertEqual(len(PHYSICS_CARDS), 17)
        self.assertEqual([card["card_id"].split("_", 2)[1] for card in PHYSICS_CARDS], [f"{index:02d}" for index in range(1, 18)])
        self.assertTrue(all({"id", "name", "cost", "type", "tags", "effects", "art_path"} <= card.keys() for card in PHYSICS_CARDS))
        self.assertTrue(all(card["subject"] == "ly" and card["effects"] and card["art_path"].endswith(".png") for card in PHYSICS_CARDS))
        self.assertEqual(PHYSICS_CARDS[8]["name"], "Mặt phẳng nghiêng")
        self.assertEqual(PHYSICS_CARDS[-1]["name"], "Cơ năng bảo toàn")

    def test_vulnerable_is_flat_and_consumed_by_next_hit(self):
        battle = create_battle_state(
            ["mark", "defense-hit", "strike", "strike-2", "filler"],
            {"hp": 100, "max_hp": 100, "attack": 0},
            player_hp=50,
            player_hp_max=80,
            seed=3,
        )
        battle["hand"] = ["mark", "defense-hit", "strike", "strike-2", "filler"]
        battle = play_card(battle, "mark", {
            "card_id": "physics_01_trong_luc",
            "card_type": "spell",
            "tags": ["vat_ly"],
            "mana_cost": 0,
            "effects": [{"op": "apply_status", "target": "enemy", "status": "vulnerable", "stacks": 2}],
        })
        battle = play_card(battle, "defense-hit", {
            "card_id": "defense_hit", "card_type": "defense", "tags": ["vat_ly"], "mana_cost": 0,
            "effects": [{"op": "attack", "value": 5}],
        })
        self.assertEqual(battle["enemy"]["hp"], 95)
        self.assertEqual(battle["enemy"]["active_effects"], [{"type": "vulnerable", "stacks": 2}])
        battle = play_card(battle, "strike", {
            "card_id": "strike_1", "card_type": "attack", "tags": ["vat_ly"], "mana_cost": 0,
            "effects": [{"op": "attack", "value": 5}],
        })
        self.assertEqual(battle["enemy"]["hp"], 88)
        self.assertFalse(battle["enemy"]["active_effects"])
        battle = play_card(battle, "strike-2", {
            "card_id": "strike_2", "card_type": "attack", "tags": [], "mana_cost": 0,
            "effects": [{"op": "attack", "value": 5}],
        })
        self.assertEqual(battle["enemy"]["hp"], 83)
        battle = play_card(battle, "filler", {
            "card_id": "physics_16_hien_tuong_cong_huong", "card_type": "attack", "tags": ["vat_ly"], "mana_cost": 0,
            "effects": [{"op": "attack", "value": 8, "bonus_per_prior_tag": {"tag": "vat_ly", "value": 4}}],
        })
        self.assertEqual(battle["enemy"]["hp"], 63)

    def test_tutor_cost_override_conditional_shield_and_turn_history(self):
        battle = create_battle_state(
            ["density", "mass", "filler-1", "filler-2", "filler-3"],
            {"hp": 100, "max_hp": 100, "attack": 0},
            player_hp=50,
            player_hp_max=80,
            seed=7,
            card_metadata={
                "density": {"card_id": "physics_03_trong_luong_rieng", "type": "defense", "tags": ["vat_ly"], "cost": 2},
                "mass": {"card_id": "physics_02_khoi_luong_rieng", "type": "defense", "tags": ["vat_ly"], "cost": 2},
            },
        )
        battle["hand"] = ["mass"]
        battle["draw_pile"] = ["density", "filler-1", "filler-2", "filler-3"]
        battle = play_card(battle, "mass", {
            "card_id": "physics_02_khoi_luong_rieng", "card_type": "defense", "tags": ["vat_ly"], "mana_cost": 2,
            "effects": [
                {"op": "gain_shield", "value": 7},
                {"op": "tutor", "card_id": "physics_03_trong_luong_rieng"},
                {"op": "set_cost_modifier", "target_card_id": "physics_03_trong_luong_rieng", "cost": 0},
            ],
        })
        self.assertIn("density", battle["hand"])
        self.assertEqual(battle["cost_modifiers"]["density"]["cost"], 0)
        battle = play_card(battle, "density", {
            "card_id": "physics_03_trong_luong_rieng", "card_type": "defense", "tags": ["vat_ly"], "mana_cost": 2,
            "effects": [
                {"op": "gain_shield", "value": 7},
                {"op": "gain_shield_if_card_played", "card_id": "physics_02_khoi_luong_rieng", "value": 2},
            ],
        })
        self.assertEqual(battle["player"]["shield"], 16)
        self.assertEqual([entry["card_id"] for entry in battle["turn_history"]], ["physics_02_khoi_luong_rieng", "physics_03_trong_luong_rieng"])

    def test_exothermic_reaction_damages_by_enemy_poison_through_enemy_shield(self):
        battle = create_battle_state(
            ["exothermic"],
            {
                "hp": 40,
                "max_hp": 40,
                "attack": 0,
                "shield": 4,
                "active_effects": [{"type": "poison", "stacks": 6}],
            },
            player_hp=80,
            player_hp_max=80,
            seed=11,
        )
        battle["hand"] = ["exothermic"]
        battle["player"]["mana"] = 3

        result = play_card(battle, "exothermic", {
            "card_id": "chemistry_02_exothermic_reaction",
            "card_type": "defense",
            "mana_cost": 1,
            "effects": [
                {"op": "gain_shield", "value": 6},
                {"op": "damage_from_enemy_poison"},
            ],
        })

        self.assertEqual(result["player"]["shield"], 6)
        self.assertEqual(result["enemy"]["shield"], 0)
        self.assertEqual(result["enemy"]["hp"], 38)

    def test_draw_cost_aura_discounts_matching_hand_and_drawn_cards_for_one_turn(self):
        battle = create_battle_state(
            ["ecosystem", "bio-existing", "physics-existing", "draw-card", "bio-drawn"],
            {"hp": 100, "max_hp": 100, "attack": 0},
            player_hp=80,
            player_hp_max=80,
            seed=13,
            card_metadata={
                "ecosystem": {"card_id": "biology_10_ecosystem", "type": "defense", "tags": ["sinh_hoc"], "cost": 1},
                "bio-existing": {"card_id": "biology_01_photosynthesis", "type": "defense", "tags": ["sinh_hoc", "heal"], "cost": 2},
                "physics-existing": {"card_id": "physics_01", "type": "attack", "tags": ["vat_ly"], "cost": 1},
                "draw-card": {"card_id": "draw_card", "type": "spell", "tags": [], "cost": 0},
                "bio-drawn": {"card_id": "biology_02_roots", "type": "attack", "tags": ["sinh_hoc"], "cost": 2},
            },
        )
        battle["hand"] = ["ecosystem", "bio-existing", "physics-existing", "draw-card"]
        battle["draw_pile"] = ["bio-drawn"]

        battle = play_card(battle, "ecosystem", {
            "card_id": "biology_10_ecosystem",
            "card_type": "defense",
            "tags": ["sinh_hoc"],
            "mana_cost": 1,
            "effects": [
                {"op": "gain_shield", "value": 5},
                {"op": "set_draw_cost_aura_by_tag", "tag": "sinh_hoc", "delta": -1, "minimum": 0},
            ],
        })
        self.assertEqual(battle["cost_modifiers"]["bio-existing"]["delta"], -1)
        self.assertNotIn("physics-existing", battle["cost_modifiers"])

        battle = play_card(battle, "draw-card", {
            "card_id": "draw_card", "card_type": "spell", "mana_cost": 0,
            "effects": [{"op": "draw", "count": 1}],
        })
        self.assertIn("bio-drawn", battle["hand"])
        self.assertEqual(battle["cost_modifiers"]["bio-drawn"]["delta"], -1)

        battle = play_card(battle, "bio-existing", {
            "card_id": "biology_01_photosynthesis", "card_type": "defense", "mana_cost": 2, "effects": [],
        })
        self.assertEqual(battle["player"]["mana"], 1)
        battle = end_player_turn(battle)
        self.assertEqual(battle["draw_cost_auras"], [])
        self.assertEqual(battle["cost_modifiers"], {})

    def test_all_three_decks_play_and_resolve_without_unsupported_effects(self):
        cards = PHYSICS_CARDS + CHEMISTRY_CARDS + BIOLOGY_CARDS
        instance_ids = [f"catalog-instance-{index}" for index in range(len(cards))]
        filler_ids = ["catalog-filler-a", "catalog-filler-b"]
        all_instances = [*instance_ids, *filler_ids]
        metadata = {
            instance_id: {
                "card_id": card["card_id"],
                "type": card["card_type"],
                "tags": card.get("tags", []),
                "cost": card["mana_cost"],
            }
            for instance_id, card in zip(instance_ids, cards)
        }
        metadata.update({filler_id: {"card_id": filler_id, "type": "spell", "tags": [], "cost": 1} for filler_id in filler_ids})

        for instance_id, card in zip(instance_ids, cards):
            battle = create_battle_state(
                all_instances,
                {
                    "hp": 1000,
                    "max_hp": 1000,
                    "attack": 0,
                    "shield": 5,
                    "strength": 2,
                    "active_effects": [{"type": "poison", "stacks": 12}],
                },
                player_hp=30,
                player_hp_max=80,
                seed=29,
                card_metadata=metadata,
            )
            battle["hand"] = [instance_id, *filler_ids]
            battle["draw_pile"] = [candidate for candidate in all_instances if candidate not in battle["hand"]]
            battle["player"]["mana"] = 10
            battle["player"]["shield"] = 6
            battle["player"]["healed_this_turn"] = 1
            battle["player"]["active_effects"].append({"type": "regeneration", "amount": 2, "turns_left": 2})
            if card["card_id"] == "chemistry_04_neutralization":
                battle["turn_history"] = [{
                    "card_id": "chemistry_03_base_indicator",
                    "type": "defense",
                    "tags": ["hoa_hoc"],
                }]

            resolved = play_card(battle, instance_id, card)
            self.assertIn(instance_id, resolved["discard_pile"] + resolved["exhaust_pile"], card["card_id"])
            end_player_turn(resolved)

    def test_poison_piercing_doubling_and_stun_mechanics(self):
        battle = create_battle_state(
            ["poison-card"],
            {"hp": 40, "max_hp": 40, "attack": 7, "shield": 10},
            player_hp=80,
            player_hp_max=80,
            seed=19,
        )
        battle["hand"] = ["poison-card"]
        battle["enemy"]["poison_doubling_turns"] = 2
        battle["enemy"]["stunned_turns"] = 1
        battle = play_card(battle, "poison-card", {
            "card_id": "chemistry_01_acid_properties",
            "card_type": "attack",
            "mana_cost": 1,
            "effects": [{"op": "apply_poison", "stacks": 3, "pierce_shield": True}],
        })
        battle = end_player_turn(battle)
        self.assertEqual(battle["player"]["hp"], 80)
        self.assertEqual(battle["enemy"]["hp"], 37)
        self.assertEqual(battle["enemy"]["shield"], 10)
        self.assertEqual(battle["enemy"]["active_effects"][0]["stacks"], 6)
        self.assertEqual(battle["enemy"]["stunned_turns"], 0)
        self.assertEqual(battle["enemy"]["poison_doubling_turns"], 1)

        battle = end_player_turn(battle)
        self.assertEqual(battle["player"]["hp"], 73)
        self.assertEqual(battle["enemy"]["hp"], 31)
        self.assertEqual(battle["enemy"]["active_effects"][0]["stacks"], 12)
        self.assertEqual(battle["enemy"]["poison_doubling_turns"], 0)

    def test_lifesteal_uses_actual_hp_damage_and_low_hp_attack_bonus(self):
        battle = create_battle_state(
            ["lifesteal"],
            {"hp": 40, "max_hp": 40, "attack": 0, "shield": 3},
            player_hp=30,
            player_hp_max=80,
            seed=23,
        )
        battle["hand"] = ["lifesteal"]
        battle["player"]["mana"] = 3
        battle = play_card(battle, "lifesteal", {
            "card_id": "biology_02_water_absorption",
            "card_type": "attack",
            "mana_cost": 1,
            "effects": [{"op": "attack", "value": 6, "lifesteal_ratio": 0.5}],
        })
        self.assertEqual(battle["enemy"]["hp"], 37)
        self.assertEqual(battle["player"]["hp"], 31)
        self.assertEqual(battle["player"]["healed_this_turn"], 1)

        battle = create_battle_state(
            ["respiration"],
            {"hp": 100, "max_hp": 100, "attack": 0, "shield": 0},
            player_hp=39,
            player_hp_max=80,
            seed=24,
        )
        battle["hand"] = ["respiration"]
        battle["player"]["mana"] = 3
        battle = play_card(battle, "respiration", {
            "card_id": "biology_17_cellular_respiration",
            "card_type": "attack",
            "mana_cost": 3,
            "effects": [{"op": "attack", "value": 10, "bonus_if_player_hp_below_ratio": 0.5, "bonus_damage": 8, "bonus_heal": 6}],
        })
        self.assertEqual(battle["enemy"]["hp"], 82)
        self.assertEqual(battle["player"]["hp"], 45)

    def test_regeneration_power_and_healing_multiplier_apply_at_end_turn(self):
        battle = create_battle_state(
            ["regen-buff"],
            {"hp": 100, "max_hp": 100, "attack": 0, "shield": 0},
            player_hp=30,
            player_hp_max=80,
            seed=25,
        )
        battle["hand"] = ["regen-buff"]
        battle["player"]["mana"] = 3
        battle["player"]["active_effects"].append({"type": "regeneration", "amount": 3, "turns_left": 2})
        battle = play_card(battle, "regen-buff", {
            "card_id": "biology_14_tissue_regeneration",
            "card_type": "spell",
            "mana_cost": 3,
            "effects": [{"op": "set_healing_multiplier", "multiplier": 2, "turns": 2}],
        })
        battle["player"]["regen_power"] = 2
        battle = end_player_turn(battle)
        self.assertEqual(battle["player"]["hp"], 40)
        self.assertEqual(battle["player"]["healing_multiplier"], 2)
        self.assertEqual(battle["player"]["healing_multiplier_turns"], 1)

    def test_mana_gain_floor_costs_and_self_damage(self):
        battle = create_battle_state(
            ["pressure", "discounted", "filler"],
            {"hp": 100, "max_hp": 100, "attack": 0},
            player_hp=20,
            player_hp_max=80,
            seed=8,
        )
        battle["hand"] = ["pressure", "discounted"]
        battle = play_card(battle, "pressure", {
            "card_id": "physics_12_ap_suat_chat_long", "card_type": "spell", "tags": ["vat_ly"], "mana_cost": 0,
            "effects": [{"op": "self_damage", "value": 5}, {"op": "gain_mana", "value": 2, "increase_temporary_max": True}],
        })
        self.assertEqual((battle["player"]["hp"], battle["player"]["mana"], battle["player"]["mana_max"]), (15, 5, 5))
        battle["cost_modifiers"]["discounted"] = {"multiplier": 0.5, "minimum": 0}
        battle["player"]["mana"] = 1
        battle = play_card(battle, "discounted", {
            "card_id": "fractional_cost", "card_type": "spell", "mana_cost": 3,
            "effects": [{"op": "gain_shield", "value": 1}],
        })
        self.assertEqual(battle["player"]["mana"], 0)
        self.assertEqual(battle["player"]["shield"], 1)

    def test_shield_retention_and_attack_type_hooks(self):
        battle = create_battle_state(
            ["lens", "defense-hit", "attack-hit", "filler"],
            {"hp": 100, "max_hp": 100, "attack": 3},
            player_hp=50,
            player_hp_max=80,
            seed=11,
        )
        battle["hand"] = ["lens", "defense-hit", "attack-hit"]
        battle = play_card(battle, "lens", {
            "card_id": "lens", "card_type": "spell", "mana_cost": 0,
            "effects": [{"op": "set_attack_repeat_aura", "count": 1}],
        })
        battle = play_card(battle, "defense-hit", {
            "card_id": "defense_hit", "card_type": "defense", "tags": ["vat_ly"], "mana_cost": 0,
            "effects": [{"op": "gain_shield", "value": 4}, {"op": "attack", "value": 5}],
        })
        self.assertEqual(battle["enemy"]["hp"], 95)
        self.assertEqual(battle["player"]["shield"], 4)
        battle = play_card(battle, "attack-hit", {
            "card_id": "attack_hit", "card_type": "attack", "tags": ["vat_ly"], "mana_cost": 0,
            "effects": [{"op": "attack", "value": 5}],
        })
        self.assertEqual(battle["enemy"]["hp"], 85)

        battle["player"]["shield"] = 9
        battle["player"]["retain_shield"] = True
        battle["phase"] = "PLAYER_TURN"
        battle["hand"] = []
        battle["next_intent"] = {"type": "attack", "damage": 3}
        battle = end_player_turn(battle)
        self.assertEqual(battle["player"]["shield"], 6)
        self.assertFalse(battle["player"]["retain_shield"])
        self.assertEqual(battle["turn_history"], [])

        inertia = create_battle_state(
            ["inertia", "filler-1", "filler-2", "filler-3"],
            {"hp": 100, "max_hp": 100, "attack": 1},
            player_hp=50,
            player_hp_max=80,
            seed=12,
        )
        inertia["hand"] = ["inertia"]
        inertia = play_card(inertia, "inertia", {
            "card_id": "physics_10_quan_tinh", "card_type": "defense", "mana_cost": 2,
            "effects": [{"op": "gain_shield", "value": 4}, {"op": "retain_shield_if_no_type_played", "type": "attack"}],
        })
        self.assertTrue(inertia["player"]["retain_shield"])
        inertia = end_player_turn(inertia)
        self.assertEqual(inertia["player"]["shield"], 3)

    def test_discard_hand_draw_reshuffles_and_cleanse_removes_debuffs(self):
        battle = create_battle_state(
            [f"card-{index}" for index in range(10)],
            {"hp": 100, "max_hp": 100, "attack": 0},
            player_hp=50,
            player_hp_max=80,
            seed=13,
        )
        battle["hand"] = ["cycle", "old-1", "old-2"]
        battle["draw_pile"] = ["new-1", "new-2"]
        battle["discard_pile"] = ["old-pile-1", "old-pile-2", "old-pile-3", "old-pile-4"]
        battle = play_card(battle, "cycle", {
            "card_id": "physics_11_truyen_thang_anh_sang", "card_type": "spell", "mana_cost": 0, "exhaust": True,
            "effects": [{"op": "discard_hand", "exclude_played_card": True}, {"op": "draw", "count": 5}],
        })
        self.assertEqual(len(battle["hand"]), 5)
        self.assertIn("cycle", battle["exhaust_pile"])
        self.assertEqual(battle["draw_events"], [{"cause": "card_effect", "card_instance_ids": battle["hand"], "reshuffled": True}])
        all_piles = set(battle["hand"] + battle["draw_pile"] + battle["discard_pile"] + battle["exhaust_pile"])
        self.assertTrue({"old-1", "old-2"} <= all_piles)

        battle["player"]["shield"] = 9
        battle["player"]["active_effects"] = [
            {"type": "poison", "stacks": 2},
            {"type": "vulnerable", "stacks": 1},
            {"type": "regeneration", "amount": 2, "turns_left": 2},
        ]
        battle["hand"] = ["cleanse"]
        battle = play_card(battle, "cleanse", {
            "card_id": "physics_17_co_nang_bao_toan", "card_type": "spell", "mana_cost": 0,
            "effects": [{"op": "consume_all_shield"}, {"op": "cleanse", "target": "player", "category": "debuff"}],
        })
        self.assertEqual(battle["player"]["shield"], 0)
        self.assertEqual(battle["player"]["active_effects"], [{"type": "regeneration", "amount": 2, "turns_left": 2}])

    def test_ohm_buff_charges_only_attack_cards_and_archimedes_floors_costs(self):
        battle = create_battle_state(
            ["ohm", "defense-hit", "attack-1", "attack-2", "archimedes", "attack-3", "spell"],
            {"hp": 100, "max_hp": 100, "attack": 0},
            player_hp=50,
            player_hp_max=80,
            seed=17,
            card_metadata={
                "attack-1": {"card_id": "strike-1", "type": "attack", "tags": ["vat_ly"], "cost": 3},
                "attack-2": {"card_id": "strike-2", "type": "attack", "tags": ["vat_ly"], "cost": 1},
                "attack-3": {"card_id": "strike-3", "type": "attack", "tags": ["vat_ly"], "cost": 4},
                "spell": {"card_id": "spell", "type": "spell", "tags": ["vat_ly"], "cost": 1},
            },
        )
        battle["player"]["shield"] = 5
        battle["hand"] = ["ohm", "defense-hit", "attack-1", "attack-2"]
        battle = play_card(battle, "ohm", {
            "card_id": "physics_13_dinh_luat_ohm", "card_type": "spell", "mana_cost": 3,
            "effects": [
                {"op": "consume_shield_ratio", "ratio": 0.5},
                {"op": "set_attack_damage_modifier", "charges": 2, "multiplier_with_shield": 2, "multiplier_without_shield": 1.5},
            ],
        })
        self.assertEqual(battle["player"]["shield"], 3)
        self.assertEqual(battle["player"]["attack_damage_modifiers"][0]["multiplier"], 2)
        battle = play_card(battle, "defense-hit", {
            "card_id": "defense_hit", "card_type": "defense", "mana_cost": 0,
            "effects": [{"op": "attack", "value": 5}],
        })
        self.assertEqual(battle["enemy"]["hp"], 95)
        self.assertEqual(battle["player"]["attack_damage_modifiers"][0]["charges"], 2)
        battle["player"]["mana"] = 3
        for instance_id in ("attack-1", "attack-2"):
            battle = play_card(battle, instance_id, {
                "card_id": instance_id, "card_type": "attack", "tags": ["vat_ly"], "mana_cost": 0,
                "effects": [{"op": "attack", "value": 4}],
            })
        self.assertEqual(battle["enemy"]["hp"], 79)
        self.assertEqual(battle["player"]["attack_damage_modifiers"], [])

        battle["hand"] = ["archimedes"]
        battle["draw_pile"] = ["attack-3", "spell"]
        battle["player"]["mana"] = 3
        battle = play_card(battle, "archimedes", {
            "card_id": "physics_14_luc_day_ac_si_met", "card_type": "spell", "mana_cost": 1,
            "effects": [
                {"op": "draw_random_by_type", "from": "draw_pile", "card_type": "attack", "count": 2},
                {"op": "modify_cost_for_drawn_cards", "multiplier": 0.5, "rounding": "floor", "minimum": 0},
            ],
        })
        self.assertIn("attack-3", battle["hand"])
        self.assertEqual(battle["cost_modifiers"]["attack-3"]["cost"], 2)

    def test_opening_and_turn_start_draw_events_identify_drawn_cards(self):
        battle = create_battle_state(
            [f"card-{index}" for index in range(8)],
            {"hp": 40, "max_hp": 40, "attack": 0},
            player_hp=60,
            player_hp_max=80,
            seed=29,
        )
        self.assertEqual(battle["draw_events"], [{"cause": "opening_hand", "card_instance_ids": battle["hand"], "reshuffled": False}])
        battle["hand"] = []
        battle["draw_pile"] = []
        battle["discard_pile"] = [f"discard-{index}" for index in range(5)]
        battle = end_player_turn(battle)
        self.assertEqual(len(battle["hand"]), 4)
        self.assertEqual(battle["draw_events"], [{"cause": "turn_start", "card_instance_ids": battle["hand"], "reshuffled": True}])

    def test_typing_accuracy_normalizes_unicode_and_spacing(self):
        self.assertEqual(typing_accuracy("Học tập  tốt", "Học tập tốt"), 1.0)
        self.assertGreaterEqual(typing_accuracy("abcdefghiX", "abcdefghij"), 0.8)
        self.assertLess(typing_accuracy("abc", "abcdefghij"), 0.8)


if __name__ == "__main__":
    unittest.main()