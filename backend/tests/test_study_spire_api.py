import sys
import json
import io
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import Player, QuestionBank, StudyActiveRun, StudyBattle, StudyBattleResolution, StudyCardInstance, StudyCardTemplate, StudyDeck, StudyDeckCard, StudyPackTemplate, StudyPassage, StudyPlayerPack, StudyPlayerRelic, StudyRunHistory, StudyActionLedger, get_db
from game_logic.study_spire_relics import RELIC_CATALOG
from routes.auth import get_current_user
from routes import study_game_api
from routes.study_game_api import LEGACY_STARTER_IDS, PACK_RARITY_WEIGHTS, STARTER_CARDS, _battle_enemy, _select_pack_card_id, router
from game_logic.physics_cards import PHYSICS_CARDS
from game_logic.biology_cards import BIOLOGY_CARDS

LEGACY_STARTER_NAMES = [
    "Tia Lý Chính Xác", "Màng Chắn Quang Học", "Tiêu Điểm Hội Tụ", "Quỹ Đạo Vệ Tinh",
    "Dung Dịch Ăn Mòn", "Liên Kết Bền Vững", "Thuốc Tái Tạo", "Phản Ứng Dây Chuyền",
    "Bào Tử Độc", "Vỏ Cây Cứng Cáp",
]


class StudySpireApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            player = Player(username="spire_test", password_hash="hash", full_name="Spire Test")
            session.add(player)
            session.add_all([
                QuestionBank(
                    subject="sinh",
                    difficulty="medium",
                    content=f"Seed question {index}?",
                    options_json=json.dumps(["Correct", "Wrong B", "Wrong C", "Wrong D"]),
                    correct_answer="A",
                    grade=6,
                )
                for index in range(5)
            ])
            session.commit()
            session.refresh(player)
            self.current_user = player

        app = FastAPI()
        app.include_router(router)

        def override_get_db():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: self.current_user
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_avatar_upload_normalizes_and_replaces_without_retaining_old_images(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            avatar_directory = Path(temporary_directory)
            with patch.object(study_game_api, "STUDY_AVATAR_DIR", avatar_directory):
                profile = self.client.get("/api/study-spire/profile")
                self.assertEqual(profile.status_code, 200, profile.text)
                self.assertEqual(profile.json()["name"], "Spire Test")
                self.assertIsNone(profile.json()["avatar_url"])

                def image_bytes(color):
                    image = Image.new("RGB", (800, 400), color)
                    output = io.BytesIO()
                    image.save(output, format="PNG")
                    return output.getvalue()

                first = self.client.post(
                    "/api/study-spire/profile/avatar",
                    files={"image": ("avatar.png", image_bytes("red"), "image/png")},
                )
                self.assertEqual(first.status_code, 200, first.text)
                avatar_path = avatar_directory / f"player_{self.current_user.id}.png"
                first_bytes = avatar_path.read_bytes()
                with Image.open(avatar_path) as avatar:
                    self.assertEqual(avatar.size, (512, 512))
                self.assertEqual(list(avatar_directory.iterdir()), [avatar_path])

                second = self.client.post(
                    "/api/study-spire/profile/avatar",
                    files={"image": ("avatar.png", image_bytes("blue"), "image/png")},
                )
                self.assertEqual(second.status_code, 200, second.text)
                second_bytes = avatar_path.read_bytes()
                self.assertNotEqual(second_bytes, first_bytes)
                self.assertEqual(list(avatar_directory.iterdir()), [avatar_path])

                invalid = self.client.post(
                    "/api/study-spire/profile/avatar",
                    files={"image": ("avatar.png", b"not an image", "image/png")},
                )
                self.assertEqual(invalid.status_code, 400)
                self.assertEqual(avatar_path.read_bytes(), second_bytes)

    def test_profile_display_name_includes_imported_class(self):
        self.current_user.class_name = "6.2"

        profile = self.client.get("/api/study-spire/profile")

        self.assertEqual(profile.status_code, 200, profile.text)
        self.assertEqual(profile.json()["name"], "Spire Test 6.2")

    def test_start_run_is_idempotent_and_creates_starter_deck_once(self):
        response = self.client.post(
            "/api/study-spire/run/start",
            json={"grade": 6, "idempotency_key": "start-test-run"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        first_result = response.json()
        self.assertEqual(first_result["run_status"], "IN_NODE")
        self.assertEqual(first_result["current_floor"], 1)
        self.assertEqual(first_result["battle"]["phase"], "PLAYER_TURN")
        self.assertEqual(len(first_result["battle"]["hand"]), 4)
        self.assertIn(first_result["battle"]["enemy"]["sprite_set"], {"Bat", "Mimic", "Rat", "Slime"})
        resumed = self.client.get("/api/study-spire/run/active")
        self.assertEqual(resumed.status_code, 200, resumed.text)
        self.assertEqual(resumed.json()["run"]["run_id"], first_result["run_id"])

        retry = self.client.post(
            "/api/study-spire/run/start",
            json={"grade": 6, "idempotency_key": "start-test-run"},
        )
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json()["run_id"], first_result["run_id"])

        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(StudyActiveRun)).all()), 1)
            self.assertEqual(len(session.exec(select(StudyDeck)).all()), 1)
            self.assertEqual(len(session.exec(select(StudyCardInstance)).all()), 10)
            self.assertEqual(len(session.exec(select(StudyActionLedger)).all()), 1)

        starter_deck = self.client.get("/api/study-spire/deck").json()
        self.assertEqual(starter_deck["minimum_cards"], 10)
        self.assertIsNone(starter_deck["maximum_cards"])
        self.assertFalse(starter_deck["must_remain_full"])
        self.assertEqual(Counter(card["name"] for card in starter_deck["cards"]), Counter({"Quét kiếm": 5, "Chống đỡ": 5}))
        self.assertTrue(all(card["rarity"] == "common" for card in starter_deck["cards"]))
        self.assertEqual(sum(card["image_url"].endswith("kiem.png") for card in starter_deck["cards"]), 5)
        self.assertEqual(sum(card["image_url"].endswith("khien.png") for card in starter_deck["cards"]), 5)

    def test_available_grades_come_from_classroom_json_sources(self):
        catalog = self.client.get("/api/study-spire/catalog")
        self.assertEqual(catalog.status_code, 200, catalog.text)
        self.assertEqual(catalog.json()["available_grades"], [6, 7])

        other_grade = self.client.post("/api/study-spire/run/start", json={
            "grade": 7,
            "idempotency_key": "start-other-grade",
        })
        self.assertEqual(other_grade.status_code, 403)
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(StudyActiveRun)).all()), 0)

    def test_physics_catalog_has_seventeen_cards_and_localized_metadata(self):
        response = self.client.get("/api/study-spire/catalog")
        self.assertEqual(response.status_code, 200, response.text)
        cards = {card["card_id"]: card for card in response.json()["cards"]}
        physics_ids = {card["card_id"] for card in PHYSICS_CARDS}
        self.assertEqual(len(physics_ids), 17)
        self.assertTrue(physics_ids <= cards.keys())
        for card_id in physics_ids:
            self.assertIn(cards[card_id]["type"], {"attack", "defense", "spell"})
            self.assertTrue(cards[card_id]["effects"])
            self.assertTrue(cards[card_id]["description"])
            self.assertTrue(cards[card_id]["type_label_vi"])
        self.assertEqual(cards["physics_09_mat_phang_nghieng"]["name"], "Mặt phẳng nghiêng")
        with Session(self.engine) as session:
            pack = session.get(StudyPackTemplate, "pack_ly")
            self.assertEqual(json.loads(pack.card_pool_json), [card["card_id"] for card in PHYSICS_CARDS])

    def test_biology_effect_tooltips_reach_catalog_and_inventory(self):
        card_definition = next(card for card in BIOLOGY_CARDS if card["card_id"] == "biology_05_organic_nutrients")
        expected_tooltips = card_definition["effect_tooltips"]
        self.assertIn("Tái tạo: Hồi 3 máu ở cuối mỗi lượt, kéo dài trong 3 lượt.", expected_tooltips)

        catalog = self.client.get("/api/study-spire/catalog")
        self.assertEqual(catalog.status_code, 200, catalog.text)
        catalog_card = next(card for card in catalog.json()["cards"] if card["card_id"] == card_definition["card_id"])
        self.assertEqual(catalog_card["effect_tooltips"], expected_tooltips)

        with Session(self.engine) as session:
            session.add(StudyCardInstance(player_id=self.current_user.id, card_id=card_definition["card_id"]))
            session.commit()
        inventory = self.client.get("/api/study-spire/inventory")
        self.assertEqual(inventory.status_code, 200, inventory.text)
        inventory_card = next(card for card in inventory.json()["cards"] if card["card_id"] == card_definition["card_id"])
        self.assertEqual(inventory_card["effect_tooltips"], expected_tooltips)

    def test_elite_enemy_profile_is_stronger_than_normal_enemy(self):
        normal = _battle_enemy(4, 21)
        elite = _battle_enemy(4, 21, elite=True)
        self.assertEqual(elite["sprite_set"], normal["sprite_set"])
        self.assertIn("tinh anh", elite["name"])
        self.assertGreater(elite["hp"], normal["hp"])
        self.assertGreater(elite["attack"], normal["attack"])
        self.assertGreater(elite["shield"], normal["shield"])

    def test_pack_rarity_roll_uses_94_5_1_boundaries_and_missing_tier_fallback(self):
        self.assertEqual(PACK_RARITY_WEIGHTS, (("rare", 94), ("ultra_rare", 5), ("legend", 1)))
        full_pool = ["rare-card", "ultra-card", "legend-card"]
        full_rarities = {"rare-card": "rare", "ultra-card": "UR", "legend-card": "legendary"}
        for roll in (0, 93):
            self.assertEqual(_select_pack_card_id(full_pool, full_rarities, roll), "rare-card")
        for roll in (94, 98):
            self.assertEqual(_select_pack_card_id(full_pool, full_rarities, roll), "ultra-card")
        self.assertEqual(_select_pack_card_id(full_pool, full_rarities, 99), "legend-card")

        current_physics_pool = ["rare-card", "ultra-card"]
        current_rarities = {"rare-card": "rare", "ultra-card": "ultra_rare"}
        self.assertEqual(_select_pack_card_id(current_physics_pool, current_rarities, 99), "ultra-card")

    def test_old_demo_cards_and_packs_are_archived_from_catalog_and_inventory(self):
        self.client.get("/api/study-spire/catalog")
        with Session(self.engine) as session:
            session.add_all([
                StudyCardTemplate(card_id="sinh_growth", name="Sinh Trưởng", subject="sinh", rarity="rare", mana_cost=1, description="demo", image_url="", effect_json="{}"),
                StudyCardTemplate(card_id="ly_orbit", name="Quỹ Đạo Vệ Tinh", subject="ly", rarity="rare", mana_cost=2, description="demo", image_url="", effect_json="{}"),
            ])
            session.flush()
            session.add(StudyCardInstance(player_id=self.current_user.id, card_id="sinh_growth"))
            session.add(StudyPlayerPack(player_id=self.current_user.id, pack_id="pack_hoa", quantity=1))
            session.commit()

        catalog = self.client.get("/api/study-spire/catalog").json()
        inventory = self.client.get("/api/study-spire/inventory").json()
        catalog_ids = {card["card_id"] for card in catalog["cards"]}
        self.assertNotIn("sinh_growth", catalog_ids)
        self.assertNotIn("ly_orbit", catalog_ids)
        self.assertEqual({pack["pack_id"] for pack in catalog["packs"]}, {"pack_ly", "pack_hoa", "pack_sinh"})
        self.assertNotIn("sinh_growth", {card["card_id"] for card in inventory["cards"]})
        self.assertEqual([pack["pack_id"] for pack in inventory["packs"]], ["pack_hoa"])

    def test_archived_cards_needed_by_active_run_are_returned_for_battle_rendering(self):
        self.client.get("/api/study-spire/catalog")
        instance_id = "archived-active-run-card"
        with Session(self.engine) as session:
            session.add(StudyCardTemplate(
                card_id="sinh_growth",
                name="Sinh Trưởng",
                subject="sinh",
                rarity="rare",
                mana_cost=1,
                description="demo",
                image_url="",
                effect_json="{}",
                is_active=False,
            ))
            session.flush()
            session.add(StudyCardInstance(player_id=self.current_user.id, card_id="sinh_growth", instance_id=instance_id))
            session.add(StudyActiveRun(
                player_id=self.current_user.id,
                grade=6,
                player_core_json=json.dumps({"deck_card_instance_ids": [instance_id]}),
            ))
            session.commit()

        inventory = self.client.get("/api/study-spire/inventory")
        self.assertEqual(inventory.status_code, 200, inventory.text)
        archived = next(card for card in inventory.json()["cards"] if card["instance_id"] == instance_id)
        self.assertFalse(archived["is_active"])

    def test_physics_card_play_api_executes_damage_and_vulnerable_effects(self):
        started = self.client.post("/api/study-spire/run/start", json={
            "grade": 6,
            "idempotency_key": "start-physics-api-test",
        })
        self.assertEqual(started.status_code, 200, started.text)
        instance_id = "physics-api-instance"
        card_id = "physics_01_trong_luc"
        with Session(self.engine) as session:
            instance = StudyCardInstance(player_id=self.current_user.id, card_id=card_id, instance_id=instance_id)
            session.add(instance)
            session.flush()
            deck = session.exec(select(StudyDeck).where(StudyDeck.player_id == self.current_user.id)).one()
            position = session.exec(select(StudyDeckCard.position).where(StudyDeckCard.deck_id == deck.id)).all()
            session.add(StudyDeckCard(deck_id=deck.id, card_instance_id=instance_id, position=max(position) + 1))

            run = session.exec(select(StudyActiveRun).where(StudyActiveRun.player_id == self.current_user.id)).one()
            core = json.loads(run.player_core_json)
            core["deck_card_instance_ids"].append(instance_id)
            run.player_core_json = json.dumps(core)
            battle = session.exec(select(StudyBattle).where(StudyBattle.run_id == run.run_id)).one()
            battle_state = json.loads(battle.battle_state_json)
            battle_state["hand"] = [instance_id]
            battle_state["player"]["mana"] = 3
            battle_state["enemy"]["hp"] = 100
            battle_state["enemy"]["max_hp"] = 100
            battle_state["enemy"]["shield"] = 0
            battle.battle_state_json = json.dumps(battle_state)
            session.commit()

        played = self.client.post("/api/study-spire/battle/play-card", json={
            "card_instance_id": instance_id,
            "expected_state_version": started.json()["state_version"],
            "idempotency_key": "play-physics-gravity",
        })
        self.assertEqual(played.status_code, 200, played.text)
        self.assertEqual(played.json()["battle"]["enemy"]["hp"], 92)
        self.assertEqual(played.json()["battle"]["enemy"]["active_effects"], [{"type": "vulnerable", "stacks": 1}])

    def test_third_copy_stays_in_inventory_and_cannot_be_saved_into_deck(self):
        deck = self.client.get("/api/study-spire/deck").json()
        self.client.get("/api/study-spire/catalog")
        card_id = "physics_01_trong_luc"
        instance_ids = [f"physics-copy-{index}" for index in range(3)]
        instances = [
            StudyCardInstance(player_id=self.current_user.id, card_id=card_id, instance_id=instance_id)
            for instance_id in instance_ids
        ]
        with Session(self.engine) as session:
            session.add_all(instances)
            session.flush()
            current_deck = session.exec(select(StudyDeck).where(StudyDeck.player_id == self.current_user.id)).one()
            session.add_all([
                StudyDeckCard(deck_id=current_deck.id, card_instance_id=instance.instance_id, position=10 + index)
                for index, instance in enumerate(instances[:2])
            ])
            session.commit()

        transfer = self.client.post("/api/study-spire/deck/add-earned", json={
            "instance_id": instance_ids[2],
            "expected_state_version": deck["state_version"],
            "idempotency_key": "claim-third-physics-copy",
        })
        self.assertEqual(transfer.status_code, 200, transfer.text)
        self.assertFalse(transfer.json()["added_to_deck"])
        inventory = self.client.get("/api/study-spire/inventory").json()
        third_copy = next(card for card in inventory["cards"] if card["instance_id"] == instance_ids[2])
        self.assertFalse(third_copy["in_deck"])

        invalid_save = self.client.put("/api/study-spire/deck", json={
            "expected_state_version": deck["state_version"],
            "idempotency_key": "force-three-physics-copies",
            "card_instance_ids": [card["instance_id"] for card in deck["cards"]] + instance_ids,
        })
        self.assertEqual(invalid_save.status_code, 422)

    def _insert_legacy_starter(self, include_active_run=False):
        self.client.get("/api/study-spire/catalog")
        with Session(self.engine) as session:
            session.add_all([
                StudyCardTemplate(
                    card_id=card_id,
                    name=name,
                    subject="legacy",
                    rarity="common",
                    mana_cost=1,
                    description="",
                    image_url="",
                    effect_json="{}",
                    is_active=False,
                )
                for card_id, name in zip(LEGACY_STARTER_IDS, LEGACY_STARTER_NAMES)
            ])
            session.flush()
            deck = StudyDeck(player_id=self.current_user.id, state_version=1, starter_version=3)
            session.add(deck)
            session.flush()
            instances = [
                StudyCardInstance(player_id=self.current_user.id, card_id=card_id)
                for card_id in LEGACY_STARTER_IDS
            ]
            session.add_all(instances)
            session.flush()
            session.add_all([
                StudyDeckCard(deck_id=deck.id, card_instance_id=instance.instance_id, position=index)
                for index, instance in enumerate(instances)
            ])
            if include_active_run:
                run = StudyActiveRun(player_id=self.current_user.id, grade=6)
                session.add(run)
                session.flush()
                session.add(StudyBattle(
                    run_id=run.run_id,
                    battle_state_json=json.dumps({"seed": 41, "hand": ["held-card"], "draw_pile": ["draw-card"]}),
                ))
            session.commit()

    def test_untouched_legacy_starter_upgrades_only_without_active_run(self):
        self._insert_legacy_starter()
        response = self.client.get("/api/study-spire/deck")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(Counter(card["name"] for card in response.json()["cards"]), Counter({"Quét kiếm": 5, "Chống đỡ": 5}))

    def test_legacy_starter_is_preserved_during_active_run(self):
        self._insert_legacy_starter(include_active_run=True)
        response = self.client.get("/api/study-spire/deck")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["cards"], [])
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(StudyDeckCard)).all()), 10)
            active_run = session.exec(select(StudyActiveRun)).one()
            core = json.loads(active_run.player_core_json)
            self.assertEqual(core, {})
            battle = session.exec(select(StudyBattle).where(StudyBattle.run_id == active_run.run_id)).one()
            battle_state = json.loads(battle.battle_state_json)
            self.assertEqual(battle_state["hand"], ["held-card"])
            self.assertEqual(battle_state["draw_pile"][0], "draw-card")
            self.assertEqual(battle_state["draw_pile"], ["draw-card"])

    def test_accidental_twenty_card_default_is_reduced_without_deleting_owned_cards(self):
        self.client.get("/api/study-spire/catalog")
        with Session(self.engine) as session:
            deck = StudyDeck(player_id=self.current_user.id, state_version=1, starter_version=4)
            session.add(deck)
            session.flush()
            card_ids = [STARTER_CARDS[0]["card_id"]] * 10 + [STARTER_CARDS[1]["card_id"]] * 10
            instances = [StudyCardInstance(player_id=self.current_user.id, card_id=card_id) for card_id in card_ids]
            session.add_all(instances)
            session.flush()
            session.add_all([
                StudyDeckCard(deck_id=deck.id, card_instance_id=instance.instance_id, position=index)
                for index, instance in enumerate(instances)
            ])
            session.commit()

        response = self.client.get("/api/study-spire/deck")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(Counter(card["name"] for card in response.json()["cards"]), Counter({"Quét kiếm": 5, "Chống đỡ": 5}))
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(StudyCardInstance)).all()), 20)
            self.assertEqual(len(session.exec(select(StudyDeckCard)).all()), 10)

    def test_battle_resolution_is_atomic_and_duplicate_returns_saved_result(self):
        started = self.client.post(
            "/api/study-spire/run/start",
            json={"grade": 6, "idempotency_key": "start-resolution-test"},
        ).json()
        battle_id = started["battle_id"]
        target_node = started["map_graph"]["edges"][0]["target_node_id"]
        with Session(self.engine) as session:
            run = session.get(StudyActiveRun, started["run_id"])
            graph = json.loads(run.map_graph_json)
            graph["nodes"][target_node]["room_type"] = "monster"
            run.map_graph_json = json.dumps(graph)
            battle = session.exec(select(StudyBattle).where(StudyBattle.battle_id == battle_id)).first()
            state = json.loads(battle.battle_state_json)
            state["enemy"]["hp"] = 0
            state["phase"] = "RESOLVING"
            battle.battle_phase = "RESOLVING"
            battle.battle_state_json = json.dumps(state)
            session.add(battle)
            session.commit()

        idempotency_key = f"{started['run_id']}_{battle_id}"
        payload = {"expected_state_version": started["state_version"], "idempotency_key": idempotency_key}
        first = self.client.post("/api/study-spire/battle/resolve", json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        first_result = first.json()
        self.assertEqual(first_result["run_status"], "CHOOSING_ROUTE")
        self.assertEqual(len(first_result["pending_pack_choices"]), 1)
        self.assertIn(first_result["pending_pack_choices"][0], {"pack_ly", "pack_hoa", "pack_sinh"})

        retry = self.client.post("/api/study-spire/battle/resolve", json=payload)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json(), first_result)

        with Session(self.engine) as session:
            player = session.get(Player, self.current_user.id)
            active_run = session.exec(select(StudyActiveRun)).one()
            self.assertEqual(int(player.tri_thuc or 0), 0)
            self.assertEqual(active_run.run_status, "CHOOSING_ROUTE")
            self.assertEqual(len(session.exec(select(StudyBattleResolution)).all()), 1)

        blocked_route = self.client.post("/api/study-spire/route/select", json={
            "expected_state_version": first_result["state_version"],
            "idempotency_key": "route-before-pack",
            "target_node_id": target_node,
        })
        self.assertEqual(blocked_route.status_code, 409)

        claimed = self.client.post("/api/study-spire/pack/claim", json={
            "expected_state_version": first_result["state_version"],
            "idempotency_key": "claim-reward-pack",
            "chosen_pack_id": first_result["pending_pack_choices"][0],
        })
        self.assertEqual(claimed.status_code, 200, claimed.text)
        self.assertEqual(claimed.json()["claimed_pack"]["quantity"], 1)

        selected = self.client.post("/api/study-spire/route/select", json={
            "expected_state_version": claimed.json()["state_version"],
            "idempotency_key": "select-floor-two",
            "target_node_id": target_node,
        })
        self.assertEqual(selected.status_code, 200, selected.text)
        self.assertEqual(selected.json()["current_node_id"], target_node)
        self.assertEqual(selected.json()["run_status"], "IN_NODE")
        self.assertEqual(len(selected.json()["battle"]["hand"]), 4)
        self.assertIn(selected.json()["battle"]["enemy"]["sprite_set"], {"Bat", "Mimic", "Rat", "Slime"})

    def test_inn_retries_lock_correct_answers_and_forfeit_reward(self):
        started = self.client.post(
            "/api/study-spire/run/start",
            json={"grade": 6, "idempotency_key": "start-inn-test"},
        ).json()
        question_ids = []
        with Session(self.engine) as session:
            for index in range(5):
                question = QuestionBank(
                    subject="sinh",
                    difficulty="medium",
                    content=f"Câu hỏi {index + 1}?",
                    options_json=json.dumps(["Sai A", "Đúng", "Sai C", "Sai D"]),
                    correct_answer="B",
                    grade=6,
                )
                session.add(question)
                session.flush()
                question_ids.append(question.id)

            run = session.get(StudyActiveRun, started["run_id"])
            graph = json.loads(run.map_graph_json)
            graph["nodes"]["f2_node_1"]["room_type"] = "inn"
            run.map_graph_json = json.dumps(graph)
            run.run_status = "IN_NODE"
            run.current_floor = 2
            run.current_node_id = "f2_node_1"
            run.history_path_json = json.dumps(["f1_node_1"])
            run.player_core_json = json.dumps({"hp": 50, "hp_max": 80, "knowledge_earned": 12, "deck_card_instance_ids": []})
            run.room_state_json = json.dumps({"challenge_type": "quiz", "question_ids": question_ids})
            session.add(run)
            session.commit()

        challenge = self.client.get("/api/study-spire/node/challenge")
        self.assertEqual(challenge.status_code, 200, challenge.text)
        self.assertEqual(challenge.json()["required_correct"], 5)
        self.assertTrue(all("correct_answer" not in question for question in challenge.json()["questions"]))
        self.assertFalse(challenge.json()["reward_forfeited"])
        self.assertEqual(challenge.json()["retry_feedback"], [])

        incomplete = self.client.post("/api/study-spire/node/complete", json={
            "expected_state_version": 1,
            "idempotency_key": "inn-incomplete-attempt",
            "answers": {},
        })
        self.assertFalse(incomplete.json()["completed"])
        self.assertNotIn("retry_required", incomplete.json())
        self.assertFalse(self.client.get("/api/study-spire/node/challenge").json()["reward_forfeited"])

        wrong = self.client.post("/api/study-spire/node/complete", json={
            "expected_state_version": 1,
            "idempotency_key": "inn-wrong-attempt",
            "answers": {str(question_id): "B" if index == 0 else "A" for index, question_id in enumerate(question_ids)},
        })
        self.assertFalse(wrong.json()["completed"])
        self.assertTrue(wrong.json()["retry_required"])
        self.assertTrue(wrong.json()["reward_forfeited"])
        self.assertEqual(wrong.json()["state_version"], 2)
        self.assertEqual(wrong.json()["feedback"][0]["is_correct"], True)
        self.assertEqual(wrong.json()["feedback"][1]["is_correct"], False)
        self.assertEqual(wrong.json()["feedback"][1]["correct_answer"], "Đúng")
        self.assertEqual(wrong.json()["locked_answers"], {str(question_ids[0]): "B"})
        self.assertEqual(self.client.post("/api/study-spire/node/complete", json={
            "expected_state_version": 1,
            "idempotency_key": "inn-wrong-attempt",
            "answers": {str(question_id): "B" if index == 0 else "A" for index, question_id in enumerate(question_ids)},
        }).json(), wrong.json())

        retry_challenge = self.client.get("/api/study-spire/node/challenge").json()
        self.assertTrue(retry_challenge["reward_forfeited"])
        self.assertEqual(retry_challenge["locked_answers"], {str(question_ids[0]): "B"})
        self.assertEqual(retry_challenge["retry_feedback"], wrong.json()["feedback"])

        second_wrong = self.client.post("/api/study-spire/node/complete", json={
            "expected_state_version": 2,
            "idempotency_key": "inn-second-wrong-attempt",
            "answers": {str(question_id): "A" for question_id in question_ids},
        })
        self.assertFalse(second_wrong.json()["completed"])
        self.assertEqual(second_wrong.json()["state_version"], 3)
        self.assertTrue(second_wrong.json()["feedback"][0]["is_correct"])
        self.assertEqual(second_wrong.json()["locked_answers"], {str(question_ids[0]): "B"})

        completed = self.client.post("/api/study-spire/node/complete", json={
            "expected_state_version": 3,
            "idempotency_key": "inn-correct-attempt",
            "answers": {str(question_id): "B" for question_id in question_ids},
        })
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertTrue(completed.json()["completed"])
        self.assertTrue(completed.json()["reward_forfeited"])
        self.assertEqual(completed.json()["reward"], {})
        self.assertEqual(completed.json()["player_core"]["hp"], 50)
        self.assertEqual(completed.json()["history_path"][-1], "f2_node_1")

    def test_inn_first_try_correct_answers_still_grant_healing(self):
        started = self.client.post(
            "/api/study-spire/run/start",
            json={"grade": 6, "idempotency_key": "start-inn-first-try"},
        ).json()
        question_ids = []
        with Session(self.engine) as session:
            for index in range(5):
                question = QuestionBank(
                    subject="sinh", difficulty="medium", content=f"Inn câu {index + 1}?",
                    options_json=json.dumps(["Sai", "Đúng", "Sai C", "Sai D"]),
                    correct_answer="B", grade=6,
                )
                session.add(question)
                session.flush()
                question_ids.append(question.id)
            run = session.get(StudyActiveRun, started["run_id"])
            graph = json.loads(run.map_graph_json)
            graph["nodes"]["f2_node_1"]["room_type"] = "inn"
            run.map_graph_json = json.dumps(graph)
            run.run_status = "IN_NODE"
            run.current_floor = 2
            run.current_node_id = "f2_node_1"
            run.history_path_json = json.dumps(["f1_node_1"])
            run.player_core_json = json.dumps({"hp": 50, "hp_max": 80, "knowledge_earned": 0, "deck_card_instance_ids": []})
            run.room_state_json = json.dumps({"challenge_type": "quiz", "question_ids": question_ids})
            session.add(run)
            session.commit()

        completed = self.client.post("/api/study-spire/node/complete", json={
            "expected_state_version": 1,
            "idempotency_key": "inn-first-try-correct",
            "answers": {str(question_id): "B" for question_id in question_ids},
        })
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertTrue(completed.json()["completed"])
        self.assertFalse(completed.json()["reward_forfeited"])
        self.assertEqual(completed.json()["player_core"]["hp"], 74)
        self.assertEqual(completed.json()["reward"]["amount"], 24)

    def _complete_event_with(self, effect, key, hp=50):
        started = self.client.post(
            "/api/study-spire/run/start",
            json={"grade": 6, "idempotency_key": f"start-{key}"},
        ).json()
        question_ids = []
        with Session(self.engine) as session:
            for index in range(3):
                question = QuestionBank(
                    subject="sinh", difficulty="medium", content=f"Event {key} {index + 1}?",
                    options_json=json.dumps(["Sai", "Đúng", "Sai C", "Sai D"]),
                    correct_answer="B", grade=6,
                )
                session.add(question)
                session.flush()
                question_ids.append(question.id)
            run = session.get(StudyActiveRun, started["run_id"])
            graph = json.loads(run.map_graph_json)
            graph["nodes"]["f2_node_1"]["room_type"] = "event"
            run.map_graph_json = json.dumps(graph)
            run.run_status = "IN_NODE"
            run.current_floor = 2
            run.current_node_id = "f2_node_1"
            run.history_path_json = json.dumps(["f1_node_1"])
            run.player_core_json = json.dumps({"hp": hp, "hp_max": 80, "deck_card_instance_ids": []})
            run.room_state_json = json.dumps({"challenge_type": "quiz", "question_ids": question_ids, "event_effect": effect})
            session.add(run)
            session.commit()
        completed = self.client.post("/api/study-spire/node/complete", json={
            "expected_state_version": 1,
            "idempotency_key": f"complete-{key}",
            "answers": {str(question_id): "B" for question_id in question_ids},
        })
        self.assertEqual(completed.status_code, 200, completed.text)
        return completed.json()

    def test_event_can_damage_player_but_never_kills(self):
        result = self._complete_event_with({"type": "damage", "percent": 10}, "event-damage")
        self.assertEqual(result["reward"], {"type": "damage", "amount": 8})
        self.assertEqual(result["player_core"]["hp"], 42)

    def test_event_damage_leaves_at_least_one_hp(self):
        result = self._complete_event_with({"type": "damage", "percent": 10}, "event-damage-low", hp=3)
        self.assertEqual(result["player_core"]["hp"], 1)

    def test_event_can_award_pack(self):
        result = self._complete_event_with({"type": "pack", "pack_id": "pack_sinh"}, "event-pack")
        self.assertEqual(result["reward"]["pack"]["pack_id"], "pack_sinh")
        inventory = self.client.get("/api/study-spire/inventory").json()
        self.assertEqual([pack["pack_id"] for pack in inventory["packs"]], ["pack_sinh"])

    def test_event_retry_after_wrong_answer_completes_without_event_reward(self):
        started = self.client.post(
            "/api/study-spire/run/start",
            json={"grade": 6, "idempotency_key": "start-event-retry"},
        ).json()
        question_ids = []
        with Session(self.engine) as session:
            for index in range(3):
                question = QuestionBank(
                    subject="sinh", difficulty="medium", content=f"Event câu {index + 1}?",
                    options_json=json.dumps(["Sai", "Đúng", "Sai C", "Sai D"]),
                    correct_answer="B", grade=6,
                )
                session.add(question)
                session.flush()
                question_ids.append(question.id)
            run = session.get(StudyActiveRun, started["run_id"])
            graph = json.loads(run.map_graph_json)
            graph["nodes"]["f2_node_1"]["room_type"] = "event"
            run.map_graph_json = json.dumps(graph)
            run.run_status = "IN_NODE"
            run.current_floor = 2
            run.current_node_id = "f2_node_1"
            run.history_path_json = json.dumps(["f1_node_1"])
            run.player_core_json = json.dumps({"hp": 50, "hp_max": 80, "knowledge_earned": 0, "deck_card_instance_ids": []})
            run.room_state_json = json.dumps({
                "challenge_type": "quiz",
                "question_ids": question_ids,
                "event_effect": {"type": "heal", "percent": 10},
            })
            session.add(run)
            session.commit()

        wrong = self.client.post("/api/study-spire/node/complete", json={
            "expected_state_version": 1,
            "idempotency_key": "event-first-wrong-attempt",
            "answers": {str(question_id): "A" for question_id in question_ids},
        })
        self.assertFalse(wrong.json()["completed"])
        self.assertEqual(wrong.json()["feedback"][0]["correct_answer"], "Đúng")

        completed = self.client.post("/api/study-spire/node/complete", json={
            "expected_state_version": 2,
            "idempotency_key": "event-correct-retry",
            "answers": {str(question_id): "B" for question_id in question_ids},
        })
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertTrue(completed.json()["completed"])
        self.assertTrue(completed.json()["reward_forfeited"])
        self.assertEqual(completed.json()["reward"], {})
        self.assertEqual(completed.json()["player_core"]["hp"], 50)

    def test_event_retry_after_wrong_answer_completes_without_event_reward(self):
        started = self.client.post(
            "/api/study-spire/run/start",
            json={"grade": 6, "idempotency_key": "start-event-retry"},
        ).json()
        question_ids = []
        with Session(self.engine) as session:
            for index in range(3):
                question = QuestionBank(
                    subject="sinh", difficulty="medium", content=f"Event câu {index + 1}?",
                    options_json=json.dumps(["Sai", "Đúng", "Sai C", "Sai D"]),
                    correct_answer="B", grade=6,
                )
                session.add(question)
                session.flush()
                question_ids.append(question.id)
            run = session.get(StudyActiveRun, started["run_id"])
            graph = json.loads(run.map_graph_json)
            graph["nodes"]["f2_node_1"]["room_type"] = "event"
            run.map_graph_json = json.dumps(graph)
            run.run_status = "IN_NODE"
            run.current_floor = 2
            run.current_node_id = "f2_node_1"
            run.history_path_json = json.dumps(["f1_node_1"])
            run.player_core_json = json.dumps({"hp": 50, "hp_max": 80, "knowledge_earned": 0, "deck_card_instance_ids": []})
            run.room_state_json = json.dumps({
                "challenge_type": "quiz", "question_ids": question_ids,
                "event_effect": {"type": "heal", "percent": 10},
            })
            session.add(run)
            session.commit()

        wrong = self.client.post("/api/study-spire/node/complete", json={
            "expected_state_version": 1,
            "idempotency_key": "event-retry-wrong",
            "answers": {str(question_id): "A" for question_id in question_ids},
        })
        self.assertTrue(wrong.json()["retry_required"])
        completed = self.client.post("/api/study-spire/node/complete", json={
            "expected_state_version": 2,
            "idempotency_key": "event-retry-correct",
            "answers": {str(question_id): "B" for question_id in question_ids},
        })
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertTrue(completed.json()["completed"])
        self.assertTrue(completed.json()["reward_forfeited"])
        self.assertEqual(completed.json()["reward"], {})
        self.assertEqual(completed.json()["player_core"]["hp"], 50)

    def test_deck_limits_and_pack_open_retry_are_idempotent(self):
        deck = self.client.get("/api/study-spire/deck")
        self.assertEqual(deck.status_code, 200, deck.text)
        deck_data = deck.json()
        self.assertEqual(len(deck_data["cards"]), 10)
        self.assertEqual(deck_data["minimum_cards"], 10)
        self.assertFalse(deck_data["must_remain_full"])
        inventory = self.client.get("/api/study-spire/inventory")
        self.assertEqual(inventory.status_code, 200, inventory.text)
        self.assertTrue(all("mana_cost" in card and "description" in card for card in inventory.json()["cards"]))
        card_ids = [card["instance_id"] for card in deck_data["cards"]]

        updated = self.client.put("/api/study-spire/deck", json={
            "expected_state_version": deck_data["state_version"],
            "idempotency_key": "update-starter-deck",
            "card_instance_ids": card_ids,
        })
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["state_version"], 2)
        retry_update = self.client.put("/api/study-spire/deck", json={
            "expected_state_version": deck_data["state_version"],
            "idempotency_key": "update-starter-deck",
            "card_instance_ids": card_ids,
        })
        self.assertEqual(retry_update.json(), updated.json())

        invalid_deck = self.client.put("/api/study-spire/deck", json={
            "expected_state_version": 2,
            "idempotency_key": "too-small-deck",
            "card_instance_ids": card_ids[:9],
        })
        self.assertEqual(invalid_deck.status_code, 422)

        with Session(self.engine) as session:
            session.add(StudyPlayerPack(player_id=self.current_user.id, pack_id="pack_ly", quantity=1))
            session.commit()
        opened = self.client.post("/api/study-spire/pack/open", json={
            "pack_id": "pack_ly",
            "expected_state_version": 1,
            "idempotency_key": "open-first-pack",
        })
        self.assertEqual(opened.status_code, 200, opened.text)
        retry_open = self.client.post("/api/study-spire/pack/open", json={
            "pack_id": "pack_ly",
            "expected_state_version": 1,
            "idempotency_key": "open-first-pack",
        })
        self.assertEqual(retry_open.json(), opened.json())
        self.assertFalse(opened.json()["card"]["added_to_deck"])
        added = self.client.post("/api/study-spire/deck/add-earned", json={
            "instance_id": opened.json()["card"]["instance_id"],
            "expected_state_version": updated.json()["state_version"],
            "idempotency_key": "claim-opened-pack-card",
        })
        self.assertEqual(added.status_code, 200, added.text)
        self.assertTrue(added.json()["added_to_deck"])
        with Session(self.engine) as session:
            pack = session.exec(select(StudyPlayerPack)).one()
            self.assertEqual(pack.quantity, 0)
            self.assertEqual(len(session.exec(select(StudyCardInstance)).all()), 11)
            self.assertEqual(len(session.exec(select(StudyDeckCard)).all()), 11)

    def test_deck_minimum_twenty_has_no_upper_limit(self):
        deck = self.client.get("/api/study-spire/deck").json()
        initial_ids = [card["instance_id"] for card in deck["cards"]]
        extra_card_ids = [PHYSICS_CARDS[index % 7]["card_id"] for index in range(13)]
        with Session(self.engine) as session:
            extra_instances = [
                StudyCardInstance(player_id=self.current_user.id, card_id=card_id)
                for card_id in extra_card_ids
            ]
            session.add_all(extra_instances)
            session.commit()
            extra_ids = [card.instance_id for card in extra_instances]

        all_ids = initial_ids + extra_ids
        first_full = self.client.put("/api/study-spire/deck", json={
            "expected_state_version": deck["state_version"],
            "idempotency_key": "save-first-twenty",
            "card_instance_ids": all_ids[:20],
        })
        self.assertEqual(first_full.status_code, 200, first_full.text)
        self.assertTrue(first_full.json()["must_remain_full"])
        self.assertEqual(len(first_full.json()["cards"]), 20)

        expanded = self.client.put("/api/study-spire/deck", json={
            "expected_state_version": first_full.json()["state_version"],
            "idempotency_key": "expand-unlimited-deck",
            "card_instance_ids": all_ids,
        })
        self.assertEqual(expanded.status_code, 200, expanded.text)
        self.assertEqual(len(expanded.json()["cards"]), 23)
        self.assertTrue(expanded.json()["must_remain_full"])

        below_minimum = self.client.put("/api/study-spire/deck", json={
            "expected_state_version": expanded.json()["state_version"],
            "idempotency_key": "try-shrink-to-nineteen",
            "card_instance_ids": all_ids[:19],
        })
        self.assertEqual(below_minimum.status_code, 422)

        minimum = self.client.put("/api/study-spire/deck", json={
            "expected_state_version": expanded.json()["state_version"],
            "idempotency_key": "save-at-least-twenty",
            "card_instance_ids": all_ids[:20],
        })
        self.assertEqual(minimum.status_code, 200, minimum.text)
        self.assertEqual(len(minimum.json()["cards"]), 20)

    def test_defeat_archives_run_and_resolution_retry_survives_active_cleanup(self):
        started = self.client.post(
            "/api/study-spire/run/start",
            json={"grade": 6, "idempotency_key": "start-defeat-test"},
        ).json()
        with Session(self.engine) as session:
            battle = session.exec(select(StudyBattle).where(StudyBattle.run_id == started["run_id"])).one()
            battle_state = json.loads(battle.battle_state_json)
            battle_state["player"]["hp"] = 0
            battle_state["phase"] = "RESOLVING"
            battle.battle_phase = "RESOLVING"
            battle.battle_state_json = json.dumps(battle_state)
            session.add(battle)
            session.commit()

        key = f"{started['run_id']}_{started['battle_id']}"
        payload = {"expected_state_version": 1, "idempotency_key": key}
        defeated = self.client.post("/api/study-spire/battle/resolve", json=payload)
        self.assertEqual(defeated.status_code, 200, defeated.text)
        self.assertEqual(defeated.json()["run_status"], "DEFEATED")
        retry = self.client.post("/api/study-spire/battle/resolve", json=payload)
        self.assertEqual(retry.json(), defeated.json())

        with Session(self.engine) as session:
            self.assertIsNone(session.exec(select(StudyActiveRun)).first())
            history = session.get(StudyRunHistory, started["run_id"])
            self.assertEqual(history.outcome, "DEFEATED")
            self.assertEqual(len(session.exec(select(StudyBattleResolution)).all()), 1)
            player = session.get(Player, self.current_user.id)
            self.assertEqual(int(player.tri_thuc or 0), 0)
            self.assertNotIn("consolation_knowledge", defeated.json())

    def test_boss_victory_clears_stage_and_awards_relic_once(self):
        started = self.client.post(
            "/api/study-spire/run/start",
            json={"grade": 6, "idempotency_key": "start-boss-test"},
        ).json()
        with Session(self.engine) as session:
            run = session.get(StudyActiveRun, started["run_id"])
            run.current_floor = 10
            run.current_node_id = "f10_boss"
            graph = json.loads(run.map_graph_json)
            graph["nodes"]["f10_boss"]["room_type"] = "boss"
            run.map_graph_json = json.dumps(graph)
            battle = session.exec(select(StudyBattle).where(StudyBattle.run_id == run.run_id)).one()
            battle_state = json.loads(battle.battle_state_json)
            battle_state["enemy"]["hp"] = 0
            battle_state["phase"] = "RESOLVING"
            battle.battle_phase = "RESOLVING"
            battle.battle_state_json = json.dumps(battle_state)
            session.add_all([run, battle])
            session.commit()

        key = f"{started['run_id']}_{started['battle_id']}"
        payload = {"expected_state_version": 1, "idempotency_key": key}
        victory = self.client.post("/api/study-spire/battle/resolve", json=payload)
        self.assertEqual(victory.status_code, 200, victory.text)
        self.assertEqual(victory.json()["run_status"], "IN_NODE")
        self.assertEqual(victory.json()["stage_cleared"], 1)
        self.assertEqual(victory.json()["stage"], 2)
        self.assertEqual(victory.json()["relic"]["id"], victory.json()["relic_id"])
        self.assertEqual(victory.json()["map_graph"]["final_floor"], 11)
        self.assertEqual(victory.json()["current_floor"], 1)
        self.assertGreater(victory.json()["battle"]["enemy"]["max_hp"], 28)
        retry = self.client.post("/api/study-spire/battle/resolve", json=payload)
        self.assertEqual(retry.json(), victory.json())

        resumed = self.client.get("/api/study-spire/run/active").json()["run"]
        self.assertEqual(resumed["map_graph"], victory.json()["map_graph"])
        self.assertEqual(resumed["player_core"]["stage"], 2)
        self.assertIn(victory.json()["relic_id"], resumed["player_core"]["relic_ids"])

        with Session(self.engine) as session:
            self.assertIsNotNone(session.exec(select(StudyActiveRun)).first())
            self.assertIsNone(session.get(StudyRunHistory, started["run_id"]))
            self.assertEqual(len(session.exec(select(StudyPlayerRelic)).all()), 1)
            player = session.get(Player, self.current_user.id)
            self.assertEqual(int(player.tri_thuc or 0), 0)

    def test_relic_collection_and_loadout_only_allow_owned_items(self):
        response = self.client.get("/api/study-spire/relics")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["total_count"], 19)
        self.assertEqual(response.json()["owned_count"], 0)

        unowned = self.client.put("/api/study-spire/relics/loadout", json={"relic_ids": ["relic_01"]})
        self.assertEqual(unowned.status_code, 422)

        with Session(self.engine) as session:
            session.add(StudyPlayerRelic(player_id=self.current_user.id, relic_id="relic_01"))
            session.commit()
        saved = self.client.put("/api/study-spire/relics/loadout", json={"relic_ids": ["relic_01"]})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["pvp_loadout_ids"], ["relic_01"])
        self.assertTrue(next(relic for relic in saved.json()["relics"] if relic["id"] == "relic_01")["equipped"])

        duplicate = self.client.put("/api/study-spire/relics/loadout", json={"relic_ids": ["relic_01", "relic_01"]})
        self.assertEqual(duplicate.status_code, 422)

    def test_legacy_random_relics_are_migrated_into_the_new_catalog(self):
        with Session(self.engine) as session:
            session.add(StudyPlayerRelic(player_id=self.current_user.id, relic_id="relic_legacy_a1b2c3"))
            session.commit()

        response = self.client.get("/api/study-spire/relics")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["owned_count"], 1)
        with Session(self.engine) as session:
            relic = session.exec(select(StudyPlayerRelic)).one()
            self.assertEqual(relic.relic_id, "relic_01")

    def test_boss_gives_no_relic_or_duplicate_conversion_after_all_are_owned(self):
        started = self.client.post(
            "/api/study-spire/run/start",
            json={"grade": 6, "idempotency_key": "start-all-relics"},
        ).json()
        with Session(self.engine) as session:
            session.add_all([
                StudyPlayerRelic(player_id=self.current_user.id, relic_id=relic["id"])
                for relic in RELIC_CATALOG
            ])
            run = session.get(StudyActiveRun, started["run_id"])
            run.current_floor = 10
            run.current_node_id = "f10_boss"
            graph = json.loads(run.map_graph_json)
            graph["nodes"]["f10_boss"]["room_type"] = "boss"
            run.map_graph_json = json.dumps(graph)
            battle = session.exec(select(StudyBattle).where(StudyBattle.run_id == run.run_id)).one()
            battle_state = json.loads(battle.battle_state_json)
            battle_state["enemy"]["hp"] = 0
            battle_state["phase"] = "RESOLVING"
            battle.battle_phase = "RESOLVING"
            battle.battle_state_json = json.dumps(battle_state)
            session.add_all([run, battle])
            session.commit()

        result = self.client.post("/api/study-spire/battle/resolve", json={
            "expected_state_version": 1,
            "idempotency_key": f"{started['run_id']}_{started['battle_id']}",
        })
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIsNone(result.json()["relic_id"])
        self.assertIsNone(result.json()["relic"])
        self.assertTrue(result.json()["all_relics_collected"])
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(StudyPlayerRelic)).all()), len(RELIC_CATALOG))

    def test_chest_typing_challenge_awards_card_and_resumes_idempotently(self):
        started = self.client.post(
            "/api/study-spire/run/start",
            json={"grade": 6, "idempotency_key": "start-chest-test"},
        ).json()
        with Session(self.engine) as session:
            run = session.get(StudyActiveRun, started["run_id"])
            graph = json.loads(run.map_graph_json)
            graph["nodes"]["f2_node_1"]["room_type"] = "chest"
            run.map_graph_json = json.dumps(graph)
            run.current_floor = 2
            run.current_node_id = "f2_node_1"
            run.run_status = "IN_NODE"
            run.history_path_json = json.dumps(["f1_node_1"])
            run.room_state_json = json.dumps({"challenge_type": "typing", "passage_id": "sample_g6_sinh_1"})
            session.add(run)
            session.commit()

        challenge = self.client.get("/api/study-spire/node/challenge")
        self.assertEqual(challenge.status_code, 200, challenge.text)
        passage = challenge.json()["passage"]["content"]
        failed = self.client.post("/api/study-spire/node/complete", json={
            "expected_state_version": 1,
            "idempotency_key": "chest-bad-text",
            "submitted_text": "không đúng",
        })
        self.assertFalse(failed.json()["completed"])

        payload = {"expected_state_version": 1, "idempotency_key": "chest-correct-text", "submitted_text": passage}
        opened = self.client.post("/api/study-spire/node/complete", json=payload)
        self.assertEqual(opened.status_code, 200, opened.text)
        self.assertTrue(opened.json()["completed"])
        self.assertEqual(opened.json()["reward"]["type"], "card")
        retry = self.client.post("/api/study-spire/node/complete", json=payload)
        self.assertEqual(retry.json(), opened.json())

        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(StudyCardInstance)).all()), 11)
            self.assertEqual(len(session.exec(select(StudyDeckCard)).all()), 11)


if __name__ == "__main__":
    unittest.main()