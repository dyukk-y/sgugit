import asyncio, unittest
from datetime import date, timedelta
from app.db.core import Database
from app.db.schema import migrate
from app.db.repo import Repo
from app.providers.site import parse_html, ParseError, parse_group_links
from app.providers.importer import parse_rows, parse_file, parse_manual_line, read_csv
from app.services.sync import SyncService
from app.timeutil import today, iso
from app.models import LessonRec

HTML = """<html><body>
<h3>Группа ИС-11</h3>
<table><tr><th>Дата</th><th>Время</th><th>Дисциплина</th><th>Преподаватель</th><th>Аудитория</th><th>Вид</th></tr>
<tr><td>20.10.2026</td><td>08:30-10:05</td><td>Математика</td><td>Иванов И. И.</td><td>310</td><td>лекция</td></tr>
<tr><td>20.10.2026</td><td>10:15-11:50</td><td>Физика</td><td>Петров П. П.</td><td>215</td><td>практика</td></tr>
<tr><td>21.10.2026</td><td>08:30-10:05</td><td>История</td><td>Сидоров С. С.</td><td>101</td><td>лекция</td></tr></table>
<h3>ГД-21</h3>
<table><tr><th>Время</th><th>Дисциплина</th><th>Аудитория</th></tr><tr><td colspan=3>22 октября</td></tr>
<tr><td>08:30-10:05</td><td>Геодезия</td><td>12</td></tr></table></body></html>"""
CSV = "группа;дата;пара;начало;конец;предмет;преподаватель;аудитория;тип;подгруппа\nИС-11;2026-10-20;1;08:30;10:05;Математика;Иванов И. И.;310;лекция;\nИС-11;21.10.2026;;10:15;11:50;Физика;;215;;2\n"

class T(unittest.TestCase):
    def test_parse_html(self):
        recs = parse_html(HTML, date(2026, 10, 14))
        self.assertEqual(len(recs), 4)
        self.assertEqual((recs[0].group, recs[0].day, recs[0].num, recs[0].start, recs[0].subject), ("ИС-11", "2026-10-20", 1, "08:30", "Математика"))
        self.assertEqual(recs[1].num, 2)
        g = [r for r in recs if r.group == "ГД-21"][0]
        self.assertEqual((g.day, g.subject), ("2026-10-22", "Геодезия"))
        with self.assertRaises(ParseError): parse_html("<html><body><p>нет таблиц</p></body></html>", date(2026, 10, 14))

    def test_parse_group_links(self):
        html = """<html><body>
        <a href="/raspisanie/group/1776/">Группа МД-22.1</a>
        <a href="https://sgugit.ru/raspisanie/group/1777/">ИС-21</a>
        <a href="/raspisanie/">Расписание</a>
        <a href="/raspisanie/group/1776/">дубликат</a>
        </body></html>"""
        links = parse_group_links(html, "https://sgugit.ru/raspisanie/")
        self.assertEqual(links, [
            ("Группа МД-22.1", "https://sgugit.ru/raspisanie/group/1776/"),
            ("ИС-21", "https://sgugit.ru/raspisanie/group/1777/"),
        ])
    def test_bundled_group_url_manifest_contains_candidates_and_known_group(self):
        import json
        from pathlib import Path
        manifest_path = Path(__file__).resolve().parents[1] / "data" / "group_url_candidates.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertIn("https://sgugit.ru/raspisanie/group/1776/", manifest["candidate_urls"])
        self.assertIn(1776, {item["id"] for item in manifest["known_groups"]})
        self.assertEqual(len(manifest["candidate_urls"]), 351)
    def test_parse_group_links_from_script_and_data_attributes(self):
        html = r"""<html><body>
        <div data-url="/raspisanie/group/1778/"></div>
        <script>const schedule = {url: "/raspisanie/group/1779/", groupId: 1780};</script>
        <script>const escaped = "\/raspisanie\/group\/1781\/";</script>
        </body></html>"""
        links = parse_group_links(html, "https://sgugit.ru/raspisanie/")
        ids = {url.rsplit("/", 2)[-2] for _, url in links}
        self.assertTrue({"1778", "1779", "1780", "1781"}.issubset(ids))
    def test_import(self):
        recs, errs = parse_file("x.csv", CSV.encode("utf-8"))
        self.assertEqual(errs, []); self.assertEqual(len(recs), 2); self.assertEqual(recs[1].subgroup, 2); self.assertEqual(recs[1].day, "2026-10-21")
        recs, errs = parse_file("x.csv", CSV.encode("cp1251"))
        self.assertEqual(len(recs), 2)
        _, errs = parse_rows([["группа","дата","начало","конец","предмет"], ["ИС-11","32.13.2026","8:30","8:00",""]])
        self.assertEqual(len(errs), 1)
        r, e = parse_manual_line("25.10;10:00;11:30;Консультация;Иванов И. И.;310", "ИС-11", date(2026, 10, 14))
        self.assertEqual((e, r.day, r.room), ("", "2026-10-25", "310"))
        self.assertIsNone(parse_manual_line("25.10;10:00", "ИС-11", date(2026, 10, 14))[0])
        with self.assertRaises(ValueError): parse_file("x.pdf", b"")
        from openpyxl import Workbook
        import io
        wb = Workbook(); ws = wb.active
        ws.append(["группа","дата","пара","начало","конец","предмет"]); ws.append(["ИС-11", date(2026,10,20), 1, "08:30", "10:05", "Математика"])
        b = io.BytesIO(); wb.save(b)
        recs, errs = parse_file("t.xlsx", b.getvalue()); self.assertEqual((errs, len(recs), recs[0].day), ([], 1, "2026-10-20"))
    def test_sync(self):
        async def go():
            db = Database("sqlite:///:memory:"); await db.connect(); await migrate(db); r = Repo(db); await r.load_settings()
            d = iso(today() + timedelta(days=1)); alerts = []; changes = []
            state = {"recs": [LessonRec("ИС-11", d, 1, "08:30", "10:05", "Математика", "Иванов И. И.", "1")], "err": None}
            async def fetch():
                if state["err"]: raise ConnectionError(state["err"])
                return state["recs"]
            async def on_alert(t): alerts.append(t)
            async def on_changes(res): changes.append(res)
            s = SyncService(r, fetch, on_changes, on_alert)
            rep = await s.run_once(); self.assertTrue(rep.ok); self.assertEqual(changes, [])
            state["recs"] = [LessonRec("ИС-11", d, 1, "08:30", "10:05", "Математика", "Иванов И. И.", "2")]
            rep = await s.run_once(); self.assertEqual(len(changes), 1)
            state["err"] = "нет сети"
            for _ in range(3): rep = await s.run_once()
            self.assertFalse(rep.ok); self.assertEqual(len(alerts), 1); self.assertEqual(r.setting("sync_fail_count"), "3")
            gid = (await r.search_groups("ис11"))[0]["id"]
            self.assertEqual((await r.lessons_day(gid, d))[0]["room"], "2")  # расписание сохранилось
            state["err"] = None; rep = await s.run_once(); self.assertTrue(rep.ok); self.assertEqual(len(alerts), 2)
            snaps = await r.list_snapshots(); self.assertEqual(len(snaps), 2)
            self.assertTrue(await s.rollback(snaps[-1]["id"])); self.assertEqual((await r.lessons_day(gid, d))[0]["room"], "1")
            state["recs"] = []; state["err"] = None
            rep = await s.run_once(); self.assertFalse(rep.ok)
            await db.close()
        asyncio.run(go())
if __name__ == "__main__":
    unittest.main()
