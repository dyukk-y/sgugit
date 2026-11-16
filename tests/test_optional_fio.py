import unittest
from datetime import datetime
from types import SimpleNamespace

from app.bot.core import Ctx


class OptionalStudentFioTests(unittest.TestCase):
    def make_ctx(self, user):
        return Ctx(
            repo=object(),
            cfg=SimpleNamespace(superadmin_id=999),
            user={"id": 123, "role": "student", **user},
            now=datetime(2026, 11, 16, 12, 0),
        )

    def test_student_with_group_does_not_need_fio_for_main_access(self):
        ctx = self.make_ctx({"group_id": 7, "fio": None, "fio_status": "none"})
        self.assertTrue(ctx.registered)
        self.assertFalse(ctx.verified)

    def test_student_without_group_still_needs_group_selection(self):
        ctx = self.make_ctx({"group_id": None, "fio": "Иванов Иван Иванович", "fio_status": "verified"})
        self.assertFalse(ctx.registered)

    def test_teacher_access_uses_linked_teacher_profile(self):
        ctx = self.make_ctx({"role": "teacher", "_teacher_registered": True})
        self.assertTrue(ctx.registered)

    def test_admin_access_does_not_depend_on_student_profile(self):
        ctx = self.make_ctx({"role": "admin", "group_id": None, "fio": None})
        self.assertTrue(ctx.registered)


if __name__ == "__main__":
    unittest.main()
