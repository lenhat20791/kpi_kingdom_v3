import sys
import unittest
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import QuestionBank, StudyPassage
from services.classroom_content import (
    load_grade_lessons,
    load_grade_lesson_files,
    load_grade_quiz_files,
    load_grade_quiz_questions,
    sync_grade_classroom_content,
)


class ClassroomContentTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine, tables=[QuestionBank.__table__, StudyPassage.__table__])

    def tearDown(self):
        self.engine.dispose()

    def test_grade_folders_provide_distinct_lessons_and_quizzes(self):
        grade_six_lessons = load_grade_lessons(6)
        grade_seven_lessons = load_grade_lessons(7)
        grade_six_questions = load_grade_quiz_questions(6)
        grade_seven_questions = load_grade_quiz_questions(7)
        grade_six_quiz_files = load_grade_quiz_files(6)
        grade_seven_lesson_files = load_grade_lesson_files(7)

        self.assertEqual(len(grade_six_lessons), 46)
        self.assertEqual(len(grade_seven_lessons), 60)
        self.assertEqual(len(grade_six_questions), 100)
        self.assertEqual(len(grade_seven_questions), 60)
        self.assertTrue(all(item["source_key"].startswith("json:g6:") for item in grade_six_questions))
        self.assertTrue(all(item["source_key"].startswith("json:g7:") for item in grade_seven_questions))
        self.assertNotEqual(grade_six_lessons[0]["content"], grade_seven_lessons[0]["content"])
        self.assertEqual(sum(map(len, grade_six_quiz_files.values())), 100)
        self.assertEqual(sum(map(len, grade_seven_lesson_files.values())), 60)
        self.assertIn("answer", grade_six_quiz_files[next(iter(grade_six_quiz_files))][0])
        self.assertIn("text", grade_seven_lesson_files[next(iter(grade_seven_lesson_files))][0])

    def test_sync_is_idempotent_and_keeps_grade_sources_separate(self):
        with Session(self.engine) as session:
            sync_grade_classroom_content(session, 6)
            sync_grade_classroom_content(session, 7)
            session.commit()

            first_count = len(session.exec(select(QuestionBank)).all())
            sync_grade_classroom_content(session, 6)
            session.commit()

            questions = session.exec(select(QuestionBank)).all()
            lessons = session.exec(select(StudyPassage)).all()

        self.assertEqual(first_count, 160)
        self.assertEqual(len(questions), first_count)
        self.assertEqual(sum(question.grade == 6 for question in questions), 100)
        self.assertEqual(sum(question.grade == 7 for question in questions), 60)
        self.assertEqual(sum(passage.grade == 6 for passage in lessons), 46)
        self.assertEqual(sum(passage.grade == 7 for passage in lessons), 60)


if __name__ == "__main__":
    unittest.main()
