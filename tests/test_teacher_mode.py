import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.bot.core import Ctx, Out
from app.bot.logic_teacher import _room_floor, _same_room
from app.bot.router import handle_callback


class TeacherRoomDisplayTests(unittest.TestCase):
    def test_removed_class_leader_role_is_safe_for_legacy_callers(self):
        ctx = Ctx(None, SimpleNamespace(superadmin_id=999), {"id": 1, "role": "student"})
        self.assertFalse(ctx.is_head)

    def test_floor_is_inferred_from_three_digit_room_number(self):
        self.assertEqual(_room_floor("корпус 2, каб. 310"), "3 этаж (по номеру аудитории)")

    def test_floor_is_not_guessed_for_nonstandard_room(self):
        self.assertEqual(_room_floor("ауд. 25"), "этаж не указан")

    def test_room_prefixes_are_normalized_for_occupancy(self):
        self.assertTrue(_same_room("310", "ауд. 310"))
        self.assertFalse(_same_room("корпус 1, каб. 310", "корпус 2, каб. 310"))



class TeacherCallbackRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_teacher_day_button_does_not_fall_into_student_registration(self):
        class Repo:
            @staticmethod
            def flag(_name):
                return False

        ctx = Ctx(Repo(), SimpleNamespace(superadmin_id=999),
                  {"id": 1, "role": "teacher", "_teacher_registered": False})
        with patch("app.bot.router.logic_teacher.on_cb", new_callable=AsyncMock,
                   return_value=Out(toast="teacher route")) as teacher_handler:
            result = await handle_callback(ctx, "p:day:today")

        teacher_handler.assert_awaited_once_with(ctx, ["day", "today"])
        self.assertEqual(result.toast, "teacher route")


if __name__ == "__main__":
    unittest.main()
