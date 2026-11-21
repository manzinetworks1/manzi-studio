"""L2, second step: puts a landmark case video together from the Manzi Engine's results.

python landmark/make.py --case <slug> [--no-upload] [--no-email]

Reads landmark/cases/<slug>/story.json and out/landmark/<slug>/engine/ (scenes, Professor clips, narration
sentences), and makes in out/landmark/<slug>/:
  - the long video (1920x1080): Professor intro -> the story in scenes and cards, narrated in the Professor's voice ->
    Professor outro, with soft music
  - English captions (.srt) to upload with it
  - 2 thumbnails (a scene with big words, and the title card)
  - 2-3 upright Shorts made from the story's beats (full-screen scenes, upright cards, captions, end card)
  - the posting plan (title, description with chapters and credits, tags, pinned comment, AI disclosure)
then uploads everything (Google Drive if set up, otherwise a GitHub Release) and emails you.
Missing pieces never stop the video: a missing scene becomes a chapter card, a missing narration sentence is read by
the Microsoft Indian English voice.
"""
import argparse, datetime, html, json, math, os, re, shutil, subprocess, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "pipeline")); sys.path.insert(0, os.path.join(REPO, "render")); sys.path.insert(0, HERE)
from common import ROOT, config, log, to_pcm, wav_write  # noqa: E402
from voice import speakable, trim, SR  # noqa: E402
import ai_assemble, deliver, mail  # noqa: E402
from cards import render_cards, W, H  # noqa: E402
import motion  # noqa: E402

FPS = 30
LEAD, GAP, TAIL = 0.35, 0.35, 0.5          # seconds of quiet before, between and after narration sentences
XF = 0.4                                   # dissolve between beats (seconds)
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


def kenburns(index, frames, label, z_from=1.0, z_to=1.06, w=W, h=H):
    """A still picture (input `index`) with a slow, smooth zoom towards the centre (drawn at 2x, so it never steps)."""
    return (f"[{index}:v]scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase:flags=lanczos,crop={w * 2}:{h * 2},"
            f"zoompan=z='{z_from}+({z_to}-{z_from})*on/{max(1, frames)}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={max(1, frames)}:s={w}x{h}:fps={FPS},setsar=1,format=yuv420p[{label}]")


def exact_duration(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                capture_output=True, text=True).stdout or 0)


def dissolve_join(paths, tmp, tag, x=XF):
    """Parts -> ffmpeg input args + graph that joins them with short dissolves, labels [cv][ca].
    Each dissolve is made separately as a small clip (the last `x` seconds of one part over the first `x` of the
    next), so the final join only plays the pieces one after another and needs little memory.
    Returns (input args, graph, total seconds)."""
    durs = [exact_duration(p) for p in paths]
    args, n = [], 0
    for k, (p, d) in enumerate(zip(paths, durs)):
        if k:
            mix = os.path.join(tmp, f"{tag}_x{k:03d}.mp4")
            run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{durs[k - 1] - x:.3f}", "-i", paths[k - 1],
                 "-t", f"{x:.3f}", "-i", p, "-filter_complex",
                 f"[0:v]settb=AVTB,fps={FPS},format=yuv420p,setsar=1[a];[1:v]settb=AVTB,fps={FPS},format=yuv420p,setsar=1[b];"
                 f"[a][b]xfade=transition=fade:duration={x:.3f}:offset=0[v];"
                 f"[0:a]aresample=48000,apad=whole_dur={x:.3f}[p];[1:a]aresample=48000,apad=whole_dur={x:.3f}[q];"
                 f"[p][q]acrossfade=d={x - 0.02:.3f}:c1=tri:c2=tri,apad=whole_dur={x:.3f}[s]",
                 "-map", "[v]", "-map", "[s]", "-t", f"{x:.3f}", *V_OUT, mix])
            args += ["-i", mix]; n += 1
        start = x if k else 0.0
        end = d - x if k < len(paths) - 1 else d
        args += ["-ss", f"{start:.3f}", "-t", f"{max(0.05, end - start):.3f}", "-i", p]; n += 1
    graph = "".join(f"[{i}:v][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[cv][ca]"
    return args, graph, sum(durs) - x * (len(paths) - 1), n


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


def seg_still(png, nar_wav, dur, out, fade=False):
    frames = int(round(dur * FPS))
    vf = kenburns(0, frames, "k") + (f";[k]fade=t=in:st=0:d=0.3,fade=t=out:st={max(0, dur - 0.3):.3f}:d=0.3[v]"
                                     if fade else ";[k]null[v]")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", png, "-i", nar_wav, "-filter_complex",
         vf + ";[1:a]aresample=48000,aformat=channel_layouts=stereo,apad[a]",
         "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}", *V_OUT, out])
    return dur


def seg_scene(clip, nar_wav, dur, out, tmp, slow_max=1.3):
    """The scene under its narration. If the narration fits the clip (slowed down up to 1.3x), the clip simply plays.
    If the narration is longer, the clip plays forward, eases to a stop, plays slowly backward, eases to a stop,
    forward again... until the narration ends (passes of about 9 s, never faster than normal speed), so the people
    never stop moving. A slow zoom runs on top. Only the narration is heard."""
    clen = ai_assemble.duration(clip) or 5.0
    zoom = min(0.16, 0.04 + 0.006 * dur)            # longer beats travel further, but stay gentle
    frames = int(round(dur * FPS)) + 2
    zp = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase:flags=lanczos,crop={W * 2}:{H * 2},"
          f"zoompan=z='1+{zoom:.4f}*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},"
          f"setsar=1,format=yuv420p")
    if dur <= clen * slow_max:
        f = max(dur / clen, 1.0)
        inputs = ["-i", clip]
        graph = [f"[0:v]setpts={f:.4f}*PTS,fps={FPS},tpad=stop_mode=clone:stop_duration=0.5,{zp}[v]"]
    else:
        src = os.path.join(tmp, "bounce_src"); seq = os.path.join(tmp, "bounce_seq")
        for d in (src, seq):
            shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
        # the clip's frames at 60 fps (blended in-betweens), so slow playback stays smooth
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-vf",
             f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},framerate=fps=60",
             "-q:v", "2", os.path.join(src, "f%05d.jpg")])
        names = sorted(os.listdir(src)); n = len(names)
        span = n / 60
        passes = max(1, round(dur / 9.0))
        if math.pi / 2 * span / (dur / passes) > 1.0:          # keep the fastest moment at normal speed or slower
            passes = max(1, int(dur / (math.pi / 2 * span)))
        T = dur / passes
        for j in range(frames):
            t = min(j / FPS, dur - 1e-6)
            k = int(t // T); ph = (t - k * T) / T
            if passes == 1:
                pos = t / dur                                  # one slow pass: an even slow motion, no stop
            else:
                e = math.sin(math.pi / 2 * ph) if k == 0 else (1 - math.cos(math.pi * ph)) / 2   # starts already moving
                pos = e if k % 2 == 0 else 1 - e
            os.symlink(os.path.join(src, names[min(n - 1, int(round(pos * (n - 1))))]), os.path.join(seq, f"o{j:05d}.jpg"))
        inputs = ["-framerate", str(FPS), "-i", os.path.join(seq, "o%05d.jpg"), "-i", clip]
        graph = [f"[0:v]{zp}[v]"]
        log(f"    forward/backward: {passes} pass(es) of {T:.1f}s over {dur:.1f}s" if passes > 1
            else f"    slow motion: {span / dur:.2f}x over {dur:.1f}s")
    # only the Professor's narration: the clip's own sound is left out (the AI makes up mumbling in scenes where
    # nobody should speak; a spoken line is shown separately by seg_dialogue with its sound)
    ai = len([x for x in inputs if x == "-i"])          # the narration's input index
    graph.append(f"[{ai}:a]aresample=48000,aformat=channel_layouts=stereo,apad[a]")
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-i", nar_wav, "-filter_complex", ";".join(graph),
         "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}", *V_OUT, out])
    return dur


def seg_card(card, case, chapter, times, nar_wav, dur, out, tmp, tag, portrait=False):
    """A moving card (motion.py) under its narration. Returns the beat's length (a pause is added after the
    narration when the card shows a point the narration never mentions). The upright version for the Shorts
    (portrait=True) gets the same timing and the same sound."""
    js, events, extra = motion.plan(card, times, portrait)
    total = dur + extra
    if not portrait:
        pcm = to_pcm(nar_wav, SR)
        pcm = np.concatenate([pcm, np.zeros(int(round(total * SR)) - len(pcm), np.int16)]) if total * SR > len(pcm) else pcm
        wav_write(nar_wav, motion.add_sounds(pcm, events, SR), SR)
    fdir = os.path.join(tmp, f"frames_{tag}")
    motion.record([(card, case, chapter, times, total, fdir, portrait, js)], FPS)
    w, h = (SW, SH) if portrait else (W, H)
    run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", os.path.join(fdir, "f%05d.jpg"),
         "-i", nar_wav, "-filter_complex",
         f"[0:v]scale={w}:{h},setsar=1,format=yuv420p[v];[1:a]aresample=48000,aformat=channel_layouts=stereo,apad[a]",
         "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}", *V_OUT, out])
    shutil.rmtree(fdir, ignore_errors=True)
    return total


def seg_dialogue(clip, out):
    """A scene with a spoken line: shown at normal speed with its own sound."""
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-filter_complex",
         f"[0:v]{SCALE},fps={FPS},format=yuv420p[v];[0:a]aresample=48000,aformat=channel_layouts=stereo[a]",
         "-map", "[v]", "-map", "[a]", *V_OUT, out])
    return ai_assemble.duration(out)


def spot_who(st, b):
    """Who said a scene's line, by role only (the lines are invented, so never a real person's name):
    b["quote_by"] {"name": "The senior advocate", "role": "for the petitioners"}, else the cast member's label.
    The role always ends in "dramatised"."""
    q = b.get("quote_by") or {}
    c = next((c for c in st.get("cast", []) if c.get("id") == b.get("speaker")), {})
    name = q.get("name") or (c.get("label") or "").strip() or "In court"
    role = " · ".join(x for x in (q.get("role", "").strip(), "dramatised") if x)
    return name[:1].upper() + name[1:], role


def seg_spotlight(clip, wav, dur, times, quote, who, role, keys, out, tmp, tag, portrait=False, bg=None):
    """While the Professor explains a scene where a character spoke: the scene keeps moving (forward/backward),
    blurred and darkened (faded in over 0.6 s), with the line as a quote and key words popping in as he says them
    (motion.spotlight). The landscape call mixes the pop sounds into `wav` and returns its background clip, which the
    upright (Shorts) call re-uses."""
    html, js, events = motion.spotlight(quote, who, role, keys, times, portrait)
    if not portrait:
        wav_write(wav, motion.add_sounds(to_pcm(wav, SR), events, SR), SR)
        bg = os.path.join(tmp, f"spotbg_{tag}.mp4")
        seg_scene(clip, wav, dur, bg, tmp)
    fdir = os.path.join(tmp, f"spot_{tag}")
    motion.record_overlay(html, js, dur, fdir, portrait, FPS)
    fit = f"scale=-2:{SH},crop={SW}:{SH}," if portrait else ""
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", bg, "-framerate", str(FPS), "-i", os.path.join(fdir, "f%05d.png"),
         "-filter_complex",
         f"[0:v]{fit}split[a][b];[b]gblur=sigma=22,eq=brightness=-0.26:saturation=0.75[bl];"
         f"[a][bl]blend=all_expr='A*(1-min(T/0.6,1))+B*min(T/0.6,1)'[bg];"
         f"[bg][1:v]overlay=0:0:format=auto,setsar=1,format=yuv420p[v];[0:a]aresample=48000[a]",
         "-map", "[v]", "-map", "[a]", "-t", f"{dur:.3f}", *V_OUT, out])
    shutil.rmtree(fdir, ignore_errors=True)
    return bg


# ------------------------------------------------------------------ helpers for the outputs
def mmss(s):
    s = int(s); return f"{s // 60}:{s % 60:02d}"


def srt_time(t):
    ms = int(round(t * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


SMALL = {"a", "an", "the", "of", "to", "in", "on", "at", "by", "for", "with", "and", "or", "but", "her", "his",
         "their", "its", "my", "your", "under", "from", "that", "this", "is", "was", "be", "as"}


def split_caption(text, n=30, lines=2):
    """A sentence -> caption chunks of at most `lines` lines of about `n` characters, split where the sentence
    naturally pauses (after , ; : or before and/but/because/so...), never after a small word like "a" or "the",
    and never between "Article" / "Section" and its number."""
    limit = n * lines
    if len(text) <= limit:
        return [text]
    words = text.split()
    glue = lambda w, nxt: (w.lower().strip(",;:") in SMALL or re.fullmatch(r"(Article|Section|Articles|Sections)", w)
                           or (nxt or "x")[:1].isdigit())     # keep "Articles 14, 19 and 21" together
    chunks, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None:
            break
        here = " ".join(cur)
        rest = " ".join(words[i + 1:])
        punct = w[-1] in ",;:.?!"
        conj = (nxt.lower() in ("and", "but", "because", "so", "which", "who", "when", "while")
                and not w.rstrip(",").isdigit())          # "14, 19 and 21" is a list, not a pause
        too_long = len(here) + 1 + len(nxt) > limit
        if glue(w, nxt) and not too_long:
            continue
        if too_long:
            carry = []           # never end a chunk on a small word: move it to the next chunk
            while len(cur) > 1 and (cur[-1].lower().strip(",;:") in SMALL):
                carry.insert(0, cur.pop())
            chunks.append(" ".join(cur)); cur = carry
        elif len(rest) >= 12 and ((punct and len(here) >= n * 0.6) or (conj and len(here) >= n)):
            chunks.append(here); cur = []
    if cur:
        chunks.append(" ".join(cur))
    # short pieces join a neighbour when the two still fit on the screen together
    i = 0
    while i < len(chunks) - 1:
        a, b = chunks[i], chunks[i + 1]
        if min(len(a), len(b)) < 25 and len(a) + len(b) + 1 <= limit + 8:
            chunks[i:i + 2] = [a + " " + b]
        else:
            i += 1
    return chunks


def captions(cues):
    """[(text, start, end)] -> caption cues split by meaning; each cue stays on screen until the next one starts
    (when the pause between them is short), so there are no empty moments."""
    out = []
    for text, a, b in cues:
        text = re.sub(r"\*\*", "", text)
        parts = split_caption(text)
        total = sum(len(p) for p in parts) or 1
        t = a
        for p in parts:
            d = (b - a) * len(p) / total
            out.append([p, t, t + d]); t += d
    out.sort(key=lambda c: c[1])
    for c, nxt in zip(out, out[1:]):
        if 0 < nxt[1] - c[2] < 1.5:
            c[2] = nxt[1]
    return [tuple(c) for c in out]


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
SW, SH = 1080, 1920
SHORT_MAX = 59.0
END_CARD = 2.5


def short_lines(text, n, k=3):
    return wrap(text, n)[:k]


def short_piece(kind, src, seg, d, out):
    """One piece of a Short, upright 1080x1920, `d` seconds, with the sound of its long-video segment `seg`:
    "scene" = centre crop of the segment; "upright" = a ready upright version (moving card, spotlight; own sound);
    "card" = an upright card picture with a slow zoom."""
    if kind == "upright":
        run(["ffmpeg", "-y", "-loglevel", "error", "-t", f"{d:.3f}", "-i", src,
             "-filter_complex", f"[0:v]setsar=1,fps={FPS},format=yuv420p[v];[0:a]aresample=48000[a]",
             "-map", "[v]", "-map", "[a]", "-t", f"{d:.3f}", *V_OUT, out])
    elif kind == "card":
        frames = int(round(d * FPS))
        graph = kenburns(0, frames + 2, "v", 1.0, 1.05, SW, SH)
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-t", f"{d:.3f}", "-i", seg, "-filter_complex", graph,
             "-map", "[v]", "-map", "1:a", "-t", f"{d:.3f}", *V_OUT, out])
    else:
        run(["ffmpeg", "-y", "-loglevel", "error", "-t", f"{d:.3f}", "-i", src,
             "-filter_complex", f"[0:v]scale=-2:{SH}:flags=lanczos,crop={SW}:{SH},setsar=1,fps={FPS},format=yuv420p[v];"
                                f"[0:a]aresample=48000,aformat=channel_layouts=stereo[a]",
             "-map", "[v]", "-map", "[a]", "-t", f"{d:.3f}", *V_OUT, out])
    return d


def stretch_short(st, sh, least=30.0, most=55.0):
    """A Short range whose beats would last under `least` seconds (e.g. a scene and the title card, which a Short
    leaves out) is stretched forward beat by beat, staying under `most` (estimated from the narration)."""
    ids = [b["id"] for b in st["beats"]]
    if sh.get("start") not in ids or sh.get("end") not in ids:
        return sh
    est = lambda b: 0.0 if b["type"] == "professor" or (b["type"] == "card" and b["card"].get("style") == "title") \
        else len(" ".join(b.get("narration", [])).split()) / 2.6 + 0.9 + (5.0 if b.get("dialogue") else 0.0)
    i0, i1 = ids.index(sh["start"]), ids.index(sh["end"])
    total = sum(est(b) for b in st["beats"][i0:i1 + 1])
    while total < least and i1 + 1 < len(ids) and st["beats"][i1 + 1]["type"] != "professor" \
            and total + est(st["beats"][i1 + 1]) <= most:
        i1 += 1; total += est(st["beats"][i1])
    if ids[i1] != sh["end"]:
        log(f"Short '{sh.get('title', '')}': {sh['start']}..{sh['end']} is too short, made {sh['start']}..{ids[i1]}")
    return dict(sh, end=ids[i1])


def make_short(st, sh, beat_times, long_mp4, engine_dir, pcard, cues, out, tmp, k, missing, pvid=None,
               pspot=None, spot_start=None, beat_segs=None):
    """An upright Short made from the beats sh["start"]..sh["end"] of the long video. The title card and the
    Professor are left out (they belong to the long video); it ends on an end card."""
    ids = [b["id"] for b in st["beats"]]
    i0, i1 = ids.index(sh["start"]), ids.index(sh["end"])
    pvid, pspot, spot_start = pvid or {}, pspot or {}, spot_start or {}
    pieces, remap, t = [], [], 0.0
    beat_segs = beat_segs or {}

    def room_for(a, full):
        """How much of a piece (starting at a, `full` seconds) fits: all of it, else up to the end of the last
        whole sentence that fits (never in the middle of the Professor's words), else nothing."""
        room = SHORT_MAX - END_CARD - t
        if full <= room:
            return full
        ends = [cb for _, ca, cb in cues if a < cb and cb + 0.3 - a <= room]
        return (max(ends) + 0.3 - a) if ends and max(ends) + 0.3 - a >= 3.0 else 0.0

    stop = False
    for b in st["beats"][i0:i1 + 1]:
        if stop:
            break
        if b["type"] == "professor" or (b["type"] == "card" and b["card"].get("style") == "title"):
            continue
        # each beat's own segment(s) -- the exact pieces the long video was joined from, with their full sound
        for j, (seg, a) in enumerate(beat_segs.get(b["id"], [])):
            full = exact_duration(seg)
            d = room_for(a, full)
            if d < 1.0:
                stop = True; break
            piece = os.path.join(tmp, f"short{k}_{b['id']}_{j}.mp4")
            if b["id"] in pspot and j == len(beat_segs[b["id"]]) - 1:
                src, kind = pspot[b["id"]], "upright"            # the upright spotlight
            elif b["type"] == "card" and b["id"] in pvid:
                src, kind = pvid[b["id"]], "upright"             # the moving upright card
            elif b["type"] == "card" or b["id"] in missing:
                src, kind = pcard.get(b["id"]), "card"
            else:
                src, kind = seg, "scene"
            short_piece(kind, src, seg, d, piece)
            pieces.append(piece); remap.append((a, a + d, t)); t += d - XF
            if d < full - 0.05:
                stop = True; break                                # shortened to fit: the Short ends here
    if not pieces:
        return None, 0
    endp = os.path.join(tmp, f"short{k}_end.mp4")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", pcard["__end__"], "-f", "lavfi", "-i",
         "anullsrc=r=48000:cl=stereo", "-filter_complex",
         kenburns(0, int(END_CARD * FPS) + 2, "v", 1.0, 1.04, SW, SH),
         "-map", "[v]", "-map", "1:a", "-t", f"{END_CARD}", *V_OUT, endp])
    pieces.append(endp); total = t + END_CARD

    # title at the top (one drawtext per line, no line breaks inside the text) + captions near the bottom
    title = re.sub(r"\b\d+\s*sec(ond)?s?\b", f"{int(round(t / 5.0) * 5)} seconds", sh["title"], flags=re.I)
    draws = []
    for j, line in enumerate(short_lines(title.upper(), 22, 3)):
        f = drawtext_file(tmp, f"short{k}_t{j}.txt", line)
        draws.append(f"drawtext=fontfile='{FONT}':textfile='{f}':fontsize=64:fontcolor=white:box=1:"
                     f"boxcolor=0x0e1a2b@0.85:boxborderw=20:x=(w-text_w)/2:y={170 + j * 100}:enable='lt(t,{t:.2f})'")
    n = 0
    for text, ca, cb in cues:
        for a, e, off in remap:
            if cb <= a or ca >= e:
                continue
            s0, s1 = max(ca, a) - a + off, min(cb, e) - a + off
            if cb >= e - 0.01:
                s1 -= XF        # the next piece dissolves in over the last XF seconds: hand over to its caption
            if s1 - s0 < 0.6 and not (ca >= a and cb <= e):
                continue        # only the tail of a caption from a beat that is left out: skip it
            for j, line in enumerate(short_lines(text, 28, 3)):
                f = drawtext_file(tmp, f"short{k}_c{n}_{j}.txt", line)
                draws.append(f"drawtext=fontfile='{FONT}':textfile='{f}':fontsize=58:fontcolor=white:borderw=6:"
                             f"bordercolor=black:x=(w-text_w)/2:y={1400 + j * 78}:enable='between(t,{s0:.2f},{s1:.2f})'")
            n += 1
    inputs, graph, total, _ = dissolve_join(pieces, tmp, f"short{k}")
    graph += ";[cv]" + (",".join(draws) if draws else "null") + "[v]"
    music = os.path.join(tmp, f"short{k}_music.wav")
    from render import make_music
    make_music(music, total + 1)
    m = len([x for x in inputs if x == "-i"])
    inputs += ["-i", music]
    graph += (f";[{m}:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.10[m]"
              f";[ca]aresample=48000,aformat=channel_layouts=stereo[c0];[c0][m]amix=inputs=2:duration=first:normalize=0[cm]"
              f";[cm]afade=t=out:st={max(0, total - END_CARD - 0.6):.2f}:d=0.6,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]")
    script = os.path.join(tmp, f"short{k}.txt"); open(script, "w", encoding="utf-8").write(graph)
    run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex_script", script, "-map", "[v]", "-map", "[a]",
         *V_OUT, "-movflags", "+faststart", out])
    return title, ai_assemble.duration(out)


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
    # every sentence must be in the Professor's voice: stop (and say which) rather than use the Microsoft voice
    missing_voice = [x for b in st["beats"] for x in b.get("narration", []) if speakable(x) not in voices.premade]
    if missing_voice and not lcfg.get("allow_fallback_voice", False):
        items = "".join(f"<li>{html.escape(x)}</li>" for x in missing_voice)
        log(f"stopped: {len(missing_voice)} sentence(s) have no Professor voice:\n  " + "\n  ".join(missing_voice))
        if not a.no_email:
            mail.send(cfg, f"[Manzi Studio] {st['case']}: {len(missing_voice)} sentence(s) missing the Professor's voice",
                      f"<p>The video was <b>not</b> made, so the Microsoft voice is never used. These sentences have no "
                      f"recording in the Professor's voice from Kaggle:</p><ol>{items}</ol>"
                      f"<p>Send Claude this email: the sentences can be voiced again on Kaggle (a few minutes of GPU).</p>")
        raise SystemExit(1)

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
    pcard = {}
    for job in list(card_jobs):
        bid = os.path.basename(job[3])[:-4]
        pcard[bid] = os.path.join(tmp, f"{bid}_short.png")
        card_jobs.append((*job[:3], pcard[bid], True))
    pcard["__end__"] = os.path.join(tmp, "end_short.png")
    short_case = re.sub(r"\s*\(.*?\)", "", st["case"])
    card_jobs.append(({"style": "chapter", "heading": "Watch the full case", "sub": f"{short_case} · on the channel"},
                      "", "", pcard["__end__"], True))
    log(f"cards: {len(card_jobs)} ({len(missing)} in place of missing scenes, upright versions for the Shorts)")
    render_cards(card_jobs)

    # 2. one or two video segments per beat
    ids = [b["id"] for b in st["beats"]]
    st["shorts"] = [stretch_short(st, sh) for sh in st.get("shorts", [])]
    in_shorts = {x for sh in st.get("shorts", [])[:3] if sh.get("start") in ids and sh.get("end") in ids
                 for x in ids[ids.index(sh["start"]):ids.index(sh["end"]) + 1]}
    pvid = {}                                   # moving upright cards for the Shorts
    pspot, spot_start = {}, {}                  # upright spotlight parts of speaking scenes, and where they start
    segs, cues, marks, beat_times, t = [], [], [], {}, 0.0
    beat_segs = {}                              # beat id -> [(segment file, its start in the timeline)]
    for i, b in enumerate(st["beats"]):
        start = t
        beat_segs[b["id"]] = []
        marks.append((t, b.get("chapter") or ""))
        if b["type"] == "professor":
            clip = ai_assemble.clip(engine_dir, b["id"])
            if not clip:
                log(f"  {b['id']}: no Professor clip, left out"); beat_times[b["id"]] = (t, t); continue
            out = os.path.join(tmp, f"seg{i:03d}.mp4"); seg_professor(clip, out); d = exact_duration(out); segs.append(out)
            beat_segs[b["id"]].append((out, t))
            cues.append((b["line"], t + 0.3, t + d - 0.3)); t += d - XF
        else:
            if b["type"] == "scene" and b.get("dialogue") and b["id"] not in missing:
                out = os.path.join(tmp, f"seg{i:03d}a.mp4"); seg_dialogue(ai_assemble.clip(engine_dir, b["id"]), out)
                d = exact_duration(out)
                segs.append(out); beat_segs[b["id"]].append((out, t))
                cues.append((b["dialogue"], t + 0.4, t + d - 0.3)); t += d - XF
            if b["type"] == "scene" and b.get("dialogue") and not b.get("narration"):
                beat_times[b["id"]] = (start, t); continue
            wav = os.path.join(tmp, f"nar{i:03d}.wav")
            is_scene = b["type"] == "scene" and b["id"] not in missing and not b.get("dialogue")
            dur, times = voices.beat(b.get("narration", []), wav, min_len=4.5 if is_scene else 3.5)
            out = os.path.join(tmp, f"seg{i:03d}.mp4")
            if is_scene:
                seg_scene(ai_assemble.clip(engine_dir, b["id"]), wav, dur, out, tmp)
            elif b["type"] == "scene" and b.get("dialogue") and b["id"] not in missing:
                who, role = spot_who(st, b)
                spot_start[b["id"]] = t
                bgv = seg_spotlight(ai_assemble.clip(engine_dir, b["id"]), wav, dur, times, b["dialogue"], who, role,
                                    b.get("keywords") or [], out, tmp, b["id"])
                if b["id"] in in_shorts:
                    pspot[b["id"]] = os.path.join(tmp, f"{b['id']}_spot_short.mp4")
                    seg_spotlight(None, wav, dur, times, b["dialogue"], who, role, b.get("keywords") or [],
                                  pspot[b["id"]], tmp, b["id"] + "_p", portrait=True, bg=bgv)
                log(f"    spotlight: quote + {len(b.get('keywords') or [])} key words")
            elif b["type"] == "card":
                case_name = re.sub(r"\s*\(.*?\)", "", st["case"])
                d_long = seg_card(b["card"], case_name, b.get("chapter"), times, wav, dur, out, tmp, b["id"])
                if b["id"] in in_shorts:
                    pvid[b["id"]] = os.path.join(tmp, f"{b['id']}_short.mp4")
                    seg_card(b["card"], case_name, b.get("chapter"), times, wav, dur, pvid[b["id"]], tmp,
                             b["id"] + "_p", portrait=True)
                log(f"    moving card: {d_long - dur:+.1f}s pause for points the narration does not read" if d_long > dur
                    else "    moving card")
            else:
                seg_still(card_png[b["id"]], wav, dur, out)
            segs.append(out); beat_segs[b["id"]].append((out, t))
            cues += [(s, t + x, t + y) for s, x, y in times]
            t += exact_duration(out) - XF
        beat_times[b["id"]] = (start, t)
        log(f"  {b['id']:>8} {b['type']:<9} {t - start:5.1f}s  (total {mmss(t)})")

    # 3. join (the concat filter keeps sound and picture in step), music, loudness
    long_mp4 = os.path.join(out_dir, base + ".mp4")
    inputs, graph, _, n = dissolve_join(segs, tmp, "long")
    graph += ";[cv]null[v];[ca]anull[j]"
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
        title, d = make_short(st, sh, beat_times, long_mp4, engine_dir, pcard, cap, out, tmp, k, missing, pvid,
                                  pspot, spot_start, beat_segs)
        if not title:
            continue
        shorts.append({"file": out, "title": title, "duration": d}); files.append(out)
        log(f"Short {k}: {d:.0f}s · {title}")

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
