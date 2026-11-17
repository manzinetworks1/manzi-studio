"""On-screen cards for the landmark videos (case title, the law, the Court's holdings, timeline, exam recap...).

Each card is a small HTML page drawn by headless Chromium into a 1920x1080 PNG; the video then shows it with a slow
zoom while the Professor's narration plays.
"""
import html
import os

FONTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "render", "fonts")
W, H = 1920, 1080
GOLD, INK, PAPER, MUTED = "#d9ab4f", "#0e1a2b", "#f4efe4", "#a9b4c4"

CSS = f"""
@font-face {{ font-family: L; src: url('file://{FONTS}/Lora-Variable.ttf'); font-weight: 400 700; }}
@font-face {{ font-family: L; src: url('file://{FONTS}/Lora-Italic-Variable.ttf'); font-weight: 400 700; font-style: italic; }}
@font-face {{ font-family: T; src: url('file://{FONTS}/Inter-Medium.otf'); font-weight: 500; }}
@font-face {{ font-family: T; src: url('file://{FONTS}/Inter-SemiBold.otf'); font-weight: 600; }}
@font-face {{ font-family: T; src: url('file://{FONTS}/Inter-Bold.otf'); font-weight: 700; }}
@font-face {{ font-family: D; src: url('file://{FONTS}/InterDisplay-ExtraBold.otf'); font-weight: 800; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ width: {W}px; height: {H}px; overflow: hidden; }}
body {{ font-family: T, sans-serif; color: {PAPER};
  background: radial-gradient(ellipse at 30% 20%, #1d3150 0%, {INK} 55%, #070e18 100%); }}
.frame {{ position: absolute; inset: 44px; border: 2px solid rgba(217,171,79,.35); border-radius: 6px; }}
.top {{ position: absolute; left: 110px; top: 96px; right: 110px; display: flex; justify-content: space-between;
  font: 600 26px T; letter-spacing: 5px; text-transform: uppercase; color: {GOLD}; }}
.top span:last-child {{ color: {MUTED}; letter-spacing: 3px; }}
.main {{ position: absolute; left: 110px; right: 110px; top: 175px; bottom: 120px; display: flex;
  flex-direction: column; justify-content: center; }}
h1 {{ font: 700 76px/1.12 L, serif; color: #fff; }}
h1.big {{ font-size: 92px; text-align: center; }}
.sub {{ margin-top: 22px; font: 500 36px/1.35 T; color: {MUTED}; }}
.center {{ text-align: center; }}
.rule {{ width: 160px; height: 5px; background: {GOLD}; margin: 34px auto; border-radius: 3px; }}
.stats {{ display: flex; gap: 34px; justify-content: center; margin-top: 10px; }}
.stat {{ flex: 1; max-width: 480px; border: 2px solid rgba(217,171,79,.45); border-radius: 18px; padding: 26px 30px;
  background: rgba(255,255,255,.04); }}
.stat b {{ display: block; font: 600 24px T; letter-spacing: 3px; text-transform: uppercase; color: {GOLD}; }}
.stat span {{ display: block; margin-top: 10px; font: 600 38px/1.25 T; }}
.list {{ margin-top: 46px; display: flex; flex-direction: column; gap: 26px; }}
.row {{ display: flex; gap: 30px; align-items: flex-start; }}
.num {{ flex: none; width: 70px; height: 70px; border-radius: 50%; background: {GOLD}; color: {INK};
  font: 800 36px/70px D; text-align: center; }}
.row .txt {{ font: 500 38px/1.35 T; padding-top: 10px; }}
.row .txt b {{ font-weight: 700; color: #fff; }}
.row .txt i {{ font-style: normal; color: {GOLD}; font-weight: 700; }}
.quote {{ font: italic 600 84px/1.25 L, serif; color: #fff; text-align: center; padding: 0 60px; }}
.quote:before {{ content: "\\201C"; color: {GOLD}; }}
.quote:after {{ content: "\\201D"; color: {GOLD}; }}
.grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 26px 34px; margin-top: 40px; }}
.cell {{ border-left: 7px solid {GOLD}; background: rgba(255,255,255,.05); border-radius: 0 16px 16px 0;
  padding: 20px 28px; }}
.cell b {{ display: block; font: 700 26px T; letter-spacing: 3px; text-transform: uppercase; color: {GOLD}; }}
.cell span {{ display: block; margin-top: 8px; font: 500 34px/1.32 T; }}
.tl {{ position: relative; margin-top: 70px; display: flex; justify-content: space-between; }}
.tl:before {{ content: ""; position: absolute; left: 4%; right: 4%; top: 92px; height: 5px; background: {GOLD};
  opacity: .6; }}
.ev {{ flex: 1; text-align: center; position: relative; padding: 0 14px; }}
.ev b {{ display: block; font: 800 52px D; color: #fff; height: 70px; }}
.ev i {{ display: block; width: 34px; height: 34px; margin: 6px auto 26px; border-radius: 50%; background: {GOLD};
  border: 6px solid {INK}; box-shadow: 0 0 0 4px {GOLD}; position: relative; }}
.ev span {{ display: block; font: 500 32px/1.3 T; color: {PAPER}; }}
svg text {{ font-family: T; }}
"""


def _e(s):
    return html.escape(str(s or ""))


def _bold(s):
    """**word** -> <b> (kept from the storyboard's emphasis, if any)."""
    import re
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", _e(s))


def card_html(card, case, chapter):
    style = card.get("style", "holding")
    items = card.get("items") or []
    top = f"<div class='top'><span>{_e(chapter or 'Landmark Case')}</span><span>{_e(case)}</span></div>"
    if style == "title":
        body = (f"<div class='center'><div class='top' style='position:static;justify-content:center'>"
                f"<span>Landmark Case</span></div><div style='height:30px'></div>"
                f"<h1 class='big'>{_e(card['heading'])}</h1><div class='sub center'>{_e(card.get('sub'))}</div>"
                f"<div class='rule'></div><div class='stats'>"
                + "".join(f"<div class='stat'><b>{_e(i['label'])}</b><span>{_e(i['text'])}</span></div>" for i in items[:3])
                + "</div></div>")
        top = ""
    elif style == "quote":
        body = (f"<div class='quote'>{_e(card['heading'])}</div>"
                f"<div class='rule'></div><div class='sub center'>{_e(card.get('sub'))}</div>")
    elif style == "triangle":
        pts = [(W / 2 - 110, 130), (W / 2 - 110 - 560, 560), (W / 2 - 110 + 560, 560)]
        labels = (items + [{"label": "", "text": ""}] * 3)[:3]
        svg = [f"<svg width='{W - 220}' height='700' viewBox='0 0 {W - 220} 700'>",
               f"<polygon points='{' '.join(f'{x},{y}' for x, y in pts)}' fill='rgba(217,171,79,.08)' "
               f"stroke='{GOLD}' stroke-width='6' stroke-linejoin='round'/>"]
        for (x, y), it in zip(pts, labels):
            svg.append(f"<circle cx='{x}' cy='{y}' r='84' fill='{GOLD}'/>"
                       f"<text x='{x}' y='{y + 2}' text-anchor='middle' dominant-baseline='middle' font-size='34' "
                       f"font-weight='800' fill='{INK}'>{_e(it['label'].replace('Article ', 'Art. '))}</text>"
                       f"<text x='{x + (0 if y > 300 else 110)}' y='{y + (130 if y > 300 else 12)}' "
                       f"text-anchor='{'middle' if y > 300 else 'start'}' font-size='38' "
                       f"font-weight='600' fill='{PAPER}'>{_e(it['text'])}</text>")
        svg.append("</svg>")
        body = (f"<h1 class='center' style='font-size:62px'>{_e(card['heading'])}</h1>"
                f"<div style='margin-top:40px'>{''.join(svg)}</div>")
    elif style == "timeline":
        body = (f"<h1>{_e(card['heading'])}</h1><div class='tl'>"
                + "".join(f"<div class='ev'><b>{_e(i['label'])}</b><i></i><span>{_e(i['text'])}</span></div>"
                          for i in items[:6]) + "</div>")
    elif style == "exam":
        body = (f"<h1>{_e(card['heading'])}</h1><div class='grid'>"
                + "".join(f"<div class='cell'><b>{_e(i['label'])}</b><span>{_bold(i['text'])}</span></div>"
                          for i in items[:6]) + "</div>")
    elif style == "chapter":
        body = (f"<div class='center'><h1 class='big'>{_e(card['heading'])}</h1><div class='rule'></div>"
                f"<div class='sub center'>{_e(card.get('sub'))}</div></div>")
    else:  # law, holding
        body = (f"<h1>{_e(card['heading'])}</h1>" + (f"<div class='sub'>{_e(card.get('sub'))}</div>" if card.get("sub") else "")
                + "<div class='list'>"
                + "".join(f"<div class='row'><div class='num'>{n}</div><div class='txt'><i>{_e(i['label'])}</i>"
                          f"{' · ' if i.get('label') and i.get('text') else ''}{_bold(i['text'])}</div></div>"
                          for n, i in enumerate(items[:5], 1)) + "</div>")
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>"
            f"<div class='frame'></div>{top}<div class='main'>{body}</div></body></html>")


def render_cards(jobs):
    """jobs: [(card dict, case name, chapter, out_png)] -> PNGs (one browser for all)."""
    if not jobs:
        return
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--allow-file-access-from-files"])
        pg = b.new_page(viewport={"width": W, "height": H})
        for card, case, chapter, out in jobs:
            tmp = out + ".html"
            open(tmp, "w", encoding="utf-8").write(card_html(card, case, chapter))
            pg.goto("file://" + os.path.abspath(tmp))
            pg.evaluate("document.fonts.ready")
            pg.wait_for_timeout(150)
            pg.screenshot(path=out)
            os.remove(tmp)
        b.close()
