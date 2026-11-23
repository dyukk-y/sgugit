import unittest
from datetime import date

from app.services.group_schedule_changes import _resolve_subject, parse_group_change

TODAY = date(2026, 11, 1)
CATALOG = [("математика", "Математика"), ("английский", "Английский язык"),
           ("химия", "Химия")]
LESSONS = [
    {"day": "2026-11-02", "num": 4, "start_t": "15:20", "end_t": "16:50",
     "subject": "История", "teacher": "", "room": ""},
    {"day": "2026-11-02", "num": 2, "start_t": "11:00", "end_t": "12:30",
     "subject": "Химия", "teacher": "", "room": ""},
]


class GroupScheduleChangeTests(unittest.TestCase):
    def test_casual_grade_message_is_not_a_schedule_change(self):
        catalog = CATALOG + [
            ("построение 3d моделей местности для целей землеустройства и кадастров",
             "Построение 3D моделей местности для целей землеустройства и кадастров")
        ]
        for phrase in ("ну мне 4 поставили", "мне четвёрку поставили",
                       "ну мне 4 поставили по построению"):
            with self.subTest(phrase=phrase):
                draft, clarification = parse_group_change(phrase, TODAY, catalog, LESSONS)
                self.assertIsNone(draft)
                self.assertIsNone(clarification)

    def test_explicit_subject_prefix_still_resolves(self):
        catalog = [("математический анализ", "Математический анализ")]
        self.assertEqual(_resolve_subject("математи", catalog), "Математический анализ")

    def test_cancel_existing_subject(self):
        draft, clarification = parse_group_change(
            "Химии завтра не будет", TODAY, CATALOG, LESSONS)
        self.assertIsNone(clarification)
        self.assertEqual((draft.action, draft.day, draft.num, draft.subject),
                         ("cancel", "2026-11-02", 2, "Химия"))

    def test_add_using_ordinal_pair(self):
        draft, clarification = parse_group_change(
            "Завтра будет математика четвёртой парой", TODAY, CATALOG, LESSONS)
        self.assertIsNone(clarification)
        self.assertEqual((draft.action, draft.day, draft.num, draft.start, draft.end),
                         ("add", "2026-11-02", 4, "15:20", "16:50"))

    def test_add_using_start_time(self):
        draft, clarification = parse_group_change(
            "Английский будет в 15:20", TODAY, CATALOG, LESSONS)
        self.assertIsNone(clarification)
        self.assertEqual((draft.action, draft.num, draft.start, draft.end),
                         ("add", 4, "15:20", "16:50"))

    def test_question_is_not_a_change(self):
        draft, clarification = parse_group_change(
            "Завтра будет математика?", TODAY, CATALOG, LESSONS)
        self.assertIsNone(draft)
        self.assertIsNone(clarification)

    def test_change_without_subject_is_ignored(self):
        for text in ("Завтра не будет второй пары", "Завтра отменили 2 пару",
                     "Завтра пар не будет", "Встречу перенесли на завтра"):
            with self.subTest(text=text):
                draft, clarification = parse_group_change(text, TODAY, CATALOG, LESSONS)
                self.assertIsNone(draft)
                self.assertIsNone(clarification)

    def test_short_subject_alias_is_recognized(self):
        catalog = CATALOG + [("мат.", "Математика")]
        lessons = LESSONS + [{
            "day": "2026-11-02", "num": 4, "start_t": "15:20", "end_t": "16:50",
            "subject": "Математика", "teacher": "", "room": ""}]
        draft, clarification = parse_group_change(
            "Завтра мат. не будет", TODAY, catalog, lessons)
        self.assertIsNone(clarification)
        self.assertEqual((draft.action, draft.subject, draft.num),
                         ("cancel", "Математика", 4))

    def test_ambiguous_cancel_requests_pair_number(self):
        lessons = LESSONS + [{
            "day": "2026-11-02", "num": 5, "start_t": "17:00", "end_t": "18:30",
            "subject": "Химия", "teacher": "", "room": ""}]
        draft, clarification = parse_group_change(
            "Химии завтра не будет", TODAY, CATALOG, lessons)
        self.assertIsNone(draft)
        self.assertIn("Уточните номер пары", clarification)


    def test_change_room_by_audience_phrase(self):
        catalog = [("маркшейдерско-геодезические приборы", "Маркшейдерско-геодезические приборы")]
        lessons = [{"day": "2026-11-01", "num": 2, "start_t": "11:00", "end_t": "12:30",
                    "subject": "Маркшейдерско-геодезические приборы", "room": "215"}]
        draft, clarification = parse_group_change(
            "Маркшейдерско-геодезические приборы будут в 310 аудитории, если я правильно понял, из-за недоступности 4-го этажа сегодня",
            TODAY, catalog, lessons)
        self.assertIsNone(clarification)
        self.assertEqual((draft.action, draft.room, draft.num), ("room", "310", 2))

    def test_room_change_requires_unambiguous_lesson(self):
        catalog = [("химия", "Химия")]
        lessons = [dict(LESSONS[1], day="2026-11-01", room="215"),
                   dict(LESSONS[1], day="2026-11-01", num=3, room="216")]
        draft, clarification = parse_group_change(
            "Химия сегодня будет в аудитории 310", TODAY, catalog, lessons)
        self.assertIsNone(draft)
        self.assertIn("Уточните номер пары", clarification)


    def test_common_short_forms(self):
        catalog = CATALOG + [
            ("математика", "Математика"),
            ("информатика", "Информатика"),
            ("геодезия", "Геодезия"),
        ]
        lessons = LESSONS + [
            {"day": "2026-11-02", "num": 3, "start_t": "12:50", "end_t": "14:20",
             "subject": "Математика", "teacher": "", "room": ""},
            {"day": "2026-11-02", "num": 1, "start_t": "09:00", "end_t": "10:30",
             "subject": "Информатика", "teacher": "", "room": ""},
            {"day": "2026-11-02", "num": 5, "start_t": "17:00", "end_t": "18:30",
             "subject": "Геодезия", "teacher": "", "room": ""},
        ]
        for phrase, subject in (("матан", "Математика"), ("инфа", "Информатика"), ("геод", "Геодезия")):
            with self.subTest(phrase=phrase):
                draft, clarification = parse_group_change(
                    f"Завтра {phrase} отменили", TODAY, catalog, lessons)
                self.assertIsNone(clarification)
                self.assertEqual(draft.subject, subject)

    def test_room_abbreviation_and_colloquial_transfer(self):
        catalog = [("геодезия", "Геодезия")]
        lessons = [{"day": "2026-11-02", "num": 2, "start_t": "11:00", "end_t": "12:30",
                    "subject": "Геодезия", "teacher": "", "room": "215"}]
        for phrase in ("Завтра геодезия будет в ауд. 310",
                       "Завтра геодезию перевели в каб. 310",
                       "Завтра геодезия теперь в 310"):
            with self.subTest(phrase=phrase):
                draft, clarification = parse_group_change(phrase, TODAY, catalog, lessons)
                self.assertIsNone(clarification)
                self.assertEqual((draft.action, draft.room), ("room", "310"))

    def test_cancel_synonyms(self):
        for phrase in ("Завтра химию сняли", "Завтра химию убрали из расписания"):
            with self.subTest(phrase=phrase):
                draft, clarification = parse_group_change(phrase, TODAY, CATALOG, LESSONS)
                self.assertIsNone(clarification)
                self.assertEqual((draft.action, draft.subject), ("cancel", "Химия"))


    def test_colloquial_transfer_verbs_are_recognized(self):
        catalog = [("геодезия", "Геодезия")]
        lessons = [
            {"day": "2026-11-02", "num": 2, "start_t": "11:00", "end_t": "12:30",
             "subject": "Геодезия", "teacher": "", "room": ""},
            {"day": "2026-11-02", "num": 3, "start_t": "12:50", "end_t": "14:20",
             "subject": "История", "teacher": "", "room": ""}
        ]
        for phrase in ("Завтра геодезию перевели на третью пару",
                       "Завтра геодезию переместили на третью пару",
                       "Завтра геодезию переставили на третью пару"):
            with self.subTest(phrase=phrase):
                draft, clarification = parse_group_change(phrase, TODAY, catalog, lessons)
                self.assertIsNone(clarification)
                self.assertEqual((draft.action, draft.num), ("move", 3))

    def test_transfer_without_target_asks_for_clarification(self):
        catalog = [("геодезия", "Геодезия")]
        lessons = [dict(LESSONS[1], day="2026-11-02", subject="Геодезия")]
        draft, clarification = parse_group_change(
            "Завтра геодезию перевели", TODAY, catalog, lessons)
        self.assertIsNone(draft)
        self.assertIn("На какую пару перенесли", clarification)


if __name__ == "__main__":
    unittest.main()
