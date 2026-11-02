import json
import re
from pathlib import Path
from typing import Any

from sqlmodel import Session, delete, select

from database import QuestionBank, StudyPassage


CONTENT_ROOT = Path(__file__).resolve().parents[2] / "data câu hỏi"
SUPPORTED_GRADES = (6, 7)


def _read_grade_files(category: str, grade: int) -> list[tuple[Path, list[dict[str, Any]]]]:
    if grade not in SUPPORTED_GRADES:
        raise ValueError(f"Chưa hỗ trợ dữ liệu khối {grade}.")

    grade_directory = CONTENT_ROOT / category / f"khoi_{grade}"
    files = sorted(grade_directory.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"Không tìm thấy JSON khối {grade} trong {grade_directory}.")

    result = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Không đọc được dữ liệu {path}: {error}") from error
        if not isinstance(data, list):
            raise ValueError(f"Dữ liệu {path} phải là danh sách JSON.")
        if not all(isinstance(item, dict) for item in data):
            raise ValueError(f"Mỗi phần tử trong {path} phải là một object JSON.")
        result.append((path, data))
    return result


def load_grade_lessons(grade: int) -> list[dict[str, str]]:
    lessons = []
    for path, rows in _read_grade_files("bai_hoc", grade):
        relative_path = path.relative_to(CONTENT_ROOT).as_posix()
        for index, row in enumerate(rows):
            content = row.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError(f"Thiếu nội dung bài học ở {relative_path}, dòng {index + 1}.")
            source_id = row.get("id", index + 1)
            lessons.append({
                "passage_id": f"json:g{grade}:{relative_path}:{source_id}",
                "grade": grade,
                "subject": str(row.get("subject") or path.stem),
                "content": content.strip(),
            })
    if not lessons:
        raise ValueError(f"Không có bài học hợp lệ cho khối {grade}.")
    return lessons


def load_grade_lesson_files(grade: int) -> dict[str, list[dict[str, str]]]:
    lesson_files = {}
    for path, rows in _read_grade_files("bai_hoc", grade):
        lessons = []
        for index, row in enumerate(rows):
            content = row.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError(f"Thiếu nội dung bài học ở {path.name}, dòng {index + 1}.")
            lessons.append({"text": content.strip(), "content": content.strip()})
        lesson_files[path.name] = lessons
    return lesson_files


def load_grade_quiz_questions(grade: int) -> list[dict[str, str]]:
    questions = []
    for path, rows in _read_grade_files("trac_nghiem", grade):
        relative_path = path.relative_to(CONTENT_ROOT).as_posix()
        for index, row in enumerate(rows):
            content = row.get("content") or row.get("question")
            choices = row.get("options")
            if not isinstance(choices, list):
                choices = [row.get(letter) or row.get(letter.upper()) for letter in "abcd"]
            if (
                not isinstance(content, str)
                or not content.strip()
                or len(choices) != 4
                or any(not isinstance(choice, (str, int, float)) or not str(choice).strip() for choice in choices)
            ):
                raise ValueError(f"Câu hỏi không đúng định dạng ở {relative_path}, dòng {index + 1}.")

            correct = row.get("correct", row.get("answer"))
            if correct is None or not str(correct).strip():
                raise ValueError(f"Thiếu đáp án đúng ở {relative_path}, dòng {index + 1}.")
            correct_text = str(correct).strip()
            if re.fullmatch(r"[a-d]\.?", correct_text, re.IGNORECASE):
                correct_text = str(choices[ord(correct_text[0].lower()) - ord("a")])
            elif correct_text not in {str(choice) for choice in choices}:
                raise ValueError(f"Đáp án không khớp lựa chọn ở {relative_path}, dòng {index + 1}.")

            questions.append({
                "source_key": f"json:g{grade}:{relative_path}:{row.get('id', index + 1)}",
                "subject": str(row.get("subject") or path.stem),
                "difficulty": str(row.get("difficulty") or "medium"),
                "content": content.strip(),
                "options_json": json.dumps([str(choice) for choice in choices], ensure_ascii=False),
                "correct_answer": correct_text,
                "explanation": str(row.get("explain") or row.get("explanation") or ""),
            })
    if not questions:
        raise ValueError(f"Không có câu hỏi trắc nghiệm hợp lệ cho khối {grade}.")
    return questions


def load_grade_quiz_files(grade: int) -> dict[str, list[dict[str, Any]]]:
    files: dict[str, list[dict[str, Any]]] = {}
    for question in load_grade_quiz_questions(grade):
        source_path = question["source_key"].split(":", 2)[2].rsplit(":", 1)[0]
        filename = Path(source_path).name
        files.setdefault(filename, []).append({
            "question": question["content"],
            "content": question["content"],
            "options": json.loads(question["options_json"]),
            "answer": question["correct_answer"],
            "correct_answer": question["correct_answer"],
            "explain": question["explanation"],
            "subject": question["subject"],
            "difficulty": question["difficulty"],
        })
    return files


def sync_grade_quiz_questions(db: Session, grade: int) -> list[QuestionBank]:
    questions = load_grade_quiz_questions(grade)
    source_prefix = f"json:g{grade}:"
    existing = db.exec(
        select(QuestionBank).where(QuestionBank.source_key.startswith(source_prefix))
    ).all()
    existing_by_key = {question.source_key: question for question in existing}
    current_keys = {item["source_key"] for item in questions}

    for item in questions:
        question = existing_by_key.get(item["source_key"])
        if question is None:
            question = QuestionBank(grade=grade, **item)
        else:
            for key, value in item.items():
                setattr(question, key, value)
        question.grade = grade
        db.add(question)

    for question in existing:
        if question.source_key not in current_keys:
            db.delete(question)

    db.flush()
    return db.exec(
        select(QuestionBank)
        .where(QuestionBank.grade == grade, QuestionBank.source_key.startswith(source_prefix))
        .order_by(QuestionBank.id)
    ).all()


def sync_grade_lessons(db: Session, grade: int) -> list[StudyPassage]:
    lessons = load_grade_lessons(grade)
    source_prefix = f"json:g{grade}:"
    existing = db.exec(
        select(StudyPassage).where(StudyPassage.passage_id.startswith(source_prefix))
    ).all()
    existing_by_id = {passage.passage_id: passage for passage in existing}
    current_ids = {item["passage_id"] for item in lessons}

    for item in lessons:
        passage = existing_by_id.get(item["passage_id"])
        if passage is None:
            passage = StudyPassage(**item)
        else:
            passage.subject = item["subject"]
            passage.content = item["content"]
            passage.is_active = True
        db.add(passage)

    for passage in existing:
        if passage.passage_id not in current_ids:
            db.delete(passage)

    db.flush()
    return db.exec(
        select(StudyPassage)
        .where(
            StudyPassage.grade == grade,
            StudyPassage.is_active == True,
            StudyPassage.passage_id.startswith(source_prefix),
        )
        .order_by(StudyPassage.passage_id)
    ).all()


def sync_grade_classroom_content(db: Session, grade: int) -> tuple[list[QuestionBank], list[StudyPassage]]:
    questions = sync_grade_quiz_questions(db, grade)
    lessons = sync_grade_lessons(db, grade)
    return questions, lessons


def normalize_subject(subject: str) -> str:
    from unidecode import unidecode

    normalized = re.sub(r"[^a-z0-9]", "", unidecode(subject).lower())
    aliases = {
        "ly": "vatli",
        "vatly": "vatli",
        "sinh": "sinhhoc",
        "biology": "sinhhoc",
        "hoa": "hoahoc",
        "chemistry": "hoahoc",
        "math": "toan",
        "mathematics": "toan",
    }
    return aliases.get(normalized, normalized)
