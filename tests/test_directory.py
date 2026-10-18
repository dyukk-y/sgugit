import asyncio, unittest
from app.providers import directory as d

LIST1 = """<html><body><nav><a href="/about">Об Университете</a><a href="/news">Новости</a></nav>
<ul><li><a href="/teachers/krylov-aa/">Крылов Андрей Андреевич</a></li><li><a href="/teachers/ivanov/">Иванов Иван Иванович</a></li></ul>
<div class="pager"><a href="/teachers/?PAGEN_1=2">2</a><a href="/teachers/?PAGEN_1=2">»</a></div></body></html>"""
LIST2 = """<html><body><a href="/teachers/petrova/">Петрова Мария Сергеевна</a><a href="/teachers/?PAGEN_1=1">1</a></body></html>"""
CARD_A = """<html><body><h1>Крылов Андрей Андреевич</h1><div class="row"><span>Структурное подразделение:</span>
<a href="/struct/geodesy/">Кафедра геодезии</a></div></body></html>"""
CARD_B = """<html><body><dl><dt>Структурное подразделение</dt><dd>Кафедра высшей математики</dd></dl></body></html>"""
CARD_C = """<html><body><p>Структурное подразделение: Институт геодезии и менеджмента</p></body></html>"""
UNIT_A = """<html><body><h2>Кафедра геодезии</h2><p><b>Кабинет:</b> 215</p><p>Корпус 2, ауд. 215</p></body></html>"""
UNIT_B = """<html><body><div>Адрес: ул. Плахотного, 10, корпус 1, каб. 304</div></body></html>"""
ABLOVA_CARD = """<html><body><h1>Аблова Наталья Алексеевна</h1>
<div class="row"><span>Наименование структурного подразделения</span>
<a href="/university/struct/kafedry/ypimk/">Кафедра языковой подготовки и межкультурных коммуникаций</a></div></body></html>"""
YPIMK_PAGE = """<html><body><h1>Кафедра языковой подготовки и межкультурных коммуникаций</h1>
<p>Кабинет № 309</p></body></html>"""

class T(unittest.TestCase):
    def test_parsers(self):
        links = d.parse_teacher_links(LIST1, "https://sgugit.ru/teachers/")
        self.assertEqual([n for n, _ in links], ["Крылов Андрей Андреевич", "Иванов Иван Иванович"])
        self.assertEqual(links[0][1], "https://sgugit.ru/teachers/krylov-aa/")
        self.assertEqual(d.parse_pagination(LIST1, "https://sgugit.ru/teachers/"), ["https://sgugit.ru/teachers/?PAGEN_1=2"])
        self.assertEqual(d.parse_teacher_page(CARD_A, "https://sgugit.ru/teachers/krylov-aa/"), ("Кафедра геодезии", "https://sgugit.ru/struct/geodesy/"))
        self.assertEqual(d.parse_teacher_page(CARD_B, "https://x/")[0], "Кафедра высшей математики")
        self.assertEqual(d.parse_teacher_page(CARD_C, "https://x/")[0], "Институт геодезии и менеджмента")
        self.assertEqual(d.parse_teacher_page("<html><body>пусто</body></html>", "https://x/"), ("", ""))
        self.assertEqual(d.parse_teacher_page(ABLOVA_CARD, "https://sgugit.ru/teachers/ablova-natalia-alekseevna/"),
                         ("Кафедра языковой подготовки и межкультурных коммуникаций", "https://sgugit.ru/university/struct/kafedry/ypimk/"))
        self.assertEqual(d.parse_unit_page(YPIMK_PAGE), "каб. 309")
        self.assertIn("215", d.parse_unit_page(UNIT_A))
        self.assertIn("304", d.parse_unit_page(UNIT_B)); self.assertIn("корпус 1", d.parse_unit_page(UNIT_B))
        self.assertEqual(d.parse_unit_page("<html><body>ничего</body></html>"), "")
    def test_crawl(self):
        pages = {"https://sgugit.ru/teachers/": LIST1, "https://sgugit.ru/teachers/?PAGEN_1=2": LIST2,
                 "https://sgugit.ru/teachers/krylov-aa/": CARD_A, "https://sgugit.ru/teachers/ivanov/": CARD_B,
                 "https://sgugit.ru/teachers/petrova/": CARD_C, "https://sgugit.ru/struct/geodesy/": UNIT_A, "https://sgugit.ru/teachers/?PAGEN_1=1": LIST1}
        async def fetch(url):
            if url not in pages: raise ConnectionError("404 " + url)
            return pages[url]
        staff, units = asyncio.run(d.crawl_directory("https://sgugit.ru/teachers/", fetch))
        self.assertEqual(len(staff), 3); self.assertEqual({u["name"] for u in units}, {"Кафедра геодезии", "Кафедра высшей математики", "Институт геодезии и менеджмента"})
        self.assertIn("215", [u for u in units if u["name"] == "Кафедра геодезии"][0]["room"])
        with self.assertRaises(d.DirectoryError): asyncio.run(d.crawl_directory("https://sgugit.ru/teachers/", lambda u: asyncio.sleep(0, "<html></html>")))
        async def bad(url): raise ConnectionError("нет сети")
        with self.assertRaises(d.DirectoryError): asyncio.run(d.crawl_directory("https://sgugit.ru/teachers/", bad))
    def test_file(self):
        csv = "ФИО;Подразделение;Кабинет\nКрылов Андрей Андреевич;Кафедра геодезии;215\nИванов Иван Иванович;Кафедра геодезии;\nмусор;x;1\n".encode("utf-8")
        staff, units, errs = d.parse_directory_file("d.csv", csv)
        self.assertEqual((len(staff), len(units), len(errs)), (2, 1, 1)); self.assertEqual(units[0]["room"], "215")
        staff, units, errs = d.parse_directory_rows([["Петров Пётр Петрович", "Кафедра X", "101"]]); self.assertEqual((len(staff), errs), (1, []))
if __name__ == "__main__":
    unittest.main()
