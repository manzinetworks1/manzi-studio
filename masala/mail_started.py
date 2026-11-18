"""Email: a Masala Short's clips are on their way. usage: python masala/mail_started.py <slug> <sent|waiting>"""
import html, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pipeline")); sys.path.insert(0, HERE)
import common, mail  # noqa: E402
from story import load  # noqa: E402

slug, state = sys.argv[1], sys.argv[2]
mode = sys.argv[3] if len(sys.argv) > 3 else "draft"
st = load(slug)
n = len(st["scenes"])
when = "now" if state == "sent" else "at 11:00 am India time, when Kaggle's free GPUs are least busy"
warn = os.path.join(HERE, "stories", slug, "warnings.txt")
notes = open(warn, encoding="utf-8").read().split("\n") if os.path.exists(warn) else []
mail.send(common.config(), f"[Masala Shorts] Making the {mode} clips for: {st['title']}",
          (f"<p>✅ Story file checked. The <b>draft</b> clips (544p, to check) are made on Kaggle's free GPU {when}: "
           f"about 11 min a clip, only for new or changed scenes. You get a <b>Draft ready</b> email to check them.</p>"
           if mode == "draft" else
           f"<p>✅ Making the <b>final</b> Short: the approved clips are sharpened to 720p on Kaggle {when} "
           "(about 9 min a clip).</p>")
          + ("<p>Small things noticed (the video is still made):</p><ul>"
             + "".join(f"<li>⚠️ {html.escape(x)}</li>" for x in notes if x) + "</ul>" if any(notes) else "")
          + "<p>When the clips are back, everything is put together automatically. If another engine run is still on "
            "Kaggle, this one waits for it.</p>")
