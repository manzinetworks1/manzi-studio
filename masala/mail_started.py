"""Email: a Masala Short's clips are on their way. usage: python masala/mail_started.py <slug> <sent|waiting>"""
import html, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pipeline")); sys.path.insert(0, HERE)
import common, mail  # noqa: E402
from story import load  # noqa: E402

slug, state = sys.argv[1], sys.argv[2]
st = load(slug)
n = len(st["scenes"])
when = "now" if state == "sent" else "at 11:00 am India time, when Kaggle's free GPUs are least busy"
warn = os.path.join(HERE, "stories", slug, "warnings.txt")
notes = open(warn, encoding="utf-8").read().split("\n") if os.path.exists(warn) else []
mail.send(common.config(), f"[Masala Shorts] Making the clips for: {st['title']}",
          f"<p>✅ Story file checked. The {n} AI clips will be made on Kaggle's free GPU {when}; that takes about "
          f"{max(1, round(n * 11 / 60, 1))} hours of GPU time.</p>"
          + ("<p>Small things noticed (the video is still made):</p><ul>"
             + "".join(f"<li>⚠️ {html.escape(x)}</li>" for x in notes if x) + "</ul>" if any(notes) else "")
          + "<p>When the clips are back, the Short is put together automatically and you get a <b>Short ready</b> "
            "email. If another engine run is still on Kaggle, this one waits for it.</p>")
