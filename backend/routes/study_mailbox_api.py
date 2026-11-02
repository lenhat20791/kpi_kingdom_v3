import secrets
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, select, update, func

from database import (
    Player,
    StudyMailboxMessage,
    StudyPackTemplate,
    StudyPlayerPack,
    get_db,
    player_display_name,
)
from routes.auth import get_current_user


router = APIRouter(prefix="/api/study-spire/mailbox", tags=["Study Spire Mailbox"])


class SubmitMessageRequest(BaseModel):
    subject: str = PydanticField(min_length=1, max_length=120)
    body: str = PydanticField(min_length=1, max_length=5000)


class ReplyMessageRequest(BaseModel):
    reply_text: str = PydanticField(min_length=1, max_length=5000)


def _require_admin(current_user: Player) -> None:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Chỉ quản trị viên mới được truy cập thư từ học giả.")


def _get_message(db: Session, message_id: str) -> StudyMailboxMessage:
    message = db.get(StudyMailboxMessage, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy thư.")
    return message


def _message_data(message: StudyMailboxMessage, *, admin_view: bool = False) -> dict[str, Any]:
    result = {
        "message_id": message.message_id,
        "sender_name": message.sender_name,
        "sender_grade": message.sender_grade,
        "subject": message.subject,
        "body": message.body,
        "created_at": message.created_at.isoformat(),
        "admin_reply": message.admin_reply,
        "admin_reply_at": message.admin_reply_at.isoformat() if message.admin_reply_at else None,
        "gift_pack_id": message.gift_pack_id,
        "gift_sent_at": message.gift_sent_at.isoformat() if message.gift_sent_at else None,
    }
    if admin_view:
        result["is_read"] = message.admin_read_at is not None
    else:
        result["has_unread_reply"] = bool(message.admin_reply and message.player_read_at is None)
    return result


@router.get("/messages")
def list_player_messages(
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    messages = db.exec(
        select(StudyMailboxMessage)
        .where(StudyMailboxMessage.player_id == current_user.id)
        .order_by(StudyMailboxMessage.created_at.desc())
        .limit(100)
    ).all()
    return {
        "messages": [_message_data(message) for message in messages],
        "unread_count": _unread_reply_count(db, current_user.id),
    }


def _unread_reply_count(db: Session, player_id: int) -> int:
    return int(db.exec(
        select(func.count(StudyMailboxMessage.message_id)).where(
            StudyMailboxMessage.player_id == player_id,
            StudyMailboxMessage.admin_reply.is_not(None),
            StudyMailboxMessage.player_read_at.is_(None),
        )
    ).one())


@router.get("/unread-count")
def get_unread_reply_count(
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {"unread_count": _unread_reply_count(db, current_user.id)}


@router.post("/messages")
def submit_player_message(
    request: SubmitMessageRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    subject = request.subject.strip()
    body = request.body.strip()
    if not subject or not body:
        raise HTTPException(status_code=422, detail="Tiêu đề và nội dung thư không được để trống.")
    message = StudyMailboxMessage(
        player_id=current_user.id,
        sender_name=player_display_name(current_user),
        sender_grade=current_user.grade,
        subject=subject,
        body=body,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return _message_data(message)


@router.post("/messages/{message_id}/open")
def open_player_message(
    message_id: str,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    message = _get_message(db, message_id)
    if message.player_id != current_user.id:
        raise HTTPException(status_code=404, detail="Không tìm thấy thư.")
    if message.admin_reply and message.player_read_at is None:
        message.player_read_at = datetime.now()
        db.add(message)
        db.commit()
        db.refresh(message)
    return _message_data(message)


@router.get("/admin/messages")
def list_admin_messages(
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    messages = db.exec(
        select(StudyMailboxMessage)
        .order_by(StudyMailboxMessage.created_at.desc())
        .limit(200)
    ).all()
    return {"messages": [_message_data(message, admin_view=True) for message in messages]}


@router.post("/admin/messages/{message_id}/open")
def open_admin_message(
    message_id: str,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    message = _get_message(db, message_id)
    if message.admin_read_at is None:
        message.admin_read_at = datetime.now()
        db.add(message)
        db.commit()
        db.refresh(message)
    return _message_data(message, admin_view=True)


@router.post("/admin/messages/{message_id}/reply")
def reply_to_player_message(
    message_id: str,
    request: ReplyMessageRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    message = _get_message(db, message_id)
    reply_text = request.reply_text.strip()
    if not reply_text:
        raise HTTPException(status_code=422, detail="Nội dung phản hồi không được để trống.")
    message.admin_reply = reply_text
    message.admin_reply_at = datetime.now()
    message.player_read_at = None
    db.add(message)
    db.commit()
    db.refresh(message)
    return _message_data(message, admin_view=True)


@router.post("/admin/messages/{message_id}/gift")
def gift_random_pack(
    message_id: str,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    message = _get_message(db, message_id)
    if message.gift_sent_at is not None:
        raise HTTPException(status_code=409, detail="Thư này đã được tặng pack.")

    packs = db.exec(
        select(StudyPackTemplate).where(StudyPackTemplate.is_active == True)
    ).all()
    if not packs:
        raise HTTPException(status_code=503, detail="Hiện không có pack bài nào khả dụng để tặng.")

    gift_sent_at = datetime.now()
    claim = db.exec(
        update(StudyMailboxMessage)
        .where(
            StudyMailboxMessage.message_id == message_id,
            StudyMailboxMessage.gift_sent_at.is_(None),
        )
        .values(gift_sent_at=gift_sent_at)
        .execution_options(synchronize_session=False)
    )
    if claim.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Thư này đã được tặng pack.")

    pack = secrets.choice(packs)
    inventory = db.exec(
        select(StudyPlayerPack).where(
            StudyPlayerPack.player_id == message.player_id,
            StudyPlayerPack.pack_id == pack.pack_id,
        )
    ).first()
    if inventory:
        inventory.quantity += 1
        inventory.state_version += 1
    else:
        inventory = StudyPlayerPack(
            player_id=message.player_id,
            pack_id=pack.pack_id,
            quantity=1,
            state_version=1,
        )
    db.add(inventory)

    notification = (
        f"Cảm ơn {message.sender_name} đã góp phần xây dựng game , "
        f"đây là món quà nhỏ gửi đến {message.sender_name}, "
        "hãy kiểm tra kho đồ để nhận quà!"
    )
    message.admin_reply = (
        f"{message.admin_reply.rstrip()}\n\n{notification}"
        if message.admin_reply
        else notification
    )
    message.admin_reply_at = datetime.now()
    message.player_read_at = None
    message.gift_pack_id = pack.pack_id
    message.gift_sent_at = gift_sent_at
    db.add(message)
    db.commit()
    db.refresh(message)

    result = _message_data(message, admin_view=True)
    result["gift_pack_name"] = pack.name
    return result
