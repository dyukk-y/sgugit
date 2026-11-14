import unittest
from app.services.fio import validate_fio, short_name, FioContext, fio_key, patronymic_known

GOOD = ["Петрова Анна Сергеевна", "Смирнов Алексей Дмитриевич", "Кузнецова Мария Андреевна",
        "Попов Дмитрий Александрович", "Соколова Екатерина Владимировна", "Лебедев Никита Павлович",
        "Козлов Артём Максимович", "Новикова Дарья Игоревна", "Морозов Егор Олегович", "Алиев Тимур Рашид оглы",
        "Ахмедова Лейла Руслановна", "Сидоров-Петров Пётр Иванович", "Гусейнов Али Мамедович",
        "Ким Анастасия Викторовна", "Нгуен Тхи Лан", "Хусаинов Ильдар Рустамович", "Бекова Айгуль Кайратовна",
        "Мартынов Кирилл Андреевич", "Ковалевич Ольга Николаевна", "Жуков Георгий Константинович",
        "Дьяконов Матвей Ильич", "Щербакова Полина Сергеевна", "Чернов Ян Юрьевич", "Абдуллаев Шерзод Баходирович"]
BAD = ["", "Фамилия Имя Отчество", "ФИО", "Иванов Иван Иванович", "Тест", "asdf asdf", "Ivan Ivanov",
       "Иван", "Аааа Бббб Вввв", "Йцукен Фывапр Олджэ", "хуй пизда джигурда", "Иванов Иван Ивaнович",
       "Иванов И.И.", "123 456", "Иванов Иван Иванович Петрович Сидорович", "Иван Иванович Иванов",
       "Лох Дурак Идиотович", "Студент Студентов Студентович", "Иванов Иван Иванов", "Ъъъ Ыыы Эээ",
       "Кцк Пшт Втр", "Админ Админов Админович", "Пупкин Василий", "Иванов Хуй Иванович", "!!! ???",
       "Иванов @ivan Иванович", "Ебанов Иван Иванович", "Дерьмов Иван Петрович", "Сука Иван Петрович"]
class T(unittest.TestCase):
    def test_good(self):
        for s in GOOD:
            self.assertNotEqual(validate_fio(s).verdict, "reject", s)
    def test_bad(self):
        for s in BAD:
            self.assertEqual(validate_fio(s).verdict, "reject", s)
    def test_soft_mode_accepts_review(self):
        self.assertEqual(validate_fio("Иванов Тимофей", strict=False).verdict, "ok")
        self.assertEqual(validate_fio("Мамаев Тагирчик").verdict, "review")
    def test_normalize(self):
        self.assertEqual(validate_fio("  сМИРНОВ   алексей дмитриевич ").fio, "Смирнов Алексей Дмитриевич")
        self.assertEqual(validate_fio("алиев тимур рашид оглы").fio, "Алиев Тимур Рашид оглы")
        self.assertEqual(validate_fio("сидоров-петров пётр иванович").fio, "Сидоров-Петров Пётр Иванович")
    def test_short(self):
        self.assertEqual(short_name("Смирнов Алексей Дмитриевич"), "Смирнов А. Д.")
        self.assertEqual(short_name(None), "аноним")

CELEB = ["Путин Владимир Владимирович", "Владимир Путин", "Путтин Владимир", "Зеленский Владимир Александрович", "Месси Лионель",
         "Гарри Поттер", "Поттер Гарри Джеймсович", "Пушкин Александр Сергеевич", "Маск Илон", "Гагарин Юрий Алексеевич"]
NOT_NAMES = ["Кошка Мурка Васильевна", "Привет Пока Здравствуйте", "Пупкин Василий Петрович", "Васечкин Иван Иванович"]
GENDER = ["Иванова Иван Петрович", "Иванов Анна Сергеевна", "Иванов Иван Сергеевна", "Петрова Мария Сергеевич"]
OBFUSCATED = ["Хууууй Иванов Петрович", "Ху Йов Петрович", "Иванов Ху Йович", "Курвалов Иван Петрович"]
RANDOM = ["Фкпнов Ыюшг Ррыа", "Аиоуэ Аиоуэ Ииоа", "Бабабабаев Иван Петрович", "Абвгдеев Пётр Иванович"]
REAL_TRICKY = ["Гончарова Ульяна Олеговна", "Сапожников Глеб Анатольевич",
               "Хренова Мария Петровна", "Членов Олег Игоревич", "Мкртчян Арам Георгиевич", "Дьяконов Матвей Ильич",
               "Ковалевич Ольга Николаевна", "Шестопалова Ксения Ильинична"]


class Strict(unittest.TestCase):
    def test_celebrities_rejected(self):
        for x in CELEB:
            self.assertEqual(validate_fio(x).code, "celebrity", x)

    def test_namesake_of_common_surname_goes_to_review(self):
        r = validate_fio("Медведев Дмитрий Сергеевич")
        self.assertEqual((r.verdict, r.code), ("review", "celebrity_namesake"))

    def test_everyday_words_and_jokes_rejected(self):
        for x in NOT_NAMES:
            self.assertEqual(validate_fio(x).verdict, "reject", x)

    def test_gender_mismatch_rejected(self):
        for x in GENDER:
            self.assertEqual(validate_fio(x).code, "gender", x)

    def test_obfuscated_profanity_and_random_rejected(self):
        for x in OBFUSCATED + RANDOM:
            self.assertEqual(validate_fio(x).verdict, "reject", x)

    def test_real_names_with_suspicious_substrings_pass(self):
        for x in REAL_TRICKY:
            self.assertNotEqual(validate_fio(x).verdict, "reject", x)

    def test_patronymic_derived_from_known_father_name(self):
        for p in ("Сергеевич", "Сергеевна", "Ильич", "Ильинична", "Николаевич", "Павлович", "Михайловна",
                  "Юрьевич", "Игоревна", "Рашид оглы", "Баходирович", "Кузьминична", "Никитична"):
            self.assertTrue(patronymic_known(p), p)
        self.assertFalse(patronymic_known("Ывапович"))

    def test_confident_requires_known_name_patronymic_and_surname(self):
        self.assertTrue(validate_fio("Смирнова Анна Сергеевна").confident)
        self.assertFalse(validate_fio("Смирнов Алексей").confident)
        self.assertFalse(validate_fio("Смирнов Тагирчик Сергеевич").confident)
        self.assertFalse(validate_fio("Смирнов Алексей Ывапович").confident)

    def test_unknown_but_plausible_surname_needs_review_in_strict_mode(self):
        loose = validate_fio("Зубаиров Тимур Айратович", ctx=FioContext())
        self.assertTrue(loose.confident)
        strict = validate_fio("Зубаиров Тимур Айратович", ctx=FioContext(require_known_surname=True))
        self.assertEqual((strict.verdict, strict.confident, strict.code), ("review", False, "surname_pattern"))
        known = validate_fio("Зубаиров Тимур Айратович",
                             ctx=FioContext(known_surnames=frozenset({"зубаиров"}), require_known_surname=True))
        self.assertTrue(known.confident)

    def test_surname_not_like_a_surname_is_review(self):
        self.assertNotEqual(validate_fio("Дрмпг Тимур Айратович").verdict, "ok")

    def test_staff_impersonation_goes_to_review(self):
        ctx = FioContext(known_surnames=frozenset({"сидоров"}), staff_pairs=frozenset({("сидоров", "сс")}))
        r = validate_fio("Сидоров Сергей Семёнович", ctx=ctx)
        self.assertEqual((r.verdict, r.code), ("review", "staff_match"))
        self.assertEqual(validate_fio("Сидоров Павел Андреевич", ctx=ctx).verdict, "ok")

    def test_duplicate_key_ignores_case_yo_and_gender_forms(self):
        self.assertEqual(fio_key("Иванова Анна Сергеевна"), fio_key("иванова  анна сергеевна"))
        self.assertEqual(fio_key("Фёдоров Артём Иванович"), fio_key("Федоров Артем Игоревич"))
        self.assertNotEqual(fio_key("Фёдоров Артём Иванович"), fio_key("Фёдоров Артём Павлович"))


if __name__ == "__main__":
    unittest.main()


class AutoVerificationSafety(unittest.TestCase):
    def test_only_independently_manually_confirmed_group_surnames_are_trusted(self):
        from app.services.fio_verify import _auto_context, _manual_group_surnames

        rows = [
            {"id": 1, "group_id": 10, "fio": "Смирнов Алексей Дмитриевич"},
            {"id": 2, "group_id": 10, "fio": "Смирнова Анна Сергеевна"},
            {"id": 3, "group_id": 10, "fio": "Петров Иван Петрович"},
            {"id": 4, "group_id": 20, "fio": "Кузнецов Пётр Иванович"},
            {"id": 5, "group_id": 20, "fio": "Кузнецова Мария Андреевна"},
            {"id": 6, "group_id": 10, "fio": "Орлов Иван Петрович", "verification_action": "fio_ok", "verification_ts": 10, "audit_id": 1},
            {"id": 6, "group_id": 10, "fio": "Орлов Иван Петрович", "verification_action": "fio_auto_verified", "verification_ts": 20, "audit_id": 2},
            {"id": 7, "group_id": 10, "fio": "Орлова Анна Сергеевна", "verification_action": "fio_ok", "verification_ts": 15, "audit_id": 3},
        ]
        roster = _manual_group_surnames(rows)
        self.assertIn("смирнов", roster[10])
        self.assertEqual(roster[10]["смирнов"], 2)
        self.assertNotIn("петров", roster[10])
        self.assertNotIn("орлов", roster[10])  # старое ручное решение перекрыто авто-подтверждением
        self.assertIn("кузнецов", roster[20])
        self.assertNotIn("кузнецов", roster[10])

        base = FioContext()
        group_ctx = _auto_context(base, set(roster[10]))
        self.assertTrue(validate_fio("Смирнов Алексей Дмитриевич", ctx=group_ctx).confident)
        self.assertFalse(validate_fio("Петров Иван Петрович", ctx=group_ctx).confident)
        # Официальная фамилия преподавателя сама по себе не даёт права на автоподтверждение.
        staff_only = _auto_context(base, {"Иванов"})
        self.assertFalse(validate_fio("Иванов Иван Иванович", ctx=staff_only).confident)
