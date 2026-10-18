from datetime import date

from app.providers.site import parse_html


def test_parse_official_sgugit_div_schedule():
    html = '''<!doctype html><html lang="ru"><head><title>Расписание занятий | Группа МД-22.1</title></head>
    <body><h1>Группа МД-22.1</h1>
      <div class="rasp_wrapper" data-week-range="12.10.2026 - 18.10.2026">
        <div class="half_week">
          <div class="date_info"><div class="date">12.10.26</div><div class="day_of_the_week">Понедельник</div></div>
          <div class="day">
            <div class="day_hours"><div class="hour"><p>08:30</p><p>10:00</p></div><div class="lesson"><div class="lesson_name empty"></div></div></div>
            <div class="day_hours"><div class="hour"><p>10:10</p><p>11:40</p></div><div class="lesson"><div class="lesson_info"><div class="lesson_name">Геодезия</div><a class="teach_name">Иванов Иван Иванович</a><div class="aud_wrap"><a class="aud_num">227</a></div><p class="lesson_type">лекция</p></div></div></div>
          </div>
          <div class="date_info"><div class="date">13.10.26</div><div class="day_of_the_week">Вторник</div></div>
          <div class="day"><div class="day_hours"><div class="hour"><p>12:10</p><p>13:40</p></div><div class="lesson"><div class="lesson_info"><div class="lesson_name">Экология</div><a class="teach_name">Петрова Наталья</a><p class="lesson_type">практика</p></div></div></div></div>
        </div>
      </div>
    </body></html>'''
    lessons = parse_html(html, date(2026, 10, 18))
    assert len(lessons) == 2
    assert lessons[0].group == "МД-22.1"
    assert (lessons[0].day, lessons[0].num, lessons[0].start, lessons[0].end) == (
        "2026-10-12", 2, "10:10", "11:40"
    )
    assert lessons[0].subject == "Геодезия"
    assert lessons[0].teacher == "Иванов Иван Иванович"
    assert lessons[0].room == "227"
    assert lessons[0].kind == "лекция"
    assert lessons[1].day == "2026-10-13"
    assert lessons[1].subject == "Экология"
