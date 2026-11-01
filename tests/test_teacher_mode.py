import unittest

from app.bot.logic_teacher import _room_floor, _same_room


class TeacherRoomDisplayTests(unittest.TestCase):
    def test_floor_is_inferred_from_three_digit_room_number(self):
        self.assertEqual(_room_floor("корпус 2, каб. 310"), "3 этаж (по номеру аудитории)")

    def test_floor_is_not_guessed_for_nonstandard_room(self):
        self.assertEqual(_room_floor("ауд. 25"), "этаж не указан")

    def test_room_prefixes_are_normalized_for_occupancy(self):
        self.assertTrue(_same_room("310", "ауд. 310"))
        self.assertFalse(_same_room("корпус 1, каб. 310", "корпус 2, каб. 310"))


if __name__ == "__main__":
    unittest.main()
