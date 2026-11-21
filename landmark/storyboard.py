"""L1: Gemini writes the storyboard of one landmark case, and you get it by email to check and approve.

python landmark/storyboard.py [--case "Maneka Gandhi"] [--no-email] [--no-git]

Picks the first case in landmark/cases.csv that has no folder in landmark/cases/ yet (status "skip"/"done" are left
out), or the case you name. Writes landmark/cases/<slug>/story.json and emails the storyboard with a Fix link and an
Approve link ("L2 - Make landmark video").
"""
import argparse, csv, html, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pipeline"))
from common import ROOT, config, secret, http_json, log, slug  # noqa: E402
import mail  # noqa: E402
from write import pick_models, GEMINI  # noqa: E402  (the weekly writer's Gemini model picker)

CASES_CSV = os.path.join(HERE, "cases.csv")
CASES_DIR = os.path.join(HERE, "cases")
SETTINGS = os.path.join(HERE, "settings.json")


def settings():
    return json.load(open(SETTINGS, encoding="utf-8"))


def case_slug(row):
    name = re.sub(r"\(.*?\)", "", row["case"])
    name = re.sub(r"\b(v|vs)\.?\s", "v ", name, flags=re.I)
    return slug(f"{name} {row.get('year', '')}", 60)


def load_cases():
    rows = []
    with open(CASES_CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
            if r.get("case"):
                rows.append(r)
    return rows


def pick_case(want=None):
    rows = load_cases()
    if want:
        hits = [r for r in rows if want.lower() in r["case"].lower() or want.lower() == case_slug(r)]
        if not hits:
            raise SystemExit(f"No case matching {want!r} in landmark/cases.csv")
        return hits[0]
    for r in rows:
        if r.get("status", "").lower() in ("skip", "done"):
            continue
        if not os.path.exists(os.path.join(CASES_DIR, case_slug(r), "story.json")):
            return r
    return None


# ------------------------------------------------------------------ Gemini
S = lambda **p: {"type": "OBJECT", "properties": p, "required": list(p)}
STR, INT, BOOL = {"type": "STRING"}, {"type": "INTEGER"}, {"type": "BOOLEAN"}
ARR = lambda x: {"type": "ARRAY", "items": x}
CARD_STYLES = ["title", "law", "quote", "triangle", "timeline", "holding", "exam"]
SCHEMA = S(
    case_name=STR, citation=STR, year=INT, court=STR, bench=STR, subject=STR, topic=STR, principle=STR,
    look=STR,
    cast=ARR(S(id=STR, label=STR, look=STR)),
    beats=ARR({"type": "OBJECT",
               "properties": {"type": {"type": "STRING", "enum": ["scene", "card"]}, "id": STR, "chapter": STR,
                              "scene": STR, "cast": ARR(STR), "speaker": STR, "dialogue": STR, "sound": STR,
                              "quote_by": S(name=STR, role=STR), "keywords": ARR(S(show=STR, say=STR)),
                              "continue": BOOL,
                              "card": {"type": "OBJECT", "nullable": True,
                                       "properties": {"style": {"type": "STRING", "enum": CARD_STYLES}, "heading": STR,
                                                      "sub": STR, "items": ARR(S(label=STR, text=STR)),
                                                      "prop": STR,
                                                      "stamps": ARR(S(text=STR, at=STR, color=STR))},
                                       "required": ["style", "heading", "items"]},
                              "narration": ARR(STR)},
               "required": ["type", "id", "chapter", "narration"]}),
    professor_intro=STR, professor_outro=STR,
    thumbnail=S(scene=STR, text=STR),
    shorts=ARR(S(title=STR, start=STR, end=STR)),
    title=STR, summary=STR, tags=ARR(STR), pinned_comment=STR,
    check=ARR(STR))

PROMPT = """You are an Indian law professor and a documentary film writer. Write the STORYBOARD of a YouTube video that
explains one landmark case to LLB students as a continuous story, told in short realistic AI video scenes.

Case: {case} ({year})
What it is famous for: {topic}
Subject: {subject}
Video length: about {minutes} minutes in total, so {words_lo}-{words_hi} words of narration altogether.

HOW THE VIDEO WORKS
- An unseen narrator (the channel's Professor, a warm, clear Indian English teacher) tells the story. His narration is
  written in "narration": 1-4 sentences per beat, each sentence at most 24 words, simple spoken English, no lists, no
  brackets, no abbreviations except "v." in case names. Write Article / Section numbers in full ("Article 21",
  "Section 10(3)(c)").
- The beats are shown in order. A "scene" beat is ONE 5-second AI video clip; it can be slowed to about 7.5 seconds,
  and after that its last picture just stands still, which looks frozen. So a scene beat has AT MOST 2 short sentences
  and AT MOST 22 words of narration in total. When a moment of the story needs more words, split it over two or three
  scene beats with different shots (a wide shot, then a close-up of a face, then the hands or the document), or move
  the explanation to a card. A "card" beat is a clean on-screen graphic (text, diagram) for the law itself; cards can
  carry longer narration (up to 4 sentences).
- Story order: the facts as they happened -> the legal question -> the old law (earlier cases) -> the arguments of both
  sides -> the judgment and its reasoning -> what changed afterwards -> a short exam recap.
- {scenes_lo}-{scenes_hi} scene beats and 5-7 card beats. Start with a scene (a strong visual hook), then the "title"
  card as the second beat. End with an "exam" card. Give every beat a unique id: s01, s02... for scenes, c01, c02...
  for cards, numbered in order.
- "chapter": a 1-4 word chapter name; consecutive beats of the same part share it (5-8 chapters in total). They become
  the YouTube chapters.

THE SCENES (these rules come from tests with the AI video model; follow them exactly)
- This is a DRAMATISED RECONSTRUCTION. The actors must NOT look like, or be described as, the real people. Describe
  people only by role, age, build, hair, clothes and mood. Never write a real person's name in "scene", "cast",
  "dialogue" or "sound". Judges are never named on screen.
- Everyone is clearly Indian, with brown skin. Period-accurate {year} India: clothes, cars, phones, offices.
- "cast": the recurring people (3-6), each with an "id" (e.g. "petitioner"), a "label" (e.g. "the petitioner") and a
  "look": one distinct description of about 20 words (gender, age, build, face, hair, clothes) that stays the same in
  every scene, so the same person is recognisable. Make every cast member look clearly different from the others.
- "scene": 40-80 words describing ONE continuous 5-second shot: the place, the light, the camera (static, slow push-in,
  close-up, wide), who is in the frame (by label, e.g. "the petitioner") and the ONE simple action. No text, letters,
  newspapers with readable headlines, logos or captions in the picture. NO signboards, shop signs, banners, posters,
  name plates or number plates in view (the AI writes nonsense letters on them): choose framings where none are
  visible. Nothing gory or violent.
- "cast" in a scene beat: the ids of the cast members visible in it.
- "look" (top level): the shared visual style of the whole film in about 30 words (era, colour grade, lens, mood),
  for example warm 1970s film look, soft natural light.
- Dialogue: at most 3 scenes may have a spoken line. "dialogue" is AT MOST 7 words, invented (never claimed as a real
  quote), spoken by ONE person ("speaker" = a cast id); the speaker is filmed close-up from just behind the listener.
  All other scenes: "dialogue" and "speaker" are empty strings and nobody speaks.
- For each scene WITH dialogue, while the Professor's narration plays the line is shown on screen as a quote:
  "quote_by" = who said it BY ROLE ONLY, never a real name (name e.g. "The senior advocate", role e.g. "for the
  petitioners"), and "keywords" = 2-3 key words from that scene's narration that pop up as the Professor says them:
  "show" = 1-3 words for the screen (e.g. "31 days", "Article 32"), "say" = the exact words of the narration at that
  moment (e.g. "thirty-one days"), in the order they are said. Other scenes: quote_by and keywords empty.
- "sound": 5-12 words of background sound for the scene (no music, no speech unless there is dialogue).
- "continue": true ONLY when this scene directly continues the previous scene in the same place (it then starts from
  the previous scene's last picture, which keeps the people and place identical). Use it 2-5 times. The first scene
  is never "continue".

THE CARDS
- "card" is null for scenes. For card beats, "scene", "cast", "speaker", "dialogue" and "sound" are empty.
- style "title": heading = the case name, sub = "{year} · Supreme Court of India" style line, items = 1-3 key facts
  (label + text), e.g. label "Bench", text "7 judges".
- style "law": the legal provision at stake: heading = the provision, items = what it says in plain words (2-4 items).
- style "quote": one well-known SHORT phrase associated with the judgment (at most 12 words) in "heading", and in
  "sub" who it is attributed to. Only use phrases you are sure about; put it in "check" too.
- style "triangle": three connected provisions or ideas (e.g. Articles 14, 19 and 21): exactly 3 items, label = the
  provision, text = 2-5 words.
- style "timeline": 3-6 items, label = year, text = at most 8 words.
- style "holding": the Court's main holdings, 3-5 items, label = 2-5 words, text = at most 20 words.
- style "exam": the exam recap: 4-6 items, label = 1-3 words (Facts, Issue, Held, Principle, Cited in...), text =
  at most 18 words. Narration here sounds like a teacher's quick revision.
- The cards MOVE with the narration: each item comes on screen when the narration talks about it, and **bold** words
  in an item's text are highlighted at the moment the narration says them. So the card's narration must mention EVERY
  item, in the same order as the items (use the item's label word, year or Article number, or its bold words), and
  bold words should be words the narration actually says.
- Optional, for 1 or 2 dramatic cards only (usually "law" or "quote"): "prop" = one word for a document shown on the
  card (e.g. "PASSPORT", "FIR", "ORDER"), and "stamps" = 1-3 rubber stamps that land on it: text = at most 3 words
  in capitals (e.g. "IMPOUNDED", "NO HEARING"), at = the exact words of the narration at which it lands (or "end"),
  color = "red" (what went wrong) or "green" (what the Court set right). Leave both empty on all other cards.

PROFESSOR AND PACKAGING
- professor_intro: what the Professor says ON CAMERA at the very start: AT MOST 12 words, a hook about the case.
- professor_outro: AT MOST 12 words at the very end, e.g. "Comment the next landmark case you want. See you next time!"
- thumbnail.scene: the id of the scene whose picture works best as a thumbnail (a face with emotion);
  thumbnail.text: 2-5 big words for the thumbnail (no case name needed).
- shorts: 2-3 YouTube Shorts cut from this video: "start" and "end" are beat ids (start before end); together the
  beats from start to end must have at most 130 words of narration and must make sense on their own. "title" = a
  Short's title (at most 60 characters).
- title: topic-first YouTube title, at most 95 characters, e.g. "{case} ({year}) | Article 21 Explained | Landmark Case".
- summary: 2-3 sentences for the description. tags: 12-20 YouTube tags. pinned_comment: one question to viewers.
- case_name, citation (the reporter citations), year, court, bench (e.g. "7 judges"), subject, topic (3-8 words),
  principle (the rule of the case in at most 20 words).

ACCURACY (this is law: be careful)
- Only facts from the judgment and well-established history. Real dates, real Article / Section numbers, real case
  names. If you are not sure of a detail, leave it out instead of guessing.
- Dialogue is invented and generic; the narration never says that anyone "said" a specific line unless it is a
  well-known phrase of the judgment.
- List in "check" every fact a teacher should verify before publishing (dates, numbers, who wrote which opinion,
  quotes). It can be empty.
"""


def validate(st, cfg):
    beats = st["beats"]
    ids = [b["id"] for b in beats]
    assert len(set(ids)) == len(ids), "beat ids are not unique"
    scenes = [b for b in beats if b["type"] == "scene"]
    cards = [b for b in beats if b["type"] == "card"]
    assert len(scenes) >= cfg["scenes_min"], f"only {len(scenes)} scenes"
    assert len(scenes) <= cfg["scenes_max"] + 2, f"{len(scenes)} scenes is too many"
    assert cards, "no cards"
    cast = {c["id"] for c in st["cast"]}
    for b in scenes:
        assert b.get("scene"), f"{b['id']} has no scene description"
        b["cast"] = [c for c in (b.get("cast") or []) if c in cast]
        if b.get("dialogue"):
            assert len(b["dialogue"].split()) <= 9, f"{b['id']}: dialogue too long"
    for b in cards:
        assert b.get("card") and b["card"].get("heading"), f"{b['id']} has no card"
    assert all(b.get("narration") for b in beats), "a beat has no narration"
    words = sum(len(s.split()) for b in beats for s in b["narration"])
    assert words >= 0.7 * cfg["words_lo"], f"only {words} words of narration"
    for sh in st.get("shorts", []):
        assert sh["start"] in ids and sh["end"] in ids and ids.index(sh["start"]) <= ids.index(sh["end"]), \
            f"short {sh['title']!r}: bad start/end"


def gemini_story(key, models, row, cfg):
    minutes = cfg["minutes"]
    words_lo, words_hi = int(minutes * 135), int(minutes * 160)
    text = PROMPT.format(case=row["case"], year=row.get("year", ""), topic=row.get("topic", ""),
                         subject=row.get("subject", ""), minutes=minutes, words_lo=words_lo, words_hi=words_hi,
                         scenes_lo=cfg["scenes_min"], scenes_hi=cfg["scenes_max"])
    body = {"contents": [{"parts": [{"text": text}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": SCHEMA, "temperature": 0.4}}
    errors = []
    while models:
        model = models[0]
        try:
            for _ in range(3):
                res = http_json(f"{GEMINI}/models/{model}:generateContent", body, {"x-goog-api-key": key},
                                timeout=900, tries=2)
                try:
                    txt = "".join(p.get("text", "") for p in res["candidates"][0]["content"]["parts"])
                    st = json.loads(txt)
                    validate(st, dict(cfg, words_lo=words_lo))
                    log(f"  written by {model}")
                    return st
                except Exception as e:
                    log(f"  {model}: storyboard not usable ({e}), asking again…")
            raise RuntimeError("no usable storyboard after 3 tries")
        except RuntimeError as e:
            errors.append(f"{model}: {str(e)[:160]}")
            log(f"  {model} can't be used ({str(e)[:160]}), trying the next model…")
            models.pop(0)
    raise RuntimeError("No Gemini model could write the storyboard:\n" + "\n".join(errors))


def to_story(raw, row, sl):
    beats = [{"type": "professor", "id": "p_intro", "chapter": "Introduction", "line": raw["professor_intro"],
              "narration": []}]
    for b in raw["beats"]:
        d = {"type": b["type"], "id": b["id"], "chapter": b.get("chapter", ""), "narration": b["narration"]}
        if b["type"] == "scene":
            d.update(scene=b["scene"], cast=b.get("cast", []), speaker=b.get("speaker", ""),
                     dialogue=b.get("dialogue", ""), sound=b.get("sound", ""), cont=bool(b.get("continue")))
        else:
            d["card"] = b["card"]
        beats.append(d)
    beats.append({"type": "professor", "id": "p_outro", "chapter": "Recap", "line": raw["professor_outro"],
                  "narration": []})
    if beats[1]["type"] == "scene":
        beats[1]["cont"] = False
    return {"slug": sl, "language": "english", "case": raw.get("case_name") or row["case"],
            "citation": raw.get("citation", ""), "year": raw.get("year") or row.get("year"), "court": raw.get("court", ""),
            "bench": raw.get("bench", ""), "subject": raw.get("subject") or row.get("subject", ""),
            "topic": raw.get("topic") or row.get("topic", ""), "principle": raw.get("principle", ""),
            "look": raw["look"], "cast": raw["cast"], "beats": beats, "thumbnail": raw["thumbnail"],
            "shorts": raw.get("shorts", []), "title": raw["title"], "summary": raw["summary"], "tags": raw["tags"],
            "pinned_comment": raw["pinned_comment"], "check": raw.get("check", []), "approved": False}


# ------------------------------------------------------------------ email
def gpu_hours(st):
    """Rough Kaggle time: ~10 min per clip (preview + 720p), ~0.55 min per narration sentence, ~20 min setup."""
    clips = sum(b["type"] in ("scene", "professor") for b in st["beats"])
    sentences = sum(len(b["narration"]) for b in st["beats"])
    return round((clips * 10 + sentences * 0.55 + 20) / 60, 1)


def approval_email(cfg, st, path):
    repo = os.environ.get("GITHUB_REPOSITORY", "manzinetworks1/manzi-studio")
    gh = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    run_url = f"{gh}/{repo}/actions/workflows/landmark_make.yml"
    e = lambda s: html.escape(str(s or ""))
    words = sum(len(s.split()) for b in st["beats"] for s in b["narration"])
    n_scenes = sum(b["type"] == "scene" for b in st["beats"])
    cast = {c["id"]: c for c in st["cast"]}
    p = [f"<h2 style='margin:0'>⚖️ Landmark case storyboard: {e(st['case'])}</h2>",
         f"<p>{e(st['citation'])} · {e(st['bench'])} · {e(st['topic'])}<br><b>Principle:</b> {e(st['principle'])}</p>",
         f"<p>{n_scenes} AI scenes + 2 Professor clips · {words} words of narration (about {words / 150:.1f} min) · "
         f"about {gpu_hours(st)} h of Kaggle GPU.</p>",
         f"<p>Read it below. To change anything, tap <b>Fix</b>, edit the text and Commit. When it's right, tap the button, "
         f"type the case code <b>{e(st['slug'])}</b> if it isn't filled in, and press <b>Run workflow</b>.</p>",
         f"<p><a href='{run_url}' style='background:#1f8a3b;color:#fff;padding:12px 20px;border-radius:8px;"
         f"text-decoration:none;font-weight:bold'>✅ Approve and make the video</a> &nbsp; "
         f"<a href='{gh}/{repo}/edit/main/{path}'>✏️ Fix the storyboard</a></p>"]
    if st.get("check"):
        p.append("<div style='background:#fdecea;padding:10px;border-radius:8px'><b>⚠️ Please double-check:</b><ul>"
                 + "".join(f"<li>{e(c)}</li>" for c in st["check"]) + "</ul></div>")
    p.append("<h3>Cast (fictional look-alikes are NOT used: every actor is invented)</h3><ul>"
             + "".join(f"<li><b>{e(c['label'])}</b>: {e(c['look'])}</li>" for c in st["cast"]) + "</ul>")
    p.append("<table style='border-collapse:collapse;width:100%;font-size:14px'>")
    chapter = None
    for b in st["beats"]:
        if b.get("chapter") and b["chapter"] != chapter:
            chapter = b["chapter"]
            p.append(f"<tr><td colspan=2 style='padding:10px 4px 4px;font-weight:bold;color:#7a4b00'>▶ {e(chapter)}</td></tr>")
        if b["type"] == "professor":
            vis = f"🎓 <b>Professor on camera</b>: “{e(b['line'])}”"
        elif b["type"] == "scene":
            who = ", ".join(cast[c]["label"] for c in b.get("cast", []) if c in cast)
            vis = (f"🎬 <b>{e(b['id'])}</b>{' (continues)' if b.get('cont') else ''}: {e(b['scene'])}"
                   + (f"<br><i>{e(who)}</i>" if who else "")
                   + (f"<br>🗣️ {e(cast.get(b.get('speaker'), {}).get('label', b.get('speaker')))}: “{e(b['dialogue'])}”"
                      if b.get("dialogue") else ""))
        else:
            c = b["card"]
            vis = (f"🟦 <b>{e(b['id'])} card ({e(c['style'])})</b>: {e(c['heading'])}"
                   + (f" · {e(c.get('sub'))}" if c.get("sub") else "")
                   + "<br>" + "<br>".join(f"• <b>{e(i['label'])}</b> {e(i['text'])}" for i in c.get("items", [])))
        nar = " ".join(b["narration"])
        p.append(f"<tr><td style='vertical-align:top;padding:6px;border-bottom:1px solid #eee;width:45%'>{vis}</td>"
                 f"<td style='vertical-align:top;padding:6px;border-bottom:1px solid #eee'>{e(nar)}</td></tr>")
    p.append("</table>")
    p.append("<h3>Shorts</h3><ul>" + "".join(f"<li>{e(s['title'])} ({e(s['start'])} → {e(s['end'])})</li>"
                                          for s in st.get("shorts", [])) + "</ul>")
    p.append(f"<p><b>Title:</b> {e(st['title'])}<br><b>Thumbnail:</b> scene {e(st['thumbnail']['scene'])}, "
             f"text “{e(st['thumbnail']['text'])}”</p>")
    p.append(f"<p><a href='{run_url}'>✅ Approve and make the video</a> (case code: <b>{e(st['slug'])}</b>)</p>")
    mail.send(cfg, f"[{cfg['channel']}] Check the landmark case storyboard: {st['case']}", "\n".join(p))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case"); ap.add_argument("--no-email", action="store_true"); ap.add_argument("--no-git", action="store_true")
    a = ap.parse_args()
    cfg = config(); lcfg = settings()
    row = pick_case(a.case)
    if not row:
        if not a.no_email:
            mail.send(cfg, f"[{cfg['channel']}] Landmark case list is empty",
                      "<p>Every case in <b>landmark/cases.csv</b> has a storyboard. Add new rows to the list.</p>")
        log("no cases left"); return
    sl = case_slug(row)
    log(f"writing the storyboard of {row['case']} ({sl})")
    key = secret("GEMINI_API_KEY"); models = pick_models(key, cfg)
    raw = gemini_story(key, models, row, lcfg)
    st = to_story(raw, row, sl)
    d = os.path.join(CASES_DIR, sl); os.makedirs(d, exist_ok=True)
    path = f"landmark/cases/{sl}/story.json"
    json.dump(st, open(os.path.join(ROOT, path), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    log(f"saved {path}")
    json.dump({"latest": sl}, open(os.path.join(HERE, "latest.json"), "w"), indent=2)  # L2's default case
    if not a.no_git:
        subprocess.run(["git", "add", path, "landmark/latest.json"], cwd=ROOT, check=True)
        subprocess.run(["git", "commit", "-m", f"Landmark storyboard: {st['case']}"], cwd=ROOT, check=True)
        subprocess.run(["git", "pull", "-q", "--rebase"], cwd=ROOT, check=False)
        subprocess.run(["git", "push"], cwd=ROOT, check=True)
    if not a.no_email:
        approval_email(cfg, st, path)


if __name__ == "__main__":
    main()
