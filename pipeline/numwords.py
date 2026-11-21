"""Compare a script with what Whisper heard, when one writes numbers as words and the other as digits.

"decided on twenty-fourth April nineteen seventy-three" and "decided on 24 April 1973" both become
["decided", "on", "24", "april", "1973"]. Used by the voice check on Kaggle (engine/voice_stage.py keeps a copy of
these few lines, because it runs on its own there) and by the video makers when they pick the Professor's sentences.
"""
import difflib
import re

UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
ORD = {w: i for i, w in enumerate("_ first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth "
                                  "thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth".split())
       if w != "_"}
ORD.update({w: 10 * i for i, w in enumerate("_ _ twentieth thirtieth fortieth fiftieth sixtieth seventieth eightieth "
                                            "ninetieth".split()) if w != "_"})
SAME = {"vs": "versus", "v": "versus", "mr": "mister", "dr": "doctor"}


def _merge(tokens):
    out, i = [], 0
    while i < len(tokens):
        groups, j = [], i
        while j < len(tokens):
            w = tokens[j]
            if w in TENS:
                v = TENS[w]
                nxt = tokens[j + 1] if j + 1 < len(tokens) else ""
                if nxt in UNITS and 0 < UNITS[nxt] < 10:
                    v += UNITS[nxt]; j += 1
                elif nxt in ORD and ORD[nxt] < 10:
                    v += ORD[nxt]; j += 1
                groups.append(v)
            elif w in UNITS:
                groups.append(UNITS[w])
            elif w in ORD and not groups:
                groups.append(ORD[w]); j += 1
                break
            elif w in ("hundred", "thousand") and groups:
                groups[-1] *= 100 if w == "hundred" else 1000
                if j + 1 < len(tokens) and tokens[j + 1] == "and" and j + 2 < len(tokens) and \
                        (tokens[j + 2] in UNITS or tokens[j + 2] in TENS):
                    j += 1
            else:
                break
            j += 1
        if not groups:
            out.append(tokens[i]); i += 1
            continue
        if len(groups) == 1:
            out.append(str(groups[0]))
        elif len(groups) == 2 and groups[0] % 100 == 0 and groups[0] and groups[1] < groups[0]:
            out.append(str(groups[0] + groups[1]))          # three hundred sixty eight, two thousand seven
        elif len(groups) == 2 and 1 <= groups[0] <= 99 and groups[1] < 100:
            out.append(str(groups[0] * 100 + groups[1]))    # nineteen seventy three
        else:
            out += [str(g) for g in groups]
        i = j
    return out


def words(text):
    t = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text.lower())          # 31st -> 31
    t = re.sub(r"(\d),(\d{3})", r"\1\2", t)                          # 1,000 -> 1000
    toks = re.sub(r"[^a-z0-9' ]+", " ", t).split()
    toks = [SAME.get(w, w) for w in toks]
    return _merge(toks)


def match(script, heard):
    return difflib.SequenceMatcher(None, words(script), words(heard)).ratio()
