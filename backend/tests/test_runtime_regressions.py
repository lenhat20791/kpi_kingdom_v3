import asyncio
from io import BytesIO
import sys
import unittest
from pathlib import Path
from threading import Lock
from unittest.mock import patch

import pandas as pd
from fastapi import FastAPI, UploadFile
from sqlalchemy import event, inspect
from sqlmodel import SQLModel, Session, create_engine, select
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import Inventory, Item, Player, migrate_study_spire_schema
from main import check_engine_status
from routes.admin import get_all_players_overview, import_excel


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

    def test_import_excel_preserves_class_and_extracts_grade(self):
        workbook = BytesIO()
        pd.DataFrame([{"Full Name": "Student Example", "Lớp": "6/2"}]).to_excel(
            workbook,
            index=False,
        )
        workbook.seek(0)

        async def import_students():
            with Session(self.engine) as session:
                with patch("routes.admin.get_password_hash", return_value="hash"):
                    first_result = await import_excel(
                        UploadFile(filename="students.xlsx", file=BytesIO(workbook.getvalue())),
                        grade=6,
                        db=session,
                    )
                    second_result = await import_excel(
                        UploadFile(filename="students.xlsx", file=BytesIO(workbook.getvalue())),
                        grade=6,
                        db=session,
                    )
                student = session.exec(
                    select(Player).where(Player.username == "studentexample")
                ).one()
                students = session.exec(
                    select(Player).where(Player.full_name == "Student Example")
                ).all()
                return first_result, second_result, student.grade, student.class_name, len(students)

        first_result, second_result, grade, class_name, student_count = asyncio.run(import_students())

        self.assertEqual(first_result["added"], 1)
        self.assertEqual(second_result["added"], 0)
        self.assertEqual(second_result["updated"], 1)
        self.assertEqual(grade, 6)
        self.assertEqual(class_name, "6.2")
        self.assertEqual(student_count, 1)

    def test_database_migration_adds_player_class_name_column(self):
        legacy_engine = create_engine("sqlite://")
        try:
            with legacy_engine.begin() as connection:
                connection.exec_driver_sql("CREATE TABLE player (id INTEGER PRIMARY KEY)")

            migrate_study_spire_schema(legacy_engine)

            columns = {column["name"] for column in inspect(legacy_engine).get_columns("player")}
            self.assertIn("class_name", columns)
        finally:
            legacy_engine.dispose()

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