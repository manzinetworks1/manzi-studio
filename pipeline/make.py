"""Step 2 of the week (after you approve): voices, videos, thumbnails, notes, titles/descriptions, upload, email.

python pipeline/make.py [--week 2026-11-15] [--only long,myth] [--no-upload] [--no-email]
"""
import argparse, datetime, glob, html, json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "render"))
from common import ROOT, config, log, slug
from specs import all_specs, add_pops, plain
from voice import voice_spec
from render import render
import meta, notes, deliver, mail


def latest_week():
    ws = sorted(os.path.basename(d) for d in glob.glob(os.path.join(ROOT, "weeks", "*")) if os.path.isdir(d))
    if not ws: raise SystemExit("No scripts yet: run the 'Write scripts' workflow first.")
    return ws[-1]


def load_packs(week):
    packs = []
    for f in sorted(glob.glob(os.path.join(ROOT, "weeks", week, "q*.json"))):
        try: packs.append((f, json.load(open(f, encoding="utf-8"))))
        except ValueError as e:
            raise SystemExit(f"{os.path.relpath(f, ROOT)} has a typing mistake after your edit: {e}. Open it on GitHub, fix that line, and run again.")
    return packs


def schedule(items, week, cfg):
    """One post a day at the short time; long videos at the long time; extra Shorts take an evening slot."""
    start = max(datetime.date.fromisoformat(week) + datetime.timedelta(days=1), datetime.date.today())   # never in the past if you approve late
    lt, st, st2 = cfg.get("long_time", "18:00"), cfg.get("short_time", "13:00"), cfg.get("short_time_2", "20:00")
    longs = [i for i in items if i["kind"] == "long"]; shorts = [i for i in items if i["kind"] != "long"]
    for k, it in enumerate(longs): it["when"] = (start + datetime.timedelta(days=min(6, k * 3)), lt)
    days = 7; slots = [(start + datetime.timedelta(days=d), st) for d in range(days)] + [(start + datetime.timedelta(days=d), st2) for d in range(days)]
    for it, s in zip(shorts, slots): it["when"] = s
    return sorted(items, key=lambda i: (i["when"][0], i["when"][1]))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--week"); ap.add_argument("--only"); ap.add_argument("--no-upload", action="store_true"); ap.add_argument("--no-email", action="store_true")
    a = ap.parse_args(); cfg = config(); week = a.week or latest_week(); ch = cfg["channel"]
    out = os.path.join(ROOT, "out", week); os.makedirs(out, exist_ok=True)
    only = set(a.only.split(",")) if a.only else None
    order = cfg.get("shorts", ["datadrop", "myth", "quiz", "case", "compare", "flow"]); per = int(cfg.get("shorts_per_topic", 4))
    items, files, cache, t_all = [], [], {}, time.time()
    from playwright.sync_api import sync_playwright
    for f, pack in load_packs(week):
        specs = all_specs(pack, ch)
        longs = [s for s in specs if s["format"] == "long"]
        shorts = sorted([s for s in specs if s["format"] == "short"], key=lambda s: order.index(s["template"]) if s["template"] in order else 99)
        shorts = [s for s in shorts if s["template"] in order][:per]
        base = slug(" ".join([plain(pack["topic"]), pack.get("subject", ""), "llb"]), 80)
        for s in longs + shorts:
            if only and s["name"] not in only: continue
            kind = "long" if s["format"] == "long" else s["template"]
            name = base if kind == "long" else slug(plain(s["meta"].get("thumbTitle") or pack["topic"]), 50) + f"-{kind}-shorts"
            log(f"Q{pack['qnum']} {kind}: voice…"); wav = os.path.join(out, name + ".voice.wav")
            voice_spec(s, cfg, wav, cache); add_pops(s)
            log(f"Q{pack['qnum']} {kind}: video ({s['duration']:.0f}s)…")
            mp4, png = os.path.join(out, name + ".mp4"), os.path.join(out, name + "-thumbnail.png")
            render(s, mp4, voice=wav, thumb=png, fps=int(cfg.get("fps", 30)), music=cfg.get("music", True), log=lambda *x: None)
            os.remove(wav)
            m = meta.long_meta(pack, s, ch) if kind == "long" else meta.short_meta(pack, s, ch)
            items.append({"kind": kind, "q": pack["qnum"], "file": os.path.basename(mp4), "thumb": os.path.basename(png), "duration": s["duration"], **m})
            files += [mp4, png]
        tg = meta.tags(pack)
        for it in items:
            if it["q"] == pack["qnum"] and "tags" not in it: it["tags"] = ", ".join(tg if it["kind"] == "long" else tg[:12])
        with sync_playwright() as p:
            b = p.chromium.launch(); pdf = os.path.join(out, base + "-notes.pdf"); notes.make_pdf(pack, ch, pdf, b); b.close(); files.append(pdf)
    items = schedule(items, week, cfg)
    plan_txt = []
    for it in items:
        d, tm = it["when"]
        plan_txt += [f"=== {d.strftime('%a %d %b')} {tm} | {it['file']} ===", "TITLE:", it["title"], "", "DESCRIPTION:", it["description"], "",
                     "TAGS:", it["tags"], "", "PINNED COMMENT:", it["pinned_comment"], "", "THUMBNAIL: " + it["thumb"], "", ""]
    plan = os.path.join(out, f"publish-plan-{week}.txt"); open(plan, "w", encoding="utf-8").write("\n".join(plan_txt)); files.append(plan)
    log(f"all made in {(time.time() - t_all) / 60:.1f} min")
    where, links = ("(not uploaded)", {})
    if not a.no_upload: where, links = deliver.deliver(files, week, cfg)
    if not a.no_email:
        e = html.escape
        rows = "".join(f"<tr><td style='padding:6px;border-bottom:1px solid #eee;white-space:nowrap'><b>{it['when'][0].strftime('%a %d %b')}</b><br>{it['when'][1]}</td>"
                       f"<td style='padding:6px;border-bottom:1px solid #eee'>{'🎬 Long video' if it['kind'] == 'long' else '📱 Short'}<br><b>{e(it['title'])}</b><br>"
                       f"<a href='{links.get(it['file'], where)}'>⬇ video</a> · <a href='{links.get(it['thumb'], where)}'>⬇ thumbnail</a></td></tr>" for it in items)
        pdfs = "".join(f"<li><a href='{links.get(os.path.basename(f), where)}'>{e(os.path.basename(f))}</a></li>" for f in files if f.endswith(".pdf"))
        mail.send(cfg, f"[{ch}] {len(items)} videos ready for week {week}",
                  f"<h2 style='margin:0'>🎉 {len(items)} videos are ready</h2><p>All files: <a href='{where}'>{e(where)}</a></p>"
                  f"<p>Posting plan (titles, descriptions, tags and pinned comments are in <b>{e(os.path.basename(plan))}</b>, "
                  f"<a href='{links.get(os.path.basename(plan), where)}'>open it</a> on your phone to copy them):</p>"
                  f"<table style='border-collapse:collapse;width:100%'>{rows}</table>"
                  f"<p><b>Notes PDFs</b> for students who comment NOTES:</p><ul>{pdfs}</ul>"
                  f"<p>In the YouTube Studio app: + → Upload → choose the video → paste title and description → Visibility → <b>Schedule</b> → pick the date and time above.</p>")
    log("done")


if __name__ == "__main__":
    main()
