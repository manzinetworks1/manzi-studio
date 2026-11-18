"""Masala Shorts: reading and checking a story file (the file Claude writes in chat and you paste into masala/inbox/).

python masala/story.py <file>      prints the problems, if any (the same check the workflow runs)

The format is described in masala/README.md. Every rule here exists so the video never freezes or drifts:
one clip per scene, the scene's line fits inside its clip, one speaker per clip, every person described.
"""
import hashlib, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = json.load(open(os.path.join(HERE, "settings.json"), encoding="utf-8"))
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def parse(text):
    """The pasted text -> dict. Accepts the JSON with or without a ```json fence or chat text around it."""
    text = text.strip().lstrip("﻿")
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    elif not text.startswith("{"):
        a, b = text.find("{"), text.rfind("}")
        if a >= 0 and b > a:
            text = text[a:b + 1]
    try:
        return json.loads(text)
    except ValueError as e:
        lines = text.splitlines()
        near = lines[e.lineno - 1].strip()[:80] if 0 < getattr(e, "lineno", 0) <= len(lines) else ""
        raise ValueError(f"The file is not valid JSON (line {getattr(e, 'lineno', '?')}: {e.msg}). "
                         f"Near: «{near}». Usually a missing comma or quote: copy the whole block from the chat again.")


def words(text):
    return len(re.findall(r"[\wऀ-ॿ']+", text or ""))


def check(st):
    """(errors, warnings): errors stop the video, warnings are only mentioned in the email."""
    E, W = [], []
    for k in ("slug", "title", "duration", "characters", "wardrobe", "scenes", "youtube"):
        if k not in st:
            E.append(f"Missing \"{k}\".")
    if E:
        return E, W
    if not SLUG.match(str(st["slug"])):
        E.append(f"\"slug\" must be lowercase English letters, numbers and dashes (got \"{st['slug']}\").")
    rng = SETTINGS["scenes_for_duration"].get(st["duration"])
    if not rng:
        E.append(f"\"duration\" must be one of {', '.join(SETTINGS['scenes_for_duration'])} (got \"{st['duration']}\").")
    chars = {}
    for c in st["characters"]:
        cid = c.get("id", "?")
        for k in ("id", "name", "age", "face"):
            if not c.get(k):
                E.append(f"Character {cid}: missing \"{k}\".")
        if cid in chars:
            E.append(f"Character id \"{cid}\" is used twice.")
        chars[cid] = c
        if c.get("face") and words(c["face"]) < 25:
            W.append(f"Character {cid}: the face description is short ({words(c['face'])} words); "
                     "longer, specific descriptions keep the face the same from clip to clip.")
    wardrobe = {str(k): v for k, v in st["wardrobe"].items()}
    scenes, ids = st["scenes"], set()
    if rng and not rng[0] <= len(scenes) <= rng[1]:
        E.append(f"{len(scenes)} scenes for {st['duration']}: it needs {rng[0]}-{rng[1]} "
                 f"(each scene is one {SETTINGS['clip_seconds']} s clip).")
    limit = SETTINGS["max_words_per_clip"]
    prev = None
    for i, s in enumerate(scenes, 1):
        sid = s.get("id") or f"scene {i}"
        if not re.match(r"^s\d{2}$", str(s.get("id", ""))):
            E.append(f"{sid}: \"id\" must look like s01, s02...")
        if s.get("id") in ids:
            E.append(f"{sid}: id used twice.")
        ids.add(s.get("id"))
        for k in ("day", "place", "action", "cast"):
            if not s.get(k):
                E.append(f"{sid}: missing \"{k}\".")
        cast = s.get("cast") or []
        if len(cast) > SETTINGS["max_cast_per_scene"]:
            E.append(f"{sid}: {len(cast)} people in one shot; at most {SETTINGS['max_cast_per_scene']} "
                     "(more people means mixed-up faces).")
        for c in cast:
            if c not in chars:
                E.append(f"{sid}: \"{c}\" is not in the characters list.")
            elif c not in wardrobe.get(str(s.get("day")), {}):
                E.append(f"{sid}: no clothes for {c} on day {s.get('day')} (add them under \"wardrobe\").")
        line = (s.get("line") or "").strip()
        if line:
            if s.get("speaker") not in cast:
                E.append(f"{sid}: the speaker must be one of the people in the shot ({', '.join(cast)}).")
            n = words(line)
            if n > limit:
                E.append(f"{sid}: the line has {n} words; at most {limit} fit in a {SETTINGS['clip_seconds']} s clip "
                         "with good lip-sync. Split it over two scenes.")
            if not DEVANAGARI.search(line):
                W.append(f"{sid}: the line is not in Devanagari; the AI speaks Hindi best from Devanagari text.")
        elif s.get("speaker"):
            W.append(f"{sid}: a speaker is set but there is no line; the shot will be silent.")
        if s.get("continue") and prev is None:
            E.append(f"{sid}: the first scene cannot \"continue\" from a previous one.")
        if s.get("continue") and prev and (prev.get("place") != s.get("place") or prev.get("day") != s.get("day")):
            W.append(f"{sid}: \"continue\" from a scene in another place or day; it will start from the previous "
                     "scene's last picture anyway.")
        prev = s
    for cid in {s.get("speaker") for s in scenes if (s.get("line") or "").strip()}:
        if cid in chars and not chars[cid].get("voice"):
            E.append(f"Character {cid} speaks but has no \"voice\" description.")
    yt = st["youtube"]
    if not yt.get("description") or not yt.get("tags"):
        E.append("\"youtube\" needs a \"description\" and \"tags\".")
    th = st.get("thumbnail") or {}
    if th.get("scene") and th["scene"] not in ids:
        W.append(f"Thumbnail scene \"{th['scene']}\" does not exist; the middle scene is used.")
    if len(st["title"]) > 100:
        E.append(f"The title has {len(st['title'])} characters; YouTube allows 100.")
    return E, W


def story_hash(st):
    """Changes whenever anything that the AI scenes depend on changes (so an edited story is made again)."""
    key = {k: st.get(k) for k in ("characters", "wardrobe", "scenes", "look")}
    return hashlib.sha1(json.dumps(key, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:8]


def load(slug):
    return json.load(open(os.path.join(HERE, "stories", slug, "story.json"), encoding="utf-8"))


if __name__ == "__main__":
    st = parse(open(sys.argv[1], encoding="utf-8").read())
    errs, warns = check(st)
    for e in errs:
        print("❌", e)
    for w in warns:
        print("⚠️", w)
    print(f"{len(st.get('scenes', []))} scenes · {'OK' if not errs else 'NOT OK'}")
    sys.exit(1 if errs else 0)
