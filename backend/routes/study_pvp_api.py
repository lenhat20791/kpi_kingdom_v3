"""Public PvP card rooms for Study Spire."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import string
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select, update

from database import (
    Player,
    StudyCardInstance,
    StudyCardTemplate,
    StudyDeck,
    StudyDeckCard,
    StudyPvpActionLedger,
    StudyPvpRoom,
    get_db,
)
from game_logic.study_spire import _ensure_battle_fields
from game_logic.study_spire_pvp import create_pvp_battle_state, end_pvp_turn, play_pvp_card
from game_logic.study_spire_relics import RELIC_BY_ID, pvp_loadout_ids
from routes.auth import get_current_user
from routes.study_game_api import _ensure_starter_deck, _json, ensure_catalog


router = APIRouter(prefix="/api/study-spire/pvp", tags=["Study Spire PvP"])
PASSWORD_ROUNDS = 180_000
ROOM_CODE_LENGTH = 6


class CreateRoomRequest(BaseModel):
    room_name: str = Field(min_length=2, max_length=48)
    password: str | None = Field(default=None, max_length=64)
    spectators_allowed: bool = True


class JoinRoomRequest(BaseModel):
    password: str | None = Field(default=None, max_length=64)


class ReadyRequest(BaseModel):
    ready: bool = True


class RoomActionRequest(BaseModel):
    expected_state_version: int = Field(ge=1)
    action_key: str = Field(min_length=8, max_length=120)


class PlayPvpCardRequest(RoomActionRequest):
    instance_id: str


def _password_hash(password: str | None) -> str | None:
    if not password:
        return None
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ROUNDS)
    return f"{salt.hex()}:{digest.hex()}"


def _password_matches(password: str | None, encoded: str | None) -> bool:
    if encoded is None:
        return not password
    if not password:
        return False
    try:
        salt_hex, expected_hex = encoded.split(":", maxsplit=1)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), PASSWORD_ROUNDS)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), expected_hex)


def _room_code_exists(db: Session, room_code: str) -> bool:
    return db.exec(select(StudyPvpRoom.room_id).where(StudyPvpRoom.room_code == room_code)).first() is not None


def _new_room_code(db: Session) -> str:
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(10):
        room_code = "".join(secrets.choice(alphabet) for _ in range(ROOM_CODE_LENGTH))
        if not _room_code_exists(db, room_code):
            return room_code
    raise HTTPException(status_code=503, detail="Không tạo được mã phòng. Hãy thử lại.")


def _get_room(db: Session, room_code: str) -> StudyPvpRoom:
    room = db.exec(select(StudyPvpRoom).where(StudyPvpRoom.room_code == room_code.upper())).first()
    if room is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy phòng PvP.")
    return room


def _player_name(db: Session, player_id: int) -> str:
    player = db.get(Player, player_id)
    return (player.full_name or player.username) if player else "Người chơi"


def _room_summary(db: Session, room: StudyPvpRoom) -> dict[str, Any]:
    return {
        "room_id": room.room_id,
        "room_code": room.room_code,
        "room_name": room.room_name,
        "host_player_id": room.host_player_id,
        "host_name": _player_name(db, room.host_player_id),
        "guest_player_id": room.guest_player_id,
        "guest_name": _player_name(db, room.guest_player_id) if room.guest_player_id else None,
        "status": room.status,
        "host_ready": room.host_ready,
        "guest_ready": room.guest_ready,
        "spectators_allowed": room.spectators_allowed,
        "has_password": bool(room.password_hash),
        "state_version": room.state_version,
        "created_at": room.created_at.isoformat(),
    }


def _load_player_deck(db: Session, player_id: int) -> list[dict[str, Any]]:
    deck, instance_ids = _ensure_starter_deck(db, player_id)
    if not deck or not instance_ids:
        raise HTTPException(status_code=409, detail="Người chơi chưa có deck Study Spire hợp lệ.")
    rows = db.exec(
        select(StudyCardInstance, StudyCardTemplate)
        .join(StudyCardTemplate, StudyCardInstance.card_id == StudyCardTemplate.card_id)
        .join(StudyDeckCard, StudyDeckCard.card_instance_id == StudyCardInstance.instance_id)
        .join(StudyDeck, StudyDeckCard.deck_id == StudyDeck.id)
        .where(
            StudyDeck.id == deck.id,
            StudyCardInstance.player_id == player_id,
            StudyCardTemplate.is_active == True,
        )
        .order_by(StudyDeckCard.position)
    ).all()
    cards = []
    for instance, template in rows:
        cards.append({
            "instance_id": instance.instance_id,
            "card_id": template.card_id,
            "name": template.name,
            "subject": template.subject,
            "rarity": template.rarity,
            "type": template.card_type,
            "card_type": template.card_type,
            "tags": _json(template.tags_json, []),
            "mana_cost": template.mana_cost,
            "description": template.description,
            "image_url": template.image_url,
            "effect_tooltips": _json(template.effect_tooltips_json, []),
            "effects": _json(template.effects_json, []),
            "exhaust": template.exhaust,
        })
    if not cards:
        raise HTTPException(status_code=409, detail="Deck hiện tại không có lá active để đấu PvP.")
    return cards


def _action_replay(db: Session, player_id: int, action_key: str) -> dict[str, Any] | None:
    action = db.exec(select(StudyPvpActionLedger).where(
        StudyPvpActionLedger.player_id == player_id,
        StudyPvpActionLedger.action_key == action_key,
    )).first()
    return _json(action.result_json, {}) if action else None


def _commit_room_action(
    db: Session,
    room: StudyPvpRoom,
    player_id: int,
    action_key: str,
    action_type: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    db.add(StudyPvpActionLedger(
        action_key=action_key,
        room_id=room.room_id,
        player_id=player_id,
        action_type=action_type,
        result_json=json.dumps(result, ensure_ascii=False),
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        replay = _action_replay(db, player_id, action_key)
        if replay is not None:
            return replay
        raise HTTPException(status_code=409, detail="Hành động vừa được xử lý ở phiên khác.")
    return result


def _battle_snapshot(room: StudyPvpRoom, viewer_id: int) -> dict[str, Any]:
    state = _json(room.battle_state_json, {})
    if not state:
        return {"status": room.status, "battle": None, "can_act": False, "spectator": False}

    host_id = room.host_player_id
    guest_id = room.guest_player_id
    is_player = viewer_id in {host_id, guest_id}
    spectator = not is_player
    players = []
    for player_key, seat in state["players"].items():
        player_id = int(player_key)
        can_view_hand = spectator or player_id == viewer_id
        hand_ids = seat["hand"]
        hand = [
            {"instance_id": instance_id, **state["cards"][instance_id]}
            for instance_id in hand_ids
            if instance_id in state["cards"]
        ] if can_view_hand else None
        players.append({
            "player_id": player_id,
            "username": seat["username"],
            "name": seat["name"],
            "hp": seat["stats"]["hp"],
            "hp_max": seat["stats"]["hp_max"],
            "mana": seat["stats"]["mana"],
            "mana_max": seat["stats"]["mana_max"],
            "shield": seat["stats"]["shield"],
            "strength": seat["stats"]["strength"],
            "active_effects": seat["stats"]["active_effects"],
            "hand": hand,
            "hand_count": len(hand_ids),
            "draw_count": len(seat["draw_pile"]),
            "discard_count": len(seat["discard_pile"]),
            "exhaust_count": len(seat["exhaust_pile"]),
            "relics": [
                {
                    "id": relic_id,
                    "name": RELIC_BY_ID[relic_id]["name"],
                    "image_url": f"/assets/items/charms/{RELIC_BY_ID[relic_id]['image']}",
                }
                for relic_id in seat.get("relic_ids", [])
                if relic_id in RELIC_BY_ID
            ],
            "is_active": player_id == int(state["active_player_id"]),
        })
    return {
        "status": room.status,
        "spectator": spectator,
        "can_act": is_player and viewer_id == int(state["active_player_id"]) and room.status == "ACTIVE",
        "state_version": room.state_version,
        "battle": {
            "turn_number": state["turn_number"],
            "active_player_id": int(state["active_player_id"]),
            "winner_player_id": state.get("winner_player_id"),
            "sudden_death": bool(state.get("sudden_death", False)),
            "players": players,
            "log": state.get("log", [])[-30:],
        },
    }


def _room_view(db: Session, room: StudyPvpRoom, viewer_id: int) -> dict[str, Any]:
    summary = _room_summary(db, room)
    if room.status == "ACTIVE" and viewer_id not in {room.host_player_id, room.guest_player_id} and not room.spectators_allowed:
        raise HTTPException(status_code=403, detail="Phòng này không cho phép quan chiến.")
    viewer_role = "host" if viewer_id == room.host_player_id else "guest" if viewer_id == room.guest_player_id else "spectator" if room.status == "ACTIVE" else "visitor"
    return {"room": summary, "viewer_role": viewer_role, **_battle_snapshot(room, viewer_id)}


def _start_battle(db: Session, room: StudyPvpRoom) -> dict[str, Any]:
    if room.guest_player_id is None:
        raise HTTPException(status_code=409, detail="Phòng chưa có đối thủ.")
    host = db.get(Player, room.host_player_id)
    guest = db.get(Player, room.guest_player_id)
    if not host or not guest:
        raise HTTPException(status_code=409, detail="Không tìm thấy tài khoản của người chơi.")
    host_cards = _load_player_deck(db, room.host_player_id)
    guest_cards = _load_player_deck(db, room.guest_player_id)
    room.battle_state_json = json.dumps(create_pvp_battle_state(
        room.host_player_id,
        host.username,
        host.full_name or host.username,
        host_cards,
        room.guest_player_id,
        guest.username,
        guest.full_name or guest.username,
        guest_cards,
        secrets.randbits(32),
        host_relic_ids=pvp_loadout_ids(db, room.host_player_id),
        guest_relic_ids=pvp_loadout_ids(db, room.guest_player_id),
    ), ensure_ascii=False)
    room.status = "ACTIVE"
    room.state_version += 1
    room.updated_at = datetime.now()
    db.add(room)
    db.flush()
    return _room_view(db, room, room.host_player_id)


@router.get("/lobby")
def list_pvp_rooms(
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rooms = db.exec(
        select(StudyPvpRoom)
        .where(StudyPvpRoom.status.in_(["WAITING", "ACTIVE"]))
        .order_by(StudyPvpRoom.created_at.desc())
    ).all()
    return {
        "rooms": [
            _room_summary(db, room)
            for room in rooms
            if room.status == "WAITING" or room.spectators_allowed or current_user.id in {room.host_player_id, room.guest_player_id}
        ]
    }


@router.post("/rooms")
def create_pvp_room(
    request: CreateRoomRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room_name = request.room_name.strip()
    if len(room_name) < 2:
        raise HTTPException(status_code=422, detail="Tên phòng cần ít nhất 2 ký tự.")
    password = request.password.strip() if request.password else ""
    if password and len(password) < 4:
        raise HTTPException(status_code=422, detail="Mật khẩu phòng cần ít nhất 4 ký tự.")

    ensure_catalog(db)
    _load_player_deck(db, current_user.id)
    room = StudyPvpRoom(
        room_code=_new_room_code(db),
        room_name=room_name,
        host_player_id=current_user.id,
        password_hash=_password_hash(password or None),
        spectators_allowed=request.spectators_allowed,
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return {"room": _room_summary(db, room)}


@router.post("/rooms/{room_code}/join")
def join_pvp_room(
    room_code: str,
    request: JoinRoomRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = _get_room(db, room_code)
    if room.status != "WAITING":
        raise HTTPException(status_code=409, detail="Phòng đã bắt đầu hoặc đã đóng.")
    if current_user.id == room.host_player_id:
        raise HTTPException(status_code=409, detail="Bạn là chủ phòng.")
    if room.guest_player_id is not None:
        if room.guest_player_id == current_user.id:
            return {"room": _room_summary(db, room)}
        raise HTTPException(status_code=409, detail="Phòng đã đủ người.")
    if not _password_matches(request.password, room.password_hash):
        raise HTTPException(status_code=403, detail="Mật khẩu phòng không đúng.")

    ensure_catalog(db)
    _load_player_deck(db, current_user.id)
    room.guest_player_id = current_user.id
    room.guest_ready = False
    room.state_version += 1
    room.updated_at = datetime.now()
    db.add(room)
    db.commit()
    return {"room": _room_summary(db, room)}


@router.get("/rooms/{room_code}/state")
def get_pvp_room_state(
    room_code: str,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _room_view(db, _get_room(db, room_code), current_user.id)


@router.post("/rooms/{room_code}/spectate")
def spectate_pvp_room(
    room_code: str,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = _get_room(db, room_code)
    if room.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Chỉ có thể quan chiến trận đang diễn ra.")
    if not room.spectators_allowed and current_user.id not in {room.host_player_id, room.guest_player_id}:
        raise HTTPException(status_code=403, detail="Chủ phòng đã tắt quyền quan chiến.")
    return _room_view(db, room, current_user.id)


@router.post("/rooms/{room_code}/leave")
def leave_pvp_room(
    room_code: str,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = _get_room(db, room_code)
    if current_user.id not in {room.host_player_id, room.guest_player_id}:
        raise HTTPException(status_code=403, detail="Bạn không phải người chơi trong phòng.")
    if room.status == "WAITING":
        if current_user.id == room.host_player_id:
            room.status = "CANCELLED"
        else:
            room.guest_player_id = None
            room.guest_ready = False
        room.state_version += 1
        room.updated_at = datetime.now()
        db.add(room)
        db.commit()
        return {"success": True, "status": room.status, "room": _room_summary(db, room)}
    if room.status == "ACTIVE":
        winner_id = room.guest_player_id if current_user.id == room.host_player_id else room.host_player_id
        state = _json(room.battle_state_json, {})
        state["winner_player_id"] = winner_id
        room.battle_state_json = json.dumps(state, ensure_ascii=False)
        room.winner_player_id = winner_id
        room.status = "FINISHED"
        room.state_version += 1
        room.updated_at = datetime.now()
        db.add(room)
        db.commit()
        return {"success": True, "status": room.status, "winner_player_id": winner_id, "room": _room_summary(db, room)}
    return {"success": True, "status": room.status, "room": _room_summary(db, room)}


@router.post("/rooms/{room_code}/ready")
def set_pvp_ready(
    room_code: str,
    request: ReadyRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = _get_room(db, room_code)
    if room.status != "WAITING" or room.guest_player_id is None:
        raise HTTPException(status_code=409, detail="Cần đủ hai người trong phòng chờ.")
    if current_user.id == room.host_player_id:
        room.host_ready = request.ready
    elif current_user.id == room.guest_player_id:
        room.guest_ready = request.ready
    else:
        raise HTTPException(status_code=403, detail="Bạn không phải người chơi trong phòng.")
    room.state_version += 1
    room.updated_at = datetime.now()
    db.add(room)
    db.commit()
    return {"room": _room_summary(db, room)}


@router.post("/rooms/{room_code}/start")
def start_pvp_room(
    room_code: str,
    request: RoomActionRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    replay = _action_replay(db, current_user.id, request.action_key)
    if replay is not None:
        return replay
    room = _get_room(db, room_code)
    if current_user.id != room.host_player_id:
        raise HTTPException(status_code=403, detail="Chỉ chủ phòng mới được bắt đầu trận.")
    if room.status != "WAITING" or not room.guest_player_id or not (room.host_ready and room.guest_ready):
        raise HTTPException(status_code=409, detail="Cả hai người chơi cần sẵn sàng trước khi bắt đầu.")
    if room.state_version != request.expected_state_version:
        raise HTTPException(status_code=409, detail="Phòng vừa thay đổi. Hãy tải lại.")
    result = _start_battle(db, room)
    return _commit_room_action(db, room, current_user.id, request.action_key, "start", result)


def _require_active_player(room: StudyPvpRoom, state: dict[str, Any], player_id: int) -> None:
    if room.status != "ACTIVE" or not state:
        raise HTTPException(status_code=409, detail="Trận đấu chưa bắt đầu hoặc đã kết thúc.")
    if player_id not in {room.host_player_id, room.guest_player_id}:
        raise HTTPException(status_code=403, detail="Spectator không được thao tác trận đấu.")
    if int(state["active_player_id"]) != player_id:
        raise HTTPException(status_code=409, detail="Chưa đến lượt của bạn.")


def _save_pvp_action(
    db: Session,
    room: StudyPvpRoom,
    player_id: int,
    request: RoomActionRequest,
    action_type: str,
    battle_state: dict[str, Any],
) -> dict[str, Any]:
    if room.state_version != request.expected_state_version:
        raise HTTPException(status_code=409, detail="Trạng thái trận đấu vừa thay đổi. Hãy tải lại.")
    room.state_version += 1
    room.battle_state_json = json.dumps(battle_state, ensure_ascii=False)
    room.status = "FINISHED" if battle_state.get("winner_player_id") else "ACTIVE"
    room.winner_player_id = battle_state.get("winner_player_id")
    room.updated_at = datetime.now()
    db.add(room)
    db.flush()
    result = _room_view(db, room, player_id)
    return _commit_room_action(db, room, player_id, request.action_key, action_type, result)


@router.post("/rooms/{room_code}/play-card")
def play_pvp_card_endpoint(
    room_code: str,
    request: PlayPvpCardRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    replay = _action_replay(db, current_user.id, request.action_key)
    if replay is not None:
        return replay
    room = _get_room(db, room_code)
    state = _json(room.battle_state_json, {})
    _require_active_player(room, state, current_user.id)
    if room.state_version != request.expected_state_version:
        raise HTTPException(status_code=409, detail="Trạng thái trận đấu vừa thay đổi. Hãy tải lại.")
    try:
        updated = play_pvp_card(state, current_user.id, request.instance_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _save_pvp_action(db, room, current_user.id, request, "play_card", updated)


@router.post("/rooms/{room_code}/end-turn")
def end_pvp_room_turn(
    room_code: str,
    request: RoomActionRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    replay = _action_replay(db, current_user.id, request.action_key)
    if replay is not None:
        return replay
    room = _get_room(db, room_code)
    state = _json(room.battle_state_json, {})
    _require_active_player(room, state, current_user.id)
    if room.state_version != request.expected_state_version:
        raise HTTPException(status_code=409, detail="Trạng thái trận đấu vừa thay đổi. Hãy tải lại.")
    updated = end_pvp_turn(state, current_user.id)
    return _save_pvp_action(db, room, current_user.id, request, "end_turn", updated)