"""The answer as neat notes -> PDF (for students who comment NOTES)."""
import html, os, re
from common import ROOT

FONTS = os.path.join(ROOT, "render", "fonts")


def notes_html(pack, channel):
    e = lambda s: html.escape(s or "")
    rich = lambda s: re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", e(s))
    body = []
    for s in pack["long"]["sections"]:
        body.append(f"<h2>{e(s['heading'])}</h2>")
        for p in s.get("paras", []): body.append(f"<p>{rich(p)}</p>")
        if s.get("points"): body.append("<ol>" + "".join(f"<li><b>{e(x['title'])}</b>: {rich(x['text'])}</li>" for x in s["points"]) + "</ol>")
        for c in s.get("cases", []): body.append(f"<p class='case'><i>{e(c['name'])}</i>: {rich(c['text'])}</p>")
        if s.get("tip"): body.append(f"<p class='tip'>✍️ <b>Exam tip:</b> {rich(s['tip'])}</p>")
    badges = " · ".join(x for x in [pack.get("course"), pack.get("subject"), f"{pack['marks']} marks" if pack.get("marks") else "",
                                    "Asked: " + ", ".join(pack["asked_years"]) if pack.get("asked_years") else ""] if x)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@font-face {{ font-family: P; src: url(file://{FONTS}/Poppins-Regular.ttf); font-weight: 400; }}
@font-face {{ font-family: P; src: url(file://{FONTS}/Poppins-Bold.ttf); font-weight: 700; }}
@page {{ size: A4; margin: 16mm; }}
body {{ font: 11pt/1.6 P, sans-serif; color: #1d2433; }}
.top {{ display: flex; justify-content: space-between; border-bottom: 3px solid #1d3b8a; padding-bottom: 6px; color: #1d3b8a; font-weight: 700; }}
h1 {{ font-size: 18pt; line-height: 1.25; color: #1d3b8a; margin: 14px 0 4px; }} .b {{ color: #6b7280; font-size: 9.5pt; margin-bottom: 8px; }}
h2 {{ font-size: 13pt; color: #1d3b8a; margin: 16px 0 4px; }} b {{ background: #fff2a8; }} li {{ margin-bottom: 6px; }}
p.case {{ border-left: 4px solid #c0392b; background: #faf7f0; padding: 6px 10px; }} p.tip {{ background: #fff8c4; padding: 6px 10px; border-radius: 6px; }}
.foot {{ margin-top: 20px; border-top: 1px solid #ddd; padding-top: 6px; font-size: 9pt; color: #6b7280; text-align: center; }}
</style></head><body><div class="top"><span>⚖ {e(channel)}</span><span>Q{pack.get('qnum', '')}</span></div>
<h1>{e(pack['question'])}</h1><div class="b">{e(badges)}</div>{''.join(body)}
<div class="foot">Free notes from {e(channel)} on YouTube. Watch the video for the full explanation.</div></body></html>"""


def make_pdf(pack, channel, out, browser):
    tmp = out + ".html"; open(tmp, "w", encoding="utf-8").write(notes_html(pack, channel))
    pg = browser.new_page(); pg.goto("file://" + os.path.abspath(tmp)); pg.wait_for_timeout(300)
    pg.pdf(path=out, format="A4", print_background=True); pg.close(); os.remove(tmp)
