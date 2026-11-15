"""Email: the week's AI part is on its way. usage: python pipeline/mail_ai_started.py <week> <sent|waiting>"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common, mail

week, state = sys.argv[1], sys.argv[2]
when = "now" if state == "sent" else "at 11:00 am India time, when Kaggle's free GPUs are least busy"
mail.send(common.config(), f"[Manzi Studio] Making the AI scenes for week {week}",
          f"<p>✅ Scripts approved. The opening scenes, the Professor clips and the Professor voice will be made on "
          f"Kaggle's free GPU {when}.</p><p>When they are ready, the videos are made automatically and you get the usual "
          f"<b>videos ready</b> email (about 1.5 to 2.5 hours later). If Kaggle keeps the job waiting for more than 4 hours, "
          f"the videos are made without the AI part so nothing is late.</p>")
