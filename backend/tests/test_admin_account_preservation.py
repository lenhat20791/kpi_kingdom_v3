import asyncio
import sys
import unittest
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import Player
from routes.admin import reset_season


class AdminAccountPreservationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_reset_season_preserves_master_admin_even_if_its_role_was_changed(self):
        with Session(self.engine) as session:
            admin = Player(
                username="admin",
                password_hash="admin-hash",
                full_name="System Admin",
                role="student",
            )
            student = Player(
                username="student",
                password_hash="student-hash",
                full_name="Student",
            )
            session.add_all([admin, student])
            session.commit()
            admin_id = admin.id

            result = asyncio.run(reset_season(session))

            self.assertTrue(result["success"])
            remaining_players = session.exec(select(Player)).all()
            self.assertEqual(len(remaining_players), 1)
            self.assertEqual(remaining_players[0].id, admin_id)
            self.assertEqual(remaining_players[0].username, "admin")
            self.assertEqual(remaining_players[0].role, "admin")


if __name__ == "__main__":
    unittest.main()
