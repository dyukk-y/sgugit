import unittest
from datetime import date
from app.services.nlu import detect_intent, parse_when, parse_hw_phrase, find_subject

TODAY = date(2026, 10, 14)  # среда
CAT = [("математика", "Математика"), ("матеша", "Математика"), ("матан", "Математика"),
       ("физика", "Физика"), ("физра", "Физическая культура"), ("физическая культура", "Физическая культура"),
       ("информатика", "Информатика"), ("инфа", "Информатика"), ("история", "История"),
       ("геодезия", "Геодезия"), ("инженерная графика", "Инженерная графика")]

class T(unittest.TestCase):
    def check(self, text, name, day=None, num=None, subject=None):
        i = detect_intent(text, TODAY, CAT)
        self.assertIsNotNone(i, text)
        self.assertEqual(i.name, name, text)
        if day is not None: self.assertEqual(i.day, day, text)
        if num is not None: self.assertEqual(i.num, num, text)
        if subject is not None: self.assertEqual(i.subject, subject, text)

    def test_when(self):
        self.assertEqual(parse_when("завтра", TODAY)[0], date(2026, 10, 15))
        self.assertEqual(parse_when("послезавтра", TODAY)[0], date(2026, 10, 16))
        self.assertEqual(parse_when("в пятницу", TODAY)[0], date(2026, 10, 16))
        self.assertEqual(parse_when("в среду", TODAY)[0], date(2026, 10, 21))
        self.assertEqual(parse_when("на 25.10", TODAY)[0], date(2026, 10, 25))
        self.assertEqual(parse_when("25 октября", TODAY)[0], date(2026, 10, 25))
        self.assertEqual(parse_when("через 3 дня", TODAY)[0], date(2026, 10, 17))
        self.assertEqual(parse_when("1 января", TODAY)[0], date(2027, 1, 1))
        self.assertEqual(parse_when("на следующей неделе", TODAY), (None, 1))
        self.assertEqual(parse_when("в следующий понедельник", TODAY)[0], date(2026, 10, 26))
        self.assertEqual(parse_when("31.02", TODAY)[0], None)

    def test_first(self):
        for s in ["какая завтра первая пара?", "первая пара завтра", "к скольки завтра", "во сколько завтра начинаем",
                  "с какой пары завтра", "когда завтра первая пара", "Какая завтра первая пара"]:
            self.check(s, "first", day=date(2026, 10, 15))

    def test_day(self):
        for s in ["какие завтра пары?", "расписание на завтра", "пары на завтра", "что завтра по парам", "что у нас завтра по парам",
                  "скинь расписание на завтра", "какие пары завтра"]:
            self.check(s, "day", day=date(2026, 10, 15))
        self.check("что у нас в пятницу", "day", day=date(2026, 10, 16))
        self.check("расписание на 25.10", "day", day=date(2026, 10, 25))
        self.check("пары на сегодня", "day", day=TODAY)

    def test_others(self):
        self.check("когда завтра заканчиваем", "last")
        self.check("во сколько домой завтра", "last")
        self.check("какая следующая пара", "next")
        self.check("что сейчас идёт", "next")
        self.check("что дальше", "next")
        self.check("сколько пар завтра", "count")
        self.check("завтра выходной?", "count")
        self.check("есть ли завтра пары", "count")
        self.check("расписание на неделю", "week")
        self.check("пары на следующей неделе", "week")
        self.check("какая сейчас неделя", "parity")
        self.check("что задали", "hw")
        self.check("дз на завтра", "hw")
        self.check("домашка по математике", "hw")
        self.check("когда экзамен по физике", "exam")
        self.check("привет", "greet")
        self.check("спасибо", "thanks")
        self.check("помощь", "help")

    def test_subject(self):
        self.check("в какой аудитории математика", "room", subject="Математика")
        self.check("где завтра вторая пара", "room", num=2)
        self.check("куда идти на физику", "room", subject="Физика")
        self.check("кто ведёт физику", "teacher", subject="Физика")
        self.check("кто завтра у нас по математике", "teacher", subject="Математика")
        self.check("когда физика", "when_subject", subject="Физика")
        self.check("когда следующая матеша", "when_subject", subject="Математика")
        self.check("когда физра", "when_subject", subject="Физическая культура")
        self.check("какая завтра 3 пара", "day", num=3)

    def test_unknown(self):
        for s in ["", "асдф", "как дела у тебя", "я люблю котиков", "ок"]:
            self.assertIsNone(detect_intent(s, TODAY, CAT), s)

    def test_find_subject(self):
        self.assertEqual(find_subject("задали по инженерной графике", CAT), "Инженерная графика")
        self.assertEqual(find_subject("матешу", CAT), "Математика")
        self.assertIsNone(find_subject("привет как дела", CAT))

    def test_hw_phrase(self):
        p = parse_hw_phrase("дз математика №15-20 к пятнице", CAT, TODAY)
        self.assertIsNotNone(p); self.assertEqual(p.subject, "Математика"); self.assertEqual(p.due, date(2026, 10, 16))
        self.assertIn("№15-20", p.text)
        p = parse_hw_phrase("задание физика: лаба 3 до 25.10", CAT, TODAY)
        self.assertEqual((p.subject, p.due), ("Физика", date(2026, 10, 25))); self.assertIn("лаба 3", p.text)
        self.assertIsNone(parse_hw_phrase("дз на завтра", CAT, TODAY))
        self.assertIsNone(parse_hw_phrase("домашка по математике", CAT, TODAY))
        self.assertIsNone(parse_hw_phrase("что задали по физике?", CAT, TODAY))
        self.assertIsNone(parse_hw_phrase("дз", CAT, TODAY))
if __name__ == "__main__":
    unittest.main()
