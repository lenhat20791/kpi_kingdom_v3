import asyncio
import sys
import unittest
from pathlib import Path
from threading import Lock

from fastapi import FastAPI
from sqlalchemy import event
from sqlmodel import SQLModel, Session, create_engine
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import Inventory, Item, Player
from main import check_engine_status
from routes.admin import get_all_players_overview


class RuntimeRegressionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(
            self.engine,
            tables=[Player.__table__, Item.__table__, Inventory.__table__],
        )

    def tearDown(self):
        self.engine.dispose()

    def test_admin_overview_batches_inventory_without_changing_response(self):
        with Session(self.engine) as session:
            player_with_item = Player(username="alpha", password_hash="hash", full_name="Alpha")
            player_without_item = Player(username="beta", password_hash="hash", full_name="Beta")
            item = Item(name="Charm", image_url="charm.png")
            session.add_all([player_with_item, player_without_item, item])
            session.flush()
            session.add(Inventory(player_id=player_with_item.id, item_id=item.id, amount=2))
            session.commit()

            select_count = 0
            count_lock = Lock()

            def count_selects(connection, cursor, statement, parameters, context, executemany):
                nonlocal select_count
                if statement.lstrip().upper().startswith("SELECT"):
                    with count_lock:
                        select_count += 1

            event.listen(self.engine, "before_cursor_execute", count_selects)
            try:
                result = get_all_players_overview(session)
            finally:
                event.remove(self.engine, "before_cursor_execute", count_selects)

        by_username = {player["username"]: player for player in result}
        self.assertEqual(by_username["alpha"]["inventory"], [
            {"item_name": "Charm", "amount": 2, "category": "Vật phẩm", "rarity": "Thường"}
        ])
        self.assertEqual(by_username["beta"]["inventory"], [])
        self.assertEqual(select_count, 2)

    def test_campaign_engine_status_reports_task_lifecycle(self):
        app = FastAPI()
        request = Request({"type": "http", "app": app, "headers": []})

        async def run_check():
            task = asyncio.create_task(asyncio.sleep(60))
            app.state.campaign_engine_task = task
            try:
                running = await check_engine_status(request)
                self.assertTrue(running["success"])
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            stopped = await check_engine_status(request)
            self.assertFalse(stopped["success"])

        asyncio.run(run_check())


if __name__ == "__main__":
    unittest.main()