import sys
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import Player, StudyMailboxMessage, StudyPackTemplate, StudyPlayerPack, get_db
from routes.auth import get_current_user
from routes.study_mailbox_api import router


class StudyMailboxApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            player = Player(
                username="mail_player",
                password_hash="hash",
                full_name="Học Giả",
                grade=7,
                class_name="7.5",
            )
            admin = Player(
                username="mail_admin",
                password_hash="hash",
                full_name="Admin",
                role="admin",
            )
            session.add_all([
                player,
                admin,
                StudyPackTemplate(pack_id="pack_ly", name="Pack Vật Lý", subject="ly", is_active=True),
                StudyPackTemplate(pack_id="pack_hoa", name="Pack Hóa Học", subject="hoa", is_active=True),
            ])
            session.commit()
            session.refresh(player)
            session.refresh(admin)
            self.player = player
            self.admin = admin
            self.auth_user = player

        app = FastAPI()
        app.include_router(router)

        def override_get_db():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_current_user] = lambda: self.auth_user
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_player_identity_is_fixed_and_admin_reply_is_unread_until_opened(self):
        sent = self.client.post(
            "/api/study-spire/mailbox/messages",
            json={
                "subject": " Góp ý game ",
                "body": "Thêm lựa chọn bộ bài.",
                "sender_name": "Tên giả",
                "sender_grade": 9,
            },
        )
        self.assertEqual(sent.status_code, 200, sent.text)
        sent_message = sent.json()
        self.assertEqual(sent_message["sender_name"], "Học Giả 7.5")
        self.assertEqual(sent_message["sender_grade"], 7)
        self.assertEqual(sent_message["subject"], "Góp ý game")

        self.auth_user = self.admin
        inbox = self.client.get("/api/study-spire/mailbox/admin/messages")
        self.assertEqual(inbox.status_code, 200, inbox.text)
        self.assertEqual(len(inbox.json()["messages"]), 1)
        self.assertFalse(inbox.json()["messages"][0]["is_read"])

        opened = self.client.post(
            f"/api/study-spire/mailbox/admin/messages/{sent_message['message_id']}/open"
        )
        self.assertEqual(opened.status_code, 200, opened.text)
        self.assertTrue(opened.json()["is_read"])

        reply = self.client.post(
            f"/api/study-spire/mailbox/admin/messages/{sent_message['message_id']}/reply",
            json={"reply_text": "Cảm ơn bạn đã góp ý."},
        )
        self.assertEqual(reply.status_code, 200, reply.text)

        self.auth_user = self.player
        player_inbox = self.client.get("/api/study-spire/mailbox/messages")
        self.assertEqual(player_inbox.status_code, 200, player_inbox.text)
        self.assertEqual(player_inbox.json()["unread_count"], 1)
        self.assertEqual(
            self.client.get("/api/study-spire/mailbox/unread-count").json()["unread_count"],
            1,
        )
        opened_reply = self.client.post(
            f"/api/study-spire/mailbox/messages/{sent_message['message_id']}/open"
        )
        self.assertEqual(opened_reply.status_code, 200, opened_reply.text)
        self.assertFalse(opened_reply.json()["has_unread_reply"])
        self.assertEqual(opened_reply.json()["admin_reply"], "Cảm ơn bạn đã góp ý.")
        self.assertEqual(self.client.get("/api/study-spire/mailbox/messages").json()["unread_count"], 0)
        self.assertEqual(
            self.client.get("/api/study-spire/mailbox/unread-count").json()["unread_count"],
            0,
        )

    def test_admin_can_gift_one_random_pack_directly_to_inventory(self):
        sent = self.client.post(
            "/api/study-spire/mailbox/messages",
            json={"subject": "Báo lỗi", "body": "Màn hình bị lỗi."},
        )
        self.assertEqual(sent.status_code, 200, sent.text)
        message_id = sent.json()["message_id"]
        self.auth_user = self.admin

        gifted = self.client.post(f"/api/study-spire/mailbox/admin/messages/{message_id}/gift")
        self.assertEqual(gifted.status_code, 200, gifted.text)
        result = gifted.json()
        self.assertIn(result["gift_pack_id"], {"pack_ly", "pack_hoa"})
        self.assertIn("Cảm ơn Học Giả 7.5 đã góp phần xây dựng game", result["admin_reply"])
        self.assertTrue(result["gift_sent_at"])
        with Session(self.engine) as session:
            inventory = session.exec(
                select(StudyPlayerPack).where(StudyPlayerPack.player_id == self.player.id)
            ).one()
            self.assertEqual(inventory.pack_id, result["gift_pack_id"])
            self.assertEqual(inventory.quantity, 1)

        duplicate = self.client.post(f"/api/study-spire/mailbox/admin/messages/{message_id}/gift")
        self.assertEqual(duplicate.status_code, 409)

    def test_non_admin_cannot_read_admin_inbox_or_send_replies(self):
        sent = self.client.post(
            "/api/study-spire/mailbox/messages",
            json={"subject": "Góp ý", "body": "Nội dung góp ý."},
        )
        message_id = sent.json()["message_id"]

        self.assertEqual(self.client.get("/api/study-spire/mailbox/admin/messages").status_code, 403)
        self.assertEqual(
            self.client.post(
                f"/api/study-spire/mailbox/admin/messages/{message_id}/reply",
                json={"reply_text": "Không được phép"},
            ).status_code,
            403,
        )


if __name__ == "__main__":
    unittest.main()
