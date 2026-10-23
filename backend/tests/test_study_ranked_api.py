import json
import sys
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import (
    Player,
    StudyPlayerRelic,
    StudyPvpRelicLoadout,
    StudyRankedMatch,
    StudyRankedPlayer,
    get_db,
)
from routes.study_ranked_api import router


class StudyRankedApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            self.host = Player(username="rank_host", password_hash="hash", full_name="Host")
            self.guest = Player(username="rank_guest", password_hash="hash", full_name="Guest")
            self.other = Player(username="rank_other", password_hash="hash", full_name="Other")
            session.add_all([self.host, self.guest, self.other])
            session.commit()
            for player in (self.host, self.guest, self.other):
                session.refresh(player)
        self.current_user = self.host
        app = FastAPI()
        app.include_router(router)

        def override_get_db():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[
            __import__("routes.auth", fromlist=["get_current_user"]).get_current_user
        ] = lambda: self.current_user
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_board_lists_only_top_twenty_and_opponents_in_nearest_rank_order(self):
        with Session(self.engine) as session:
            players = [self.host, self.guest, self.other]
            for rank in range(1, 25):
                player = Player(username=f"rank_{rank}", password_hash="hash", full_name=f"Player {rank}")
                session.add(player)
                session.commit()
                session.refresh(player)
                players.append(player)
            for rank, player in enumerate(players, start=1):
                session.add(StudyRankedPlayer(player_id=player.id, rank_position=rank, placement_matches=3))
            session.commit()
            last_player_id = players[-1].id
        with Session(self.engine) as session:
            self.current_user = session.get(Player, last_player_id)

        first_batch = self.client.get("/api/study-spire/ranked/board?batch=0")
        self.assertEqual(first_batch.status_code, 200, first_batch.text)
        body = first_batch.json()
        self.assertEqual(len(body["top_players"]), 20)
        self.assertEqual([entry["rank_position"] for entry in body["opponents"]], [len(players) - 1, len(players) - 2, len(players) - 3])
        self.assertTrue(body["has_next_opponent_batch"])

        second_batch = self.client.get("/api/study-spire/ranked/board?batch=1")
        self.assertEqual(second_batch.status_code, 200, second_batch.text)
        self.assertEqual([entry["rank_position"] for entry in second_batch.json()["opponents"]], [len(players) - 4, len(players) - 5, len(players) - 6])

    def test_placement_bot_turns_and_three_losses_add_player_at_bottom(self):
        board = self.client.get("/api/study-spire/ranked/board").json()
        opponent_id = board["opponents"][0]["player_id"]
        first_match = self.client.post("/api/study-spire/ranked/matches", json={"opponent_player_id": opponent_id})
        self.assertEqual(first_match.status_code, 200, first_match.text)
        self.assertEqual(first_match.json()["match_type"], "PLACEMENT")
        self.assertFalse(first_match.json()["battle"]["sudden_death"])

        first_state = first_match.json()
        first_turn = self.client.post(
            f"/api/study-spire/ranked/matches/{first_state['match_id']}/end-turn",
            json={"expected_state_version": first_state["state_version"]},
        )
        self.assertEqual(first_turn.status_code, 200, first_turn.text)
        self.assertEqual(first_turn.json()["battle"]["active_player_id"], self.host.id)

        for attempt in range(3):
            if attempt == 0:
                match = first_turn.json()
            else:
                board = self.client.get("/api/study-spire/ranked/board").json()
                opponent_id = board["opponents"][0]["player_id"]
                response = self.client.post("/api/study-spire/ranked/matches", json={"opponent_player_id": opponent_id})
                self.assertEqual(response.status_code, 200, response.text)
                match = response.json()
            result = self.client.post(
                f"/api/study-spire/ranked/matches/{match['match_id']}/forfeit",
                json={"expected_state_version": match["state_version"]},
            )
            self.assertEqual(result.status_code, 200, result.text)

        board = self.client.get("/api/study-spire/ranked/board").json()
        self.assertFalse(board["placement_required"])
        self.assertEqual(board["player"]["placement_matches"], 3)
        self.assertEqual(board["player"]["placement_wins"], 0)
        self.assertEqual(board["player"]["rank_position"], 1)

    def test_ranked_match_snapshot_exposes_sudden_death_state(self):
        board = self.client.get("/api/study-spire/ranked/board").json()
        started = self.client.post(
            "/api/study-spire/ranked/matches",
            json={"opponent_player_id": board["opponents"][0]["player_id"]},
        )
        self.assertEqual(started.status_code, 200, started.text)
        match_id = started.json()["match_id"]

        with Session(self.engine) as session:
            match = session.get(StudyRankedMatch, match_id)
            state = json.loads(match.battle_state_json)
            state["sudden_death"] = True
            state["turn_number"] = 21
            match.battle_state_json = json.dumps(state)
            session.add(match)
            session.commit()

        snapshot = self.client.get(f"/api/study-spire/ranked/matches/{match_id}")
        self.assertEqual(snapshot.status_code, 200, snapshot.text)
        self.assertTrue(snapshot.json()["battle"]["sudden_death"])

    def test_placement_wins_seed_initial_order_before_ranked_matches(self):
        with Session(self.engine) as session:
            session.add(StudyRankedPlayer(
                player_id=self.guest.id,
                rank_position=1,
                placement_matches=3,
                placement_wins=0,
            ))
            session.commit()

        for attempt in range(3):
            started = self.client.post(
                "/api/study-spire/ranked/matches",
                json={"opponent_player_id": self.other.id},
            )
            self.assertEqual(started.status_code, 200, started.text)
            with Session(self.engine) as session:
                match = session.get(StudyRankedMatch, started.json()["match_id"])
                state = json.loads(match.battle_state_json)
                state["winner_player_id"] = self.host.id
                match.battle_state_json = json.dumps(state)
                session.add(match)
                session.commit()
            result = self.client.post(
                f"/api/study-spire/ranked/matches/{started.json()['match_id']}/end-turn",
                json={"expected_state_version": started.json()["state_version"]},
            )
            self.assertEqual(result.status_code, 200, result.text)
            if attempt == 2:
                self.assertEqual(result.json()["rank_result"]["new_rank"], 1)

        board = self.client.get("/api/study-spire/ranked/board").json()
        self.assertEqual(board["player"]["placement_wins"], 3)
        self.assertEqual(board["player"]["rank_position"], 1)
        self.assertEqual(next(row["rank_position"] for row in board["top_players"] if row["player_id"] == self.guest.id), 2)

    def test_ranked_victory_exchanges_positions(self):
        with Session(self.engine) as session:
            session.add_all([
                StudyRankedPlayer(player_id=self.host.id, rank_position=2, placement_matches=3),
                StudyRankedPlayer(player_id=self.guest.id, rank_position=1, placement_matches=3),
            ])
            session.commit()
        started = self.client.post(
            "/api/study-spire/ranked/matches",
            json={"opponent_player_id": self.guest.id},
        )
        self.assertEqual(started.status_code, 200, started.text)
        match_id = started.json()["match_id"]
        with Session(self.engine) as session:
            match = session.get(StudyRankedMatch, match_id)
            state = json.loads(match.battle_state_json)
            state["winner_player_id"] = self.host.id
            match.battle_state_json = json.dumps(state)
            session.add(match)
            session.commit()
        ended = self.client.post(
            f"/api/study-spire/ranked/matches/{match_id}/end-turn",
            json={"expected_state_version": started.json()["state_version"]},
        )
        self.assertEqual(ended.status_code, 200, ended.text)
        self.assertTrue(ended.json()["rank_result"]["rank_changed"])
        self.assertEqual(ended.json()["rank_result"]["player_rank"], 1)
        self.assertEqual(ended.json()["rank_result"]["opponent_rank"], 2)

    def test_ranked_forfeit_keeps_both_positions(self):
        with Session(self.engine) as session:
            session.add_all([
                StudyRankedPlayer(player_id=self.host.id, rank_position=2, placement_matches=3),
                StudyRankedPlayer(player_id=self.guest.id, rank_position=1, placement_matches=3),
            ])
            session.commit()
        started = self.client.post(
            "/api/study-spire/ranked/matches",
            json={"opponent_player_id": self.guest.id},
        )
        self.assertEqual(started.status_code, 200, started.text)
        result = self.client.post(
            f"/api/study-spire/ranked/matches/{started.json()['match_id']}/forfeit",
            json={"expected_state_version": started.json()["state_version"]},
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertFalse(result.json()["rank_result"]["rank_changed"])
        board = self.client.get("/api/study-spire/ranked/board").json()
        self.assertEqual(board["player"]["rank_position"], 2)
        self.assertEqual(next(row["rank_position"] for row in board["top_players"] if row["player_id"] == self.guest.id), 1)

    def test_ranked_match_snapshots_each_players_equipped_relics(self):
        with Session(self.engine) as session:
            session.add_all([
                StudyPlayerRelic(player_id=self.host.id, relic_id="relic_01"),
                StudyPlayerRelic(player_id=self.guest.id, relic_id="relic_02"),
                StudyPvpRelicLoadout(player_id=self.host.id, relic_ids_json=json.dumps(["relic_01"])),
                StudyPvpRelicLoadout(player_id=self.guest.id, relic_ids_json=json.dumps(["relic_02"])),
            ])
            session.commit()

        match = self.client.post(
            "/api/study-spire/ranked/matches",
            json={"opponent_player_id": self.guest.id},
        )
        self.assertEqual(match.status_code, 200, match.text)
        seats = {seat["player_id"]: seat for seat in match.json()["battle"]["players"]}
        self.assertEqual(seats[self.host.id]["shield"], 8)
        self.assertEqual(seats[self.host.id]["relics"][0]["id"], "relic_01")
        self.assertEqual(seats[self.guest.id]["hp_max"], 88)
        self.assertEqual(seats[self.guest.id]["relics"][0]["id"], "relic_02")


if __name__ == "__main__":
    unittest.main()
