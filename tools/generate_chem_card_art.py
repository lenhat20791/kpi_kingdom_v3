"""Prepare free AI Studio prompts and normalize downloaded chemistry card art."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "data" / "deck_hoa_hoc.txt"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "frontend" / "assets" / "Deck" / "deck hoa hoc"
DEFAULT_INBOX_DIR = PROJECT_ROOT / "data" / "artbox_inbox"
DEFAULT_PROMPTS_FILE = PROJECT_ROOT / "data" / "deck_hoa_hoc_prompts.txt"
ALLOWED_RARITIES = {"R", "SR", "SSR", "UR"}

STYLE_BY_RARITY = {
    "R": "R rarity card art, 2D game illustration, bold comic lineart, deep teal and navy glow, clear silhouette",
    "SR": "SR rarity card art, 2D game illustration, bold comic lineart, rich teal and cobalt palette, luminous accents",
    "SSR": "SSR rarity card art, 2D game illustration, bold comic lineart, vivid jewel tones, radiant layered energy",
    "UR": "UR card art, 2D game illustration, bold comic lineart, mystical aura, luminous golden highlights, dramatic radiant energy",
}


@dataclass
class Card:
    filename: str
    name: str
    rarity: str
    card_type: str
    cost: int
    description: str
    art_prompt: str
    mechanics: str = ""
    tooltips: list[str] = field(default_factory=list)

    def full_prompt(self) -> str:
        subject = self.art_prompt.rstrip(". ")
        return (
            f"{subject}. {STYLE_BY_RARITY[self.rarity]}, centered square composition, "
            "single readable focal subject, strong contrast, no text, no letters, no numbers, "
            "no watermark, no card frame, no border."
        )


def parse_cards(path: Path) -> list[Card]:
    cards: list[Card] = []
    fields: dict[str, list[str]] = {}

    def finish_record() -> None:
        if not fields:
            return
        required = ("filename", "name", "rarity", "card_type", "cost", "description", "art_prompt")
        missing = [key for key in required if key not in fields]
        if missing:
            raise ValueError(f"Thẻ thiếu trường {', '.join(missing)}: {fields.get('name', ['?'])[0]}")
        values = {key: entries[0].strip() for key, entries in fields.items() if key != "tooltip"}
        filename = values["filename"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.png", filename, flags=re.IGNORECASE):
            raise ValueError(f"Tên file không hợp lệ: {filename!r}; chỉ chấp nhận tên .png đơn giản")
        rarity = values["rarity"].upper()
        if rarity not in ALLOWED_RARITIES:
            raise ValueError(f"Độ hiếm không hợp lệ ở {filename}: {rarity}")
        try:
            cost = int(values["cost"])
        except ValueError as error:
            raise ValueError(f"Cost phải là số nguyên ở {filename}") from error
        cards.append(Card(
            filename=filename,
            name=values["name"],
            rarity=rarity,
            card_type=values["card_type"],
            cost=cost,
            description=values["description"],
            art_prompt=values["art_prompt"],
            mechanics=values.get("mechanics", ""),
            tooltips=[entry.strip() for entry in fields.get("tooltip", []) if entry.strip()],
        ))
        fields.clear()

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line == "---":
            finish_record()
            continue
        if ":" not in line:
            raise ValueError(f"Dòng {line_number}: cần định dạng 'trường: nội dung'")
        key, value = (part.strip() for part in line.split(":", maxsplit=1))
        key = key.lower()
        if key not in {"filename", "name", "rarity", "card_type", "cost", "description", "mechanics", "art_prompt", "tooltip"}:
            raise ValueError(f"Dòng {line_number}: trường không được hỗ trợ: {key}")
        fields.setdefault(key, []).append(value)
    finish_record()
    filenames = [card.filename.casefold() for card in cards]
    if not cards:
        raise ValueError(f"Không tìm thấy thẻ nào trong {path}")
    if len(filenames) != len(set(filenames)):
        raise ValueError("File đầu vào có tên artbox bị trùng")
    return cards


def select_cards(cards: list[Card], only: str | None) -> list[Card]:
    if not only:
        return cards
    wanted = {name.strip().casefold() for name in only.split(",") if name.strip()}
    selected = [card for card in cards if card.filename.casefold() in wanted or Path(card.filename).stem.casefold() in wanted]
    found = {card.filename.casefold() for card in selected} | {Path(card.filename).stem.casefold() for card in selected}
    missing = wanted - found
    if missing:
        raise ValueError(f"Không tìm thấy thẻ: {', '.join(sorted(missing))}")
    return selected


def export_prompts(cards: list[Card], output_file: Path | None) -> None:
    content = "\n\n".join(
        f"FILE: {card.filename}\nTÊN THẺ: {card.name} ({card.rarity})\nPROMPT: {card.full_prompt()}"
        for card in cards
    ) + "\n"
    if output_file is None:
        print(content, end="")
        return
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(content, encoding="utf-8")
    print(f"Đã xuất {len(cards)} prompt: {output_file}")


def normalize_images(cards: list[Card], inbox_dir: Path, output_dir: Path, force: bool) -> tuple[int, int, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    done = skipped = failed = 0
    for card in cards:
        source = inbox_dir / card.filename
        destination = output_dir / card.filename
        if destination.exists() and not force:
            print(f"Bỏ qua artbox đã có (dùng --force để ghi đè): {destination.name}")
            skipped += 1
            continue
        if not source.is_file():
            print(f"Thiếu ảnh tải từ AI Studio: {source}")
            failed += 1
            continue
        temporary = destination.with_name(f".{destination.stem}.tmp.png")
        try:
            with Image.open(source) as image:
                normalized = ImageOps.fit(image.convert("RGB"), (512, 512), method=Image.Resampling.LANCZOS)
                normalized.save(temporary, format="PNG", optimize=True)
            temporary.replace(destination)
            print(f"Đã chuẩn hóa: {destination}")
            done += 1
        except (OSError, ValueError) as error:
            temporary.unlink(missing_ok=True)
            print(f"Lỗi ảnh {source.name}: {error}")
            failed += 1
    return done, skipped, failed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Chuẩn bị prompt AI Studio miễn phí và chuẩn hóa ảnh artbox tải về.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="File TXT dữ liệu thẻ")
    parser.add_argument("--only", help="Chỉ chọn danh sách filename hoặc basename, phân cách bằng dấu phẩy")
    parser.add_argument("--normalize", action="store_true", help="Chuẩn hóa ảnh đã tải trong inbox thành PNG 512x512")
    parser.add_argument("--inbox", type=Path, default=DEFAULT_INBOX_DIR, help="Thư mục đặt ảnh tải xuống từ AI Studio")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Thư mục artbox game")
    parser.add_argument("--prompts-out", type=Path, default=DEFAULT_PROMPTS_FILE, help="File xuất prompt; dùng '-' để in ra màn hình")
    parser.add_argument("--force", action="store_true", help="Ghi đè artbox đã có khi dùng --normalize")
    parser.add_argument("--dry-run", action="store_true", help="Chỉ in prompt, không ghi file và không xử lý ảnh")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        cards = select_cards(parse_cards(args.input), args.only)
        if args.normalize:
            if args.dry_run:
                print(f"Dry-run: sẽ xử lý {len(cards)} ảnh từ {args.inbox} sang {args.output_dir}")
                return 0
            done, skipped, failed = normalize_images(cards, args.inbox, args.output_dir, args.force)
            print(f"Kết quả: {done} hoàn tất, {skipped} bỏ qua, {failed} lỗi.")
            return 1 if failed else 0
        output_file = None if str(args.prompts_out) == "-" else args.prompts_out
        if args.dry_run:
            for card in cards:
                print(f"{card.filename}: {card.full_prompt()}")
            print(f"Dry-run: {len(cards)} thẻ; không gọi API, không ghi ảnh.")
            return 0
        export_prompts(cards, output_file)
        print("Tạo ảnh thủ công trong Google AI Studio; script không gọi API và không thực hiện thanh toán.")
        return 0
    except (OSError, ValueError) as error:
        print(f"Lỗi: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())