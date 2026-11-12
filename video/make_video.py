"""Видеоинструкция Certa: озвучка (edge-tts) + запись экрана (Playwright) + сборка (ffmpeg).

python -X utf8 make.py tts|record|build|all
"""
import asyncio
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
DEMO = HERE.parent / "demo"
AUDIO = HERE / "audio"
OUT = HERE / "out"
BASE = "http://localhost:5180"
VOICE = "ru-RU-SvetlanaNeural"
RATE = "+30%"  # 1,25 × прежней скорости (+4%)
PITCH = "+12Hz"  # выше тон — звучит бодрее
GAP = 0.35  # пауза после фразы, с

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# ---------------------------------------------------------------- сценарий
# (субтитр, действие[, текст для синтеза]) — действие выполняется в начале фразы.
STEPS = [
    ("Привет! Это Certa — почта менеджера логистической компании!", "intro", "Привет! Это Серта — почта менеджера логистической компании!"),
    ("Помощник сам читает письма клиентов из почты и Telegram, определяет тему и срочность и готовит черновик ответа.", "none", "Помощник сам читает письма клиентов из почты и телеграма, определяет тему и срочность и готовит черновик ответа."),
    ("Отвечает клиенту всегда человек: вы проверяете черновик и решаете, что отправить.", "login"),
    ("После входа открывается «Почта». Сверху — четыре счётчика.", "hover_stat0"),
    ("«Ждут решения» — письма с готовым черновиком. «Срочные» — где есть срок или серьёзные последствия.", "hover_stat1"),
    ("«Просрочены» — срок ответа уже прошёл. «Проверить вручную» — помощник не уверен или видит риск.", "hover_stat23"),
    ("Слева — папки: письма разложены по ящикам и ботам, а внутри — по срочности.", "hover_folders"),
    ("Нажмите «Высокий» — и перед вами только срочные письма!", "click_high"),
    ("Ниже — папки по работе: что ждёт решения, что нужно проверить, что уже принято.", "hover_work"),
    ("Вкладки над списком делят письма по темам: продажи, жалобы, вопросы и спам.", "click_tabs"),
    ("Фильтры уточняют выбор, а кнопка «Сначала важные» поднимает срочное наверх.", "click_important"),
    ("Строка поиска находит письмо по имени, адресу, тексту или номеру накладной.", "search"),
    ("Откроем письмо. Карточка собирает всё в одном месте — очень удобно!", "open_card"),
    ("Жёлтый блок подсказывает, на что обратить внимание: здесь срочная жалоба.", "hover_alert"),
    ("Слева — само письмо и то, что понял помощник: даты, контакты, номера грузов. Каждое значение подтверждено цитатой.", "hover_left"),
    ("Справа — оценка: тема, срочность, следующий шаг и черновик ответа.", "hover_right"),
    ("Нужно поправить черновик — нажмите «Исправить».", "click_correct"),
    ("Можно сменить тему или срочность и дописать текст.", "type_draft"),
    ("Сохраните: правка попадёт в историю и в отчёт о качестве.", "save_correct"),
    ("«Отклонить» — если помощник ошибся. «Назначить» — передать письмо сотруднику и задать срок.", "hover_buttons"),
    ("Когда почта подключена, ответ уходит прямо отсюда — с того ящика или бота, куда написал клиент.", "scroll_reply"),
    ("Всё верно? Жмите «Принять» — и письмо уходит в папку «Приняты»!", "accept_other"),
    ("Раздел «Разбор писем» показывает работу помощника.", "nav_jobs"),
    ("Почта проверяется раз в минуту, и новые письма разбираются сами. Разбор можно запустить и вручную.", "hover_jobs"),
    ("«Качество ответов» — сколько черновиков принято без правок и где помощник ошибается чаще.", "nav_quality"),
    ("В «Почте и сервисах» подключаются почтовые ящики и Telegram-боты — сколько угодно.", "nav_connectors", "В разделе «Почта и сервисы» подключаются почтовые ящики и телеграм-боты — сколько угодно."),
    ("Здесь же — сервисы компании: статусы перевозок, тарифы и CRM.", "hover_services", "Здесь же — сервисы компании: статусы перевозок, тарифы и си-ар-эм."),
    ("В «Базу знаний» загружают тарифы и регламенты. Подходящие фрагменты появятся в карточке письма как источники для ответа.", "nav_kb"),
    ("В «Настройках» — тема оформления, рабочее время и сроки ответа для каждой срочности.", "nav_settings"),
    ("Администратор добавляет сотрудников, а журнал хранит все действия.", "scroll_settings"),
    ("Кнопка «Пройти обучение заново» покажет все кнопки по шагам прямо в приложении.", "hover_tour"),
    ("Вот и всё! Письма разобраны, срочное — наверху, а решение — за вами. Удачной работы!", "outro"),
]


def tts_path(text: str) -> Path:
    h = hashlib.sha1(f"{VOICE}|{RATE}|{PITCH}|{text}".encode()).hexdigest()[:12]
    return AUDIO / f"{h}.mp3"


def duration(path: Path) -> float:
    r = subprocess.run([FFMPEG, "-i", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    t = r.stderr.split("Duration: ")[1].split(",")[0]
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


async def tts() -> None:
    import edge_tts

    AUDIO.mkdir(exist_ok=True)
    for step in STEPS:
        text = step[2] if len(step) > 2 else step[0]
        p = tts_path(text)
        if p.exists() and p.stat().st_size > 0:
            continue
        for attempt in range(5):
            try:
                await edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH).save(str(p))
                if p.stat().st_size > 0:
                    break
            except Exception as e:
                print("retry", attempt, e)
            await asyncio.sleep(2)
        print("tts", p.name, text[:50])


# ---------------------------------------------------------------- запись
CURSOR_JS = r"""
(() => {
  const add = () => {
    if (document.getElementById('__cur')) return;
    const c = document.createElement('div');
    c.id = '__cur';
    c.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M4 2l15 9.5-6.6 1.4L16 20l-3 1.4-3.6-7.2L4 19z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    Object.assign(c.style, {position:'fixed', left:'-50px', top:'-50px', zIndex:2147483647, pointerEvents:'none', transform:'translate(-3px,-2px)', filter:'drop-shadow(0 1px 2px rgba(0,0,0,.35))'});
    document.documentElement.appendChild(c);
    document.addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    document.addEventListener('mousedown', e => {
      const r = document.createElement('div');
      Object.assign(r.style, {position:'fixed', left:(e.clientX-18)+'px', top:(e.clientY-18)+'px', width:'36px', height:'36px', borderRadius:'50%', background:'rgba(200,40,50,.35)', zIndex:2147483646, pointerEvents:'none', transition:'transform .45s ease-out, opacity .45s ease-out'});
      document.documentElement.appendChild(r);
      requestAnimationFrame(() => { r.style.transform = 'scale(1.8)'; r.style.opacity = '0'; });
      setTimeout(() => r.remove(), 600);
    }, true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add); else add();
})();
try { localStorage.setItem('leads.onboarding', 'done'); } catch (e) {}
"""


class Director:
    def __init__(self, page):
        self.page = page
        self.x, self.y = 640, 400

    def move(self, x, y, steps=28):
        self.page.mouse.move(x, y, steps=steps)
        self.x, self.y = x, y

    def to(self, loc, dx=0.5, dy=0.5, steps=28):
        loc.scroll_into_view_if_needed()
        b = loc.bounding_box()
        self.move(b["x"] + b["width"] * dx, b["y"] + b["height"] * dy, steps)

    def click(self, loc, **kw):
        self.to(loc, **kw)
        self.page.wait_for_timeout(180)
        self.page.mouse.down()
        self.page.wait_for_timeout(70)
        self.page.mouse.up()

    def type(self, text, delay=55):
        self.page.keyboard.type(text, delay=delay)

    def wait(self, ms):
        self.page.wait_for_timeout(ms)


def actions(d: "Director", name: str, creds):
    p = d.page
    card = p.locator("article.card")
    if name in ("intro", "none"):
        if name == "intro":
            d.move(900, 360, 40)
        return
    if name == "login":
        d.click(p.locator("input").nth(0))
        d.type(creds[0], 90)
        d.click(p.locator("input[type=password]"))
        d.type(creds[1][:10], 35)
        p.locator("input[type=password]").fill(creds[1])
        d.click(p.get_by_role("button", name="Войти"))
        p.wait_for_url("**/leads**")
        return
    if name == "hover_stat0":
        d.wait(600)
        d.to(p.get_by_text("Ждут решения").nth(1))
        return
    if name == "hover_stat1":
        d.to(p.get_by_text("Ждут решения").nth(1))
        d.wait(2200)
        d.to(p.get_by_text("Срочные").first)
        return
    if name == "hover_stat23":
        d.to(p.get_by_text("Просрочены").first)
        d.wait(2200)
        d.to(p.get_by_text("Проверить вручную").first)
        return
    if name == "hover_folders":
        nav = p.locator("aside, nav").first
        d.to(p.get_by_text("Telegram").first)
        d.wait(1500)
        d.to(p.get_by_text("Почта (JSON)").first)
        return
    if name == "click_high":
        d.click(p.get_by_text("Высокий", exact=True).nth(1))
        return
    if name == "hover_work":
        d.to(p.get_by_text("Ждут решения", exact=True).first)
        d.wait(1200)
        p.mouse.wheel(0, 300)
        d.wait(800)
        d.to(p.get_by_text("Приняты", exact=True).first)
        d.wait(800)
        p.mouse.wheel(0, -300)
        return
    if name == "click_tabs":
        d.click(p.get_by_text("Все письма", exact=True).first)
        d.wait(900)
        for t in ("Продажи", "Жалобы"):
            d.click(p.get_by_role("tab").filter(has_text=t))
            d.wait(1100)
        return
    if name == "click_important":
        d.click(p.get_by_role("tab").filter(has_text="Все"))
        d.wait(800)
        d.click(p.get_by_role("button", name="Сначала важные"))
        return
    if name == "search":
        d.click(p.locator("input[type=search]"))
        d.type("договор", 120)
        return
    if name == "open_card":
        d.wait(500)
        d.click(p.get_by_text("Петров").first)
        return
    if name == "hover_alert":
        d.wait(500)
        d.to(card.locator(".alert.warn").first, dx=0.2)
        return
    if name == "hover_left":
        d.to(card.locator("pre.source"), dx=0.3)
        d.wait(1800)
        d.to(card.get_by_text("Что понял помощник"), dx=0.6)
        d.wait(900)
        d.to(card.locator("table").first, dx=0.6)
        return
    if name == "hover_right":
        d.to(card.get_by_text("Оценка помощника"), dx=0.5)
        d.wait(1400)
        d.to(card.locator("pre.draft"), dx=0.4)
        return
    if name == "click_correct":
        d.click(card.get_by_role("button", name="Исправить"))
        return
    if name == "type_draft":
        ta = card.locator("#draft")
        d.click(ta, dx=0.9, dy=0.9)
        p.keyboard.press("Control+End")
        d.type(" Номер договора менеджер пришлёт в ответном письме.", 45)
        return
    if name == "save_correct":
        d.click(card.get_by_role("button", name="Сохранить исправление"))
        return
    if name == "hover_buttons":
        d.wait(400)
        d.to(card.get_by_role("button", name="Отклонить"))
        d.wait(2400)
        d.to(card.get_by_role("button", name="Назначить"))
        return
    if name == "scroll_reply":
        d.to(card.get_by_text("Ответ клиенту").first)
        d.wait(1500)
        return
    if name == "accept_other":
        p.keyboard.press("Escape")
        d.wait(400)
        inp = p.locator("input[type=search]")
        d.click(inp)
        p.keyboard.press("Control+A")
        d.type("Казань", 90)
        d.wait(900)
        d.click(p.get_by_text("Николай").first)
        d.wait(1300)
        d.click(p.locator("article.card").get_by_role("button", name="Принять"))
        d.wait(1500)
        p.keyboard.press("Escape")
        d.wait(300)
        p.locator("input[type=search]").fill("")
        return
    if name == "nav_jobs":
        d.click(p.get_by_role("link", name="Разбор писем"))
        return
    if name == "hover_jobs":
        d.to(p.get_by_text("Почта проверяется автоматически"))
        d.wait(2500)
        d.to(p.get_by_role("button").filter(has_text="Нов").first)
        return
    if name == "nav_quality":
        d.click(p.get_by_role("link", name="Качество ответов"))
        d.wait(1200)
        d.to(p.get_by_text("Принято без правок").first)
        return
    if name == "nav_connectors":
        d.click(p.get_by_role("link", name="Почта и сервисы"))
        d.wait(1200)
        d.to(p.get_by_role("button", name="Добавить ящик"))
        d.wait(1500)
        d.to(p.get_by_role("button", name="Добавить бота"))
        return
    if name == "hover_services":
        d.to(p.get_by_text("Сервисы компании"))
        d.wait(600)
        p.mouse.wheel(0, 400)
        d.wait(900)
        d.to(p.get_by_text("Тарифы", exact=True))
        return
    if name == "nav_kb":
        d.click(p.get_by_role("link", name="База знаний"))
        d.wait(1500)
        d.to(p.get_by_text("Загрузить документ"))
        d.wait(1500)
        d.to(p.get_by_role("button", name="Загрузить"))
        return
    if name == "nav_settings":
        d.click(p.get_by_role("link", name="Настройки"))
        d.wait(1000)
        d.to(p.get_by_text("Тема оформления"))
        d.wait(1500)
        d.to(p.get_by_text("Рабочее время и сроки ответа"))
        return
    if name == "scroll_settings":
        for _ in range(5):
            p.mouse.wheel(0, 220)
            d.wait(250)
        d.to(p.get_by_text("Сотрудники", exact=True), dx=0.3)
        d.wait(1500)
        for _ in range(5):
            p.mouse.wheel(0, 220)
            d.wait(250)
        return
    if name == "hover_tour":
        p.mouse.wheel(0, -5000)
        d.wait(900)
        d.to(p.get_by_role("button", name="Пройти обучение заново"))
        return
    if name == "outro":
        d.click(p.get_by_role("link", name="Почта").first)
        d.wait(1200)
        d.move(900, 380, 40)
        return
    raise ValueError(name)


def record() -> None:
    import base64
    import shutil
    from playwright.sync_api import sync_playwright

    creds = (DEMO / "demo-login.txt").read_text().split()[:2]
    frames_dir = OUT / "frames"
    shutil.rmtree(frames_dir, ignore_errors=True)
    frames_dir.mkdir(parents=True)
    frames = []
    timeline = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=1.5, locale="ru-RU")
        ctx.add_init_script(CURSOR_JS)
        page = ctx.new_page()
        page.goto(BASE + "/login")
        page.wait_for_timeout(1200)
        cdp = ctx.new_cdp_session(page)

        def on_frame(ev):
            n = len(frames)
            f = frames_dir / f"{n:06d}.jpg"
            f.write_bytes(base64.b64decode(ev["data"]))
            frames.append((ev["metadata"]["timestamp"], f.name))
            try:
                cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
            except Exception:
                pass

        cdp.on("Page.screencastFrame", on_frame)
        t0 = time.time()
        cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": 1920, "maxHeight": 1080, "everyNthFrame": 1})
        page.wait_for_timeout(1500)
        d = Director(page)
        for step in STEPS:
            sub, act = step[0], step[1]
            text = step[2] if len(step) > 2 else sub
            dur = duration(tts_path(text))
            start = time.time() - t0
            actions(d, act, creds)
            left = dur + GAP - (time.time() - t0 - start)
            if left > 0:
                page.wait_for_timeout(int(left * 1000))
            timeline.append({"start": start, "dur": dur, "sub": sub, "audio": tts_path(text).name, "act": act})
            print(f"{start:6.1f}s {act}", flush=True)
        page.wait_for_timeout(1800)
        total = time.time() - t0
        cdp.send("Page.stopScreencast")
        ctx.close()
        b.close()
    # ffconcat: каждый кадр держится до следующего; начало выравниваем на t0
    lines = ["ffconcat version 1.0"]
    for i, (ts, name) in enumerate(frames):
        a = 0.0 if i == 0 else ts - t0
        nxt = frames[i + 1][0] - t0 if i + 1 < len(frames) else total
        lines += [f"file frames/{name}", f"duration {max(nxt - a, 0.001):.4f}"]
    lines.append(f"file frames/{frames[-1][1]}")
    (OUT / "frames.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT / "timeline.json").write_text(json.dumps({"video": "frames.txt", "total": total, "steps": timeline}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("frames", len(frames), "total", round(total, 1))


# ---------------------------------------------------------------- сборка
def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def wrap(text: str, width: int = 62) -> str:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    return "\n".join(lines)


def build(lead_in: float = 0.0) -> None:
    tl = json.loads((OUT / "timeline.json").read_text(encoding="utf-8"))
    steps = tl["steps"]
    # субтитры: длинную фразу делим на части по предложениям, пропорционально длине
    import re

    cues = []
    for s in steps:
        parts = [x for x in re.split(r"(?<=[.!?])\s+", s["sub"]) if x]
        total_len = sum(len(x) for x in parts)
        t = s["start"] + lead_in
        for part in parts:
            span = s["dur"] * len(part) / total_len
            cues.append((t, t + span, part))
            t += span
    srt = "\n".join(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{wrap(txt)}\n" for i, (a, b, txt) in enumerate(cues, 1))
    (OUT / "certa-instrukciya.srt").write_text(srt, encoding="utf-8")

    inputs, filters = [], []
    for i, s in enumerate(steps):
        inputs += ["-i", str(AUDIO / s["audio"])]
        ms = int((s["start"] + lead_in) * 1000)
        filters.append(f"[{i + 1}:a]adelay={ms}|{ms},aresample=48000[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(len(steps)))
    total = tl["total"]
    style = ("FontName=Segoe UI,FontSize=13,PrimaryColour=&H00FFFFFF,BackColour=&H1A1F1A14,"
             "BorderStyle=4,Outline=0,Shadow=0,MarginV=16,Alignment=2")
    vf = (f"[0:v]fps=30,scale=1920:1080:flags=lanczos:in_range=pc:out_range=tv,format=yuv420p,"
          f"subtitles=certa-instrukciya.srt:force_style='{style}',"
          f"fade=t=in:st=0:d=0.6,fade=t=out:st={total - 1.2:.2f}:d=1.2[v]")
    fc = ";".join(filters + [f"{mix}amix=inputs={len(steps)}:normalize=0,afade=t=out:st={total - 1.2:.2f}:d=1.2[a]", vf])
    cmd = [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", tl["video"], *inputs, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-t", f"{total:.2f}", "certa-instrukciya.mp4"]
    r = subprocess.run(cmd, cwd=OUT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        print(r.stderr[-3000:])
        sys.exit(1)
    print("ok", OUT / "certa-instrukciya.mp4")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("tts", "all"):
        asyncio.run(tts())
    if what in ("record", "all"):
        record()
    if what in ("build", "all"):
        build(float(sys.argv[2]) if len(sys.argv) > 2 else 0.0)
