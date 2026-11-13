"""Titles, descriptions with chapters, tags, pinned comments and the posting plan."""
import json, re, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from specs import plain

SUGGEST = "https://suggestqueries.google.com/complete/search"


def mmss(s): s = int(s); return f"{s // 60}:{s % 60:02d}"


def chapters(spec):
    out = []; last = None
    for b in spec["beats"]:
        k = b["k"]
        if k == "cover": label = "Question"
        elif k == "end": label = "Free notes & next steps"
        elif k == "tip": continue
        else: label = b.get("section") or ("Case Law" if k == "case" else None)
        if label and label != last: out.append([b["t0"], label]); last = label
    clean = []
    for c in out:
        if clean and c[0] - clean[-1][0] < 10:
            if len(clean) == 1: clean[-1][1] += " & " + c[1]
            continue
        clean.append(c)
    if clean: clean[0][0] = 0
    return clean if len(clean) >= 3 else []


def yt_suggest(q, hl):
    url = SUGGEST + "?" + urllib.parse.urlencode({"client": "firefox", "ds": "yt", "hl": hl, "gl": "IN", "q": q})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=10) as r:
            d = json.loads(r.read().decode("utf-8", "replace")); return [str(x) for x in d[1]]
    except Exception:
        return []


def tags(pack, extra=()):
    subj = (pack.get("subject") or "").lower(); topic = plain(pack.get("topic", "")).lower(); course = (pack.get("course") or "").lower()
    m = re.search(r"(\d+)", course); sem = m.group(1) if m else ""; ordn = {"1": "1st", "2": "2nd", "3": "3rd"}.get(sem, f"{sem}th") if sem else ""
    kw = set(w for w in re.findall(r"[a-z]+", topic + " " + subj) if len(w) > 3)
    seeds = [topic, f"{topic} llb", subj, f"{subj} llb", f"llb {ordn} semester important questions" if ordn else "llb important questions"] + list(extra)
    with ThreadPoolExecutor(6) as ex: res = list(ex.map(lambda s: yt_suggest(s, "hi" if pack.get("language") == "hindi" else "en"), [s for s in seeds if s]))
    score = {}
    for sugg in res:
        for r, s in enumerate(sugg):
            s = s.lower().strip(); ws = s.split()
            if len(s) > 60 or len(ws) != len(set(ws)) or not (set(ws) & (kw | {"llb", "law"})): continue
            score[s] = score.get(s, 0) + (10 - r) * 0.1 + len(set(ws) & kw)
    base = [topic, f"{topic} llb", subj, f"{subj} notes", "llb", f"llb {ordn} semester" if ordn else "", "llb important questions", "law notes", "law exam preparation"]
    for i, b in enumerate(base):
        if b: score[b] = score.get(b, 0) + 20 - i
    out, n = [], 0
    for t in sorted(score, key=lambda x: -score[x]):
        if n + len(t) + 2 > 480: continue
        out.append(t); n += len(t) + 2
    return out


def hashtags(pack):
    subj = re.sub(r"[^A-Za-z0-9]", "", pack.get("subject", "")); course = re.sub(r"[^A-Za-z0-9]", "", pack.get("course", ""))
    return " ".join(x for x in ["#LLB", f"#{subj}" if subj else "", f"#{course}" if course else "", "#LawStudents", "#LawNotes"] if x)


def long_meta(pack, spec, channel):
    t = plain(pack["topic"]); subj = pack.get("subject", ""); course = pack.get("course", "")
    title = f"{t} | {subj} | {course} Important Question" if subj else f"{t} | {course} Important Question"
    if len(title) > 100: title = f"{t} | {course} Important Question"[:100]
    ch = chapters(spec)
    desc = [pack["question"], "", f"Exam-ready answer for {course}{' - ' + subj if subj else ''}: the main points, case law and how to write it in the exam.",
            "", "📌 Free notes PDF: comment NOTES and I'll share the link.", ""]
    if ch: desc += ["Chapters:"] + [f"{mmss(a)} {l}" for a, l in ch] + [""]
    desc += [f"Subscribe to {channel} for a new important question every week.", "", hashtags(pack)]
    pin = (f"📌 Want the FREE notes PDF of this answer? Comment \"NOTES\" below 📄\n\n✍️ Exam tip: write each point as a heading and add one case under it.\n\n"
           f"👇 Which question should I cover next?")
    return {"title": title, "description": "\n".join(desc), "pinned_comment": pin}


SHORT_TITLE = {"datadrop": "{thumb} 🔥 Asked {n}× in Exams", "myth": "{thumb} ❌ Myth vs Law", "quiz": "{thumb} 🤔 Law Quiz",
               "case": "{thumb} ⚖️ Landmark Case", "compare": "{thumb} ⚖️ Old vs New Law", "flow": "{thumb} ⚖️ Step by Step"}
SHORT_PIN = {"datadrop": "📌 Save this for your exam! Which other question keeps coming in your exams? 👇",
             "myth": "Did you believe this myth before? Reply YES or NO 👇\n📄 Full answer + notes on the channel.",
             "quiz": "Write your answer: A, B, C or D 👇 No cheating! 😄",
             "case": "📌 Save this case for your exam. Which landmark case should I explain next? 👇",
             "compare": "📌 Save this. Which IPC → BNS section should I cover next? 👇",
             "flow": "📌 Save this for revision. Which procedure should I explain next? 👇"}


def short_meta(pack, spec, channel):
    tm = spec["template"]; thumb = plain(spec["meta"].get("thumbTitle") or pack["topic"]).rstrip("?.!")
    title = SHORT_TITLE[tm].format(thumb=thumb, n=len(pack.get("asked_years", []))) + " #shorts"
    desc = [plain(pack["question"]) if tm == "datadrop" else thumb, "", f"Full answer: watch the long video on {channel}.", "", hashtags(pack) + " #shorts"]
    return {"title": title[:100], "description": "\n".join(desc), "pinned_comment": SHORT_PIN[tm]}
