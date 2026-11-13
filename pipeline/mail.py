"""Emails through Gmail (an app password, not your real password)."""
import os, smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from common import secret, log


def send(cfg, subject, html):
    dry = os.environ.get("MAIL_DRYRUN")
    if dry:
        os.makedirs(dry, exist_ok=True); n = len(os.listdir(dry))
        open(os.path.join(dry, f"{n:02d}.html"), "w", encoding="utf-8").write(f"<h1>{subject}</h1>" + html); log("email saved (dry run):", subject); return
    user = secret("GMAIL_ADDRESS"); pw = secret("GMAIL_APP_PASSWORD").replace(" ", "")
    to = cfg.get("email_to") or user
    msg = MIMEMultipart("alternative"); msg["Subject"] = subject; msg["From"] = f"Manzi Studio <{user}>"; msg["To"] = to
    msg.attach(MIMEText("<div style='font-family:Arial,sans-serif;font-size:15px;line-height:1.5;max-width:720px'>" + html + "</div>", "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(user, pw); s.sendmail(user, [to], msg.as_string())
    log("email sent:", subject)
