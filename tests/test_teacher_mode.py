import unittest

from app.bot.logic_teacher import _room_floor


class TeacherRoomDisplayTests(unittest.TestCase):
    def test_floor_is_inferred_from_three_digit_room_number(self):
        self.assertEqual(_room_floor("корпус 2, каб. 310"), "3 этаж (по номеру аудитории)")

    def test_floor_is_not_guessed_for_nonstandard_room(self):
        self.assertEqual(_room_floor("ауд. 25"), "этаж не указан")


if __name__ == "__main__":
    unittest.main()
