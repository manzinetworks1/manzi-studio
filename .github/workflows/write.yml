"""Step 1 of the week (runs Sunday night): pick topics, let Gemini write the topic packs, email them for approval.

python pipeline/write.py [--topics N] [--no-email] [--no-git]
"""
import argparse, csv, datetime, hashlib, io, json, os, re, subprocess, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, config, secret, http_json, log
import mail

GEMINI = os.environ.get("GEMINI_URL", "https://generativelanguage.googleapis.com/v1beta")
STATE = os.path.join(ROOT, "state.json")


# ------------------------------------------------------------------ topics
def load_topics(cfg):
    url = cfg.get("topics_csv_url", "").strip()
    if url:
        with urllib.request.urlopen(url, timeout=60) as r: text = r.read().decode("utf-8-sig")
    else:
        text = open(os.path.join(ROOT, "topics.csv"), encoding="utf-8-sig").read()
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
        if r.get("question") and r.get("status", "").lower() not in ("done", "skip"): rows.append(r)
    return rows


def qid(q): return hashlib.sha1(re.sub(r"\W+", " ", q.lower()).strip().encode()).hexdigest()[:10]


def state():
    try: return json.load(open(STATE, encoding="utf-8"))
    except (OSError, ValueError): return {"used": [], "qnum": 0}


# ------------------------------------------------------------------ Gemini
def pick_models(key, cfg):
    """Gemini models to try, best first: newest version first, Pro before Flash. If one is unavailable or over the free
    limit, the next one is used automatically."""
    if cfg.get("gemini_model"): return [cfg["gemini_model"]]
    data = http_json(f"{GEMINI}/models?pageSize=1000", headers={"x-goog-api-key": key})
    names = [m["name"].split("/")[-1] for m in data.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])
             and "gemini" in m["name"] and not re.search(r"image|tts|live|audio|embed|native|exp|computer|robot|lite|nano|learn", m["name"])]
    def rank(n):
        v = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        return (float(v.group(1)) if v else 0, "pro" in n, "latest" not in n)
    names.sort(key=rank, reverse=True)
    if not names: raise SystemExit("No Gemini model available for this key.")
    return names[:8]


S = lambda **p: {"type": "OBJECT", "properties": p, "required": list(p)}
STR, INT = {"type": "STRING"}, {"type": "INTEGER"}
ARR = lambda x: {"type": "ARRAY", "items": x}
SCHEMA = S(
    topic=STR,
    long=S(sections=ARR({"type": "OBJECT", "properties": {"heading": STR, "kind": {"type": "STRING", "enum": ["paras", "points", "cases"]},
                                                           "paras": ARR(STR), "points": ARR(S(title=STR, text=STR)), "cases": ARR(S(name=STR, text=STR)),
                                                           "tip": STR}, "required": ["heading", "kind"]})),
    shorts=S(
        myth=S(myth=STR, law=STR, source=STR, source_say=STR, thumb=STR),
        quiz=S(question=STR, options=ARR(STR), answer=INT, explain=STR, thumb=STR),
        case=S(name=STR, facts=STR, issue=STR, held=STR, principle=STR, thumb=STR),
        compare={"type": "OBJECT", "nullable": True, "properties": {"title": STR, "title_say": STR, "left": S(name=STR, sub=STR), "right": S(name=STR, sub=STR),
                                                                    "rows": ARR(S(label=STR, left=STR, right=STR, say=STR)), "thumb": STR}},
        flow={"type": "OBJECT", "nullable": True, "properties": {"title": STR, "steps": ARR(S(title=STR, sub=STR, say=STR)), "thumb": STR}},
        datadrop_thumb=STR),
    check=ARR(STR))

PROMPT = """You are an expert Indian law teacher who writes exam answers for LLB students, and a YouTube Shorts editor.
Write a TOPIC PACK for this exam question. It is turned automatically into one long video and several Shorts, so follow the format exactly.

Question: {question}
Subject: {subject}
Course: {course}
Marks: {marks}
Language: {language_rule}

THE LONG VIDEO (the exam answer):
- 4 to 6 sections in exam order, for example: Introduction, Meaning / Definition, the main points (essentials, grounds, powers, kinds...), Case Law, Conclusion.
- kind "paras": 1-2 paragraphs, each at most 70 words.
- kind "points": the heart of the answer: 3-7 points; "title" is 2-6 words; "text" explains it in at most 45 words.
- kind "cases": 1-3 REAL leading cases, name with year, e.g. "Maneka Gandhi v. Union of India (1978)"; "text" = what the court held, at most 50 words.
- Put 1-3 key terms of every paragraph/point/case in **double asterisks** (they get highlighted).
- Add a short "tip" (exam-writing advice, at most 25 words) to ONE section, usually the points section.
- 450-700 words in total. Simple, clear English for Indian students.

THE SHORTS (each must make sense on its own, without the long video):
- myth: a common wrong belief connected to this topic, and the correct law ("law", at most 30 words, with **bold** key words) and its source (Act + section).
- quiz: one question on this topic with exactly 4 options and the index (0-3) of the right one; "explain" at most 30 words.
- case: ONE landmark case on this topic: facts, issue, held, principle (each at most 30 words, a few **bold** words in held and principle).
- compare: ONLY if there is a real "old vs new" or "X vs Y" comparison for this topic (e.g. IPC vs BNS sections, libel vs slander). 2-4 rows; "say" is one natural spoken sentence per row. Otherwise null.
- flow: ONLY if the topic is a procedure with steps (3-6 steps). Otherwise null.
- "thumb" fields: a 3-7 word thumbnail headline (curiosity, no clickbait lies). "datadrop_thumb" likewise for the topic.
- "topic": the topic in 3-7 words, topic-first, for the YouTube title (e.g. "Judicial Review of Discretionary Powers").

ACCURACY RULES (very important, this is law):
- Criminal law: use the new laws (Bharatiya Nyaya Sanhita, 2023; Bharatiya Nagarik Suraksha Sanhita, 2023; Bharatiya Sakshya Adhiniyam, 2023) and give the old IPC / CrPC / Evidence Act section in brackets.
- Only real cases, real years and real section numbers. If you are not sure of a detail, leave it out rather than guess.
- List in "check" every fact a teacher should double-check before publishing (section numbers, case years, holdings you are less sure about). Can be empty.
"""


def gemini_pack(key, models, row, cfg):
    lang = (row.get("language") or cfg.get("language", "english")).lower()
    rule = ("Hindi: write all text in simple Hindi (Devanagari). Keep case names, Act names and section numbers in English letters."
            if lang == "hindi" else "English (Indian English, simple words).")
    body = {"contents": [{"parts": [{"text": PROMPT.format(question=row["question"], subject=row.get("subject") or cfg.get("subject", ""),
                                                            course=cfg.get("course", "LLB"), marks=row.get("marks") or "not given", language_rule=rule)}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": SCHEMA, "temperature": 0.3}}
    errors = []
    while models:
        model = models[0]
        try:
            for k in range(3):
                res = http_json(f"{GEMINI}/models/{model}:generateContent", body, {"x-goog-api-key": key}, timeout=600, tries=2)
                try:
                    txt = "".join(p.get("text", "") for p in res["candidates"][0]["content"]["parts"])
                    pack = json.loads(txt); validate(pack); log(f"  written by {model}"); return pack, lang
                except Exception as e:
                    log(f"  {model}: answer not usable ({e}), asking again…")
            raise RuntimeError("no usable answer after 3 tries")
        except RuntimeError as e:
            msg = str(e); errors.append(f"{model}: {msg[:160]}")
            log(f"  {model} can't be used ({msg[:160]}), trying the next model…")
            models.pop(0)          # this model is unavailable / over its free limit / not giving usable answers
    raise RuntimeError("No Gemini model could write the topic pack:\n" + "\n".join(errors))


def validate(p):
    assert p.get("topic") and p["long"]["sections"], "empty pack"
    for s in p["long"]["sections"]:
        if s["kind"] == "points": assert s.get("points"), "points section without points"
        if s["kind"] == "cases": assert s.get("cases"), "cases section without cases"
        if s["kind"] == "paras": assert s.get("paras"), "paras section without paragraphs"
    q = p["shorts"]["quiz"]; assert len(q["options"]) == 4 and 0 <= int(q["answer"]) <= 3, "quiz needs 4 options"


def to_pack(raw, row, lang, cfg, qnum):
    """Gemini's answer -> the pack format used by specs.py."""
    secs = []
    for s in raw["long"]["sections"]:
        d = {"heading": s["heading"]}
        if s["kind"] == "points": d["points"] = s["points"]
        elif s["kind"] == "cases": d["cases"] = s["cases"]
        else: d["paras"] = s.get("paras", [])
        if s.get("tip"): d["tip"] = s["tip"]
        secs.append(d)
    hits = [y for y in re.findall(r"(?:19|20)\d\d", row.get("asked_years", ""))]
    sh = dict(raw["shorts"]); sh["datadrop"] = {"thumb": sh.pop("datadrop_thumb", raw["topic"])}
    if not sh.get("compare"): sh.pop("compare", None)
    if not sh.get("flow"): sh.pop("flow", None)
    last = max([int(y) for y in hits] + [datetime.date.today().year - 1]) if hits else None
    return {"language": lang, "qnum": qnum, "course": cfg.get("course", "LLB"), "subject": row.get("subject") or cfg.get("subject", ""),
            "topic": raw["topic"], "question": row["question"].rstrip(), "marks": row.get("marks", ""), "asked_years": hits,
            "years_range": [str(y) for y in range(last - 5, last + 1)] if hits else [], "long": {"sections": secs}, "shorts": sh,
            "check": raw.get("check", []), "approved": False}


# ------------------------------------------------------------------ approval email
def approval_email(cfg, week, packs, files):
    repo = os.environ.get("GITHUB_REPOSITORY", "your-name/manzi-studio"); gh = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    run_url = f"{gh}/{repo}/actions/workflows/make.yml"
    esc = lambda s: re.sub(r"\*\*(.+?)\*\*", r"<b style='background:#fff2a8'>\1</b>", (s or "").replace("&", "&amp;").replace("<", "&lt;"))
    parts = [f"<h2 style='margin:0'>?? {len(packs)} topic{'s' if len(packs) > 1 else ''} ready for your check</h2>",
             f"<p>Week of {week}. Read the scripts below. If something is wrong, tap <b>Fix</b> under that topic, correct the text and Commit. "
             f"When everything is right, tap the button and then <b>Run workflow</b>.</p>",
             f"<p><a href='{run_url}' style='background:#1f8a3b;color:#fff;padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:bold'>? Approve and make the videos</a></p>"]
    for p, f in zip(packs, files):
        parts.append(f"<hr><h3>Q{p['qnum']}. {esc(p['question'])}</h3><p>{esc(p['subject'])} · {esc(p.get('marks') or '')} marks"
                     f"{' · asked ' + ', '.join(p['asked_years']) if p['asked_years'] else ''}</p>"
                     f"<p><a href='{gh}/{repo}/edit/main/{f}'>?? Fix this topic</a></p>")
        if p.get("check"):
            parts.append("<div style='background:#fdecea;padding:10px;border-radius:8px'><b>?? Please double-check:</b><ul>" + "".join(f"<li>{esc(c)}</li>" for c in p["check"]) + "</ul></div>")
        for s in p["long"]["sections"]:
            parts.append(f"<h4 style='margin-bottom:4px'>{esc(s['heading'])}</h4>")
            for x in s.get("paras", []): parts.append(f"<p>{esc(x)}</p>")
            if s.get("points"): parts.append("<ol>" + "".join(f"<li><b>{esc(x['title'])}</b>: {esc(x['text'])}</li>" for x in s["points"]) + "</ol>")
            for c in s.get("cases", []): parts.append(f"<p>?? <i>{esc(c['name'])}</i>: {esc(c['text'])}</p>")
            if s.get("tip"): parts.append(f"<p>?? Tip: {esc(s['tip'])}</p>")
        sh = p["shorts"]; parts.append("<h4>Shorts</h4><ul>")
        if sh.get("myth"): parts.append(f"<li><b>Myth:</b> {esc(sh['myth']['myth'])} ? <b>Law:</b> {esc(sh['myth']['law'])} ({esc(sh['myth']['source'])})</li>")
        if sh.get("quiz"): q = sh["quiz"]; parts.append(f"<li><b>Quiz:</b> {esc(q['question'])} ? <b>{esc(q['options'][int(q['answer'])])}</b>. {esc(q['explain'])}</li>")
        if sh.get("case"): c = sh["case"]; parts.append(f"<li><b>Case:</b> {esc(c['name'])}: {esc(c['held'])}</li>")
        if sh.get("compare"): parts.append(f"<li><b>Compare:</b> {esc(sh['compare']['title'])}: " + "; ".join(f"{esc(r['label'])}: {esc(r['left'])} ? {esc(r['right'])}" for r in sh['compare']['rows']) + "</li>")
        if sh.get("flow"): parts.append(f"<li><b>Steps:</b> " + " ? ".join(esc(s['title']) for s in sh['flow']['steps']) + "</li>")
        parts.append("</ul>")
    parts.append(f"<p><a href='{run_url}'>? Approve and make the videos</a></p>")
    mail.send(cfg, f"[{cfg['channel']}] Check this week's scripts ({week})", "\n".join(parts))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--topics", type=int); ap.add_argument("--no-email", action="store_true"); ap.add_argument("--no-git", action="store_true")
    a = ap.parse_args(); cfg = config(); st = state()
    n = a.topics or int(cfg.get("topics_per_week", 2))
    todo = [r for r in load_topics(cfg) if qid(r["question"]) not in st["used"]][:n]
    if not todo: mail.send(cfg, f"[{cfg['channel']}] Topic list is empty", "<p>All topics in your list are done. Add new rows to your topic list.</p>") if not a.no_email else None; log("no topics left"); return
    key = secret("GEMINI_API_KEY"); models = pick_models(key, cfg); log("Gemini models to try:", ", ".join(models))
    week = datetime.date.today().isoformat(); wdir = os.path.join(ROOT, "weeks", week); os.makedirs(wdir, exist_ok=True)
    packs, files = [], []
    for i, row in enumerate(todo, 1):
        log(f"writing topic {i}: {row['question'][:70]}")
        raw, lang = gemini_pack(key, models, row, cfg)
        st["qnum"] = st.get("qnum", 0) + 1
        pack = to_pack(raw, row, lang, cfg, row.get("qnum") or st["qnum"])
        f = f"weeks/{week}/q{i}.json"; json.dump(pack, open(os.path.join(ROOT, f), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        packs.append(pack); files.append(f); st["used"].append(qid(row["question"]))
    json.dump(st, open(STATE, "w"), indent=1)
    if not a.no_git:
        subprocess.run(["git", "add", "weeks", "state.json"], cwd=ROOT, check=True)
        subprocess.run(["git", "commit", "-m", f"Scripts for week {week}"], cwd=ROOT, check=True)
        subprocess.run(["git", "push"], cwd=ROOT, check=True)
    if not a.no_email: approval_email(cfg, week, packs, files)
    log("done:", files)


if __name__ == "__main__":
    main()
