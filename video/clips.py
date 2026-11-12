"""Беззвучные зацикленные ролики для лендинга (landing/media/NN-*.mp4).

python -X utf8 clips.py [имя ...]   — без аргументов все ролики
"""
import base64
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from make import CURSOR_JS, DEMO, FFMPEG, Director

HERE = Path(__file__).parent
WORK = HERE / "clips"
DEST = Path(r"C:\Users\Dozer\Desktop\work\CERTATZ\TZ\landing\media")
APP = "http://localhost:5180"
SCENES = (HERE / "scenes.html").as_uri()
XF = 0.8  # длина перехода конца в начало, с


# ------------------------------------------------------------ сценарии
def login(p, creds):
    p.goto(APP + "/login")
    p.locator("input").nth(0).fill(creds[0])
    p.locator("input[type=password]").fill(creds[1])
    p.keyboard.press("Enter")
    p.wait_for_url("**/leads**")
    p.wait_for_timeout(1200)


def triage(d):
    p = d.page
    d.wait(600)
    d.click(p.get_by_text("ТехноСтрой").first)
    d.wait(1300)
    card = p.locator("article.card")
    d.to(card.locator("pre.source"), dx=0.3)
    d.wait(1500)
    d.to(card.locator("table").first, dx=0.55)
    d.wait(1500)
    d.to(card.get_by_text("Оценка помощника"))
    d.wait(900)
    d.to(card.locator("pre.draft"), dx=0.4)
    d.wait(1600)
    p.keyboard.press("Escape")
    d.wait(900)


def workspace(d):
    p = d.page
    d.wait(500)
    d.click(p.get_by_text("Высокий", exact=True).nth(1))
    d.wait(1300)
    d.click(p.get_by_text("Все письма", exact=True).first)
    d.wait(900)
    d.click(p.get_by_role("tab").filter(has_text="Жалобы"))
    d.wait(1200)
    d.click(p.get_by_role("tab").filter(has_text="Вопросы"))
    d.wait(1200)
    d.click(p.get_by_role("tab").filter(has_text="Все"))
    d.wait(700)
    d.click(p.get_by_role("button", name="Сначала важные"))
    d.wait(1500)
    d.click(p.get_by_role("button", name="Сначала важные"))
    d.wait(700)


def channels(d):
    p = d.page
    d.wait(400)
    d.click(p.get_by_text("Telegram").first)
    d.wait(1300)
    d.click(p.get_by_text("Виктор").first)
    d.wait(1300)
    d.to(p.locator("article.card").get_by_text("Telegram").first)
    d.wait(1200)
    p.keyboard.press("Escape")
    d.wait(500)
    d.click(p.get_by_role("link", name="Почта и сервисы"))
    d.wait(1300)
    d.to(p.get_by_role("button", name="Добавить ящик"))
    d.wait(1000)
    d.to(p.get_by_role("button", name="Добавить бота"))
    d.wait(1300)


def quality(d):
    p = d.page
    d.click(p.get_by_role("link", name="Качество ответов"))
    d.wait(1300)
    d.to(p.get_by_text("Принято без правок").first)
    d.wait(1300)
    d.to(p.get_by_text("Исправления приоритетов").first)
    d.wait(1300)
    d.click(p.get_by_role("link", name="Разбор писем"))
    d.wait(1300)
    d.to(p.get_by_text("Почта проверяется автоматически"))
    d.wait(1500)


CLIPS = {
    "00-hero": ("scene", "hero", 10.6),
    "01-triage": ("app", triage, None),
    "02-local-model": ("scene", "local", 8.6),
    "03-mcp-tools": ("scene", "mcp", 9.0),
    "04-guardrails": ("scene", "guard", 8.6),
    "05-reliability": ("scene", "reliab", 8.6),
    "06-workspace": ("app", workspace, None),
    "07-channels": ("app", channels, None),
    "08-quality": ("app", quality, None),
}


# ------------------------------------------------------------ запись
def record(name, kind, what, seconds, creds):
    frames_dir = WORK / name
    shutil.rmtree(frames_dir, ignore_errors=True)
    frames_dir.mkdir(parents=True)
    frames = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 800}, device_scale_factor=1.25,
                            locale="ru-RU", color_scheme="dark")
        if kind == "app":
            ctx.add_init_script(CURSOR_JS)
        page = ctx.new_page()
        if kind == "app":
            login(page, creds)
        else:
            page.goto(f"{SCENES}?s={what}")
            page.wait_for_function("document.title === 'ready'")
            page.reload()  # шрифты уже в кэше — анимация стартует сразу
            page.wait_for_function("document.title === 'ready'")
        cdp = ctx.new_cdp_session(page)

        def on_frame(ev):
            f = frames_dir / f"{len(frames):05d}.jpg"
            f.write_bytes(base64.b64decode(ev["data"]))
            frames.append((ev["metadata"]["timestamp"], f.name))
            try:
                cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
            except Exception:
                pass

        cdp.on("Page.screencastFrame", on_frame)
        t0 = time.time()
        cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": 1600, "maxHeight": 1000})
        if kind == "app":
            what(Director(page))
        else:
            page.wait_for_timeout(int(seconds * 1000))
        total = time.time() - t0
        cdp.send("Page.stopScreencast")
        ctx.close()
        b.close()
    lines = ["ffconcat version 1.0"]
    for i, (ts, fname) in enumerate(frames):
        a = 0.0 if i == 0 else ts - t0
        nxt = frames[i + 1][0] - t0 if i + 1 < len(frames) else total
        lines += [f"file {name}/{fname}", f"duration {max(nxt - a, 0.001):.4f}"]
    lines.append(f"file {name}/{frames[-1][1]}")
    (WORK / f"{name}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return total


def encode(name, total, seamless):
    out = DEST / f"{name}.mp4"
    base = "fps=30,scale=1600:1000:flags=lanczos:in_range=pc:out_range=tv,format=yuv420p"
    if seamless:  # периодическая анимация: берём ровно один период
        fc = f"[0:v]{base},trim=0:{total:.3f},setpts=PTS-STARTPTS[v]"
    else:  # конец плавно переходит в начало — петля без шва
        L = total
        fc = (f"[0:v]{base},split[a][b];[a]trim={XF}:{L:.3f},setpts=PTS-STARTPTS[m];"
              f"[b]trim=0:{XF},setpts=PTS-STARTPTS[h];[m][h]xfade=transition=fade:duration={XF}:offset={L - 2 * XF:.3f}[v]")
    cmd = [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", f"{name}.txt", "-filter_complex", fc, "-map", "[v]",
           "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "23", "-movflags", "+faststart", str(out)]
    r = subprocess.run(cmd, cwd=WORK, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        print(r.stderr[-2500:])
        raise SystemExit(1)
    print(f"{name}: {out.stat().st_size / 1e6:.1f} МБ")


if __name__ == "__main__":
    creds = (DEMO / "demo-login.txt").read_text().split()[:2]
    WORK.mkdir(exist_ok=True)
    names = sys.argv[1:] or list(CLIPS)
    for n in names:
        kind, what, secs = CLIPS[n]
        total = record(n, kind, what, secs if secs else 0, creds)
        encode(n, 10.0 if n == "00-hero" else total, seamless=(n == "00-hero"))
