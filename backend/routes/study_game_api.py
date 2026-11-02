import json
import ast
import random
import secrets
import os
import io
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, select, update, delete
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from PIL import Image, ImageOps, UnidentifiedImageError

from database import (
    Player,
    StudyActionLedger,
    StudyActiveRun,
    StudyBattle,
    StudyBattleResolution,
    StudyCardInstance,
    StudyCardTemplate,
    StudyDeck,
    StudyDeckCard,
    StudyPackTemplate,
    StudyPassage,
    StudyPlayerPack,
    StudyPlayerRelic,
    StudyPvpRelicLoadout,
    StudyRunHistory,
    QuestionBank,
    get_db,
    player_display_name,
)
from game_logic.study_spire import (
    create_battle_state,
    end_player_turn,
    generate_map_graph,
    get_route_options,
    normalize_study_text,
    play_card,
    stage_power_multiplier,
    typing_accuracy,
)
from game_logic.study_spire_relics import (
    RELIC_BY_ID,
    RELIC_CATALOG,
    RELIC_IDS,
    next_unowned_relic_id,
    owned_relic_ids,
    pvp_loadout_ids,
)
from game_logic.physics_cards import PHYSICS_CARDS, legacy_effects
from game_logic.chemistry_cards import CHEMISTRY_CARDS
from game_logic.biology_cards import BIOLOGY_CARDS
from routes.auth import get_current_user


router = APIRouter(prefix="/api/study-spire", tags=["Study Spire"])
PROJECT_ROOT = Path(__file__).resolve().parents[2]
STUDY_AVATAR_DIR = PROJECT_ROOT / "frontend" / "assets" / "images" / "avatars" / "study_spire"
MAX_AVATAR_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_AVATAR_PIXELS = 30_000_000
ALLOWED_AVATAR_FORMATS = {"JPEG", "PNG", "WEBP"}


STARTER_CARDS = [
    {"card_id": "starter_sword", "name": "Quét kiếm", "subject": "starter", "rarity": "common", "mana_cost": 1, "description": "Gây 6 sát thương mỗi lần dùng.", "image_url": "/assets/Deck/deck%20starter/kiem.png", "effect": {"type": "attack", "value": 6}},
    {"card_id": "starter_shield", "name": "Chống đỡ", "subject": "starter", "rarity": "common", "mana_cost": 1, "description": "Nhận 5 khiên mỗi lần dùng.", "image_url": "/assets/Deck/deck%20starter/khien.png", "effect": {"type": "shield", "target": "player", "value": 5}},
]
STARTER_VERSION = 5
LEGACY_STARTER_IDS = [
    "ly_strike", "ly_barrier", "ly_focus", "ly_orbit", "hoa_acid",
    "hoa_guard", "hoa_tonic", "hoa_reaction", "sinh_spore", "sinh_bark",
]
DEMO_CARD_IDS = LEGACY_STARTER_IDS + ["sinh_growth", "sinh_predator"]

REWARD_PACK_IDS = ("pack_ly", "pack_hoa", "pack_sinh")

SAMPLE_PACKS = [
    {"pack_id": "pack_ly", "name": "Pack Vật Lý", "subject": "ly", "card_ids": [card["card_id"] for card in PHYSICS_CARDS]},
    {"pack_id": "pack_hoa", "name": "Pack Hóa Học", "subject": "hoa", "card_ids": [card["card_id"] for card in CHEMISTRY_CARDS]},
    {"pack_id": "pack_sinh", "name": "Pack Sinh Học", "subject": "sinh", "card_ids": [card["card_id"] for card in BIOLOGY_CARDS]},
]

SAMPLE_PASSAGES = [
    {"passage_id": "sample_g6_sinh_1", "grade": 6, "subject": "sinh", "content": "Tế bào là đơn vị cấu trúc và chức năng cơ bản của cơ thể sống."},
    {"passage_id": "sample_g7_ly_1", "grade": 7, "subject": "ly", "content": "Ánh sáng truyền theo đường thẳng trong môi trường trong suốt và đồng tính."},
    {"passage_id": "sample_g8_hoa_1", "grade": 8, "subject": "hoa", "content": "Nguyên tử gồm hạt nhân mang điện tích dương và các electron chuyển động xung quanh."},
    {"passage_id": "sample_g9_sinh_1", "grade": 9, "subject": "sinh", "content": "Di truyền học nghiên cứu cơ sở vật chất, cơ chế và quy luật của hiện tượng di truyền."},
]

CARD_TYPE_LABELS = {"attack": "Tấn công", "defense": "Phòng thủ", "spell": "Phép"}
RARITY_LABELS = {"common": "Thường", "rare": "Hiếm", "ultra_rare": "Siêu hiếm", "legend": "Huyền thoại"}
PACK_RARITY_WEIGHTS = (("rare", 94), ("ultra_rare", 5), ("legend", 1))
RARITY_ORDER = ("common", "rare", "ultra_rare", "legend")


def _select_pack_card_id(card_ids: list[str], rarity_by_card_id: dict[str, str], roll: int | None = None) -> str:
    candidates: dict[str, list[str]] = {rarity: [] for rarity in RARITY_ORDER}
    rarity_aliases = {"r": "rare", "ur": "ultra_rare", "legendary": "legend"}
    for card_id in card_ids:
        rarity = rarity_by_card_id.get(card_id, "")
        rarity = rarity_aliases.get(rarity.lower(), rarity.lower())
        if rarity in candidates:
            candidates[rarity].append(card_id)
    available = {rarity for rarity, pool in candidates.items() if pool}
    if not available:
        raise ValueError("Pack không có lá bài active.")

    roll = secrets.randbelow(100) if roll is None else max(0, min(99, int(roll)))
    if roll < 94:
        selected_rarity = "rare"
    elif roll < 99:
        selected_rarity = "ultra_rare"
    else:
        selected_rarity = "legend"

    if selected_rarity not in available:
        target_index = RARITY_ORDER.index(selected_rarity)
        fallback_order = [
            *reversed(RARITY_ORDER[:target_index]),
            *RARITY_ORDER[target_index + 1:],
        ]
        selected_rarity = next(rarity for rarity in fallback_order if rarity in available)
    return secrets.choice(candidates[selected_rarity])


class StartRunRequest(BaseModel):
    grade: int = PydanticField(ge=6, le=9)
    idempotency_key: str = PydanticField(min_length=8, max_length=120)


class RelicLoadoutRequest(BaseModel):
    relic_ids: list[str] = PydanticField(default_factory=list)


class VersionedActionRequest(BaseModel):
    expected_state_version: int = PydanticField(ge=1)
    idempotency_key: str = PydanticField(min_length=8, max_length=120)


class RouteSelectionRequest(VersionedActionRequest):
    target_node_id: str


class PlayCardRequest(VersionedActionRequest):
    card_instance_id: str


class ChallengeCompletionRequest(VersionedActionRequest):
    answers: dict[str, str] = PydanticField(default_factory=dict)
    submitted_text: str | None = None


class ClaimPackRequest(VersionedActionRequest):
    chosen_pack_id: str


class ResolveBattleRequest(BaseModel):
    expected_state_version: int = PydanticField(ge=1)
    idempotency_key: str = PydanticField(min_length=8, max_length=160)


class DeckUpdateRequest(BaseModel):
    expected_state_version: int = PydanticField(ge=1)
    idempotency_key: str = PydanticField(min_length=8, max_length=120)
    card_instance_ids: list[str]


class OpenPackRequest(BaseModel):
    pack_id: str
    expected_state_version: int = PydanticField(ge=1)
    idempotency_key: str = PydanticField(min_length=8, max_length=120)


class AddEarnedCardRequest(VersionedActionRequest):
    instance_id: str


def _json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _study_player_profile(player: Player) -> dict[str, Any]:
    avatar_path = STUDY_AVATAR_DIR / f"player_{player.id}.png"
    avatar_url = None
    if avatar_path.is_file():
        avatar_url = f"/assets/images/avatars/study_spire/{avatar_path.name}?v={avatar_path.stat().st_mtime_ns}"
    return {
        "player_id": player.id,
        "name": player_display_name(player),
        "username": player.username,
        "avatar_url": avatar_url,
    }


@router.get("/profile")
def get_study_player_profile(current_user: Player = Depends(get_current_user)):
    return _study_player_profile(current_user)


@router.get("/relics")
def get_study_player_relics(
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    owned = set(owned_relic_ids(db, current_user.id))
    equipped = set(pvp_loadout_ids(db, current_user.id))
    db.commit()
    return {
        "owned_count": len(owned),
        "total_count": len(RELIC_CATALOG),
        "pvp_loadout_ids": sorted(equipped),
        "relics": [
            {
                "id": relic["id"],
                "name": relic["name"],
                "description": relic["description"],
                "image_url": f"/assets/items/charms/{relic['image']}",
                "owned": relic["id"] in owned,
                "equipped": relic["id"] in equipped,
            }
            for relic in RELIC_CATALOG
        ],
    }


@router.put("/relics/loadout")
def save_study_pvp_relic_loadout(
    request: RelicLoadoutRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if len(request.relic_ids) != len(set(request.relic_ids)):
        raise HTTPException(status_code=422, detail="Không thể trang bị trùng một relic.")
    unknown = set(request.relic_ids) - RELIC_IDS
    if unknown:
        raise HTTPException(status_code=422, detail="Loadout có relic không tồn tại.")
    unowned = set(request.relic_ids) - set(owned_relic_ids(db, current_user.id))
    if unowned:
        raise HTTPException(status_code=422, detail="Chỉ có thể trang bị relic đã mở khóa.")

    loadout = db.get(StudyPvpRelicLoadout, current_user.id)
    if loadout is None:
        loadout = StudyPvpRelicLoadout(player_id=current_user.id)
    loadout.relic_ids_json = json.dumps(sorted(request.relic_ids))
    db.add(loadout)
    db.commit()
    return get_study_player_relics(current_user, db)


@router.post("/profile/avatar")
async def upload_study_player_avatar(
    image: UploadFile = File(...),
    current_user: Player = Depends(get_current_user),
):
    content = await image.read(MAX_AVATAR_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="File ảnh đang trống.")
    if len(content) > MAX_AVATAR_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Ảnh tối đa 5 MB.")

    temporary_path = None
    try:
        with Image.open(io.BytesIO(content)) as source:
            if source.format not in ALLOWED_AVATAR_FORMATS:
                raise HTTPException(status_code=415, detail="Chỉ nhận ảnh PNG, JPG hoặc WEBP.")
            if source.width * source.height > MAX_AVATAR_PIXELS:
                raise HTTPException(status_code=413, detail="Kích thước ảnh quá lớn.")
            source.verify()
        with Image.open(io.BytesIO(content)) as source:
            oriented = ImageOps.exif_transpose(source) or source
            normalized = ImageOps.fit(
                oriented.convert("RGB"),
                (512, 512),
                method=Image.Resampling.LANCZOS,
            )
            STUDY_AVATAR_DIR.mkdir(parents=True, exist_ok=True)
            avatar_path = STUDY_AVATAR_DIR / f"player_{current_user.id}.png"
            temporary_path = STUDY_AVATAR_DIR / f".player_{current_user.id}_{secrets.token_hex(6)}.tmp.png"
            normalized.save(temporary_path, format="PNG", optimize=True)
            os.replace(temporary_path, avatar_path)
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise HTTPException(status_code=400, detail="File tải lên không phải ảnh hợp lệ.") from error
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink(missing_ok=True)

    return _study_player_profile(current_user)


def ensure_catalog(db: Session) -> None:
    catalog_cards = STARTER_CARDS + PHYSICS_CARDS + CHEMISTRY_CARDS + BIOLOGY_CARDS
    for card in catalog_cards:
        legacy_effect = card.get("effect", {})
        card_type = card.get("card_type") or ("attack" if legacy_effect.get("type") == "attack" else "defense" if legacy_effect.get("type") == "shield" else "spell")
        effects = card.get("effects") or legacy_effects(legacy_effect)
        template = db.get(StudyCardTemplate, card["card_id"])
        if template is None:
            template = StudyCardTemplate(card_id=card["card_id"])
        template.name = card["name"]
        template.subject = card["subject"]
        template.rarity = card["rarity"]
        template.mana_cost = card["mana_cost"]
        template.description = card["description"]
        template.image_url = card["image_url"]
        template.effect_json = json.dumps(legacy_effect, ensure_ascii=False)
        template.card_type = card_type
        template.tags_json = json.dumps(card.get("tags", []), ensure_ascii=False)
        template.effects_json = json.dumps(effects, ensure_ascii=False)
        template.effect_tooltips_json = json.dumps(card.get("effect_tooltips", []), ensure_ascii=False)
        template.exhaust = bool(card.get("exhaust", False))
        template.is_active = True
        db.add(template)

    for card_id in DEMO_CARD_IDS:
        template = db.get(StudyCardTemplate, card_id)
        if template:
            template.is_active = False
            db.add(template)

    for pack in SAMPLE_PACKS:
        template = db.get(StudyPackTemplate, pack["pack_id"])
        if template is None:
            template = StudyPackTemplate(pack_id=pack["pack_id"], name=pack["name"], subject=pack["subject"])
        template.name = pack["name"]
        template.subject = pack["subject"]
        template.card_pool_json = json.dumps(pack["card_ids"], ensure_ascii=False)
        template.is_active = True
        db.add(template)

    for passage in SAMPLE_PASSAGES:
        if db.get(StudyPassage, passage["passage_id"]) is None:
            db.add(StudyPassage(**passage))
    db.flush()


def _award_pack(db: Session, player_id: int, pack_id: str) -> dict[str, Any]:
    pack = db.get(StudyPackTemplate, pack_id)
    if not pack or not pack.is_active:
        raise HTTPException(status_code=404, detail="Không tìm thấy pack.")
    entry = db.exec(select(StudyPlayerPack).where(StudyPlayerPack.player_id == player_id, StudyPlayerPack.pack_id == pack.pack_id)).first()
    if entry:
        entry.quantity += 1
        entry.state_version += 1
    else:
        db.add(StudyPlayerPack(player_id=player_id, pack_id=pack.pack_id, quantity=1, state_version=1))
    return {"pack_id": pack.pack_id, "name": pack.name}


def _ensure_starter_deck(db: Session, player_id: int) -> tuple[StudyDeck, list[str]]:
    deck = db.exec(select(StudyDeck).where(StudyDeck.player_id == player_id)).first()
    if deck is None:
        deck = StudyDeck(player_id=player_id, starter_version=STARTER_VERSION)
        db.add(deck)
        db.flush()

        starter_cards = [STARTER_CARDS[0]] * 5 + [STARTER_CARDS[1]] * 5
        card_instances = [
            StudyCardInstance(player_id=player_id, card_id=card["card_id"])
            for card in starter_cards
        ]
        db.add_all(card_instances)
        db.flush()
        db.add_all([
            StudyDeckCard(deck_id=deck.id, card_instance_id=instance.instance_id, position=index)
            for index, instance in enumerate(card_instances)
        ])
        db.flush()
    elif deck.starter_version < STARTER_VERSION:
        active_run = db.exec(select(StudyActiveRun).where(StudyActiveRun.player_id == player_id)).first()
        if not active_run:
            legacy_rows = db.exec(
                select(StudyDeckCard, StudyCardInstance)
                .join(StudyCardInstance, StudyDeckCard.card_instance_id == StudyCardInstance.instance_id)
                .where(StudyDeckCard.deck_id == deck.id)
                .order_by(StudyDeckCard.position)
            ).all()
            legacy_template_ids = [instance.card_id for _, instance in legacy_rows]
            accidental_full_starter = (
                len(legacy_rows) == 20
                and legacy_template_ids == [STARTER_CARDS[0]["card_id"]] * 10 + [STARTER_CARDS[1]["card_id"]] * 10
                and not deck.must_remain_full
            )
            if accidental_full_starter:
                db.exec(delete(StudyDeckCard).where(StudyDeckCard.deck_id == deck.id, StudyDeckCard.position >= 10))
                legacy_rows = legacy_rows[:10]
                for index, (_, instance) in enumerate(legacy_rows):
                    instance.card_id = STARTER_CARDS[0 if index < 5 else 1]["card_id"]
                    db.add(instance)

            if len(legacy_rows) == 10 and legacy_template_ids == LEGACY_STARTER_IDS:
                for index, (_, instance) in enumerate(legacy_rows):
                    instance.card_id = STARTER_CARDS[0 if index < 5 else 1]["card_id"]
                    db.add(instance)
            elif len(legacy_rows) < 10:
                missing_count = 10 - len(legacy_rows)
                instances = [
                    StudyCardInstance(player_id=player_id, card_id=STARTER_CARDS[index % 2]["card_id"])
                    for index in range(missing_count)
                ]
                db.add_all(instances)
                db.flush()
                db.add_all([
                    StudyDeckCard(deck_id=deck.id, card_instance_id=instance.instance_id, position=len(legacy_rows) + index)
                    for index, instance in enumerate(instances)
                ])

            final_count = min(20, max(len(legacy_rows), 10)) if accidental_full_starter else len(legacy_rows) + max(0, 10 - len(legacy_rows))
            if deck.must_remain_full and len(legacy_rows) >= 20:
                final_count = len(legacy_rows)
            deck.must_remain_full = deck.must_remain_full or final_count >= 20
            deck.state_version += 1
            deck.updated_at = datetime.now()
            deck.starter_version = STARTER_VERSION
            db.add(deck)
            db.flush()

    deck_rows = db.exec(
        select(StudyDeckCard, StudyCardInstance)
        .join(StudyCardInstance, StudyDeckCard.card_instance_id == StudyCardInstance.instance_id)
        .where(StudyDeckCard.deck_id == deck.id)
        .order_by(StudyDeckCard.position)
    ).all()
    return deck, [instance.instance_id for _, instance in deck_rows]


def _battle_enemy(
    floor: int,
    seed: int,
    boss: bool = False,
    elite: bool = False,
    stage: int = 1,
) -> dict[str, Any]:
    sprite_set = ("Bat", "Mimic", "Rat", "Slime")[seed % 4]
    power = stage_power_multiplier(stage)
    background = f"/assets/background/hg{seed % 3}.png" if seed % 3 else "/assets/background/hg.png"

    def scaled(hp: int, attack: int, shield: int = 0) -> dict[str, Any]:
        return {
            "hp": round(hp * power),
            "max_hp": round(hp * power),
            "attack": round(attack * power),
            "shield": shield,
        }

    if boss:
        return {
            "name": f"Hộ Vệ Ải {stage}",
            "sprite_set": sprite_set,
            "arena_background": "/assets/background/arena_bg.jpg",
            **scaled(100, 10),
        }
    monster_names = {"Bat": "Dơi hang", "Mimic": "Rương ngụy trang", "Rat": "Chuột hang", "Slime": "Chất nhầy"}
    if elite:
        return {
            "name": f"{monster_names[sprite_set]} tinh anh · Tầng {floor}",
            "sprite_set": sprite_set,
            "arena_background": background,
            **scaled(36 + floor * 6, 6 + floor, shield=6),
        }
    return {
        "name": f"{monster_names[sprite_set]} · Tầng {floor}",
        "sprite_set": sprite_set,
        "arena_background": background,
        **scaled(24 + floor * 4, 4 + floor),
    }


def _card_metadata_for_instances(db: Session, instance_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not instance_ids:
        return {}
    rows = db.exec(
        select(StudyCardInstance, StudyCardTemplate)
        .join(StudyCardTemplate, StudyCardInstance.card_id == StudyCardTemplate.card_id)
        .where(StudyCardInstance.instance_id.in_(instance_ids))
    ).all()
    return {
        instance.instance_id: {
            "card_id": template.card_id,
            "type": template.card_type,
            "tags": _json(template.tags_json, []),
            "cost": template.mana_cost,
        }
        for instance, template in rows
    }


def _make_battle(db: Session, run: StudyActiveRun, deck_card_ids: list[str], node_id: str) -> StudyBattle:
    node = _json(run.map_graph_json, {}).get("nodes", {}).get(node_id, {})
    floor = int(node.get("floor", run.current_floor))
    boss = node.get("room_type") == "boss"
    elite = node.get("room_type") == "elite"
    seed = secrets.randbits(32)
    core = _json(run.player_core_json, {})
    state = create_battle_state(
        deck_card_ids,
        _battle_enemy(floor, seed, boss, elite, int(core.get("stage", 1))),
        player_hp=int(core.get("hp", 80)),
        player_hp_max=80,
        seed=seed,
        card_metadata=_card_metadata_for_instances(db, deck_card_ids),
        relic_ids=core.get("relic_ids", []),
    )
    return StudyBattle(run_id=run.run_id, battle_state_json=json.dumps(state, ensure_ascii=False))


def _run_response(db: Session, run: StudyActiveRun) -> dict[str, Any]:
    battle = db.exec(select(StudyBattle).where(StudyBattle.run_id == run.run_id)).first()
    return {
        "run_id": run.run_id,
        "run_status": run.run_status,
        "state_version": run.state_version,
        "current_floor": run.current_floor,
        "current_node_id": run.current_node_id,
        "grade": run.grade,
        "map_graph": _json(run.map_graph_json, {}),
        "history_path": _json(run.history_path_json, []),
        "player_core": _json(run.player_core_json, {}),
        "pending_pack_choices": _json(run.pending_pack_choices_json, []),
        "room_state": _json(run.room_state_json, {}),
        "battle_id": battle.battle_id if battle else None,
        "battle_phase": battle.battle_phase if battle else None,
        "battle": _json(battle.battle_state_json, {}) if battle else None,
    }


def _existing_action(db: Session, player_id: int, idempotency_key: str) -> dict[str, Any] | None:
    action = db.exec(
        select(StudyActionLedger).where(
            StudyActionLedger.player_id == player_id,
            StudyActionLedger.idempotency_key == idempotency_key,
        )
    ).first()
    return _json(action.result_json, {}) if action else None


def _bump_run_version(db: Session, run: StudyActiveRun, player_id: int, expected: int) -> None:
    if run.state_version != expected:
        raise HTTPException(status_code=409, detail="Trạng thái đã thay đổi. Hãy tải lại hành trình.")

    result = db.exec(
        update(StudyActiveRun)
        .where(
            StudyActiveRun.run_id == run.run_id,
            StudyActiveRun.player_id == player_id,
            StudyActiveRun.state_version == expected,
        )
        .values(state_version=expected + 1, updated_at=datetime.now())
    )
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail="Trạng thái đã thay đổi. Hãy tải lại hành trình.")
    run.state_version = expected + 1


def _record_action(db: Session, player_id: int, run_id: str, action_type: str, key: str, result: dict[str, Any]) -> None:
    db.add(StudyActionLedger(
        idempotency_key=key,
        player_id=player_id,
        run_id=run_id,
        action_type=action_type,
        result_json=json.dumps(result, ensure_ascii=False),
    ))


def _question_options(question: QuestionBank) -> list[dict[str, str]]:
    raw_options = question.options_json
    if isinstance(raw_options, list):
        options = raw_options
    else:
        try:
            options = json.loads(raw_options)
        except (TypeError, json.JSONDecodeError):
            try:
                options = ast.literal_eval(raw_options)
            except (ValueError, SyntaxError, TypeError):
                return []

    if not isinstance(options, list) or len(options) < 2:
        return []
    return [{"key": chr(65 + index), "text": str(value)} for index, value in enumerate(options[:4])]


def _correct_option_key(question: QuestionBank, options: list[dict[str, str]]) -> str | None:
    correct = normalize_study_text(question.correct_answer).rstrip(".")
    if correct in {"a", "b", "c", "d"}:
        return correct.upper() if ord(correct.upper()) - 65 < len(options) else None
    for option in options:
        if normalize_study_text(option["text"]) == normalize_study_text(question.correct_answer):
            return option["key"]
    return None


def _available_grades(db: Session) -> list[int]:
    valid_counts: dict[int, int] = {}
    questions = db.exec(select(QuestionBank)).all()
    for question in questions:
        options = _question_options(question)
        if options and _correct_option_key(question, options):
            valid_counts[question.grade] = valid_counts.get(question.grade, 0) + 1
    return sorted(grade for grade, count in valid_counts.items() if count >= 5)


def _answer_is_correct(question: QuestionBank, submitted_answer: str) -> bool:
    options = _question_options(question)
    correct_key = _correct_option_key(question, options)
    normalized_answer = normalize_study_text(submitted_answer).rstrip(".")
    if correct_key and normalized_answer == correct_key.casefold():
        return True
    correct_text = next((item["text"] for item in options if item["key"] == correct_key), None)
    return bool(correct_text and normalize_study_text(correct_text) == normalize_study_text(submitted_answer))


def _quiz_answer_feedback(question: QuestionBank, submitted_answer: str) -> dict[str, Any]:
    options = _question_options(question)
    correct_key = _correct_option_key(question, options)
    normalized_answer = normalize_study_text(submitted_answer).rstrip(".").casefold()
    selected_option = next((
        option for option in options
        if option["key"].casefold() == normalized_answer
        or normalize_study_text(option["text"]).rstrip(".").casefold() == normalized_answer
    ), None)
    correct_option = next((option for option in options if option["key"] == correct_key), None)
    return {
        "question_id": question.id,
        "question": question.content,
        "selected_answer": selected_option["text"] if selected_option else submitted_answer,
        "is_correct": _answer_is_correct(question, submitted_answer),
        "correct_choice_key": correct_key,
        "correct_answer": correct_option["text"] if correct_option else "",
    }


def _award_card(db: Session, player_id: int, card_id: str, *, add_to_deck: bool = True) -> dict[str, Any]:
    template = db.get(StudyCardTemplate, card_id)
    if template and not template.is_active and card_id in DEMO_CARD_IDS:
        card_id = secrets.choice(PHYSICS_CARDS)["card_id"]
        template = db.get(StudyCardTemplate, card_id)
    if not template:
        raise HTTPException(status_code=409, detail="Catalog card không tồn tại.")
    if not template.is_active:
        raise HTTPException(status_code=409, detail="Lá bài đã được lưu trữ và không thể nhận thêm.")
    instance = StudyCardInstance(player_id=player_id, card_id=template.card_id)
    db.add(instance)
    db.flush()

    added_to_deck = False
    deck = db.exec(select(StudyDeck).where(StudyDeck.player_id == player_id)).first()
    if deck and add_to_deck:
        same_card_count = len(db.exec(
            select(StudyDeckCard.card_instance_id)
            .join(StudyCardInstance, StudyDeckCard.card_instance_id == StudyCardInstance.instance_id)
            .where(StudyDeckCard.deck_id == deck.id, StudyCardInstance.card_id == template.card_id)
        ).all())
        if same_card_count < 2:
            positions = db.exec(select(StudyDeckCard.position).where(StudyDeckCard.deck_id == deck.id)).all()
            new_count = len(positions) + 1
            db.add(StudyDeckCard(
                deck_id=deck.id,
                card_instance_id=instance.instance_id,
                position=max(positions, default=-1) + 1,
            ))
            if new_count >= 20:
                deck.must_remain_full = True
            deck.state_version += 1
            deck.updated_at = datetime.now()
            db.add(deck)
            added_to_deck = True

    return {
        "instance_id": instance.instance_id,
        "card_id": template.card_id,
        "name": template.name,
        "rarity": template.rarity,
        "rarity_label_vi": RARITY_LABELS.get(template.rarity, "Hiếm"),
        "mana_cost": template.mana_cost,
        "description": template.description,
        "image_url": template.image_url,
        "effect_tooltips": _json(template.effect_tooltips_json, []),
        "type": template.card_type,
        "type_label_vi": CARD_TYPE_LABELS.get(template.card_type, "Phép"),
        "added_to_deck": added_to_deck,
    }


def _deck_response(db: Session, deck: StudyDeck, player_id: int) -> dict[str, Any]:
    rows = db.exec(
        select(StudyDeckCard, StudyCardInstance, StudyCardTemplate)
        .join(StudyCardInstance, StudyDeckCard.card_instance_id == StudyCardInstance.instance_id)
        .join(StudyCardTemplate, StudyCardInstance.card_id == StudyCardTemplate.card_id)
        .where(StudyDeckCard.deck_id == deck.id, StudyCardInstance.player_id == player_id, StudyCardTemplate.is_active == True)
        .order_by(StudyDeckCard.position)
    ).all()
    return {
        "deck_id": deck.id,
        "name": deck.name,
        "state_version": deck.state_version,
        "minimum_cards": 20 if deck.must_remain_full else 10,
        "maximum_cards": None,
        "must_remain_full": deck.must_remain_full,
        "cards": [{
            "instance_id": instance.instance_id,
            "card_id": template.card_id,
            "name": template.name,
            "subject": template.subject,
            "rarity": template.rarity,
            "rarity_label_vi": RARITY_LABELS.get(template.rarity, "Hiếm"),
            "type": template.card_type,
            "type_label_vi": CARD_TYPE_LABELS.get(template.card_type, "Phép"),
            "tags": _json(template.tags_json, []),
            "mana_cost": template.mana_cost,
            "description": template.description,
            "image_url": template.image_url,
            "effect_tooltips": _json(template.effect_tooltips_json, []),
        } for _, instance, template in rows],
    }


def _prepare_room_state(db: Session, run: StudyActiveRun, node_id: str) -> dict[str, Any]:
    graph = _json(run.map_graph_json, {})
    node = graph.get("nodes", {}).get(node_id, {})
    room_type = node.get("room_type")

    if room_type in {"inn", "event"}:
        question_count = 5 if room_type == "inn" else 3
        candidates = db.exec(select(QuestionBank).where(QuestionBank.grade == run.grade)).all()
        valid_questions = [
            question for question in candidates
            if (options := _question_options(question)) and _correct_option_key(question, options)
        ]
        if len(valid_questions) < question_count:
            raise HTTPException(status_code=409, detail=f"Kho câu hỏi khối {run.grade} chưa đủ câu hợp lệ cho phòng này.")
        questions = secrets.SystemRandom().sample(valid_questions, question_count)

        state: dict[str, Any] = {
            "challenge_type": "quiz",
            "question_ids": [question.id for question in questions],
        }
        if room_type == "event":
            kind = secrets.choice(["pack", "heal", "damage"])
            if kind == "pack":
                state["event_effect"] = {"type": "pack", "pack_id": secrets.choice(REWARD_PACK_IDS)}
            else:
                state["event_effect"] = {"type": kind, "percent": secrets.choice([5, 6, 7, 8, 9, 10])}
        return state

    if room_type == "chest":
        passage = db.exec(
            select(StudyPassage)
            .where(StudyPassage.grade == run.grade, StudyPassage.is_active == True)
            .order_by(func.random())
        ).first()
        if passage is None:
            raise HTTPException(status_code=409, detail=f"Chưa có đoạn học liệu cho khối {run.grade}.")
        return {"challenge_type": "typing", "passage_id": passage.passage_id}

    return {}


def _get_active_run(db: Session, player_id: int) -> StudyActiveRun:
    run = db.exec(select(StudyActiveRun).where(StudyActiveRun.player_id == player_id)).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Không có hành trình đang hoạt động.")
    return run


def _get_battle(db: Session, run_id: str) -> StudyBattle:
    battle = db.exec(select(StudyBattle).where(StudyBattle.run_id == run_id)).first()
    if battle is None:
        raise HTTPException(status_code=404, detail="Không có trận đấu đang hoạt động.")
    return battle


def _commit_action(
    db: Session,
    player_id: int,
    run_id: str,
    action_type: str,
    idempotency_key: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    _record_action(db, player_id, run_id, action_type, idempotency_key, result)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        previous_result = _existing_action(db, player_id, idempotency_key)
        if previous_result is not None:
            return previous_result
        raise HTTPException(status_code=409, detail="Hành động đã được xử lý đồng thời. Hãy tải lại.")
    return result


@router.get("/catalog")
def get_catalog(
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_catalog(db)
    db.commit()
    cards = db.exec(select(StudyCardTemplate).where(StudyCardTemplate.is_active == True).order_by(StudyCardTemplate.subject, StudyCardTemplate.card_id)).all()
    packs = db.exec(select(StudyPackTemplate).where(StudyPackTemplate.is_active == True)).all()
    return {
        "cards": [{
            "card_id": card.card_id,
            "name": card.name,
            "subject": card.subject,
            "rarity": card.rarity,
            "rarity_label_vi": RARITY_LABELS.get(card.rarity, "Hiếm"),
            "type": card.card_type,
            "type_label_vi": CARD_TYPE_LABELS.get(card.card_type, "Phép"),
            "tags": _json(card.tags_json, []),
            "mana_cost": card.mana_cost,
            "description": card.description,
            "image_url": card.image_url,
            "effect_tooltips": _json(card.effect_tooltips_json, []),
            "effect": _json(card.effect_json, {}),
            "effects": _json(card.effects_json, []) or legacy_effects(_json(card.effect_json, {})),
            "exhaust": card.exhaust,
        } for card in cards],
        "packs": [{"pack_id": pack.pack_id, "name": pack.name, "subject": pack.subject} for pack in packs],
        "available_grades": _available_grades(db),
    }


@router.post("/run/start")
def start_run(
    request: StartRunRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    previous_result = _existing_action(db, current_user.id, request.idempotency_key)
    if previous_result is not None:
        return previous_result

    existing_run = db.exec(select(StudyActiveRun).where(StudyActiveRun.player_id == current_user.id)).first()
    if existing_run:
        raise HTTPException(status_code=409, detail="Bạn đã có một hành trình đang diễn ra.")

    available_grades = _available_grades(db)
    if request.grade not in available_grades:
        raise HTTPException(
            status_code=422,
            detail={"message": "Khối này chưa có đủ câu hỏi hợp lệ.", "available_grades": available_grades},
        )

    # Người chơi chỉ được vào kho câu hỏi đúng khối của mình (admin được chọn tự do)
    if current_user.role != "admin" and request.grade != current_user.grade:
        raise HTTPException(status_code=403, detail=f"Tài khoản của bạn thuộc khối {current_user.grade}.")

    ensure_catalog(db)
    deck, deck_card_ids = _ensure_starter_deck(db, current_user.id)
    if not deck_card_ids:
        raise HTTPException(status_code=409, detail="Bộ bài đang trống.")

    seed = secrets.randbits(32)
    graph = generate_map_graph(seed)
    player_core = {
        "hp": 80,
        "hp_max": 80,
        "stage": 1,
        "stages_cleared": 0,
        "deck_card_instance_ids": deck_card_ids,
        "deck_id": deck.id,
        "relic_ids": owned_relic_ids(db, current_user.id),
    }
    run = StudyActiveRun(
        player_id=current_user.id,
        run_status="IN_NODE",
        current_floor=1,
        current_node_id="f1_node_1",
        grade=request.grade,
        map_graph_json=json.dumps(graph),
        history_path_json="[]",
        player_core_json=json.dumps(player_core),
    )
    db.add(run)
    db.flush()

    battle = _make_battle(db, run, deck_card_ids, run.current_node_id)
    db.add(battle)
    db.flush()

    response = _run_response(db, run)
    db.add(StudyActionLedger(
        idempotency_key=request.idempotency_key,
        player_id=current_user.id,
        run_id=run.run_id,
        action_type="run_start",
        result_json=json.dumps(response, ensure_ascii=False),
    ))
    try:
        db.commit()
    except Exception:
        db.rollback()
        previous_result = _existing_action(db, current_user.id, request.idempotency_key)
        if previous_result is not None:
            return previous_result
        raise
    return response


@router.get("/run/active")
def get_active_run(
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.exec(select(StudyActiveRun).where(StudyActiveRun.player_id == current_user.id)).first()
    return {"run": _run_response(db, run) if run else None}


@router.get("/deck")
def get_study_deck(
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_catalog(db)
    deck, _ = _ensure_starter_deck(db, current_user.id)
    result = _deck_response(db, deck, current_user.id)
    db.commit()
    return result


@router.put("/deck")
def update_study_deck(
    request: DeckUpdateRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    previous_result = _existing_action(db, current_user.id, request.idempotency_key)
    if previous_result is not None:
        return previous_result

    deck = db.exec(select(StudyDeck).where(StudyDeck.player_id == current_user.id)).first()
    if not deck:
        raise HTTPException(status_code=404, detail="Chưa có bộ bài.")
    if deck.state_version != request.expected_state_version:
        raise HTTPException(status_code=409, detail="Bộ bài đã được cập nhật. Hãy tải lại.")
    minimum_cards = 20 if deck.must_remain_full else 10
    if len(request.card_instance_ids) < minimum_cards:
        raise HTTPException(status_code=422, detail=f"Bộ bài phải có tối thiểu {minimum_cards} lá.")
    if len(set(request.card_instance_ids)) != len(request.card_instance_ids):
        raise HTTPException(status_code=422, detail="Không thể đưa cùng một bản thẻ vào bộ bài nhiều lần.")

    owned_cards = db.exec(
        select(StudyCardInstance).where(
            StudyCardInstance.player_id == current_user.id,
            StudyCardInstance.instance_id.in_(request.card_instance_ids),
        )
    ).all()
    if {card.instance_id for card in owned_cards} != set(request.card_instance_ids):
        raise HTTPException(status_code=422, detail="Bộ bài chứa lá không thuộc kho của bạn.")
    copy_counts: dict[str, int] = {}
    for card in owned_cards:
        copy_counts[card.card_id] = copy_counts.get(card.card_id, 0) + 1
    if any(count > 2 and not card_id.startswith("starter_") for card_id, count in copy_counts.items()):
        raise HTTPException(status_code=422, detail="Mỗi lá bài chỉ được có tối đa 2 bản sao trong bộ bài.")

    cas = db.exec(
        update(StudyDeck)
        .where(StudyDeck.id == deck.id, StudyDeck.player_id == current_user.id, StudyDeck.state_version == request.expected_state_version)
        .values(
            state_version=request.expected_state_version + 1,
            must_remain_full=deck.must_remain_full or len(request.card_instance_ids) >= 20,
            updated_at=datetime.now(),
        )
    )
    if cas.rowcount != 1:
        raise HTTPException(status_code=409, detail="Bộ bài vừa được cập nhật ở nơi khác.")
    deck.state_version = request.expected_state_version + 1
    deck.must_remain_full = deck.must_remain_full or len(request.card_instance_ids) >= 20
    db.exec(delete(StudyDeckCard).where(StudyDeckCard.deck_id == deck.id))
    db.flush()
    db.add_all([
        StudyDeckCard(deck_id=deck.id, card_instance_id=instance_id, position=position)
        for position, instance_id in enumerate(request.card_instance_ids)
    ])
    result = _deck_response(db, deck, current_user.id)
    return _commit_action(db, current_user.id, f"deck:{deck.id}", "deck_update", request.idempotency_key, result)


@router.get("/inventory")
def get_study_inventory(
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ensure_catalog(db)
    db.commit()
    packs = db.exec(
        select(StudyPlayerPack, StudyPackTemplate)
        .join(StudyPackTemplate, StudyPlayerPack.pack_id == StudyPackTemplate.pack_id)
        .where(StudyPlayerPack.player_id == current_user.id, StudyPlayerPack.quantity > 0, StudyPackTemplate.is_active == True)
    ).all()
    active_deck = db.exec(select(StudyDeck).where(StudyDeck.player_id == current_user.id)).first()
    deck_ids = set()
    if active_deck:
        deck_ids = set(db.exec(select(StudyDeckCard.card_instance_id).where(StudyDeckCard.deck_id == active_deck.id)).all())
    active_run = db.exec(select(StudyActiveRun).where(StudyActiveRun.player_id == current_user.id)).first()
    active_run_card_ids = _json(active_run.player_core_json, {}).get("deck_card_instance_ids", []) if active_run else []
    cards = db.exec(select(StudyCardInstance, StudyCardTemplate)
        .join(StudyCardTemplate, StudyCardInstance.card_id == StudyCardTemplate.card_id)
        .where(
            StudyCardInstance.player_id == current_user.id,
            (StudyCardTemplate.is_active == True) | StudyCardInstance.instance_id.in_(active_run_card_ids),
        )
    ).all()
    return {
        "packs": [{"pack_id": template.pack_id, "name": template.name, "subject": template.subject, "quantity": entry.quantity, "state_version": entry.state_version} for entry, template in packs],
        "cards": [{
            "instance_id": instance.instance_id,
            "card_id": template.card_id,
            "name": template.name,
            "subject": template.subject,
            "rarity": template.rarity,
            "rarity_label_vi": RARITY_LABELS.get(template.rarity, "Hiếm"),
            "type": template.card_type,
            "type_label_vi": CARD_TYPE_LABELS.get(template.card_type, "Phép"),
            "tags": _json(template.tags_json, []),
            "mana_cost": template.mana_cost,
            "description": template.description,
            "image_url": template.image_url,
            "effect_tooltips": _json(template.effect_tooltips_json, []),
            "in_deck": instance.instance_id in deck_ids,
            "is_active": template.is_active,
        } for instance, template in cards],
    }


@router.post("/pack/open")
def open_study_pack(
    request: OpenPackRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    previous_result = _existing_action(db, current_user.id, request.idempotency_key)
    if previous_result is not None:
        return previous_result

    pack_template = db.get(StudyPackTemplate, request.pack_id)
    inventory = db.exec(select(StudyPlayerPack).where(
        StudyPlayerPack.player_id == current_user.id,
        StudyPlayerPack.pack_id == request.pack_id,
    )).first()
    if not pack_template or not pack_template.is_active or not inventory or inventory.quantity < 1:
        raise HTTPException(status_code=404, detail="Không có pack này trong kho.")
    if inventory.state_version != request.expected_state_version:
        raise HTTPException(status_code=409, detail="Kho pack vừa được cập nhật. Hãy tải lại kho.")
    card_ids = _json(pack_template.card_pool_json, [])
    if not card_ids:
        raise HTTPException(status_code=409, detail="Pack chưa có danh sách lá bài.")

    active_templates = db.exec(select(StudyCardTemplate).where(
        StudyCardTemplate.card_id.in_(card_ids),
        StudyCardTemplate.is_active == True,
    )).all()
    try:
        card_id = _select_pack_card_id(card_ids, {template.card_id: template.rarity for template in active_templates})
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    awarded_card = _award_card(db, current_user.id, card_id, add_to_deck=False)
    cas = db.exec(
        update(StudyPlayerPack)
        .where(
            StudyPlayerPack.id == inventory.id,
            StudyPlayerPack.player_id == current_user.id,
            StudyPlayerPack.state_version == request.expected_state_version,
            StudyPlayerPack.quantity >= 1,
        )
        .values(quantity=StudyPlayerPack.quantity - 1, state_version=request.expected_state_version + 1)
    )
    if cas.rowcount != 1:
        raise HTTPException(status_code=409, detail="Pack đã được mở ở một phiên khác.")
    db.refresh(inventory)
    result = {"pack_id": pack_template.pack_id, "remaining": inventory.quantity, "state_version": inventory.state_version, "card": awarded_card}
    return _commit_action(db, current_user.id, f"pack:{pack_template.pack_id}", "pack_open", request.idempotency_key, result)


@router.post("/deck/add-earned")
def add_earned_card_to_deck(
    request: AddEarnedCardRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    previous_result = _existing_action(db, current_user.id, request.idempotency_key)
    if previous_result is not None:
        return previous_result

    ensure_catalog(db)
    deck, _ = _ensure_starter_deck(db, current_user.id)
    if deck.state_version != request.expected_state_version:
        raise HTTPException(status_code=409, detail="Bộ bài đã được cập nhật. Hãy tải lại.")
    instance = db.get(StudyCardInstance, request.instance_id)
    if not instance or instance.player_id != current_user.id:
        raise HTTPException(status_code=404, detail="Không tìm thấy lá bài thuộc kho của bạn.")

    existing_membership = db.exec(select(StudyDeckCard).where(
        StudyDeckCard.deck_id == deck.id,
        StudyDeckCard.card_instance_id == instance.instance_id,
    )).first()
    if existing_membership:
        result = {"added_to_deck": True, "deck": _deck_response(db, deck, current_user.id)}
        return _commit_action(db, current_user.id, f"deck:{deck.id}", "deck_add_reward", request.idempotency_key, result)

    copy_count = len(db.exec(
        select(StudyDeckCard.card_instance_id)
        .join(StudyCardInstance, StudyDeckCard.card_instance_id == StudyCardInstance.instance_id)
        .where(StudyDeckCard.deck_id == deck.id, StudyCardInstance.card_id == instance.card_id)
    ).all())
    if copy_count >= 2 and not instance.card_id.startswith("starter_"):
        result = {
            "added_to_deck": False,
            "message": "Bộ bài đã có đủ 2 bản sao của lá này. Lá mới được giữ trong kho.",
            "deck": _deck_response(db, deck, current_user.id),
        }
        return _commit_action(db, current_user.id, f"deck:{deck.id}", "deck_add_reward", request.idempotency_key, result)

    positions = db.exec(select(StudyDeckCard.position).where(StudyDeckCard.deck_id == deck.id)).all()
    new_count = len(positions) + 1
    cas = db.exec(
        update(StudyDeck)
        .where(StudyDeck.id == deck.id, StudyDeck.player_id == current_user.id, StudyDeck.state_version == request.expected_state_version)
        .values(
            state_version=request.expected_state_version + 1,
            must_remain_full=deck.must_remain_full or new_count >= 20,
            updated_at=datetime.now(),
        )
    )
    if cas.rowcount != 1:
        raise HTTPException(status_code=409, detail="Bộ bài vừa được cập nhật ở nơi khác.")
    deck.state_version = request.expected_state_version + 1
    deck.must_remain_full = deck.must_remain_full or new_count >= 20
    db.add(StudyDeckCard(
        deck_id=deck.id,
        card_instance_id=instance.instance_id,
        position=max(positions, default=-1) + 1,
    ))
    result = {"added_to_deck": True, "deck": _deck_response(db, deck, current_user.id)}
    return _commit_action(db, current_user.id, f"deck:{deck.id}", "deck_add_reward", request.idempotency_key, result)


@router.post("/route/select")
def select_route(
    request: RouteSelectionRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    previous_result = _existing_action(db, current_user.id, request.idempotency_key)
    if previous_result is not None:
        return previous_result

    run = _get_active_run(db, current_user.id)
    if run.run_status != "CHOOSING_ROUTE" or run.current_node_id is not None:
        raise HTTPException(status_code=409, detail="Hành trình chưa ở trạng thái chọn đường.")
    if _json(run.pending_pack_choices_json, []):
        raise HTTPException(status_code=409, detail="Hãy nhận pack thưởng trước khi chọn đường.")

    history_path = _json(run.history_path_json, [])
    if not history_path:
        raise HTTPException(status_code=409, detail="Chưa có phòng hoàn tất để chọn đường.")
    graph = _json(run.map_graph_json, {})
    previous_node_id = history_path[-1]
    options = get_route_options(graph, previous_node_id)
    if request.target_node_id not in {option["target_node_id"] for option in options}:
        raise HTTPException(status_code=422, detail="Phòng đích không nối trực tiếp từ phòng vừa hoàn tất.")

    target_node = graph.get("nodes", {}).get(request.target_node_id)
    if not target_node or int(target_node.get("floor", -1)) != run.current_floor:
        raise HTTPException(status_code=422, detail="Phòng đích không thuộc tầng hiện tại.")

    room_state = _prepare_room_state(db, run, request.target_node_id)
    _bump_run_version(db, run, current_user.id, request.expected_state_version)
    run.run_status = "IN_NODE"
    run.current_node_id = request.target_node_id
    run.room_state_json = json.dumps(room_state, ensure_ascii=False)

    if target_node["room_type"] in {"monster", "elite", "boss"}:
        core = _json(run.player_core_json, {})
        battle = _make_battle(db, run, core.get("deck_card_instance_ids", []), request.target_node_id)
        battle.state_version = run.state_version
        db.add(battle)

    result = _run_response(db, run)
    return _commit_action(db, current_user.id, run.run_id, "route_select", request.idempotency_key, result)


@router.post("/battle/play-card")
def play_battle_card(
    request: PlayCardRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    previous_result = _existing_action(db, current_user.id, request.idempotency_key)
    if previous_result is not None:
        return previous_result

    run = _get_active_run(db, current_user.id)
    if run.run_status != "IN_NODE" or not run.current_node_id:
        raise HTTPException(status_code=409, detail="Không có trận đấu trong hành trình hiện tại.")
    battle = _get_battle(db, run.run_id)
    _bump_run_version(db, run, current_user.id, request.expected_state_version)

    instance = db.get(StudyCardInstance, request.card_instance_id)
    if not instance or instance.player_id != current_user.id:
        raise HTTPException(status_code=404, detail="Không tìm thấy lá bài thuộc sở hữu của bạn.")
    core = _json(run.player_core_json, {})
    if instance.instance_id not in core.get("deck_card_instance_ids", []):
        raise HTTPException(status_code=422, detail="Lá bài không thuộc bộ bài của hành trình.")
    template = db.get(StudyCardTemplate, instance.card_id)
    if not template:
        raise HTTPException(status_code=409, detail="Dữ liệu mẫu lá bài không tồn tại.")

    battle_state = _json(battle.battle_state_json, {})
    battle_state.setdefault("card_metadata", {}).update(
        _card_metadata_for_instances(db, core.get("deck_card_instance_ids", []))
    )
    try:
        updated_state = play_card(
            battle_state,
            instance.instance_id,
            {
                "card_id": template.card_id,
                "mana_cost": template.mana_cost,
                "card_type": template.card_type,
                "tags": _json(template.tags_json, []),
                "effects": _json(template.effects_json, []) or legacy_effects(_json(template.effect_json, {})),
                "effect": _json(template.effect_json, {}),
                "exhaust": template.exhaust,
            },
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    battle.battle_state_json = json.dumps(updated_state, ensure_ascii=False)
    battle.battle_phase = updated_state["phase"]
    battle.state_version = run.state_version
    run.updated_at = datetime.now()
    result = _run_response(db, run)
    return _commit_action(db, current_user.id, run.run_id, "battle_play_card", request.idempotency_key, result)


@router.post("/battle/end-turn")
def end_battle_turn(
    request: VersionedActionRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    previous_result = _existing_action(db, current_user.id, request.idempotency_key)
    if previous_result is not None:
        return previous_result

    run = _get_active_run(db, current_user.id)
    if run.run_status != "IN_NODE":
        raise HTTPException(status_code=409, detail="Hành trình không ở trong trận đấu.")
    battle = _get_battle(db, run.run_id)
    _bump_run_version(db, run, current_user.id, request.expected_state_version)

    try:
        updated_state = end_player_turn(_json(battle.battle_state_json, {}))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    battle.battle_state_json = json.dumps(updated_state, ensure_ascii=False)
    battle.battle_phase = updated_state["phase"]
    battle.state_version = run.state_version
    run.updated_at = datetime.now()
    result = _run_response(db, run)
    return _commit_action(db, current_user.id, run.run_id, "battle_end_turn", request.idempotency_key, result)


@router.post("/battle/resolve")
def resolve_battle(
    request: ResolveBattleRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    previous_resolution = db.exec(
        select(StudyBattleResolution).where(
            StudyBattleResolution.player_id == current_user.id,
            StudyBattleResolution.idempotency_key == request.idempotency_key,
        )
    ).first()
    if previous_resolution:
        return _json(previous_resolution.result_json, {})

    run = _get_active_run(db, current_user.id)
    battle = _get_battle(db, run.run_id)
    idempotency_key = f"{run.run_id}_{battle.battle_id}"
    if request.idempotency_key != idempotency_key:
        raise HTTPException(status_code=422, detail="Idempotency key không khớp trận hiện tại.")

    if run.state_version != request.expected_state_version:
        raise HTTPException(status_code=409, detail="Trạng thái đã thay đổi. Hãy tải lại trận đấu.")
    battle_state = _json(battle.battle_state_json, {})
    if battle_state.get("phase") != "RESOLVING":
        raise HTTPException(status_code=409, detail="Trận đấu chưa kết thúc.")

    node_id = run.current_node_id
    if not node_id:
        raise HTTPException(status_code=409, detail="Không tìm thấy phòng đang kết toán.")
    graph = _json(run.map_graph_json, {})
    node = graph.get("nodes", {}).get(node_id, {})
    floor = int(node.get("floor", run.current_floor))
    history_path = _json(run.history_path_json, [])
    if node_id not in history_path:
        history_path.append(node_id)
    core = _json(run.player_core_json, {})
    core["hp"] = int(battle_state["player"]["hp"])

    _bump_run_version(db, run, current_user.id, request.expected_state_version)
    db.delete(battle)

    if core["hp"] <= 0:
        run_summary = {
            "run_id": run.run_id,
            "outcome": "DEFEATED",
            "grade": run.grade,
            "stage": int(core.get("stage", 1)),
            "stages_cleared": int(core.get("stages_cleared", 0)),
            "history_path": history_path,
            "player_core": core,
        }
        db.add(StudyRunHistory(
            run_id=run.run_id,
            player_id=current_user.id,
            outcome="DEFEATED",
            summary_json=json.dumps(run_summary, ensure_ascii=False),
        ))
        result = {
            "run_status": "DEFEATED",
            "run_id": run.run_id,
            "stage": int(core.get("stage", 1)),
            "stages_cleared": int(core.get("stages_cleared", 0)),
            "player_core": core,
        }
        db.add(StudyBattleResolution(
            idempotency_key=idempotency_key,
            player_id=current_user.id,
            run_id=run.run_id,
            battle_id=battle.battle_id,
            result_json=json.dumps(result, ensure_ascii=False),
        ))
        db.delete(run)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            previous_resolution = db.exec(
                select(StudyBattleResolution).where(
                    StudyBattleResolution.player_id == current_user.id,
                    StudyBattleResolution.idempotency_key == idempotency_key,
                )
            ).first()
            if previous_resolution:
                return _json(previous_resolution.result_json, {})
            raise HTTPException(status_code=409, detail="Trận đấu đã được kết toán đồng thời.")
        return result

    if node.get("room_type") == "boss":
        stage = int(core.get("stage", 1))
        relic_id = next_unowned_relic_id(db, current_user.id, random.SystemRandom())
        relic = RELIC_BY_ID.get(relic_id) if relic_id else None
        if relic:
            db.add(StudyPlayerRelic(player_id=current_user.id, relic_id=relic_id))
            core["relic_ids"] = [*core.get("relic_ids", []), relic_id]
        relic_reward = {
            "id": relic["id"],
            "name": relic["name"],
            "description": relic["description"],
            "image_url": f"/assets/items/charms/{relic['image']}",
        } if relic else None

        # Hạ boss không kết thúc hành trình: sang ải kế tiếp với bản đồ mới, quái mạnh hơn.
        next_stage = stage + 1
        core["stage"] = next_stage
        core["stages_cleared"] = int(core.get("stages_cleared", 0)) + 1
        resolved_battle_id = battle.battle_id
        db.flush()
        run.map_graph_json = json.dumps(generate_map_graph(secrets.randbits(32), next_stage))
        run.history_path_json = "[]"
        run.current_floor = 1
        run.current_node_id = "f1_node_1"
        run.run_status = "IN_NODE"
        run.pending_pack_choices_json = "[]"
        run.room_state_json = "{}"
        run.player_core_json = json.dumps(core, ensure_ascii=False)
        new_battle = _make_battle(db, run, core.get("deck_card_instance_ids", []), "f1_node_1")
        new_battle.state_version = run.state_version
        db.add(new_battle)
        db.flush()

        result = _run_response(db, run)
        result.update({
            "run_status": "IN_NODE",
            "stage_cleared": stage,
            "stage": next_stage,
            "relic_id": relic_id,
            "relic": relic_reward,
            "all_relics_collected": relic is None,
        })
        db.add(StudyBattleResolution(
            idempotency_key=idempotency_key,
            player_id=current_user.id,
            run_id=run.run_id,
            battle_id=resolved_battle_id,
            result_json=json.dumps(result, ensure_ascii=False),
        ))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            previous_resolution = db.exec(
                select(StudyBattleResolution).where(
                    StudyBattleResolution.player_id == current_user.id,
                    StudyBattleResolution.idempotency_key == idempotency_key,
                )
            ).first()
            if previous_resolution:
                return _json(previous_resolution.result_json, {})
            raise HTTPException(status_code=409, detail="Trận đấu đã được kết toán đồng thời.")
        return result

    run.player_core_json = json.dumps(core, ensure_ascii=False)
    run.history_path_json = json.dumps(history_path)
    run.current_node_id = None
    run.current_floor = floor + 1
    run.run_status = "CHOOSING_ROUTE"
    run.pending_pack_choices_json = json.dumps([random.SystemRandom().choice(REWARD_PACK_IDS)])
    run.room_state_json = "{}"
    result = {
        "run_status": "CHOOSING_ROUTE",
        "run_id": run.run_id,
        "state_version": run.state_version,
        "current_floor": run.current_floor,
        "history_path": history_path,
        "pending_pack_choices": json.loads(run.pending_pack_choices_json),
        "player_core": core,
    }
    db.add(StudyBattleResolution(
        idempotency_key=idempotency_key,
        player_id=current_user.id,
        run_id=run.run_id,
        battle_id=battle.battle_id,
        result_json=json.dumps(result, ensure_ascii=False),
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        previous_resolution = db.exec(
            select(StudyBattleResolution).where(
                StudyBattleResolution.player_id == current_user.id,
                StudyBattleResolution.idempotency_key == idempotency_key,
            )
        ).first()
        if previous_resolution:
            return _json(previous_resolution.result_json, {})
        raise HTTPException(status_code=409, detail="Trận đấu đã được kết toán đồng thời.")
    return result


@router.post("/pack/claim")
def claim_pack(
    request: ClaimPackRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    previous_result = _existing_action(db, current_user.id, request.idempotency_key)
    if previous_result is not None:
        return previous_result

    run = _get_active_run(db, current_user.id)
    if run.run_status != "CHOOSING_ROUTE" or run.current_node_id is not None:
        raise HTTPException(status_code=409, detail="Chưa đến thời điểm nhận pack thưởng.")
    choices = _json(run.pending_pack_choices_json, [])
    if request.chosen_pack_id not in choices:
        raise HTTPException(status_code=422, detail="Pack này không nằm trong danh sách phần thưởng.")

    pack = db.get(StudyPackTemplate, request.chosen_pack_id)
    if not pack or not pack.is_active:
        raise HTTPException(status_code=404, detail="Không tìm thấy pack.")
    inventory_entry = db.exec(
        select(StudyPlayerPack).where(
            StudyPlayerPack.player_id == current_user.id,
            StudyPlayerPack.pack_id == pack.pack_id,
        )
    ).first()
    if inventory_entry:
        inventory_entry.quantity += 1
        inventory_entry.state_version += 1
        quantity = inventory_entry.quantity
        inventory_version = inventory_entry.state_version
    else:
        db.add(StudyPlayerPack(player_id=current_user.id, pack_id=pack.pack_id, quantity=1, state_version=1))
        quantity = 1
        inventory_version = 1

    _bump_run_version(db, run, current_user.id, request.expected_state_version)
    run.pending_pack_choices_json = "[]"
    result = {
        "run_id": run.run_id,
        "state_version": run.state_version,
        "claimed_pack": {"pack_id": pack.pack_id, "name": pack.name, "quantity": quantity, "state_version": inventory_version},
        "pending_pack_choices": [],
    }
    return _commit_action(db, current_user.id, run.run_id, "claim_pack", request.idempotency_key, result)


@router.get("/node/challenge")
def get_node_challenge(
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = _get_active_run(db, current_user.id)
    if run.run_status != "IN_NODE" or not run.current_node_id:
        raise HTTPException(status_code=409, detail="Hiện không ở trong phòng thử thách.")

    graph = _json(run.map_graph_json, {})
    room_type = graph.get("nodes", {}).get(run.current_node_id, {}).get("room_type")
    room_state = _json(run.room_state_json, {})
    if room_type in {"inn", "event"} and room_state.get("challenge_type") == "quiz":
        question_ids = room_state.get("question_ids", [])
        questions = [db.get(QuestionBank, question_id) for question_id in question_ids]
        return {
            "room_type": room_type,
            "required_correct": len(question_ids),
            "reward_forfeited": bool(room_state.get("no_reward", False)),
            "locked_answers": room_state.get("locked_answers", {}),
            "retry_feedback": room_state.get("quiz_feedback", []),
            "questions": [{
                "id": question.id,
                "content": question.content,
                "subject": question.subject,
                "choices": _question_options(question),
            } for question in questions if question],
        }

    if room_type == "chest" and room_state.get("challenge_type") == "typing":
        passage = db.get(StudyPassage, room_state.get("passage_id"))
        if not passage:
            raise HTTPException(status_code=409, detail="Đoạn học liệu của phòng không còn tồn tại.")
        return {"room_type": "chest", "passage": {"passage_id": passage.passage_id, "content": passage.content}, "required_accuracy": 0.8}

    raise HTTPException(status_code=422, detail="Phòng hiện tại không có thử thách.")


@router.post("/node/complete")
def complete_noncombat_node(
    request: ChallengeCompletionRequest,
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    previous_result = _existing_action(db, current_user.id, request.idempotency_key)
    if previous_result is not None:
        return previous_result

    run = _get_active_run(db, current_user.id)
    if run.run_status != "IN_NODE" or not run.current_node_id:
        raise HTTPException(status_code=409, detail="Không có phòng đang chờ hoàn tất.")
    graph = _json(run.map_graph_json, {})
    node = graph.get("nodes", {}).get(run.current_node_id, {})
    room_type = node.get("room_type")
    room_state = _json(run.room_state_json, {})
    core = _json(run.player_core_json, {})
    reward: dict[str, Any] = {}
    reward_forfeited = bool(room_state.get("no_reward", False))

    if room_type in {"inn", "event"}:
        question_ids = room_state.get("question_ids", [])
        if not question_ids or set(request.answers) != {str(question_id) for question_id in question_ids}:
            return {"completed": False, "message": "Hãy trả lời đầy đủ các câu hỏi rồi thử lại."}
        questions = [db.get(QuestionBank, question_id) for question_id in question_ids]
        if any(question is None for question in questions):
            raise HTTPException(status_code=409, detail="Không tìm thấy câu hỏi của phòng hiện tại.")

        locked_answers = dict(room_state.get("locked_answers", {}))
        feedback = []
        for question in questions:
            question_key = str(question.id)
            submitted_answer = locked_answers.get(question_key, request.answers[question_key])
            question_feedback = _quiz_answer_feedback(question, submitted_answer)
            feedback.append(question_feedback)
            if question_feedback["is_correct"]:
                locked_answers[question_key] = question_feedback["correct_choice_key"]

        if not all(item["is_correct"] for item in feedback):
            room_state["no_reward"] = True
            room_state["failed_attempts"] = int(room_state.get("failed_attempts", 0)) + 1
            room_state["locked_answers"] = locked_answers
            room_state["quiz_feedback"] = feedback
            run.room_state_json = json.dumps(room_state, ensure_ascii=False)
            _bump_run_version(db, run, current_user.id, request.expected_state_version)
            run.updated_at = datetime.now()
            result = {
                "completed": False,
                "retry_required": True,
                "reward_forfeited": True,
                "state_version": run.state_version,
                "feedback": feedback,
                "locked_answers": locked_answers,
            }
            return _commit_action(db, current_user.id, run.run_id, "quiz_attempt", request.idempotency_key, result)

        reward_forfeited = bool(room_state.get("no_reward", False))

        if room_type == "inn" and not reward_forfeited:
            healed = max(1, round(int(core.get("hp_max", 80)) * 0.30))
            old_hp = int(core.get("hp", 80))
            core["hp"] = min(int(core.get("hp_max", 80)), old_hp + healed)
            reward = {"type": "heal", "amount": core["hp"] - old_hp}
        elif room_type == "event" and not reward_forfeited:
            effect = room_state.get("event_effect", {})
            if effect.get("type") == "heal":
                amount = max(1, round(int(core.get("hp_max", 80)) * int(effect.get("percent", 5)) / 100))
                old_hp = int(core.get("hp", 80))
                core["hp"] = min(int(core.get("hp_max", 80)), old_hp + amount)
                reward = {"type": "heal", "amount": core["hp"] - old_hp}
            elif effect.get("type") == "damage":
                amount = max(1, round(int(core.get("hp_max", 80)) * int(effect.get("percent", 5)) / 100))
                old_hp = int(core.get("hp", 80))
                core["hp"] = max(1, old_hp - amount)
                reward = {"type": "damage", "amount": old_hp - core["hp"]}
            elif effect.get("type") == "pack":
                reward = {"type": "pack", "pack": _award_pack(db, current_user.id, effect.get("pack_id", ""))}
            else:
                raise HTTPException(status_code=409, detail="Hiệu ứng sự kiện không hợp lệ.")
    elif room_type == "chest":
        passage = db.get(StudyPassage, room_state.get("passage_id"))
        if not passage or request.submitted_text is None:
            return {"completed": False, "message": "Hãy nhập lại nội dung trong rương."}
        accuracy = typing_accuracy(request.submitted_text, passage.content)
        if accuracy < 0.8:
            return {"completed": False, "message": "Độ chính xác chưa đạt 80%.", "accuracy": round(accuracy, 3)}
        card_id = secrets.choice([card["card_id"] for card in PHYSICS_CARDS])
        reward = {"type": "card", "card": _award_card(db, current_user.id, card_id), "accuracy": round(accuracy, 3)}
    else:
        raise HTTPException(status_code=422, detail="Phòng này không phải phòng thử thách.")

    history_path = _json(run.history_path_json, [])
    if run.current_node_id not in history_path:
        history_path.append(run.current_node_id)
    floor = int(node.get("floor", run.current_floor))
    _bump_run_version(db, run, current_user.id, request.expected_state_version)
    run.history_path_json = json.dumps(history_path)
    run.current_node_id = None
    run.current_floor = floor + 1
    run.run_status = "CHOOSING_ROUTE"
    run.player_core_json = json.dumps(core, ensure_ascii=False)
    run.room_state_json = "{}"
    result = {
        "completed": True,
        "run_id": run.run_id,
        "state_version": run.state_version,
        "run_status": run.run_status,
        "current_floor": run.current_floor,
        "history_path": history_path,
        "player_core": core,
        "reward": reward,
        "reward_forfeited": reward_forfeited,
    }
    return _commit_action(db, current_user.id, run.run_id, "node_complete", request.idempotency_key, result)