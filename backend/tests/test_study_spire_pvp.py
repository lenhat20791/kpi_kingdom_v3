import json
import sys
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import Player, StudyPlayerRelic, StudyPvpRelicLoadout, get_db
from game_logic.study_spire_pvp import create_pvp_battle_state, play_pvp_card
from routes.study_pvp_api import router


class StudySpirePvpApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            self.host = Player(username="pvp_host", password_hash="hash", full_name="Host")
            self.guest = Player(username="pvp_guest", password_hash="hash", full_name="Guest")
            self.spectator = Player(username="pvp_spectator", password_hash="hash", full_name="Spectator")
            session.add_all([self.host, self.guest, self.spectator])
            session.commit()
            for player in (self.host, self.guest, self.spectator):
                session.refresh(player)
        self.current_user = self.host
        app = FastAPI()
        app.include_router(router)

        def override_get_db():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[__import__("routes.auth", fromlist=["get_current_user"]).get_current_user] = lambda: self.current_user
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_room_password_ready_start_spectator_privacy_and_turns(self):
        created = self.client.post("/api/study-spire/pvp/rooms", json={
            "room_name": "Thử sức Sinh học",
            "password": "root42",
            "spectators_allowed": True,
        })
        self.assertEqual(created.status_code, 200, created.text)
        room = created.json()["room"]
        room_code = room["room_code"]
        self.assertTrue(room["has_password"])
        self.assertNotIn("password", room)
        self.assertNotIn("password_hash", room)

        lobby = self.client.get("/api/study-spire/pvp/lobby")
        self.assertEqual(lobby.status_code, 200, lobby.text)
        self.assertEqual(lobby.json()["rooms"][0]["room_code"], room_code)

        self.current_user = self.guest
        wrong_password = self.client.post(f"/api/study-spire/pvp/rooms/{room_code}/join", json={"password": "wrong"})
        self.assertEqual(wrong_password.status_code, 403)
        joined = self.client.post(f"/api/study-spire/pvp/rooms/{room_code}/join", json={"password": "root42"})
        self.assertEqual(joined.status_code, 200, joined.text)

        self.current_user = self.host
        host_ready = self.client.post(f"/api/study-spire/pvp/rooms/{room_code}/ready", json={"ready": True})
        self.assertTrue(host_ready.json()["room"]["host_ready"])
        not_ready = self.client.post(f"/api/study-spire/pvp/rooms/{room_code}/start", json={
            "expected_state_version": host_ready.json()["room"]["state_version"],
            "action_key": "pvp-start-too-early",
        })
        self.assertEqual(not_ready.status_code, 409)

        self.current_user = self.guest
        guest_ready = self.client.post(f"/api/study-spire/pvp/rooms/{room_code}/ready", json={"ready": True})
        self.assertTrue(guest_ready.json()["room"]["guest_ready"])
        guest_start = self.client.post(f"/api/study-spire/pvp/rooms/{room_code}/start", json={
            "expected_state_version": guest_ready.json()["room"]["state_version"],
            "action_key": "pvp-guest-start",
        })
        self.assertEqual(guest_start.status_code, 403)

        self.current_user = self.host
        started = self.client.post(f"/api/study-spire/pvp/rooms/{room_code}/start", json={
            "expected_state_version": guest_ready.json()["room"]["state_version"],
            "action_key": "pvp-host-start",
        })
        self.assertEqual(started.status_code, 200, started.text)
        self.assertEqual(started.json()["status"], "ACTIVE")
        self.assertEqual(started.json()["viewer_role"], "host")
        self.assertTrue(started.json()["can_act"])
        self.assertFalse(started.json()["battle"]["sudden_death"])
        host_view = self.client.get(f"/api/study-spire/pvp/rooms/{room_code}/state").json()
        host_seats = {seat["player_id"]: seat for seat in host_view["battle"]["players"]}
        self.assertTrue(host_seats[self.host.id]["hand"])
        self.assertIsNone(host_seats[self.guest.id]["hand"])

        self.current_user = self.guest
        guest_view = self.client.get(f"/api/study-spire/pvp/rooms/{room_code}/state").json()
        guest_seats = {seat["player_id"]: seat for seat in guest_view["battle"]["players"]}
        self.assertTrue(guest_seats[self.guest.id]["hand"])
        self.assertIsNone(guest_seats[self.host.id]["hand"])

        self.current_user = self.spectator
        spectator_view = self.client.post(f"/api/study-spire/pvp/rooms/{room_code}/spectate")
        self.assertEqual(spectator_view.status_code, 200, spectator_view.text)
        self.assertTrue(spectator_view.json()["spectator"])
        self.assertFalse(spectator_view.json()["can_act"])
        self.assertTrue(all(seat["hand"] for seat in spectator_view.json()["battle"]["players"]))
        forbidden_action = self.client.post(f"/api/study-spire/pvp/rooms/{room_code}/end-turn", json={
            "expected_state_version": spectator_view.json()["state_version"],
            "action_key": "spectator-cannot-act",
        })
        self.assertEqual(forbidden_action.status_code, 403)

        self.current_user = self.host
        state = self.client.get(f"/api/study-spire/pvp/rooms/{room_code}/state").json()
        host_seat = next(seat for seat in state["battle"]["players"] if seat["player_id"] == self.host.id)
        played = self.client.post(f"/api/study-spire/pvp/rooms/{room_code}/play-card", json={
            "expected_state_version": state["state_version"],
            "action_key": "host-play-first-card",
            "instance_id": host_seat["hand"][0]["instance_id"],
        })
        self.assertEqual(played.status_code, 200, played.text)
        ended = self.client.post(f"/api/study-spire/pvp/rooms/{room_code}/end-turn", json={
            "expected_state_version": played.json()["state_version"],
            "action_key": "host-end-first-turn",
        })
        self.assertEqual(ended.status_code, 200, ended.text)
        self.assertEqual(ended.json()["battle"]["active_player_id"], self.guest.id)
        turn_state = ended.json()
        for index in range(19):
            active_player_id = turn_state["battle"]["active_player_id"]
            self.current_user = self.host if active_player_id == self.host.id else self.guest
            turn_response = self.client.post(f"/api/study-spire/pvp/rooms/{room_code}/end-turn", json={
                "expected_state_version": turn_state["state_version"],
                "action_key": f"sudden-death-turn-{index:02d}",
            })
            self.assertEqual(turn_response.status_code, 200, turn_response.text)
            turn_state = turn_response.json()
        self.assertTrue(turn_state["battle"]["sudden_death"])

        self.current_user = self.host
        host_sudden_death = self.client.get(f"/api/study-spire/pvp/rooms/{room_code}/state")
        self.assertTrue(host_sudden_death.json()["battle"]["sudden_death"])
        self.current_user = self.guest
        guest_sudden_death = self.client.get(f"/api/study-spire/pvp/rooms/{room_code}/state")
        self.assertTrue(guest_sudden_death.json()["battle"]["sudden_death"])

    def test_room_match_snapshots_equipped_relics_for_both_players(self):
        with Session(self.engine) as session:
            session.add_all([
                StudyPlayerRelic(player_id=self.host.id, relic_id="relic_01"),
                StudyPlayerRelic(player_id=self.guest.id, relic_id="relic_02"),
                StudyPvpRelicLoadout(player_id=self.host.id, relic_ids_json=json.dumps(["relic_01"])),
                StudyPvpRelicLoadout(player_id=self.guest.id, relic_ids_json=json.dumps(["relic_02"])),
            ])
            session.commit()

        created = self.client.post("/api/study-spire/pvp/rooms", json={"room_name": "Relic PvP"})
        room_code = created.json()["room"]["room_code"]
        self.current_user = self.guest
        joined = self.client.post(f"/api/study-spire/pvp/rooms/{room_code}/join", json={"password": None})
        self.assertEqual(joined.status_code, 200, joined.text)

        self.current_user = self.host
        self.client.post(f"/api/study-spire/pvp/rooms/{room_code}/ready", json={"ready": True})
        self.current_user = self.guest
        guest_ready = self.client.post(f"/api/study-spire/pvp/rooms/{room_code}/ready", json={"ready": True})
        self.current_user = self.host
        started = self.client.post(f"/api/study-spire/pvp/rooms/{room_code}/start", json={
            "expected_state_version": guest_ready.json()["room"]["state_version"],
            "action_key": "relic-room-start",
        })
        self.assertEqual(started.status_code, 200, started.text)
        seats = {seat["player_id"]: seat for seat in started.json()["battle"]["players"]}
        self.assertEqual(seats[self.host.id]["shield"], 8)
        self.assertEqual(seats[self.guest.id]["hp_max"], 88)

    def test_pvp_relics_trigger_attack_reflection_and_damage_reduction(self):
        def cards(owner):
            return [
                {
                    "instance_id": f"{owner}-card-{index}",
                    "card_id": "relic_test_strike",
                    "name": "Đòn thử",
                    "mana_cost": 0,
                    "card_type": "attack",
                    "tags": [],
                    "effects": [{"op": "attack", "value": 10}],
                    "exhaust": False,
                }
                for index in range(10)
            ]

        state = create_pvp_battle_state(
            self.host.id, self.host.username, "Host", cards("host"),
            self.guest.id, self.guest.username, "Guest", cards("guest"),
            7, guest_relic_ids=["relic_06", "relic_16"],
        )
        card_id = state["players"][str(self.host.id)]["hand"][0]
        state = play_pvp_card(state, self.host.id, card_id)
        self.assertEqual(state["players"][str(self.host.id)]["stats"]["hp"], 78)
        self.assertEqual(state["players"][str(self.guest.id)]["stats"]["hp"], 71)


if __name__ == "__main__":
    unittest.main()