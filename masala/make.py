"""M, last step: puts a Masala Short together from the Manzi Engine's clips and delivers it.

python masala/make.py --story <slug> [--no-upload] [--no-email]

Reads masala/stories/<slug>/story.json and out/masala/<slug>/engine/ and makes in out/masala/<slug>/:
  - the Short (1080x1920): every scene's clip in order with hard cuts and its own sound (the characters' Hindi lines
    are spoken inside the clips), the hook line on top at the start, Hindi captions, a soft music bed
  - the captions as .srt, a thumbnail, and the posting plan (title, description with credits, tags, AI disclosure)
then uploads them (Google Drive if set up, otherwise a GitHub Release) and emails you.
Nothing is slowed down or frozen: each clip plays once at normal speed. A scene Kaggle could not make is left out
and named in the email.
"""
import argparse, datetime, html, json, os, re, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "pipeline")); sys.path.insert(0, os.path.join(REPO, "render")); sys.path.insert(0, HERE)
from common import ROOT, config, log  # noqa: E402
import ai_assemble, deliver, mail  # noqa: E402
from story import SETTINGS, check, load  # noqa: E402
from job import plan as clip_plan, voiced  # noqa: E402

W, H, FPS = 1080, 1920, 30
FONTS = os.path.join(REPO, "render", "fonts")
CREDITS = ("🎬 AI scenes made with MiniMax H3 (MiniMax H3 Community License) · built with Wan2GP "
           "(https://github.com/deepbeepmeep/Wan2GP) and AIQUEST Academy's Kaggle H3 engine (Apache 2.0)")
DISCLAIMER = "🎭 Fictional story. All characters and scenes are AI-generated; any resemblance to real people is coincidental."


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd[:6])}…\n{r.stderr[-1500:]}")
    return r


def has_audio(path):
    return bool(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                                "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip())


def pace(full, out, spoken):
    """Cuts the dead air (keeps a little before the first and after the last word; a scene without a line keeps its
    first few seconds) and plays the result a little faster. Returns the new length."""
    d = ai_assemble.duration(full)
    lead, tail, speed = SETTINGS.get("lead", 0.4), SETTINGS.get("tail", 0.3), SETTINGS.get("speed", 1.0)
    if spoken:
        a0, a1 = speech_span(full, d)
        a, b = max(0.0, a0 - lead), min(d, a1 + tail)
    else:
        a, b = 0.3, min(d, 0.3 + SETTINGS.get("silent_max", 4.5))
    if b - a < 2.0:
        a, b = 0.0, d
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{a:.2f}", "-to", f"{b:.2f}", "-i", full,
         "-vf", f"setpts=PTS/{speed},fps={FPS},format=yuv420p", "-af", f"atempo={speed}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-ac", "2", out])
    return ai_assemble.duration(out)


def seg(clip, out, mute=False):
    """One scene: upright 1080x1920, 30 fps, its own sound (silence if it has none or is muted), at normal speed."""
    vf = f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1,fps={FPS},format=yuv420p"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", clip]
    if mute or not has_audio(clip):
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v", "-map", "1:a", "-shortest"]
    cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
            "-ar", "48000", "-ac", "2", out]
    run(cmd)
    return ai_assemble.duration(out)


# ---------------------------------------------------------------- text pictures (Chromium draws Hindi correctly)
def _font(name):
    """A font as a data: URL: a page made with set_content() may not load file:// fonts (it fell back to a plain
    font on GitHub's machine)."""
    import base64
    return "data:font/ttf;base64," + base64.b64encode(open(os.path.join(FONTS, name), "rb").read()).decode()


CSS = f"""
@font-face {{ font-family: Pop; src: url('{_font('Poppins-Bold.ttf')}'); }}
@font-face {{ font-family: MzAnton; src: url('{_font('Anton-Regular.ttf')}'); }}
html, body {{ margin: 0; width: {W}px; height: {H}px; background: transparent; overflow: hidden; }}
.box {{ position: absolute; left: 60px; right: 60px; text-align: center;
       font-family: Pop, 'Noto Sans Devanagari', 'Noto Sans', sans-serif; font-weight: 800; color: #fff;
       -webkit-text-stroke: 3px #000; paint-order: stroke fill;
       text-shadow: 0 4px 14px rgba(0,0,0,.85), 0 0 3px #000; line-height: 1.35; }}
.cap {{ top: 1300px; left: 60px; right: 170px; font-size: 64px; line-height: 1.25; }}
.en {{ font-family: MzAnton, Pop, sans-serif; font-weight: 400; font-size: 44px; text-transform: uppercase;
      letter-spacing: 2px; -webkit-text-stroke: 7px #000; line-height: 1.15;
      text-shadow: 0 4px 0 #000, 0 6px 14px rgba(0,0,0,.6); }}
.en .hl {{ color: #ffd60a; }}
.hook {{ top: 210px; font-size: 76px; }}
.hook span, .end span {{ background: #ffd400; color: #111; -webkit-text-stroke: 0; text-shadow: none;
       padding: 6px 22px; border-radius: 18px; box-decoration-break: clone; -webkit-box-decoration-break: clone; }}
.end {{ top: 170px; font-size: 80px; }}
.law {{ position: absolute; top: 300px; left: 70px; right: 70px; padding: 30px 36px; border-radius: 28px;
       background: rgba(10,14,30,.86); border: 4px solid #ffd60a; color: #fff;
       font-family: Pop, 'Noto Sans Devanagari', sans-serif; box-shadow: 0 10px 40px rgba(0,0,0,.5); }}
.law h1 {{ margin: 0 0 14px; font-size: 50px; color: #ffd60a; line-height: 1.2; }}
.law p {{ margin: 10px 0 0; font-size: 38px; line-height: 1.3; }}
.law small {{ display: block; margin-top: 16px; font-size: 26px; opacity: .75; }}
.thumb {{ position: absolute; inset: 0; background-size: cover; background-position: center; }}
.thumb .box {{ top: 1180px; font-size: 104px; }}
.thumb .box span {{ background: #e3001b; color: #fff; -webkit-text-stroke: 0; padding: 4px 26px; border-radius: 16px;
       box-decoration-break: clone; -webkit-box-decoration-break: clone; }}
"""


FILM_CSS = """
html, body { width: 1920px; height: 1080px; }
.cap { top: 880px; left: 260px; right: 260px; font-size: 52px; }
.en { font-size: 40px; -webkit-text-stroke: 6px #000; }
.end { top: 60px; font-size: 64px; }
.thumb .box { top: 700px; font-size: 110px; }
.sub { position: absolute; left: 200px; right: 200px; bottom: 70px; text-align: center; color: #fff; font-size: 44px;
       font-family: 'Noto Sans Devanagari', Pop, sans-serif; font-weight: 500; line-height: 1.3;
       text-shadow: 0 0 6px #000, 0 2px 4px #000, 0 0 14px rgba(0,0,0,.8); }
.card { position: absolute; inset: 0; background: #000; display: flex; flex-direction: column; align-items: center;
        justify-content: center; color: #f4efe4; font-family: Pop, 'Noto Sans Devanagari', sans-serif; text-align: center; }
.card h1 { margin: 0; font-size: 150px; letter-spacing: 4px; color: #f2c14e; text-shadow: 0 0 40px rgba(242,193,78,.35); }
.card p { margin: 22px 0 0; font-size: 40px; opacity: .85; }
.card .small { font-size: 30px; line-height: 1.6; opacity: .8; max-width: 1500px; }
"""


def card_seg(png, secs, out):
    """A still card (title, credits) with a slow fade in and out and silence."""
    run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-t", f"{secs:.2f}", "-i", png, "-f", "lavfi", "-t",
         f"{secs:.2f}", "-i", "anullsrc=r=48000:cl=stereo", "-vf",
         f"scale={W}:{H},setsar=1,fps={FPS},fade=t=in:st=0:d=0.8,fade=t=out:st={secs - 0.8:.2f}:d=0.8,format=yuv420p",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-shortest", out])
    return ai_assemble.duration(out)


def render(jobs):
    """jobs: [(html body, png path, transparent?)] -> PNG files."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H})
        for body, png, clear in jobs:
            pg.set_content(f"<html><head><meta charset='utf-8'><style>{CSS}{FILM_CSS if W > H else ''}</style></head>"
                           f"<body>{body}</body></html>",
                           wait_until="load")
            pg.wait_for_timeout(60)
            pg.screenshot(path=png, omit_background=clear)
        b.close()


def split_caption(text, n=26, k=3):
    """Caption pieces of at most k lines of about n characters, split at word boundaries. A scene's line (12 words at
    most) normally fits in one piece, so a sentence is not cut in two."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > n:
            lines.append(cur); cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return ["<br>".join(lines[i:i + k]) for i in range(0, len(lines), k)] or [""]


def chunks(text, most=3):
    """English caption pieces of 2-3 words, breaking after punctuation when possible."""
    w = text.split()
    out, cur = [], []
    for x in w:
        cur.append(x)
        if len(cur) >= most or (len(cur) >= 2 and x[-1] in ",.!?…;:"):
            out.append(" ".join(cur)); cur = []
    if cur:
        if len(cur) == 1 and out and len(out[-1].split()) < 4:
            out[-1] += " " + cur[0]
        else:
            out.append(" ".join(cur))
    return out


def tts_line(s, tmp):
    """The narrator line spoken by Sarvam Bulbul, made a little deeper and older, with a soft room. Stops the build
    if Sarvam fails (no Microsoft fallback)."""
    import base64
    from common import http_json, secret
    n = s["narrator"]
    body = {"text": n["line"], "target_language_code": "hi-IN", "model": n.get("sarvam_model", "bulbul:v3"),
            "speaker": n.get("sarvam_speaker", "shubh"), "pace": float(n.get("pace", 0.85)), "speech_sample_rate": 24000}
    r = http_json(os.environ.get("SARVAM_URL", "https://api.sarvam.ai/text-to-speech"), body,
                  {"api-subscription-key": secret("SARVAM_API_KEY")})
    raw = os.path.join(tmp, f"{s['id']}-tts-raw.wav"); open(raw, "wb").write(base64.b64decode(r["audios"][0]))
    p = float(n.get("pitch", 0.92))
    out = os.path.join(tmp, f"{s['id']}-tts.wav")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-af",
         f"asetrate=24000*{p},aresample=48000,atempo={1 / p:.4f},lowpass=f=7000,aecho=0.8:0.5:35:0.12,"
         "adelay=150|150,apad=pad_dur=0.4", "-ar", "48000", "-ac", "2", out])
    log(f"  {s['id']}: narration voiced by Sarvam ({body['speaker']})")
    return out


def speech_span(clip, d, floor=-32):
    """(start, end) of the loud part of a clip's sound, where the voice is; the whole clip when unsure. A voice clip
    uses a lower floor (-45 dB): a soft, slow line ending ("...असल में मेरी ज़मीन थी") fell under -32 and was cut.
    The sound is resampled to 48 kHz first, so 4800 samples are exactly 0.1 s: H3 clips are 32 kHz, which made every
    window 0.15 s and every time 1/3 too early (lines cut before their end, 27 Nov 2026)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", clip, "-af",
                        "aresample=48000,asetnsamples=4800,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
                        "-f", "null", "-"], capture_output=True, text=True).stderr
    lv = [float(x) if x not in ("-inf", "inf") else -99 for x in re.findall(r"RMS_level=(-?[\d.]+|-?inf)", r)]
    loud = [i for i, x in enumerate(lv) if x > floor]
    if not loud:
        return 0.2, d - 0.3
    a, b = loud[0] * 0.1, (loud[-1] + 1) * 0.1
    return (max(0.1, a), min(d - 0.1, b)) if b - a > 1.0 else (0.2, d - 0.3)


def srt_time(t):
    ms = int(round(t * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def freezes(mp4, min_s=2.0):
    """Still stretches of at least min_s seconds (the check for "stuck" pictures)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", mp4, "-vf", f"freezedetect=n=0.002:d={min_s}", "-map", "0:v",
                        "-f", "null", "-"], capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", r)]
    ends = [float(x) for x in re.findall(r"freeze_end: ([\d.]+)", r)]
    return [(a, b) for a, b in zip(starts, ends + [None] * (len(starts) - len(ends)))]


def deliver_draft(a, cfg, st, out_dir, tmp, missing, starts, cids, t_all):
    """Draft: every clip on its own (not joined) plus a picture sheet (3 frames of every clip, labelled), then the
    "Draft ready" email. Clips are joined into the Short only by the final run, which you start yourself."""
    rows, files = [], []
    for sid, (t0, d) in starts.items():
        src = os.path.join(tmp, f"{sid}.mp4")
        clip = os.path.join(out_dir, f"{cids[sid]}.mp4")
        shutil.copy(src, clip)
        files.append(clip)
        pics = []
        for k, frac in enumerate((0.1, 0.5, 0.9)):
            png = os.path.join(tmp, f"sheet_{sid}_{k}.png")
            run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{d * frac:.2f}", "-i", src,
                 "-frames:v", "1", "-vf", "scale=270:480", png])
            pics.append(png)
        row = os.path.join(tmp, f"row_{sid}.png")
        run(["ffmpeg", "-y", "-loglevel", "error", *sum((["-i", p] for p in pics), []), "-filter_complex",
             f"hstack=3,pad=iw+150:ih:150:0:white,drawtext=text='{sid}':x=18:y=20:fontsize=40:fontcolor=black", row])
        rows.append(row)
    sheet = os.path.join(out_dir, f"{a.story}-DRAFT-sheet.jpg")
    run(["ffmpeg", "-y", "-loglevel", "error", *sum((["-i", r] for r in rows), []), "-filter_complex",
         f"vstack={len(rows)}" if len(rows) > 1 else "null", "-q:v", "3", sheet])
    files.append(sheet)
    log(f"draft clips ready in {(time.time() - t_all) / 60:.1f} min")
    where, links = "(not uploaded)", {}
    if not a.no_upload:
        stamp = time.strftime("%Y%m%d-%H%M", time.gmtime())
        where, links = deliver.release_upload(files, f"masala-draft-{a.story}-{stamp}", f"Masala DRAFT: {st['title']}",
                                              "Draft clips (544p), one per scene, to check before the final.")
    if not a.no_email:
        e = html.escape
        repo = os.environ.get("GITHUB_REPOSITORY", "manzinetworks1/manzi-studio")
        run_url = f"https://github.com/{repo}/actions/workflows/masala_make.yml"
        lk = lambda f: links.get(os.path.basename(f), where)
        rows_html = "".join(
            f"<tr><td><b>{s['id']}</b></td><td>{'✅ approved' if s.get('clip') else '🆕 to check'}</td>"
            f"<td>{'<a href=' + chr(39) + lk(os.path.join(out_dir, cids[s['id']] + '.mp4')) + chr(39) + '>clip</a>' if s['id'] in starts else '❌ not made'}</td>"
            f"<td>{e(s.get('line') or '(no line)')}</td></tr>" for s in st["scenes"])
        mail.send(cfg, f"[Masala Shorts] Draft clips to check: {st['title']}",
                  f"<h2 style='margin:0'>👀 Draft clips ready: please check the new ones</h2>"
                  f"<p>🖼️ <a href='{lk(sheet)}'><b>picture sheet</b></a> (3 frames of every clip). The clips are "
                  "<b>not joined</b>: open each one below (544p, not sharpened).</p>"
                  + (f"<p>⚠️ Not made: {e(', '.join(missing))}.</p>" if missing else "")
                  + "<p>Look at who faces whom, where the eyes go, faces, clothes, and the Hindi lip-sync.</p>"
                  f"<table border='1' cellpadding='4' style='border-collapse:collapse'>{rows_html}</table>"
                  "<p><b>Something wrong?</b> Tell Claude in the chat; only the changed scenes are made again.</p>"
                  f"<p><b>All good?</b> Tell Claude, or <a href='{run_url}'>open “M - Make masala short”</a> → "
                  f"<b>Run workflow</b> → story <code>{e(a.story)}</code>, mode <code>final</code>: the same clips are "
                  "sharpened to 720p and joined into the Short.</p>")
    shutil.rmtree(tmp, ignore_errors=True)
    log("draft done")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", required=True); ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--mode", choices=["draft", "final", "final-544p"], default=None, help="default: what job.py downloaded")
    a = ap.parse_args()
    t_all = time.time()
    cfg, st = config(), load(a.story)
    out_dir = os.path.join(ROOT, "out", "masala", a.story)
    engine_dir = os.path.join(out_dir, "engine")
    tmp = os.path.join(out_dir, "build"); shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
    check(st)  # fills each scene's cast from its stage
    film = st.get("format") == "film"
    if film:  # a widescreen short film: normal speed, gentler trims, title card and credits, joined even as a draft
        global W, H
        W, H = 1920, 1080
        SETTINGS.update({k: v for k, v in SETTINGS["film"].items() if k in ("speed", "lead", "tail", "silent_max",
                                                                             "music_volume")})
    cover = film and bool(st.get("coverage"))   # setups + reactions + cut to the line (like a filmed short)
    if cover:
        SETTINGS.update(SETTINGS["film"]["coverage"])
    music_win = []
    info = json.load(open(os.path.join(engine_dir, "clips.json"))) if os.path.exists(os.path.join(engine_dir, "clips.json")) else {}
    mode = a.mode or info.get("mode", "final")
    cids = {s["id"]: cid for s, cid, _, _ in clip_plan(st)}
    timing = []

    # 1. one segment per scene, in order
    segs, cues, hi_cues, missing, timing, t, starts = [], [], [], [], [], 0.0, {}
    for k_s, s in enumerate(st["scenes"]):
        if s.get("setup"):   # a camera setup: only its picture is used (stills, reaction cutaways)
            continue
        if s.get("reaction"):   # the listener's face, cut silently from that setup's clip
            rc = next((os.path.join(engine_dir, f"{cids[s['reaction']]}_{q}.mp4") for q in ("720p", "544p", "480p", "384p")
                       if os.path.exists(os.path.join(engine_dir, f"{cids[s['reaction']]}_{q}.mp4"))), None)
            if not rc:
                missing.append(s["id"]); log(f"  {s['id']}: no clip for setup {s['reaction']}, left out"); continue
            full = os.path.join(tmp, f"{s['id']}-full.mp4"); fd = seg(rc, full, True)
            secs = float(s.get("secs", SETTINGS.get("reaction_secs", 1.6)))
            room = max(0.0, fd - secs - 0.4)
            x0 = 0.2 + (k_s * 1.37) % room if room > 0.2 else 0.0   # different moments of the setup for each cutaway
            out = os.path.join(tmp, f"{s['id']}.mp4")
            run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{x0:.2f}", "-t", f"{secs:.2f}", "-i", full,
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k", out])
            d = ai_assemble.duration(out)
            segs.append(out); starts[s["id"]] = (t, d)
            if s.get("music"):
                music_win.append((t, t + d))
            t += d; log(f"  {s['id']}: reaction {d:.1f}s (total {t:.1f}s)")
            continue
        src_id = s.get("still_of") or s["id"]   # "still_of": this scene shows the last picture of another scene
        clip = next((os.path.join(engine_dir, f"{cids[src_id]}_{q}.mp4") for q in ("720p", "544p", "480p", "384p")
                     if os.path.exists(os.path.join(engine_dir, f"{cids[src_id]}_{q}.mp4"))), None)
        if clip and s.get("still_of"):
            png = os.path.join(tmp, f"{s['id']}-still.png")
            run(["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.3", "-i", clip, "-frames:v", "1", png])
            held = os.path.join(tmp, f"{s['id']}-held.mp4")
            run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-t", "8", "-i", png, "-f", "lavfi", "-t", "8",
                 "-i", "anullsrc=r=48000:cl=stereo", "-vf",
                 f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
                 f"zoompan=z='1+0.0006*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},format=yuv420p",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-shortest", held])
            clip = held
        if not clip:
            missing.append(s["id"]); log(f"  {s['id']}: no clip, left out"); continue
        spoken = ((s.get("narrator") or {}).get("line") or s.get("line") or "").strip()
        out = os.path.join(tmp, f"{s['id']}.mp4")
        vclip = os.path.join(engine_dir, f"{cids[s['id']]}-v_384p.mp4") if voiced(st, s) else None
        if voiced(st, s) and (s.get("narrator") or {}).get("tts") == "sarvam":
            if os.environ.get("SARVAM_API_KEY", "").strip():
                vclip = tts_line(s, tmp)
            else:
                log(f"  {s['id']}: no SARVAM_API_KEY yet, using the H3 voice clip")   # a clean studio voice: H3 voice clips came out with gaps and missing words
        if vclip and os.path.exists(vclip):
            # the silent picture with the narration taken from its voice clip, starting 0.4 s in
            pic = os.path.join(tmp, f"{s['id']}-pic.mp4"); pd = seg(clip, pic, True)
            vd = ai_assemble.duration(vclip)
            v0, v1 = speech_span(vclip, vd, floor=-45)
            v0, v1 = max(0.0, v0 - 0.15), min(vd, v1 + 0.35)
            dd = max(3.0, (v1 - v0) + 0.9)          # the whole line plays; the picture holds if it is shorter
            src = os.path.join(tmp, f"{s['id']}-full.mp4")
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", pic, "-ss", f"{v0:.2f}", "-to", f"{v1:.2f}", "-i", vclip,
                 "-filter_complex", f"[0:v]tpad=stop_mode=clone:stop_duration={max(0.0, dd - pd) + 0.1:.2f}[v];"
                 "[1:a]aresample=48000,aformat=channel_layouts=stereo,adelay=400|400,apad[a]",
                 "-map", "[v]", "-map", "[a]", "-t", f"{dd:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                 "-c:a", "aac", "-b:a", "192k", src])
            shutil.copy(src, out); d = ai_assemble.duration(out)   # never trimmed: the line must not be cut
        elif vclip:
            missing.append(s["id"]); log(f"  {s['id']}: no voice clip for the narration, left out"); continue
        elif (mode == "draft" and not cover) or not SETTINGS.get("trim", True):
            d = seg(clip, out, s.get("mute") or (film and not spoken))
        else:
            full = os.path.join(tmp, f"{s['id']}-full.mp4"); seg(clip, full, s.get("mute") or (film and not spoken))
            d = pace(full, out, spoken)
        segs.append(out); starts[s["id"]] = (t, d)
        a0, a1 = speech_span(out, d)
        if spoken:
            hi_cues.append((spoken, t + a0, t + a1))
        if s.get("music"):
            music_win.append((t, t + d))
        if cover:   # film subtitles: the whole line, small, at the bottom
            parts = [(s.get("caption_en") if st.get("captions") == "en" else None) or spoken] if spoken else []
        elif st.get("captions") == "en":
            text = (s.get("caption_en") or "").strip()
            parts = chunks(text) if text else []
        else:
            text = (s.get("caption") or spoken)
            parts = split_caption(text) if text else []
        if parts:  # each piece gets time in proportion to its length
            wts = [len(p) + 4 for p in parts]
            x = t + a0
            for p_, w_ in zip(parts, wts):
                y = x + (a1 - a0) * w_ / sum(wts)
                cues.append((p_, x, y)); x = y
        t += d
        log(f"  {s['id']}: {d:.1f}s (total {t:.1f}s)")
        tc = st.get("title_card") or {}
        if film and tc.get("after") == s["id"]:
            png = os.path.join(tmp, "title_card.png")
            render([(f"<div class='card'><h1>{html.escape(tc.get('text', st['title']))}</h1>"
                     + (f"<p>{html.escape(tc['sub'])}</p>" if tc.get("sub") else "") + "</div>", png, False)])
            out = os.path.join(tmp, "title_card.mp4")
            d = card_seg(png, float(tc.get("seconds", 4.5)), out)
            music_win.append((max(0.0, t - 3.0), t + d))
            segs.append(out); t += d
    if not segs:
        raise SystemExit("No clips came back from Kaggle: nothing to put together.")

    if film and st.get("credits"):
        png = os.path.join(tmp, "credits.png")
        render([("<div class='card'><p class='small'>" + "<br>".join(html.escape(x) for x in st["credits"])
                 + "</p></div>", png, False)])
        out = os.path.join(tmp, "credits.mp4")
        music_win.append((max(0.0, t - 4.0), t + 7.0))
        segs.append(out); t += card_seg(png, 7.0, out)
    if mode == "draft" and not film:  # draft: the clips one by one, not joined
        return deliver_draft(a, cfg, st, out_dir, tmp, missing, starts, cids, t_all)

    # 2. text pictures: hook, captions, end line
    jobs, overlays = [], []
    if st.get("hook_text"):
        png = os.path.join(tmp, "hook.png")
        jobs.append((f"<div class='box hook'><span>{html.escape(st['hook_text'])}</span></div>", png, True))
        overlays.append((png, 0.0, min(3.0, t)))
    for k, (text, x, y) in enumerate(cues):
        png = os.path.join(tmp, f"cap{k:03d}.png")
        if cover:
            jobs.append((f"<div class='sub'>{html.escape(text)}</div>", png, True))
        elif st.get("captions") == "en":  # bold upper-case words, the longest one in yellow
            ws = [html.escape(w) for w in text.split()]
            raw = text.split()
            key = max(range(len(raw)), key=lambda i: len(re.sub(r"[^\w]", "", raw[i]))) if raw else -1  # longest word
            body = " ".join(f"<span class='hl'>{w}</span>" if i == key and len(w) > 3 else w for i, w in enumerate(ws))
            jobs.append((f"<div class='box cap en'>{body}</div>", png, True))
        else:
            jobs.append((f"<div class='box cap'>{'<br>'.join(html.escape(l) for l in text.split('<br>'))}</div>", png, True))
        overlays.append((png, x, y))
    lc = st.get("law_card")
    if lc and lc.get("scene") in starts:  # the law on screen for one whole scene
        png = os.path.join(tmp, "law.png")
        body = (f"<div class='law'><h1>{html.escape(lc['title'])}</h1>"
                + "".join(f"<p>{html.escape(x)}</p>" for x in lc.get("lines", []))
                + (f"<small>{html.escape(lc['note'])}</small>" if lc.get("note") else "") + "</div>")
        jobs.append((body, png, True))
        x0, dur = starts[lc["scene"]]
        overlays.append((png, x0, x0 + dur))
    if st.get("end_text"):
        png = os.path.join(tmp, "end.png")
        jobs.append((f"<div class='box end'><span>{html.escape(st['end_text'])}</span></div>", png, True))
        last = max(x0 + dd for x0, dd in starts.values())
        overlays.append((png, max(0.0, last - 2.5), last))
    # thumbnail: a frame from the chosen scene with the big words
    th = st.get("thumbnail") or {}
    tid = th.get("scene") if th.get("scene") in starts else list(starts)[len(starts) // 2]
    frame = os.path.join(tmp, "thumb_bg.png")
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{starts[tid][1] * 0.45:.2f}", "-i", os.path.join(tmp, f"{tid}.mp4"),
         "-frames:v", "1", frame])
    thumb = os.path.join(out_dir, f"{a.story}-thumbnail.png")
    words = th.get("text") or st.get("hook_text") or ""
    import base64
    bg = "data:image/png;base64," + base64.b64encode(open(frame, "rb").read()).decode()
    jobs.append((f"<div class='thumb' style=\"background-image:url('{bg}')\">"
                 + (f"<div class='box'><span>{html.escape(words)}</span></div>" if words else "") + "</div>", thumb, False))
    log(f"text pictures: {len(jobs)}")
    render(jobs)

    # 3. join with hard cuts, put the text on, music bed, loudness for Shorts
    inputs = []
    for p in segs:
        inputs += ["-i", p]
    n = len(segs)
    graph = "".join(f"[{i}:v][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v0][a0]"
    for k, (png, x, y) in enumerate(overlays):
        inputs += ["-i", png]
        graph += f";[v{k}][{n + k}:v]overlay=0:0:enable='between(t,{x:.3f},{y:.3f})'[v{k + 1}]"
    vlast = f"v{len(overlays)}"
    m = n + len(overlays)
    if SETTINGS.get("music", True):
        from render import make_music
        mus = os.path.join(tmp, "music.wav"); make_music(mus, t + 1)
        inputs += ["-i", mus]
        vol = f"{SETTINGS.get('music_volume', 0.06)}"
        if cover:   # music only at the title, the marked moments and the end, with 2 s fades; room tone under all
            on = "+".join(f"clip((t-{a - 2:.2f})/2,0,1)*clip(({b + 2:.2f}-t)/2,0,1)" for a, b in music_win) or "0"
            vol = f"'{SETTINGS.get('music_volume', 0.12)}*min(1,{on})':eval=frame"
        graph += (f";[{m}:a]aresample=48000,aformat=channel_layouts=stereo,volume={vol}[m]"
                  f";[a0][m]amix=inputs=2:duration=first:normalize=0[mix0]")
        if cover:
            graph += (f";anoisesrc=color=brown:amplitude={SETTINGS.get('room_tone', 0.0025)}:sample_rate=48000:duration={t + 1:.2f},"
                      "lowpass=f=900,aformat=channel_layouts=stereo[room];[mix0][room]amix=inputs=2:duration=first:normalize=0[mix]")
        else:
            graph += ";[mix0]anull[mix]"
    else:
        graph += ";[a0]anull[mix]"
    graph += ";[mix]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]"
    script = os.path.join(tmp, "join.txt"); open(script, "w").write(graph)
    short = os.path.join(out_dir, f"{a.story}.mp4")
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex_script", script, "-map", f"[{vlast}]",
         "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", short])
    total = ai_assemble.duration(short)
    stuck = freezes(short)
    log(f"Short: {total:.1f}s, still stretches of 2 s or more: {len(stuck)}")

    # 4. captions file and posting plan
    srt = os.path.join(out_dir, f"{a.story}.hi.srt")  # Hindi subtitles (whole lines) for YouTube's subtitle track
    open(srt, "w", encoding="utf-8").write("".join(
        f"{i}\n{srt_time(x)} --> {srt_time(y)}\n{c}\n\n" for i, (c, x, y) in enumerate(hi_cues, 1)))
    srt_en = None
    if st.get("captions") == "en":  # the English pieces burned into the video, also as a subtitle file
        srt_en = os.path.join(out_dir, f"{a.story}.en.srt")
        open(srt_en, "w", encoding="utf-8").write("".join(
            f"{i}\n{srt_time(x)} --> {srt_time(y)}\n{c}\n\n" for i, (c, x, y) in enumerate(cues, 1)))
    yt = st["youtube"]
    title = st["title"] if film or "#shorts" in st["title"].lower() or len(st["title"]) > 90 else f"{st['title']} #Shorts"
    desc = f"{yt['description'].strip()}\n\n{DISCLAIMER}\n\n{CREDITS}"
    tags, n_ch = [], 0
    for tg in yt.get("tags", []) + ["hindi story", "family drama", "entertainment with manzi"]:
        if tg.lower() not in [x.lower() for x in tags] and n_ch + len(tg) + 2 <= 480:
            tags.append(tg); n_ch += len(tg) + 2
    day = datetime.date.today() + datetime.timedelta(days=1)
    plan = [f"=== {day.strftime('%a %d %b')} {SETTINGS.get('post_time', '19:00')} | {os.path.basename(short)} ===",
            "TITLE:", title, "", "DESCRIPTION:", desc, "", "TAGS:", ", ".join(tags), "",
            f"THUMBNAIL: {os.path.basename(thumb)} (YouTube app → the Short → Edit → Thumbnail)",
            f"SUBTITLES: {os.path.basename(srt)} (optional: Studio → Subtitles → Hindi → Upload file → With timing)"
            + (f"; {os.path.basename(srt_en)} the same way as English" if srt_en else ""),
            "ALTERED OR SYNTHETIC CONTENT (YouTube Studio → Details): YES (realistic AI people and voices)", ""]
    plan_file = os.path.join(out_dir, f"publish-plan-{a.story}.txt")
    open(plan_file, "w", encoding="utf-8").write("\n".join(plan))
    files = [short, thumb, srt, plan_file] + ([srt_en] if srt_en else [])
    log(f"all made in {(time.time() - t_all) / 60:.1f} min")

    # 5. upload + email
    where, links = "(not uploaded)", {}
    if not a.no_upload:
        stamp = time.strftime("%Y%m%d-%H%M", time.gmtime())
        if deliver.drive_ready():
            where, links = deliver.drive_upload(files, f"Masala Short - {a.story}", cfg.get("drive_folder_id") or None)
        else:
            where, links = deliver.release_upload(files, f"masala-{a.story}-{stamp}", f"Masala Short: {st['title']}",
                                                  "Your Masala Short. See the email for the posting plan.")
    if not a.no_email:
        e = html.escape
        lk = lambda f: links.get(os.path.basename(f), where)
        notes = []
        if missing:
            notes.append(f"{len(missing)} scene(s) did not come back from Kaggle and are left out: {', '.join(missing)}.")
        if timing:
            notes.append(f"The line may be cut short or rushed in: {', '.join(timing)} (have a listen).")
        if stuck:
            notes.append("Still pictures of 2 s or more at: " + ", ".join(f"{x:.0f}s" for x, _ in stuck) + ".")
        warn_file = os.path.join(HERE, "stories", a.story, "warnings.txt")
        if os.path.exists(warn_file):
            notes += open(warn_file, encoding="utf-8").read().split("\n")
        box = ("<div style='background:#fff4e5;padding:10px;border-radius:8px'><b>Check these:</b><ul>"
               + "".join(f"<li>{e(x)}</li>" for x in notes if x) + "</ul></div>") if notes else ""
        mail.send(cfg, f"[Entertainment With Manzi] Short ready: {st['title']}",
                  f"<h2 style='margin:0'>🎉 Your Short is ready</h2>"
                  f"<p>📱 <a href='{lk(short)}'><b>{e(st['title'])}</b></a> ({total:.0f}s) · "
                  f"<a href='{lk(thumb)}'>thumbnail</a> · <a href='{lk(srt)}'>captions (.srt)</a></p>{box}"
                  f"<p>Title, description (with credits), tags and the posting time are in "
                  f"<a href='{lk(plan_file)}'><b>{e(os.path.basename(plan_file))}</b></a>. All files: "
                  f"<a href='{where}'>{e(where)}</a></p>"
                  f"<p>In YouTube Studio set <b>Altered or synthetic content = Yes</b>.</p>")
    shutil.rmtree(tmp, ignore_errors=True)
    log("done")


if __name__ == "__main__":
    main()
