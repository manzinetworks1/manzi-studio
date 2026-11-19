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

# The shots H3 handles well. Every scene picks one, and says for each person where they stand, which way they face and
# where their eyes go: without that, a speaking person tends to look into the camera.
SHOTS = {
    "two-shot-profile": (2, "Medium two-shot at eye level, the camera to the side of both figures, so both are "
                            "seen in profile, facing each other"),
    "two-shot-three-quarter": (2, "Medium two-shot at eye level, the camera slightly to one side, so one figure is seen "
                                  "in three-quarter view and the other in near-profile"),
    "close-up": (1, "Close-up of one face at eye level, filling the upper half of the frame; anyone else is "
                    "off-screen"),
    "medium": (1, "Medium shot of one figure at eye level; anyone else is off-screen"),
    "clean-over-shoulder": (1, "Over-the-shoulder shot at eye level"),
    "group": (3, "Medium-wide shot at eye level of three people standing apart from each other"),
    "wide": (None, "Wide shot at eye level showing the whole place"),
    "low-angle": (None, "Low-angle shot from near the floor"),
}
WHERE = {"left", "right", "centre", "foreground-left", "foreground-right", "background", "background-left",
         "background-right"}
FACES = {"left", "right", "camera-left", "camera-right", "camera", "away"}


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
        if not re.match(r"^s\d{2}[a-z]?$", str(s.get("id", ""))):
            E.append(f"{sid}: \"id\" must look like s01, s02... (or s06b for a shot added between s06 and s07)")
        if s.get("id") in ids:
            E.append(f"{sid}: id used twice.")
        ids.add(s.get("id"))
        if s.get("clip") and not str(s["clip"]).startswith(f"{s.get('id')}-"):
            E.append(f"{sid}: \"clip\" must be one of this scene's clips (like {s.get('id')}-3fa91c).")
        for k in ("day", "place", "action"):
            if not s.get(k):
                E.append(f"{sid}: missing \"{k}\".")
        st_ = s.get("stage")
        if not isinstance(st_, dict):
            E.append(f"{sid}: missing \"stage\" (the shot, and where each person stands, faces and looks).")
            st_ = {"people": {c: {} for c in (s.get("cast") or [])}}
        else:
            stage_errors(sid, st_, chars, E)
        s["cast"] = list((st_.get("people") or {}).keys()) + ([st_["shoulder"]] if st_.get("shoulder") else [])
        cast = s["cast"]
        if (s.get("line") or "").strip() and s.get("speaker") == st_.get("shoulder"):
            E.append(f"{sid}: the speaker cannot be the shoulder in the foreground; the speaker must be seen.")
        if len(cast) > SETTINGS["max_cast_per_scene"]:
            E.append(f"{sid}: {len(cast)} people in one shot; at most {SETTINGS['max_cast_per_scene']} "
                     "(more people means mixed-up faces).")
        for c in cast:
            if c not in chars:
                E.append(f"{sid}: \"{c}\" is not in the characters list.")
            elif c not in wardrobe.get(str(s.get("day")), {}) and c not in (s.get("wear") or {}):
                E.append(f"{sid}: no clothes for {c} on day {s.get('day')} (add them under \"wardrobe\").")
        for c in (s.get("wear") or {}):
            if c not in cast:
                E.append(f"{sid}: \"wear\" gives clothes for {c}, who is not in this shot.")
        for pid, p in (st_.get("people") or {}).items():
            if p.get("sound") and pid in chars and not is_animal(chars[pid]):
                E.append(f"{sid}: only animals get a \"sound\" ({pid} is a person; people only speak the scene's line).")
        secs = s.get("seconds", SETTINGS["clip_seconds"])
        if secs not in (8, 10):
            E.append(f"{sid}: \"seconds\" must be 8 or 10.")
            secs = SETTINGS["clip_seconds"]
        nar = s.get("narrator")
        if nar:
            if (s.get("line") or "").strip():
                E.append(f"{sid}: a scene has either a character's line or a narrator, not both.")
            if not nar.get("line") or not nar.get("voice"):
                E.append(f"{sid}: \"narrator\" needs \"line\" and \"voice\".")
            elif words(nar["line"]) > int(secs * 2.4):
                E.append(f"{sid}: the narrator's line has {words(nar['line'])} words; at most {int(secs * 2.4)} fit in "
                         f"{secs} s (a voice-over can be a little faster than lip-synced speech).")
        if st.get("captions") == "en" and ((s.get("line") or "").strip() or nar) and not s.get("caption_en"):
            E.append(f"{sid}: English captions are on, so this scene needs \"caption_en\" (the line in English).")
        line = (s.get("line") or "").strip()
        if line:
            if s.get("speaker") not in (st_.get("people") or {}):
                E.append(f"{sid}: the speaker must be one of the people in the shot ({', '.join(cast)}).")
            n = words(line)
            if n > limit * secs // SETTINGS["clip_seconds"]:
                E.append(f"{sid}: the line has {n} words; at most {limit * secs // SETTINGS['clip_seconds']} fit in a {secs} s clip "
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
    last = scenes[-1] if scenes else {}
    cta = ((last.get("narrator") or {}).get("line") or "")
    if not ("Like" in cta and "Subscribe" in cta):
        W.append("The last scene should be the hero's Like/Subscribe ending: the hero looks into the camera and the "
                 "narrator says \"<hero> के लिए एक Like तो बनता है… और Subscribe करना मत भूलिए!\"")
    lc = st.get("law_card")
    if lc and (lc.get("scene") not in ids or not lc.get("title") or not lc.get("lines")):
        E.append("\"law_card\" needs \"scene\" (an existing scene id), \"title\" and \"lines\".")
    yt = st["youtube"]
    if not yt.get("description") or not yt.get("tags"):
        E.append("\"youtube\" needs a \"description\" and \"tags\".")
    th = st.get("thumbnail") or {}
    if th.get("scene") and th["scene"] not in ids:
        W.append(f"Thumbnail scene \"{th['scene']}\" does not exist; the middle scene is used.")
    if len(st["title"]) > 100:
        E.append(f"The title has {len(st['title'])} characters; YouTube allows 100.")
    return E, W


def is_animal(c):
    return any(w in c.get("gender", "").lower() for w in ("dog", "cat", "cow", "goat", "monkey", "bird", "horse", "animal"))


def stage_errors(sid, st_, chars, E):
    shot = st_.get("shot")
    if shot not in SHOTS:
        E.append(f"{sid}: \"shot\" must be one of {', '.join(SHOTS)} (got \"{shot}\").")
        return
    people = st_.get("people") or {}
    n = SHOTS[shot][0]
    if n and len(people) != n:
        E.append(f"{sid}: a {shot} shows {n} {'person' if n == 1 else 'people'}; \"people\" has {len(people)}.")
    if not people and shot not in ("wide",):
        E.append(f"{sid}: \"people\" is empty.")
    if shot == "clean-over-shoulder":
        sh = st_.get("shoulder")
        if sh not in chars:
            E.append(f"{sid}: a clean-over-shoulder shot needs \"shoulder\": the character whose shoulder is in front.")
        elif sh in people:
            E.append(f"{sid}: {sh} is the shoulder in front, so must not also be in \"people\" (that draws them twice).")
    elif st_.get("shoulder"):
        E.append(f"{sid}: \"shoulder\" is only for the clean-over-shoulder shot.")
    spots = {}
    for pid, p in people.items():
        if pid not in chars:
            continue  # reported with the cast
        for k in ("where", "faces", "eyes", "does"):
            if not p.get(k):
                E.append(f"{sid}: {pid} needs \"{k}\".")
        if p.get("where") and p["where"] not in WHERE:
            E.append(f"{sid}: {pid} \"where\" must be one of {', '.join(sorted(WHERE))}.")
        if p.get("where") in spots:
            E.append(f"{sid}: {pid} and {spots[p['where']]} both stand at \"{p['where']}\".")
        spots[p.get("where")] = pid
        if p.get("faces") and p["faces"] not in FACES:
            E.append(f"{sid}: {pid} \"faces\" must be one of {', '.join(sorted(FACES))}.")
        eyes = str(p.get("eyes", "")).strip().lower()
        if eyes in ("camera", "the camera", "lens", "viewer") and not p.get("to_camera"):
            E.append(f"{sid}: {pid} looks into the camera; give a person or thing to look at "
                     "(or add \"to_camera\": true if that is really wanted).")
        if p.get("faces") == "camera" and not p.get("to_camera"):
            E.append(f"{sid}: {pid} faces the camera; use camera-left or camera-right (three-quarter) instead, "
                     "or add \"to_camera\": true.")
        if eyes == pid:
            E.append(f"{sid}: {pid} cannot look at themself.")


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
