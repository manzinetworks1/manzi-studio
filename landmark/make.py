"""L2, second step: puts a landmark case video together from the Manzi Engine's results.

python landmark/make.py --case <slug> [--no-upload] [--no-email]

Reads landmark/cases/<slug>/story.json and out/landmark/<slug>/engine/ (scenes, Professor clips, narration
sentences), and makes in out/landmark/<slug>/:
  - the long video (1920x1080): Professor intro -> the story in scenes and cards, narrated in the Professor's voice ->
    Professor outro, with soft music
  - English captions (.srt) to upload with it
  - 2 thumbnails (a scene with big words, and the title card)
  - 2-3 vertical Shorts cut from the story, with captions burnt in
  - the posting plan (title, description with chapters and credits, tags, pinned comment, AI disclosure)
then uploads everything (Google Drive if set up, otherwise a GitHub Release) and emails you.
Missing pieces never stop the video: a missing scene becomes a chapter card, a missing narration sentence is read by
the Microsoft Indian English voice.
"""
import argparse, datetime, html, json, os, re, shutil, subprocess, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "pipeline")); sys.path.insert(0, os.path.join(REPO, "render")); sys.path.insert(0, HERE)
from common import ROOT, config, log, to_pcm, wav_write  # noqa: E402
from voice import speakable, trim, SR  # noqa: E402
import ai_assemble, deliver, mail  # noqa: E402
from cards import render_cards, W, H  # noqa: E402

FPS = 30
LEAD, GAP, TAIL = 0.35, 0.35, 0.5          # seconds of quiet before, between and after narration sentences
FONT = os.path.join(REPO, "render", "fonts", "Poppins-Bold.ttf")
CREDITS = ("🎬 AI scenes made with MiniMax H3 (MiniMax H3 Community License) · built with Wan2GP "
           "(https://github.com/deepbeepmeep/Wan2GP) and AIQUEST Academy's Kaggle H3 engine (Apache 2.0)")
DISCLAIMER = ("🎭 This is a dramatised reconstruction for legal education. The scenes are AI-generated and every actor "
              "is fictional: they do not show the real people. Dialogue in the scenes is invented; the legal facts "
              "follow the judgment.")


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd[:6])}…\n{r.stderr[-1500:]}")
    return r


def has_audio(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of",
                          "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    return bool(out)


def last_frame(src, png):
    run(["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.2", "-i", src, "-update", "1", "-frames:v", "1", png])
    return png


V_OUT = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
SCALE = f"scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1"


def kenburns(index, frames, label, z_from=1.0, z_to=1.06):
    """A still picture (input `index`) with a slow, smooth zoom towards the centre."""
    return (f"[{index}:v]scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase:flags=lanczos,crop={W * 2}:{H * 2},"
            f"zoompan=z='{z_from}+({z_to}-{z_from})*on/{max(1, frames)}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={max(1, frames)}:s={W}x{H}:fps={FPS},setsar=1,format=yuv420p[{label}]")


# ------------------------------------------------------------------ narration
class Voices:
    def __init__(self, engine_dir, lcfg):
        self.premade = ai_assemble.premade_voices(engine_dir) if os.path.isdir(engine_dir) else {}
        self.lcfg, self.fallback = lcfg, []
        log(f"narration: {len(self.premade)} sentences in the Professor's voice")

    def get(self, sentence):
        text = speakable(sentence)
        if text in self.premade:
            return trim(to_pcm(self.premade[text], SR))
        self.fallback.append(sentence)
        from voice import edge_clip
        data, _ = edge_clip(text, self.lcfg.get("fallback_voice", "en-IN-PrabhatNeural"), "+5%")
        return trim(to_pcm(data, SR))

    def beat(self, sentences, path, min_len=0.0):
        """Narration of one beat -> wav; returns (seconds, [(sentence, start, end)])."""
        parts, t, times = [np.zeros(int(LEAD * SR), np.int16)], LEAD, []
        for i, s in enumerate(sentences):
            x = self.get(s)
            times.append((s, round(t, 3), round(t + len(x) / SR, 3)))
            parts.append(x); t += len(x) / SR
            g = GAP if i < len(sentences) - 1 else TAIL
            parts.append(np.zeros(int(g * SR), np.int16)); t += g
        if t < min_len:
            parts.append(np.zeros(int((min_len - t) * SR), np.int16)); t = min_len
        wav_write(path, np.concatenate(parts), SR)
        return round(len(np.concatenate(parts)) / SR, 3), times


# ------------------------------------------------------------------ segments (one or two per beat)
def seg_professor(clip, out):
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-filter_complex",
         f"[0:v]{SCALE},fps={FPS},format=yuv420p[v];[0:a]aresample=48000,aformat=channel_layouts=stereo[a]",
         "-map", "[v]", "-map", "[a]", *V_OUT, out])
    return ai_assemble.duration(out)


def seg_still(png, nar_wav, dur, out, fade=True):
    frames = int(round(dur * FPS))
    vf = kenburns(0, frames, "k") + (f";[k]fade=t=in:st=0:d=0.3,fade=t=out:st={max(0, dur - 0.3):.3f}:d=0.3[v]"
                                     if fade else ";[k]null[v]")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", png, "-i", nar_wav, "-filter_complex",
         vf + ";[1:a]aresample=48000,aformat=channel_layouts=stereo,apad[a]",
         "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}", *V_OUT, out])
    return dur


def seg_scene(clip, nar_wav, dur, out, tmp, slow_max=1.5):
    """The clip (slowed down up to 1.5x to fit the narration), then its last picture with a slow zoom for the rest;
    the scene's own sound stays underneath, quietly."""
    clen = ai_assemble.duration(clip) or 5.0
    f = min(max(dur / clen, 1.0), slow_max)
    shown = clen * f
    tail = max(0.0, dur - shown)
    inputs = ["-i", clip, "-i", nar_wav]
    graph = [f"[0:v]setpts={f:.4f}*PTS,{SCALE},fps={FPS},format=yuv420p[c]"]
    if tail > 0.05:
        inputs += ["-i", last_frame(clip, os.path.join(tmp, "last.png"))]
        graph.append(kenburns(2, int(round(tail * FPS)) + 2, "k", 1.0, 1.05))
        graph.append("[c][k]concat=n=2:v=1:a=0[v]")
    else:
        graph.append("[c]null[v]")
    graph.append("[1:a]aresample=48000,aformat=channel_layouts=stereo,apad[n]")
    if has_audio(clip):
        graph.append(f"[0:a]atempo={1 / f:.4f},volume=0.22,aresample=48000,aformat=channel_layouts=stereo,"
                     f"afade=t=out:st={max(0, shown - 0.6):.3f}:d=0.6,apad[m]")
        graph.append("[n][m]amix=inputs=2:duration=first:normalize=0[a]")
    else:
        graph.append("[n]anull[a]")
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(graph),
         "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}", *V_OUT, out])
    return dur


def seg_dialogue(clip, out):
    """A scene with a spoken line: shown at normal speed with its own sound."""
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-filter_complex",
         f"[0:v]{SCALE},fps={FPS},format=yuv420p[v];[0:a]aresample=48000,aformat=channel_layouts=stereo[a]",
         "-map", "[v]", "-map", "[a]", *V_OUT, out])
    return ai_assemble.duration(out)


# ------------------------------------------------------------------ helpers for the outputs
def mmss(s):
    s = int(s); return f"{s // 60}:{s % 60:02d}"


def srt_time(t):
    ms = int(round(t * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def split_caption(text, n=42):
    """Long sentences -> evenly sized caption chunks of at most two lines (about 2 x n characters)."""
    import math
    words = text.split()
    k = max(1, math.ceil(len(text) / (n * 2)))
    per = len(text) / k
    chunks, cur = [], ""
    for w in words:
        if cur and len(cur) + len(w) + 1 > per * 1.15 and len(chunks) < k - 1:
            chunks.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        chunks.append(cur)
    return chunks


def captions(cues):
    """[(text, start, end)] -> SRT cues, long sentences split by length."""
    out = []
    for text, a, b in cues:
        text = re.sub(r"\*\*", "", text)
        parts = split_caption(text)
        total = sum(len(p) for p in parts) or 1
        t = a
        for p in parts:
            d = (b - a) * len(p) / total
            out.append((p, t, t + d)); t += d
    return out


def write_srt(cues, path):
    with open(path, "w", encoding="utf-8") as f:
        for i, (text, a, b) in enumerate(cues, 1):
            f.write(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n\n")


def chapters(marks, total):
    """[(t, name)] -> YouTube chapters (first at 0:00, each at least 10 s, at least 3). A chapter that would last
    less than 10 s gives its place to the next one (e.g. the short Professor intro takes the first story chapter's name)."""
    out = []
    for t, name in marks:
        if not name or (out and out[-1][1] == name):
            continue
        if out and t - out[-1][0] < 10:
            out[-1] = (out[-1][0], name)
            continue
        out.append((t, name))
    if out:
        out[0] = (0.0, out[0][1])
    while len(out) > 1 and total - out[-1][0] < 10:
        out.pop()
    return out if len(out) >= 3 else []


def wrap(text, n):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > n and cur:
            lines.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines


def drawtext_file(tmp, name, text):
    p = os.path.join(tmp, name)
    open(p, "w", encoding="utf-8").write(text)
    return p.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


# ------------------------------------------------------------------ thumbnails
THUMB_HTML = """<!doctype html><html><head><meta charset='utf-8'><style>
@font-face {{ font-family: D; src: url('file://{fonts}/InterDisplay-Black.otf'); }}
@font-face {{ font-family: T; src: url('file://{fonts}/Inter-Bold.otf'); }}
html,body {{ margin:0; width:1280px; height:720px; overflow:hidden; }}
body {{ background: #000 url('file://{img}') center/cover; }}
.shade {{ position:absolute; inset:0; background: linear-gradient(90deg, rgba(5,10,20,.92) 0%, rgba(5,10,20,.75) 42%,
  rgba(5,10,20,0) 72%); }}
.tag {{ position:absolute; left:52px; top:48px; background:#d9ab4f; color:#0e1a2b; font:22px T; letter-spacing:3px;
  padding:10px 18px; border-radius:6px; text-transform:uppercase; }}
.big {{ position:absolute; left:52px; top:130px; width:640px; font:96px/1.0 D; color:#fff; text-transform:uppercase;
  text-shadow: 0 6px 24px rgba(0,0,0,.6); }}
.big span {{ color:#ffd36b; }}
.case {{ position:absolute; left:52px; bottom:48px; width:700px; font:34px/1.2 T; color:#f4efe4; }}
</style></head><body><div class='shade'></div><div class='tag'>Landmark case · {year}</div>
<div class='big'>{big}</div><div class='case'>{case}</div></body></html>"""


def thumbnails(st, engine_dir, title_png, out_dir, base, tmp):
    from playwright.sync_api import sync_playwright
    files = []
    sid = (st.get("thumbnail") or {}).get("scene")
    src = ai_assemble.clip(engine_dir, sid) if sid else None
    if not src:  # any scene with a face will do
        for b in st["beats"]:
            if b["type"] == "scene" and ai_assemble.clip(engine_dir, b["id"]):
                src = ai_assemble.clip(engine_dir, b["id"]); break
    with sync_playwright() as p:
        br = p.chromium.launch(args=["--allow-file-access-from-files"])
        pg = br.new_page(viewport={"width": 1280, "height": 720})
        if src:
            frame = os.path.join(tmp, "thumb_frame.png")
            run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "2.5", "-i", src, "-frames:v", "1", "-vf",
                 "scale=1280:720:flags=lanczos", frame])
            words = html.escape((st.get("thumbnail") or {}).get("text") or st.get("topic", "")).split()
            big = " ".join(words[:-1] + [f"<span>{words[-1]}</span>"]) if words else ""
            short_case = re.sub(r"\s*\(.*?\)", "", st["case"])
            page = os.path.join(tmp, "thumb.html")
            open(page, "w", encoding="utf-8").write(THUMB_HTML.format(
                fonts=os.path.join(REPO, "render", "fonts"), img=frame, year=html.escape(str(st.get("year", ""))),
                big=big, case=html.escape(short_case)))
            pg.goto("file://" + page); pg.evaluate("document.fonts.ready"); pg.wait_for_timeout(150)
            out = os.path.join(out_dir, base + "-thumbnail.png"); pg.screenshot(path=out); files.append(out)
        br.close()
    if title_png and os.path.exists(title_png):
        out = os.path.join(out_dir, base + "-thumbnail-title.png")
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", title_png, "-vf", "scale=1280:720:flags=lanczos", out])
        files.append(out)
    return files


# ------------------------------------------------------------------ Shorts
def make_short(long_mp4, a, b, title, cues, out, tmp, k):
    dur = min(59.0, b - a)
    fs = drawtext_file(tmp, f"short{k}_title.txt", "\n".join(wrap(title.upper(), 22)[:3]))
    vf = ["[0:v]split[x][y]",
          "[x]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:2,eq=brightness=-0.12[bg]",
          "[y]scale=1080:-2:flags=lanczos[fg]",
          "[bg][fg]overlay=(W-w)/2:(H-h)/2-60[o]",
          f"[o]drawtext=fontfile='{FONT}':textfile='{fs}':fontsize=64:line_spacing=14:fontcolor=white:text_align=center:"
          f"box=1:boxcolor=0x0e1a2b@0.85:boxborderw=26:x=(w-text_w)/2:y=230"]
    n = 0
    for text, ca, cb in cues:
        if cb <= a or ca >= a + dur:
            continue
        ca, cb = max(ca, a) - a, min(cb, a + dur) - a
        f = drawtext_file(tmp, f"short{k}_cap{n}.txt", "\n".join(wrap(text, 30)[:3]))
        vf.append(f"drawtext=fontfile='{FONT}':textfile='{f}':fontsize=54:line_spacing=10:fontcolor=white:text_align=center:"
                  f"borderw=5:bordercolor=black:x=(w-text_w)/2:y=1420:enable='between(t,{ca:.2f},{cb:.2f})'")
        n += 1
    vf.append(f"drawtext=fontfile='{FONT}':text='Full case on the channel':fontsize=40:fontcolor=0xd9ab4f:borderw=4:bordercolor=black:"
              f"x=(w-text_w)/2:y=1760")
    graph = vf[0] + ";" + vf[1] + ";" + vf[2] + ";" + vf[3] + ";" + ",".join(vf[4:]) + "[v]"
    run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{a:.3f}", "-t", f"{dur:.3f}", "-i", long_mp4,
         "-filter_complex", graph, "-map", "[v]", "-map", "0:a",
         "-af", f"afade=t=out:st={max(0, dur - 0.8):.2f}:d=0.8", *V_OUT, out])
    return dur


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True); ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--no-email", action="store_true")
    a = ap.parse_args()
    t_all = time.time()
    cfg = config(); lcfg = json.load(open(os.path.join(HERE, "settings.json"), encoding="utf-8"))
    st = json.load(open(os.path.join(HERE, "cases", a.case, "story.json"), encoding="utf-8"))
    out_dir = os.path.join(ROOT, "out", "landmark", a.case)
    engine_dir = os.path.join(out_dir, "engine")
    tmp = os.path.join(out_dir, "build"); shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
    base = a.case
    voices = Voices(engine_dir, lcfg)

    # 1. cards (the storyboard's cards + a chapter card for any scene Kaggle could not make)
    card_jobs, card_png, missing = [], {}, []
    for b in st["beats"]:
        png = os.path.join(tmp, f"{b['id']}.png")
        if b["type"] == "card":
            card_jobs.append((b["card"], re.sub(r"\s*\(.*?\)", "", st["case"]), b.get("chapter"), png)); card_png[b["id"]] = png
        elif b["type"] == "scene" and not ai_assemble.clip(engine_dir, b["id"]):
            missing.append(b["id"])
            card_jobs.append(({"style": "chapter", "heading": b.get("chapter") or st["case"], "sub": st["case"]},
                              "", "", png)); card_png[b["id"]] = png
    log(f"cards: {len(card_jobs)} ({len(missing)} in place of missing scenes)")
    render_cards(card_jobs)

    # 2. one or two video segments per beat
    segs, cues, marks, beat_times, t = [], [], [], {}, 0.0
    for i, b in enumerate(st["beats"]):
        start = t
        marks.append((t, b.get("chapter") or ""))
        if b["type"] == "professor":
            clip = ai_assemble.clip(engine_dir, b["id"])
            if not clip:
                log(f"  {b['id']}: no Professor clip, left out"); beat_times[b["id"]] = (t, t); continue
            out = os.path.join(tmp, f"seg{i:03d}.mp4"); seg_professor(clip, out); d = ai_assemble.duration(out); segs.append(out)
            cues.append((b["line"], t + 0.3, t + d - 0.3)); t += d
        else:
            if b["type"] == "scene" and b.get("dialogue") and b["id"] not in missing:
                out = os.path.join(tmp, f"seg{i:03d}a.mp4"); seg_dialogue(ai_assemble.clip(engine_dir, b["id"]), out)
                d = ai_assemble.duration(out)
                segs.append(out); cues.append((b["dialogue"], t + 0.4, t + d - 0.3)); t += d
            if b["type"] == "scene" and b.get("dialogue") and not b.get("narration"):
                beat_times[b["id"]] = (start, t); continue
            wav = os.path.join(tmp, f"nar{i:03d}.wav")
            is_scene = b["type"] == "scene" and b["id"] not in missing and not b.get("dialogue")
            dur, times = voices.beat(b.get("narration", []), wav, min_len=4.5 if is_scene else 3.5)
            out = os.path.join(tmp, f"seg{i:03d}.mp4")
            if is_scene:
                seg_scene(ai_assemble.clip(engine_dir, b["id"]), wav, dur, out, tmp)
            elif b["type"] == "scene" and b.get("dialogue") and b["id"] not in missing:
                seg_still(last_frame(ai_assemble.clip(engine_dir, b["id"]), os.path.join(tmp, f"last{i}.png")),
                          wav, dur, out, fade=False)
            else:
                seg_still(card_png[b["id"]], wav, dur, out, fade=True)
            segs.append(out)
            cues += [(s, t + x, t + y) for s, x, y in times]
            t += ai_assemble.duration(out)
        beat_times[b["id"]] = (start, t)
        log(f"  {b['id']:>8} {b['type']:<9} {t - start:5.1f}s  (total {mmss(t)})")

    # 3. join (the concat filter keeps sound and picture in step), music, loudness
    long_mp4 = os.path.join(out_dir, base + ".mp4")
    inputs, chains = [], []
    for k, sp in enumerate(segs):
        inputs += ["-i", sp]
        chains.append(f"[{k}:v][{k}:a]")
    n = len(segs)
    graph = "".join(chains) + f"concat=n={n}:v=1:a=1[v][j]"
    if lcfg.get("music", True):
        from render import make_music
        mus = os.path.join(tmp, "music.wav"); make_music(mus, t + 2)
        inputs += ["-i", mus]
        graph += (f";[{n}:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.10[m]"
                  f";[j][m]amix=inputs=2:duration=first:normalize=0[mix]")
    else:
        graph += ";[j]anull[mix]"
    graph += ";[mix]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]"
    script = os.path.join(tmp, "join.txt"); open(script, "w").write(graph)
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex_script", script, "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", long_mp4])
    total = ai_assemble.duration(long_mp4)
    log(f"long video: {mmss(total)} -> {os.path.relpath(long_mp4, ROOT)}")
    files = [long_mp4]

    # 4. captions, thumbnails, Shorts
    cap = captions(cues)
    srt = os.path.join(out_dir, base + ".en.srt"); write_srt(cap, srt); files.append(srt)
    title_png = next((card_png[b["id"]] for b in st["beats"] if b["type"] == "card" and b["card"].get("style") == "title"), None)
    thumbs = thumbnails(st, engine_dir, title_png, out_dir, base, tmp); files += thumbs
    shorts = []
    for k, sh in enumerate(st.get("shorts", [])[:3], 1):
        if sh["start"] not in beat_times or sh["end"] not in beat_times:
            continue
        sa, sb = beat_times[sh["start"]][0], beat_times[sh["end"]][1]
        if sb - sa < 15:
            continue
        out = os.path.join(out_dir, f"{base}-short{k}.mp4")
        d = make_short(long_mp4, sa, sb, sh["title"], cap, out, tmp, k)
        shorts.append({"file": out, "title": sh["title"], "duration": d}); files.append(out)
        log(f"Short {k}: {d:.0f}s · {sh['title']}")

    # 5. posting plan
    chaps = chapters(marks, total)
    ch_txt = "\n".join(f"{mmss(c[0])} {c[1]}" for c in chaps)
    facts = " · ".join(x for x in (st.get("citation"), st.get("court"), st.get("bench")) if x)
    desc = (f"{st['summary']}\n\n⚖️ {st['case']}" + (f"\n{facts}" if facts else "")
            + (f"\n📌 Principle: {st['principle']}" if st.get("principle") else "")
            + (f"\n\nChapters:\n{ch_txt}" if ch_txt else "")
            + f"\n\n{DISCLAIMER}\n\n{CREDITS}\n\n#LandmarkCase #LLB #LawStudents #{re.sub(r'[^A-Za-z]', '', st.get('subject', 'Law'))}")
    tags, n = [], 0
    for tg in st.get("tags", []) + ["landmark case", "llb", "law students", "the llb guide"]:
        if tg.lower() not in [x.lower() for x in tags] and n + len(tg) + 2 <= 480:
            tags.append(tg); n += len(tg) + 2
    start = datetime.date.today() + datetime.timedelta(days=1)
    plan = [f"=== {start.strftime('%a %d %b')} {lcfg.get('post_time', '18:00')} | {os.path.basename(long_mp4)} ===",
            "TITLE:", st["title"], "", "DESCRIPTION:", desc, "", "TAGS:", ", ".join(tags), "",
            "PINNED COMMENT:", st.get("pinned_comment", ""), "",
            f"THUMBNAIL: {os.path.basename(thumbs[0]) if thumbs else '-'}"
            + (f"   (also try {os.path.basename(thumbs[1])})" if len(thumbs) > 1 else ""),
            f"SUBTITLES: upload {os.path.basename(srt)} (YouTube Studio → Subtitles → English → Upload file → With timing)",
            "ALTERED OR SYNTHETIC CONTENT (YouTube Studio → Details): YES (realistic AI scenes / AI voice)", "", ""]
    for k, sh in enumerate(shorts, 1):
        day = start + datetime.timedelta(days=k)
        plan += [f"=== {day.strftime('%a %d %b')} 13:00 | {os.path.basename(sh['file'])} ===", "TITLE:",
                 f"{sh['title']} #Shorts", "", "DESCRIPTION:",
                 f"{st['case']}: {st.get('principle', '')}\nFull story on the channel.\n\n{DISCLAIMER}\n\n{CREDITS}\n\n"
                 f"#Shorts #LandmarkCase #LLB", "", "ALTERED OR SYNTHETIC CONTENT: YES", "", ""]
    plan_file = os.path.join(out_dir, f"publish-plan-{base}.txt")
    open(plan_file, "w", encoding="utf-8").write("\n".join(plan)); files.append(plan_file)
    log(f"all made in {(time.time() - t_all) / 60:.1f} min")

    # 6. upload + email
    where, links = "(not uploaded)", {}
    if not a.no_upload:
        stamp = time.strftime("%Y%m%d-%H%M", time.gmtime())
        if deliver.drive_ready():
            where, links = deliver.drive_upload(files, f"{cfg['channel']} - {st['case']}", cfg.get("drive_folder_id") or None)
        else:
            where, links = deliver.release_upload(files, f"landmark-{base}-{stamp}", f"Landmark case: {st['case']}",
                                                  "Your landmark case video. See the email for the posting plan.")
    if not a.no_email:
        e = html.escape
        lk = lambda f: links.get(os.path.basename(f), where)
        warn = ""
        if missing or voices.fallback:
            warn = ("<div style='background:#fff4e5;padding:10px;border-radius:8px'><b>Note:</b> "
                    + (f"{len(missing)} scene(s) were missing from Kaggle and show a chapter card instead "
                       f"({e(', '.join(missing))}). " if missing else "")
                    + (f"{len(voices.fallback)} sentence(s) use the Microsoft voice instead of the Professor's. "
                       if voices.fallback else "") + "</div>")
        rows = "".join(f"<li>📱 <a href='{lk(s['file'])}'>{e(s['title'])}</a> ({s['duration']:.0f}s)</li>" for s in shorts)
        mail.send(cfg, f"[{cfg['channel']}] Landmark case video ready: {st['case']}",
                  f"<h2 style='margin:0'>🎉 {e(st['case'])} is ready</h2>"
                  f"<p>🎬 <a href='{lk(long_mp4)}'><b>Long video</b></a> ({mmss(total)}) · "
                  f"<a href='{lk(thumbs[0]) if thumbs else where}'>thumbnail</a> · <a href='{lk(srt)}'>captions (.srt)</a></p>"
                  f"<ul>{rows}</ul>{warn}"
                  f"<p>Title, description (with chapters, disclaimer and credits), tags and the posting days are in "
                  f"<a href='{lk(plan_file)}'><b>{e(os.path.basename(plan_file))}</b></a>. All files: <a href='{where}'>{e(where)}</a></p>"
                  f"<p>In YouTube Studio set <b>Altered or synthetic content = Yes</b>, and upload the .srt under Subtitles.</p>")
    shutil.rmtree(tmp, ignore_errors=True)
    log("done")


if __name__ == "__main__":
    main()
