import unittest
from datetime import date

from app.services.group_schedule_changes import parse_group_change

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

    def test_ambiguous_cancel_requests_pair_number(self):
        lessons = LESSONS + [{
            "day": "2026-11-02", "num": 5, "start_t": "17:00", "end_t": "18:30",
            "subject": "Химия", "teacher": "", "room": ""}]
        draft, clarification = parse_group_change(
            "Химии завтра не будет", TODAY, CATALOG, lessons)
        self.assertIsNone(draft)
        self.assertIn("Уточните номер пары", clarification)


if __name__ == "__main__":
    unittest.main()
