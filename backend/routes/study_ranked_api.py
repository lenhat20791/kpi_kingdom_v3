"""Asynchronous ranked matches for Study Spire."""

from __future__ import annotations

import json
import random
from copy import deepcopy
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from database import Player, StudyRankedMatch, StudyRankedPlayer, get_db, player_display_name
from game_logic.study_spire_pvp import create_pvp_battle_state, end_pvp_turn, play_pvp_card
from game_logic.study_spire_relics import RELIC_BY_ID, pvp_loadout_ids
from routes.auth import get_current_user
from routes.study_game_api import STUDY_AVATAR_DIR, _json, ensure_catalog
from routes.study_pvp_api import _load_player_deck


router = APIRouter(prefix="/api/study-spire/ranked", tags=["Study Spire Ranked"])
PLACEMENT_MATCH_COUNT = 3
TOP_RANK_COUNT = 20
CHALLENGE_BATCH_SIZE = 3


class StartRankedMatchRequest(BaseModel):
    opponent_player_id: int = Field(gt=0)


class RankedActionRequest(BaseModel):
    expected_state_version: int = Field(ge=1)


class RankedPlayCardRequest(RankedActionRequest):
    instance_id: str


def _ensure_profile(db: Session, player_id: int) -> StudyRankedPlayer:
    profile = db.get(StudyRankedPlayer, player_id)
    if profile is None:
        profile = StudyRankedPlayer(player_id=player_id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def _rank_rows(db: Session) -> list[tuple[StudyRankedPlayer, Player]]:
    rows = db.exec(
        select(StudyRankedPlayer, Player)
        .join(Player, StudyRankedPlayer.player_id == Player.id)
        .where(StudyRankedPlayer.rank_position.is_not(None), Player.role != "admin")
        .order_by(StudyRankedPlayer.rank_position)
    ).all()
    return rows


def _player_avatar(player: Player) -> str | None:
    avatar_path = STUDY_AVATAR_DIR / f"player_{player.id}.png"
    if avatar_path.is_file():
        return f"/assets/images/avatars/study_spire/{avatar_path.name}?v={avatar_path.stat().st_mtime_ns}"
    if player.class_type and player.class_type != "NOVICE":
        return f"/assets/images/avatars/{player.class_type.lower()}.png"
    return "/assets/images/avatars/default.png"


def _player_summary(profile: StudyRankedPlayer, player: Player) -> dict[str, Any]:
    return {
        "player_id": player.id,
        "name": player_display_name(player),
        "avatar_url": _player_avatar(player),
        "rank_position": profile.rank_position,
        "placement_matches": profile.placement_matches,
        "placement_wins": profile.placement_wins,
    }


def _active_challenger_match(db: Session, player_id: int) -> StudyRankedMatch | None:
    return db.exec(
        select(StudyRankedMatch)
        .where(
            StudyRankedMatch.status == "ACTIVE",
            StudyRankedMatch.challenger_player_id == player_id,
        )
        .order_by(StudyRankedMatch.created_at.desc())
    ).first()


def _active_ranked_match_involving(db: Session, player_id: int) -> StudyRankedMatch | None:
    return db.exec(
        select(StudyRankedMatch)
        .where(
            StudyRankedMatch.status == "ACTIVE",
            StudyRankedMatch.match_type == "RANKED",
            (StudyRankedMatch.challenger_player_id == player_id)
            | (StudyRankedMatch.opponent_player_id == player_id),
        )
        .order_by(StudyRankedMatch.created_at.desc())
    ).first()


def _active_ranked_player_ids(db: Session) -> set[int]:
    rows = db.exec(
        select(StudyRankedMatch.challenger_player_id, StudyRankedMatch.opponent_player_id)
        .where(StudyRankedMatch.status == "ACTIVE", StudyRankedMatch.match_type == "RANKED")
    ).all()
    return {player_id for row in rows for player_id in row}


def _ranked_ladder_started(db: Session) -> bool:
    return db.exec(
        select(StudyRankedMatch.match_id)
        .where(StudyRankedMatch.match_type == "RANKED")
    ).first() is not None


def _available_opponents(
    db: Session,
    player_id: int,
    profile: StudyRankedPlayer,
    batch: int,
    busy_player_ids: set[int],
) -> tuple[list[dict[str, Any]], int]:
    if player_id in busy_player_ids:
        return [], 0
    ranked_rows = _rank_rows(db)
    ranked_by_id = {ranked.player_id: ranked for ranked, _ in ranked_rows}
    if profile.rank_position is not None:
        eligible = [
            (ranked, player)
            for ranked, player in ranked_rows
            if ranked.rank_position < profile.rank_position
            and player.id not in busy_player_ids
        ]
        eligible.sort(key=lambda row: row[0].rank_position, reverse=True)
    else:
        eligible = [
            (ranked_by_id[player.id], player)
            for player in db.exec(select(Player).where(Player.role != "admin", Player.id != player_id)).all()
            if player.id in ranked_by_id
        ]
        ranked_ids = set(ranked_by_id)
        eligible.extend(
            (None, player)
            for player in db.exec(select(Player).where(Player.role != "admin", Player.id != player_id)).all()
            if player.id not in ranked_ids
        )
        eligible.sort(key=lambda row: (row[0] is None, row[0].rank_position if row[0] else row[1].id))

    offset = batch * CHALLENGE_BATCH_SIZE
    selected = eligible[offset:offset + CHALLENGE_BATCH_SIZE]
    output = []
    for ranked, player in selected:
        if ranked is None:
            output.append({
                "player_id": player.id,
                "name": player_display_name(player),
                "avatar_url": _player_avatar(player),
                "rank_position": None,
                "placement_matches": 0,
            })
        else:
            output.append(_player_summary(ranked, player))
    return output, len(eligible)


def _overview(
    db: Session,
    player: Player,
    batch: int = 0,
) -> dict[str, Any]:
    profile = _ensure_profile(db, player.id)
    ranked_rows = _rank_rows(db)
    top = [
        _player_summary(ranked, entry)
        for ranked, entry in ranked_rows[:TOP_RANK_COUNT]
    ]
    busy_player_ids = _active_ranked_player_ids(db)
    for entry in top:
        entry["rank_busy"] = entry["player_id"] in busy_player_ids
    active_match = _active_challenger_match(db, player.id)
    incoming_match = db.exec(
        select(StudyRankedMatch)
        .where(
            StudyRankedMatch.status == "ACTIVE",
            StudyRankedMatch.match_type == "RANKED",
            StudyRankedMatch.opponent_player_id == player.id,
        )
    ).first()
    opponents, opponent_total = _available_opponents(db, player.id, profile, batch, busy_player_ids)
    ladder_started = _ranked_ladder_started(db)

    return {
        "top_players": top,
        "ranked_player_count": len(ranked_rows),
        "player": _player_summary(profile, player),
        "placement_required": profile.rank_position is None,
        "placement_matches_required": PLACEMENT_MATCH_COUNT,
        "placement_uses_score": not ladder_started,
        "opponents": opponents,
        "opponent_batch": batch,
        "opponent_batch_size": CHALLENGE_BATCH_SIZE,
        "has_next_opponent_batch": incoming_match is None and (batch + 1) * CHALLENGE_BATCH_SIZE < opponent_total,
        "active_match_id": active_match.match_id if active_match and active_match.challenger_player_id == player.id else None,
        "rank_locked_by_match": incoming_match is not None,
    }


def _match_snapshot(db: Session, match: StudyRankedMatch, viewer_id: int) -> dict[str, Any]:
    state = _json(match.battle_state_json, {})
    if not state:
        raise HTTPException(status_code=409, detail="Không tìm thấy trạng thái trận đấu.")
    players = []
    for player_key, seat in state["players"].items():
        player_id = int(player_key)
        player = db.get(Player, player_id)
        hand = [
            {"instance_id": instance_id, **state["cards"][instance_id]}
            for instance_id in seat["hand"]
            if player_id == viewer_id and instance_id in state["cards"]
        ]
        players.append({
            "player_id": player_id,
            "username": seat["username"],
            "name": player_display_name(player) if player else seat["name"],
            "hp": seat["stats"]["hp"],
            "hp_max": seat["stats"]["hp_max"],
            "mana": seat["stats"]["mana"],
            "mana_max": seat["stats"]["mana_max"],
            "shield": seat["stats"]["shield"],
            "strength": seat["stats"]["strength"],
            "active_effects": seat["stats"]["active_effects"],
            "hand": hand if player_id == viewer_id else None,
            "hand_count": len(seat["hand"]),
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
    challenger = db.get(Player, match.challenger_player_id)
    opponent = db.get(Player, match.opponent_player_id)
    if challenger is None or opponent is None:
        raise HTTPException(status_code=409, detail="Không tìm thấy tài khoản trong trận.")
    return {
        "status": match.status,
        "spectator": False,
        "can_act": (
            match.status == "ACTIVE"
            and viewer_id == match.challenger_player_id
            and int(state["active_player_id"]) == viewer_id
        ),
        "state_version": match.state_version,
        "match_id": match.match_id,
        "match_type": match.match_type,
        "viewer_role": "host",
        "room": {
            "room_code": "XH",
            "room_name": "Trận phân hạng" if match.match_type == "PLACEMENT" else "Trận leo hạng",
            "host_player_id": match.challenger_player_id,
            "host_name": player_display_name(challenger),
            "guest_player_id": match.opponent_player_id,
            "guest_name": player_display_name(opponent),
        },
        "battle": {
            "turn_number": state["turn_number"],
            "active_player_id": int(state["active_player_id"]),
            "winner_player_id": state.get("winner_player_id"),
            "sudden_death": bool(state.get("sudden_death", False)),
            "players": players,
            "log": state.get("log", [])[-30:],
        },
        "rank_result": _json(match.rank_result_json, {}),
    }


def _finish_ranked_match(db: Session, match: StudyRankedMatch, winner_id: int) -> None:
    if match.status == "FINISHED":
        return
    match.status = "FINISHED"
    match.winner_player_id = winner_id
    result: dict[str, Any] = {"winner_player_id": winner_id, "rank_changed": False}
    if match.match_type == "PLACEMENT":
        profile = _ensure_profile(db, match.challenger_player_id)
        profile.placement_matches += 1
        if winner_id == match.challenger_player_id:
            profile.placement_wins += 1
        if profile.placement_matches >= PLACEMENT_MATCH_COUNT and profile.rank_position is None:
            ranked_rows = _rank_rows(db)
            if _ranked_ladder_started(db):
                profile.rank_position = max(
                    (row.rank_position for row, _ in ranked_rows if row.rank_position is not None),
                    default=0,
                ) + 1
            else:
                profile.rank_position = next(
                    (
                        row.rank_position
                        for row, _ in ranked_rows
                        if row.placement_wins < profile.placement_wins
                    ),
                    max((row.rank_position for row, _ in ranked_rows if row.rank_position is not None), default=0) + 1,
                )
                for row, _ in sorted(
                    ranked_rows,
                    key=lambda candidate: candidate[0].rank_position or 0,
                    reverse=True,
                ):
                    if row.rank_position >= profile.rank_position:
                        row.rank_position += 1
                        db.add(row)
            result["rank_changed"] = True
            result["new_rank"] = profile.rank_position
            result["placement_uses_score"] = not _ranked_ladder_started(db)
        result["placement_matches"] = profile.placement_matches
        result["placement_wins"] = profile.placement_wins
        profile.updated_at = datetime.now()
        db.add(profile)
    elif winner_id == match.challenger_player_id:
        challenger = db.get(StudyRankedPlayer, match.challenger_player_id)
        opponent = db.get(StudyRankedPlayer, match.opponent_player_id)
        if (
            challenger is not None and opponent is not None
            and challenger.rank_position == match.challenger_rank_at_start
            and opponent.rank_position == match.opponent_rank_at_start
        ):
            challenger.rank_position, opponent.rank_position = opponent.rank_position, challenger.rank_position
            challenger.updated_at = opponent.updated_at = datetime.now()
            db.add(challenger)
            db.add(opponent)
            result.update({
                "rank_changed": True,
                "player_rank": challenger.rank_position,
                "opponent_rank": opponent.rank_position,
            })
    match.rank_result_json = json.dumps(result, ensure_ascii=False)
    match.updated_at = datetime.now()
    db.add(match)


def _save_battle(db: Session, match: StudyRankedMatch, state: dict[str, Any]) -> None:
    match.battle_state_json = json.dumps(state, ensure_ascii=False)
    match.state_version += 1
    match.updated_at = datetime.now()
    winner_id = state.get("winner_player_id")
    if winner_id is not None:
        _finish_ranked_match(db, match, int(winner_id))
    db.add(match)
    db.commit()
    db.refresh(match)


def _seat_score(state: dict[str, Any], player_id: int) -> float:
    seat = state["players"][str(player_id)]
    stats = seat["stats"]
    return (
        float(stats["hp"]) * 2
        + float(stats.get("shield", 0)) * 0.6
        + float(stats.get("strength", 0)) * 1.2
        + sum(
            float(effect.get("stacks", 0)) * (2.4 if effect.get("type") == "poison" else 0.8)
            for effect in stats.get("active_effects", [])
        )
    )


def _bot_play_turn(state: dict[str, Any], bot_id: int) -> dict[str, Any]:
    bot = state["players"][str(bot_id)]
    for _ in range(30):
        if state.get("winner_player_id") is not None or int(state["active_player_id"]) != bot_id:
            return state
        best_state = None
        best_gain = 0.0
        for instance_id in list(bot["hand"]):
            trial = deepcopy(state)
            before = _seat_score(trial, bot_id) - _seat_score(trial, next(
                int(candidate) for candidate in trial["players"] if int(candidate) != bot_id
            ))
            try:
                trial = play_pvp_card(trial, bot_id, instance_id)
            except ValueError:
                continue
            after = _seat_score(trial, bot_id) - _seat_score(trial, next(
                int(candidate) for candidate in trial["players"] if int(candidate) != bot_id
            ))
            gain = after - before
            if gain > best_gain:
                best_gain = gain
                best_state = trial
        if best_state is None:
            break
        state = best_state
        bot = state["players"][str(bot_id)]
    return state


def _run_bot_turns(state: dict[str, Any], bot_id: int, human_id: int) -> dict[str, Any]:
    for _ in range(100):
        if state.get("winner_player_id") is not None or int(state["active_player_id"]) != bot_id:
            return state
        state = _bot_play_turn(state, bot_id)
        state = end_pvp_turn(state, bot_id)
    if int(state["active_player_id"]) == bot_id and state.get("winner_player_id") is None:
        raise HTTPException(status_code=409, detail="Bot không thể kết thúc lượt an toàn.")
    return state


@router.get("/board")
def get_ranked_board(
    batch: int = 0,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if batch < 0:
        raise HTTPException(status_code=422, detail="Nhóm đối thủ không hợp lệ.")
    if current_user.role == "admin":
        raise HTTPException(status_code=403, detail="Tài khoản quản trị không tham gia xếp hạng.")
    ensure_catalog(db)
    return _overview(db, current_user, batch)


@router.post("/matches")
def start_ranked_match(
    request: StartRankedMatchRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if request.opponent_player_id == current_user.id:
        raise HTTPException(status_code=422, detail="Bạn không thể thách đấu chính mình.")
    if current_user.role == "admin":
        raise HTTPException(status_code=403, detail="Tài khoản quản trị không tham gia xếp hạng.")
    ensure_catalog(db)
    profile = _ensure_profile(db, current_user.id)
    if _active_challenger_match(db, current_user.id):
        raise HTTPException(status_code=409, detail="Bạn cần hoàn thành trận xếp hạng đang chơi trước.")
    if _active_ranked_match_involving(db, current_user.id):
        raise HTTPException(status_code=409, detail="Hạng của bạn đang được thách đấu. Hãy chờ trận đó kết thúc.")
    opponent = db.get(Player, request.opponent_player_id)
    if opponent is None or opponent.role == "admin":
        raise HTTPException(status_code=404, detail="Không tìm thấy người chơi hợp lệ.")

    opponent_profile = db.get(StudyRankedPlayer, opponent.id)
    match_type = "PLACEMENT" if profile.rank_position is None else "RANKED"
    if match_type == "PLACEMENT":
        if profile.placement_matches >= PLACEMENT_MATCH_COUNT:
            raise HTTPException(status_code=409, detail="Trạng thái phân hạng không hợp lệ. Hãy tải lại bảng.")
    else:
        if (
            opponent_profile is None or opponent_profile.rank_position is None
            or opponent_profile.rank_position >= profile.rank_position
            or profile.rank_position - opponent_profile.rank_position > CHALLENGE_BATCH_SIZE
        ):
            raise HTTPException(status_code=409, detail="Chỉ có thể thách đấu một trong ba người ngay phía trên bạn.")
        if _active_ranked_match_involving(db, opponent.id):
            raise HTTPException(status_code=409, detail="Đối thủ đang có một trận leo hạng khác.")

    ensure_catalog(db)
    challenger_cards = _load_player_deck(db, current_user.id)
    opponent_cards = _load_player_deck(db, opponent.id)
    battle_state = create_pvp_battle_state(
        current_user.id,
        current_user.username,
        player_display_name(current_user),
        challenger_cards,
        opponent.id,
        opponent.username,
        player_display_name(opponent),
        opponent_cards,
        random.SystemRandom().randrange(0, 2**32),
        host_relic_ids=pvp_loadout_ids(db, current_user.id),
        guest_relic_ids=pvp_loadout_ids(db, opponent.id),
    )
    match = StudyRankedMatch(
        challenger_player_id=current_user.id,
        opponent_player_id=opponent.id,
        match_type=match_type,
        battle_state_json=json.dumps(battle_state, ensure_ascii=False),
        challenger_rank_at_start=profile.rank_position,
        opponent_rank_at_start=opponent_profile.rank_position if opponent_profile else None,
    )
    db.add(match)
    db.commit()
    db.refresh(match)
    return _match_snapshot(db, match, current_user.id)


@router.get("/matches/{match_id}")
def get_ranked_match(
    match_id: str,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    match = db.get(StudyRankedMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy trận xếp hạng.")
    if current_user.id != match.challenger_player_id:
        raise HTTPException(status_code=403, detail="Bạn không tham gia trận đấu này.")
    return _match_snapshot(db, match, current_user.id)


def _load_active_match(db: Session, match_id: str, player_id: int, request: RankedActionRequest) -> tuple[StudyRankedMatch, dict[str, Any]]:
    match = db.get(StudyRankedMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy trận xếp hạng.")
    if player_id != match.challenger_player_id:
        raise HTTPException(status_code=403, detail="Chỉ người thách đấu mới được thao tác.")
    if match.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Trận đấu đã kết thúc.")
    if match.state_version != request.expected_state_version:
        raise HTTPException(status_code=409, detail="Trạng thái trận đấu vừa thay đổi. Hãy tải lại.")
    state = _json(match.battle_state_json, {})
    if int(state.get("active_player_id", -1)) != player_id:
        raise HTTPException(status_code=409, detail="Chưa đến lượt của bạn.")
    return match, state


@router.post("/matches/{match_id}/play-card")
def play_ranked_card(
    match_id: str,
    request: RankedPlayCardRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    match, state = _load_active_match(db, match_id, current_user.id, request)
    try:
        state = play_pvp_card(state, current_user.id, request.instance_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if state.get("winner_player_id") is None:
        state = _run_bot_turns(state, match.opponent_player_id, current_user.id)
    _save_battle(db, match, state)
    return _match_snapshot(db, match, current_user.id)


@router.post("/matches/{match_id}/end-turn")
def end_ranked_turn(
    match_id: str,
    request: RankedActionRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    match, state = _load_active_match(db, match_id, current_user.id, request)
    state = end_pvp_turn(state, current_user.id)
    if state.get("winner_player_id") is None:
        state = _run_bot_turns(state, match.opponent_player_id, current_user.id)
    _save_battle(db, match, state)
    return _match_snapshot(db, match, current_user.id)


@router.post("/matches/{match_id}/forfeit")
def forfeit_ranked_match(
    match_id: str,
    request: RankedActionRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    match = db.get(StudyRankedMatch, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy trận xếp hạng.")
    if current_user.id != match.challenger_player_id:
        raise HTTPException(status_code=403, detail="Bạn không tham gia trận đấu này.")
    if match.status != "ACTIVE" or match.state_version != request.expected_state_version:
        raise HTTPException(status_code=409, detail="Trạng thái trận đấu vừa thay đổi. Hãy tải lại.")
    state = _json(match.battle_state_json, {})
    state["winner_player_id"] = match.opponent_player_id
    _save_battle(db, match, state)
    return _match_snapshot(db, match, current_user.id)
