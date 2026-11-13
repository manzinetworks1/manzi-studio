"""Turn one topic pack (written by Gemini, checked by you) into video specs: one long video + Shorts.

Each spec is a list of "beats": one spoken sentence or paragraph plus what appears on screen while it is spoken.
Timing (t0/t1 of each beat) comes from the voice; estimate_timing() is used when there is no voice yet.
"""
import json, re

BOLD = re.compile(r"\*\*(.+?)\*\*")
ONES = "One Two Three Four Five Six Seven Eight Nine Ten".split()


def plain(s): return re.sub(r"\s+", " ", BOLD.sub(r"\1", str(s or ""))).strip()


def split_long(p, limit=85):
    words = plain(p).split()
    if len(words) <= limit: return [p]
    out, cur = [], ""
    for s in re.split(r"(?<=[.?!।])\s+", p):
        if cur and len(plain(cur + " " + s).split()) > limit * 0.6 and len(plain(cur).split()) >= 25: out.append(cur); cur = s
        else: cur = (cur + " " + s).strip()
    if cur: out.append(cur)
    return out


def T(pack, en, hi): return hi if pack.get("language") == "hindi" else en


def meta_of(pack, channel):
    years = [str(y) for y in pack.get("years_range", [])]
    hits = [str(y) for y in pack.get("asked_years", [])]
    if hits and not years:
        lo, hi = int(min(hits)), int(max(hits)); years = [str(y) for y in range(lo, hi + 1)]
    return {"qnum": pack.get("qnum", 1), "question": pack["question"], "topic": pack.get("topic", ""), "subject": pack.get("subject", ""),
            "course": pack.get("course", "LLB"), "marks": pack.get("marks", ""), "years": years, "hits": hits,
            "span": len(years) or None}


def outro_say(pack, channel):
    return T(pack, f"Save this for your exam, and follow {channel} for a new question every day.",
             f"इसे अपनी परीक्षा के लिए सेव कर लीजिए, और हर दिन नए प्रश्न के लिए {channel} को फॉलो कीजिए।")


def long_spec(pack, channel):
    L = pack["long"]; beats = []
    q = f"{T(pack, 'Question', 'प्रश्न')} {pack.get('qnum', 1)}. {pack['question']}"
    beats.append({"k": "cover", "page": "cover", "say": q})
    for si, sec in enumerate(L["sections"]):
        name = sec.get("heading", "")
        if sec.get("points"):
            for p in sec["points"]:
                beats.append({"k": "point", "page": f"s{si}", "section": name, "title": p["title"], "text": p["text"],
                              "say": f"{plain(p['title'])}. {plain(p['text'])}"})
        elif sec.get("cases"):
            for ci, c in enumerate(sec["cases"]):
                beats.append({"k": "case", "page": f"s{si}c{ci}", "section": name, "name": c["name"], "text": c["text"],
                              "say": f"{plain(c['name'])}. {plain(c['text'])}"})
        else:
            for pi, para in enumerate(sec.get("paras", [])):
                for part_i, part in enumerate(split_long(para)):
                    beats.append({"k": "para", "page": f"s{si}p{pi}_{part_i}", "section": name, "text": part, "cont": part_i > 0, "say": plain(part)})
        if sec.get("tip"):
            beats.append({"k": "tip", "page": beats[-1]["page"], "text": sec["tip"], "say": T(pack, "Exam tip: ", "परीक्षा टिप: ") + plain(sec["tip"])})
    beats.append({"k": "end", "page": "end", "say": T(pack,
        f"If this helped you, comment NOTES for the free PDF of this answer, and subscribe to {channel}. All the best for your exams!",
        f"अगर यह वीडियो काम आया, तो फ्री PDF के लिए कमेंट में NOTES लिखिए, और {channel} को सब्सक्राइब कीजिए। परीक्षा के लिए शुभकामनाएँ!")})
    return {"format": "long", "template": "notes", "name": "long", "beats": beats}


def short_specs(pack, channel):
    S = pack.get("shorts", {}); out = []
    o = _Outro(outro_say(pack, channel))
    if S.get("datadrop") and pack.get("asked_years"):
        d = S["datadrop"]; hits = pack["asked_years"]
        out.append({"template": "datadrop", "thumbTitle": d.get("thumb", pack.get("topic")), "beats": [
            {"k": "intro", "say": T(pack, "This question has come", "यह प्रश्न आया है")},
            {"k": "number", "say": T(pack, f"{len(hits)} times in the last {len(meta_of(pack, channel)['years'])} years.", f"पिछले {len(meta_of(pack, channel)['years'])} सालों में {len(hits)} बार।")},
            {"k": "question", "say": pack["question"]},
            {"k": "years", "say": T(pack, "In ", "") + ", ".join(hits) + "."},
            {"k": "cta", "say": d.get("cta", T(pack, "Will it come again? Save this video.", "क्या यह फिर आएगा? यह वीडियो सेव कर लीजिए।")), "cap": True}, o]})
    if S.get("myth"):
        m = S["myth"]
        out.append({"template": "myth", "thumbTitle": m.get("thumb", plain(m["myth"])), "beats": [
            {"k": "myth", "text": m["myth"], "say": T(pack, "Myth: ", "मिथक: ") + plain(m["myth"])},
            {"k": "bust", "say": T(pack, "That's not true.", "यह सच नहीं है।")},
            {"k": "law", "text": m["law"], "say": plain(m["law"])},
            {"k": "source", "text": m["source"], "say": plain(m.get("source_say", m["source"]))}, o]})
    if S.get("quiz"):
        qz = S["quiz"]; L = "ABCD"
        out.append({"template": "quiz", "options": qz["options"], "answer": qz["answer"], "thumbTitle": qz.get("thumb", plain(qz["question"])), "beats": [
            {"k": "q", "text": qz["question"], "say": plain(qz["question"])},
            {"k": "opts", "say": " ".join(f"{L[i]}, {plain(x)}." for i, x in enumerate(qz["options"]))},
            {"k": "timer", "say": "", "fixed": 3.0},
            {"k": "reveal", "say": T(pack, f"The answer is {L[qz['answer']]}: {plain(qz['options'][qz['answer']])}.", f"सही जवाब है {L[qz['answer']]}: {plain(qz['options'][qz['answer']])}।")},
            {"k": "explain", "text": qz["explain"], "say": plain(qz["explain"])}, o]})
    if S.get("case"):
        c = S["case"]
        out.append({"template": "case", "caseName": c["name"], "thumbTitle": c.get("thumb", c["name"]), "beats": [
            {"k": "open", "say": T(pack, "Case file: ", "केस फ़ाइल: ") + plain(c["name"]) + "."},
            {"k": "facts", "text": c["facts"], "say": T(pack, "Facts. ", "तथ्य। ") + plain(c["facts"])},
            {"k": "issue", "text": c["issue"], "say": T(pack, "Issue. ", "मुद्दा। ") + plain(c["issue"])},
            {"k": "held", "text": c["held"], "say": T(pack, "Held. ", "निर्णय। ") + plain(c["held"])},
            {"k": "principle", "text": c["principle"], "say": plain(c["principle"])}, o]})
    if S.get("compare"):
        cp = S["compare"]
        beats = [{"k": "title", "say": plain(cp.get("title_say", cp["title"]))}]
        beats += [{"k": "row", "i": i, "say": plain(r["say"])} for i, r in enumerate(cp["rows"])]
        if cp.get("note"): beats.append({"k": "note", "say": plain(cp["note"]), "cap": True})
        out.append({"template": "compare", "title": cp["title"], "left": cp["left"], "right": cp["right"], "rows": cp["rows"],
                    "thumbTitle": cp.get("thumb", cp["title"]), "beats": beats + [o]})
    if S.get("flow"):
        fl = S["flow"]
        beats = [{"k": "title", "say": plain(fl["title"])}]
        beats += [{"k": "step", "i": i, "say": (WORD(pack, i) + ". " if True else "") + plain(s.get("say", s["title"] + ". " + s.get("sub", "")))} for i, s in enumerate(fl["steps"])]
        out.append({"template": "flow", "title": fl["title"], "steps": fl["steps"], "thumbTitle": fl.get("thumb", fl["title"]), "beats": beats + [o]})
    specs = []
    for s in out:
        meta = {k: s.pop(k) for k in list(s) if k not in ("template", "beats")}
        specs.append({"format": "short", "template": s["template"], "name": s["template"], "beats": _fresh(s["beats"]), "extra": meta})
    return specs


class _Outro(dict):
    """A fresh outro beat each time it is used (each Short needs its own timing)."""
    def __init__(self, say): super().__init__(k="outro", say=say)


def _fresh(beats): return [dict(b) for b in beats]


def WORD(pack, i):
    hi = ["पहला", "दूसरा", "तीसरा", "चौथा", "पाँचवाँ", "छठा", "सातवाँ", "आठवाँ"]
    return (hi[i] + " चरण") if pack.get("language") == "hindi" else ("Step " + ONES[i].lower())


def all_specs(pack, channel="The LLB Guide"):
    meta = meta_of(pack, channel); res = []
    for s in [long_spec(pack, channel)] + short_specs(pack, channel):
        m = dict(meta); m.update(s.pop("extra", {}))
        s.update({"lang": pack.get("language", "english"), "channel": channel, "meta": m, "thumbTitle": m.get("thumbTitle")})
        res.append(s)
    return res


def estimate_timing(spec, wps=2.5):
    """Without a voice: give each beat a time from its number of words."""
    t = 0.4
    for b in spec["beats"]:
        n = len(plain(b.get("say", "")).split())
        d = b.get("fixed") or max({"bust": 1.2, "outro": 3.4, "tip": 3.0, "number": 2.2, "end": 5.0}.get(b["k"], 1.4), n / wps + 0.3)
        b["t0"] = round(t, 3); b["t1"] = round(t + d, 3)
        t += d + (0.9 if b["k"] in ("cover", "q") else 0.45)
    spec["duration"] = round(t + 0.6, 2)
    return spec


def add_pops(spec):
    """Subscribe reminder in long videos: ~30 s in, middle, and before the end (never on the cover)."""
    if spec["format"] != "long" or spec["duration"] < 45: spec["pops"] = []; return spec
    end = next((b["t0"] for b in spec["beats"] if b["k"] == "end"), spec["duration"])
    cover_end = spec["beats"][1]["t0"] if len(spec["beats"]) > 1 else 0
    pops = []
    for p in (max(28, cover_end + 2), spec["duration"] * 0.5, end - 16):
        if p + 5.5 > end - 1 or any(abs(p - x) < 25 for x in pops): continue
        pops.append(round(p, 2))
    spec["pops"] = pops; return spec


if __name__ == "__main__":
    import sys
    pack = json.load(open(sys.argv[1], encoding="utf-8"))
    for s in all_specs(pack):
        estimate_timing(s); add_pops(s)
        print(s["name"], s["duration"], len(s["beats"]))
