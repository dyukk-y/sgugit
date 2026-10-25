"""Автоподтверждение ФИО: подтверждаются только уверенные случаи, остальное уходит админам."""
import unittest

from app.services.fio_verify import auto_verify_pending
from tests.test_flows import Sim, datas, run, texts


class FioVerify(unittest.TestCase):
    def test_never_verified_instantly_and_known_name_is_verified_by_job(self):
        async def go():
            s = await Sim().setup()
            await s.do(100, command="start")
            out = await s.do(100, text="ис 11")
            await s.do(100, callback=[d for d in datas(out) if d and d.startswith("r:g:")][0])
            out = await s.do(100, text="Смирнова Анна Сергеевна")
            out = await s.do(100, callback="r:ok")
            self.assertEqual((await s.repo.get_user(100))["fio_status"], "pending")
            self.assertIn("автоматическую проверку", texts(out))
            stats = await auto_verify_pending(s.repo)
            self.assertEqual((stats["verified"], stats["manual"]), (1, 0))
            self.assertEqual((await s.repo.get_user(100))["fio_status"], "verified")
            await s.db.close()
        run(go())

    def test_pause_is_respected(self):
        async def go():
            s = await Sim().setup()
            await s.repo.set_setting("fio_auto_delay_min", "90")
            await s.register(100)
            self.assertEqual((await s.repo.get_user(100))["fio_status"], "pending")  # 90 минут ещё не прошло
            await s.db.close()
        run(go())

    def test_unknown_surname_waits_for_admin_in_strict_mode_and_is_remembered_after_approval(self):
        async def go():
            s = await Sim().setup()
            await s.register(100, "Зубаиров Тимур Айратович")
            u = await s.repo.get_user(100)
            self.assertEqual(u["fio_status"], "pending")
            self.assertIn("fio_needs_review", [a["action"] for a in await s.repo.list_audit(20)])
            await s.repo.update_user(100, fio_status="verified")  # администратор подтвердил вручную
            s.repo._fio_ctx = None  # сбрасываем кэш контекста
            await s.register(101, "Зубаирова Алсу Маратовна")  # такая же фамилия в женской форме теперь «известна»
            self.assertEqual((await s.repo.get_user(101))["fio_status"], "verified")
            await s.db.close()
        run(go())

    def test_loose_mode_accepts_plausible_surname(self):
        async def go():
            s = await Sim().setup()
            await s.repo.set_setting("fio_need_known_surname", "0")
            await s.register(100, "Зубаиров Тимур Айратович")
            self.assertEqual((await s.repo.get_user(100))["fio_status"], "verified")
            await s.db.close()
        run(go())

    def test_garbage_and_celebrity_are_rejected_at_registration(self):
        async def go():
            s = await Sim().setup()
            await s.do(100, command="start")
            out = await s.do(100, text="ис 11")
            await s.do(100, callback=[d for d in datas(out) if d and d.startswith("r:g:")][0])
            for bad in ("Путин Владимир Владимирович", "Фкпнов Ыюшг Ррыа", "Иванова Иван Петрович", "Хууууй Иванов Петрович"):
                out = await s.do(100, text=bad)
                self.assertNotIn("r:ok", datas(out), bad)
            self.assertEqual((await s.repo.get_user(100))["fio_status"], "none")
            await s.db.close()
        run(go())

    def test_student_cannot_claim_to_be_teacher(self):
        async def go():
            s = await Sim().setup()  # в расписании есть преподаватель «Сидоров С. С.»
            await s.register(100, "Сидоров Сергей Семёнович")
            self.assertEqual((await s.repo.get_user(100))["fio_status"], "pending")
            await s.register(101, "Сидоров Павел Андреевич")  # однофамилец с другими инициалами
            self.assertEqual((await s.repo.get_user(101))["fio_status"], "verified")
            await s.db.close()
        run(go())

    def test_duplicate_in_group_is_not_auto_verified(self):
        async def go():
            s = await Sim().setup()
            await s.register(100, "Орлова Ольга Игоревна")
            await s.register(101, "орлова ольга игоревна")
            self.assertEqual((await s.repo.get_user(100))["fio_status"], "verified")
            self.assertEqual((await s.repo.get_user(101))["fio_status"], "pending")
            await s.db.close()
        run(go())

    def test_fio_change_is_limited_per_day(self):
        async def go():
            s = await Sim().setup()
            await s.register(100)
            names = ["Орлова Ольга Игоревна", "Волкова Елена Павловна", "Кузнецова Мария Андреевна"]
            for n in names:
                await s.do(100, callback="me:fio")
                out = await s.do(100, text=n)
                self.assertIn("ФИО обновлено", texts(out))
            await s.do(100, callback="me:fio")
            out = await s.do(100, text="Новикова Дарья Игоревна")
            self.assertIn("За последние сутки", texts(out))
            self.assertEqual((await s.repo.get_user(100))["fio"], names[-1])
            await s.db.close()
        run(go())


if __name__ == "__main__":
    unittest.main()
