"""M, first step: picks up story files you pasted into masala/inbox/ and checks them.

python masala/intake.py

- A good file goes to masala/stories/<slug>/story.json (the inbox copy is removed) and its slug is printed in
  $GITHUB_OUTPUT as stories=<slug> <slug>...
- A file with problems goes to masala/rejected/ with a note, and you get an email listing exactly what to fix.
Nothing is made from a file with problems.
"""
import glob, html, json, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pipeline"))
sys.path.insert(0, HERE)
from common import ROOT, config, log  # noqa: E402
from story import check, parse  # noqa: E402

INBOX = os.path.join(HERE, "inbox")
SKIP = {"README.md", ".gitkeep"}


def email(subject, body):
    try:
        import mail
        mail.send(config(), subject, body)
    except Exception as e:
        log(f"⚠️ email not sent: {e}")


def main():
    files = sorted(f for f in glob.glob(os.path.join(INBOX, "*")) if os.path.isfile(f) and os.path.basename(f) not in SKIP)
    good, notes = [], []
    for f in files:
        name = os.path.basename(f)
        try:
            st = parse(open(f, encoding="utf-8").read())
            errs, warns = check(st)
        except ValueError as e:
            st, errs, warns = None, [str(e)], []
        if errs:
            stamp = time.strftime("%Y%m%d-%H%M")
            dest = os.path.join(HERE, "rejected", f"{stamp}-{name}")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            os.replace(f, dest)
            open(dest + ".problems.txt", "w", encoding="utf-8").write("\n".join(errs + warns) + "\n")
            log(f"❌ {name}: {len(errs)} problem(s)")
            title = (st or {}).get("title", name)
            email(f"[Masala Shorts] Please fix the story: {title}",
                  f"<p>The story file <b>{html.escape(name)}</b> was <b>not</b> made into a video because of "
                  f"{len(errs)} problem(s):</p><ul>" + "".join(f"<li>❌ {html.escape(e)}</li>" for e in errs)
                  + "".join(f"<li>⚠️ {html.escape(w)}</li>" for w in warns) + "</ul>"
                  "<p>Paste these lines to Claude in the chat, ask for the corrected file, and paste it into "
                  "<b>masala/inbox/</b> again.</p>")
            continue
        slug = st["slug"]
        dest = os.path.join(HERE, "stories", slug, "story.json")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        json.dump(st, open(dest, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        os.remove(f)
        if warns:
            open(os.path.join(os.path.dirname(dest), "warnings.txt"), "w", encoding="utf-8").write("\n".join(warns) + "\n")
        good.append(slug)
        notes.append(f"✅ {slug}: {len(st['scenes'])} scenes" + (f", {len(warns)} warning(s)" if warns else ""))
        log(notes[-1])
    if files:
        # only folders that exist: git add stops (and adds nothing) at a path that does not exist
        paths = [p for p in (INBOX, os.path.join(HERE, "stories"), os.path.join(HERE, "rejected")) if os.path.exists(p)]
        subprocess.run(["git", "add", "-A", *paths], cwd=ROOT, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "Masala inbox: " + ("; ".join(notes) or "rejected a story")],
                       cwd=ROOT, check=False)
        subprocess.run(["git", "pull", "-q", "--rebase", "--autostash"], cwd=ROOT, check=False)
        subprocess.run(["git", "push", "-q"], cwd=ROOT, check=False)
    else:
        log("the inbox is empty")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        open(out, "a").write(f"stories={' '.join(good)}\n")


if __name__ == "__main__":
    main()
