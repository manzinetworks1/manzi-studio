"""Email: a landmark case's AI part is on its way. usage: python landmark/mail_started.py <case slug> <sent|waiting>"""
import json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pipeline"))
import common, mail  # noqa: E402

case, state = sys.argv[1], sys.argv[2]
st = json.load(open(os.path.join(HERE, "cases", case, "story.json"), encoding="utf-8"))
clips = sum(b["type"] in ("scene", "professor") for b in st["beats"])
when = "now" if state == "sent" else "at 11:00 am India time, when Kaggle's free GPUs are least busy"
mail.send(common.config(), f"[Manzi Studio] Making the scenes for {st['case']}",
          f"<p>✅ Storyboard approved. The {clips} AI scenes and the Professor's narration will be made on Kaggle's free "
          f"GPU {when}. This takes about 3 to 4.5 hours of GPU time.</p>"
          f"<p>When they are ready, the video is put together automatically and you get a <b>video ready</b> email. "
          f"If another engine run is still on Kaggle, this one waits for it and is sent the next day at 11:00 am.</p>")
