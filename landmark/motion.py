"""Moving cards for the landmark videos, in step with the Professor's narration.

Each card is the same HTML page as cards.py draws, but recorded frame by frame while small animations play:
  - the heading slides in; each point rises when the Professor starts talking about it, earlier points dim;
  - a gold highlighter sweeps under the **bold** words as he says them;
  - per style: title facts pop in, timeline dots light up year by year, the triangle draws itself (and turns red when
    a sentence says a law "fails" one Article), the exam recap cells come in with a gold tick, a quote lights up word
    by word;
  - optional, from the storyboard: card["prop"] (a document such as "PASSPORT" that slides in) and card["stamps"]
    ([{"text": "IMPOUNDED", "at": "impounded", "color": "red"}], "at" = the words he says when it lands, or "end").
A point the narration never mentions comes in after the last sentence, with a short pause added for it.
Timing: the moment a phrase is said is estimated from its place in the sentence (the sentence's start and end are
known exactly). Soft sound effects (pop, thud) are returned to be mixed under the narration.
"""
import json, math, os, re, shutil

import numpy as np

from cards import card_html, W, H, PW, PH

PAUSE_END = 1.4          # seconds added after the narration for each point it never mentions (max 2 points)
STEP = 0.6               # smallest gap between two things appearing


# ------------------------------------------------------------------ when is a phrase said?
UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
ORD = {w: i for i, w in enumerate("_ first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth "
                                  "thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth".split())
       if w != "_"}
ORD.update({w: 10 * i for i, w in enumerate("_ _ twentieth thirtieth fortieth fiftieth sixtieth seventieth eightieth "
                                            "ninetieth".split()) if w != "_"})
SUF = lambda v: "th" if 10 <= v % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(v % 10, "th")
TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}


def _numbers(tokens):
    """Spoken numbers -> digits: "nineteen fifty one" -> 1951, "three hundred sixty eight" -> 368, "fourteen" -> 14.
    tokens: [(word, index)] -> same, with number words merged into one digit token."""
    out, i = [], 0
    while i < len(tokens):
        groups, j = [], i                     # groups of 0-99, "hundred" multiplies the last one
        while j < len(tokens):
            w = tokens[j][0]
            if w in TENS:
                v = TENS[w]
                nxt = tokens[j + 1][0] if j + 1 < len(tokens) else ""
                if nxt in UNITS and UNITS[nxt] < 10:
                    v += UNITS[nxt]; j += 1
                elif nxt in ORD and ORD[nxt] < 10:                 # twenty fourth -> 24th
                    v += ORD[nxt]; j += 2
                    groups.append(f"{v}{SUF(v)}")
                    break
                groups.append(v)
            elif w in ORD and not groups:
                groups.append(f"{ORD[w]}{SUF(ORD[w])}"); j += 1
                break
            elif w in UNITS:
                groups.append(UNITS[w])
            elif w in ("hundred", "thousand") and groups and isinstance(groups[-1], int):
                groups[-1] *= 100 if w == "hundred" else 1000
                if j + 1 < len(tokens) and tokens[j + 1][0] == "and":
                    j += 1
            else:
                break
            j += 1
        if not groups:
            out.append(tokens[i]); i += 1
            continue
        if any(isinstance(g, str) for g in groups):           # an ordinal ends the number
            if len(groups) == 1:
                out.append((groups[0], tokens[i][1])); i = j
            else:
                out += tokens[i:j]; i = j
            continue
        if len(groups) == 1:
            v = groups[0]
        elif len(groups) == 2 and groups[0] % 100 == 0 and groups[0] and groups[1] < groups[0]:
            v = groups[0] + groups[1]                       # three hundred | sixty eight, two thousand | seven
        elif len(groups) == 2 and 1 <= groups[0] <= 99 and groups[1] < 100:
            v = groups[0] * 100 + groups[1]                 # nineteen | fifty one, three | sixty eight
        else:
            out += tokens[i:j]; i = j
            continue
        out.append((str(v), tokens[i][1])); i = j
    return out


def _norm(s):
    """lower case, punctuation -> spaces, spoken numbers -> digits; returns (text, index map back to the original)."""
    tokens = [(m.group(0).lower(), m.start()) for m in re.finditer(r"[A-Za-z0-9]+", s)]
    tokens = _numbers(tokens)
    out, idx = [], []
    for w, i in tokens:
        if out:
            out.append(" "); idx.append(i)
        out.extend(w); idx.extend([i] * len(w))
    return "".join(out), idx


def find(times, phrase, after=0.0, frac=0.0):
    """Moment the Professor says `phrase` (first time at or after `after`), or None."""
    if not phrase:
        return None
    p, _ = _norm(phrase)
    p = p.strip()
    if not p:
        return None
    for text, a, b in times:
        if b < after:
            continue
        n, idx = _norm(text)
        for m in re.finditer(r"(?<![a-z0-9])" + re.escape(p) + r"(?![0-9])", n):
            pos = idx[m.start()] + frac * len(phrase)
            t = a + (b - a) * pos / max(1, len(text))
            if t >= after - 0.01:
                return round(t, 2)
    return None


def _strip(s):
    return re.sub(r"\*\*", "", s or "")


def _bolds(s):
    return re.findall(r"\*\*(.+?)\*\*", s or "")


SMALL = set("a an the of to in on at by for with and or but is are was be as its it his her their this that "
            "under from not no any".split())


def item_time(times, it, after):
    """When an item (a point, a cell, a corner...) is first talked about."""
    label, text = it.get("label") or "", _strip(it.get("text"))
    cands = []
    nums = re.findall(r"\b\d{2,4}\b", label)
    cands += [n for n in nums]                                   # "Article 14" -> "14", "1967"
    cands += [label] if label and not nums else []
    cands += _bolds(it.get("text"))
    for c in cands:
        t = find(times, c, after)
        if t is not None:
            return t
    # all the label's real words in one sentence -> the first of them
    words = [w for w in _norm(label)[0].split() if len(w) > 3 and w not in SMALL]
    need = len(words) if len(words) <= 2 else len(words) - 1     # "Basic Structure Doctrine" -> 2 of 3 is enough
    for s in times:
        if s[2] < after or not words:
            continue
        hits = [find([s], x) for x in words]
        if sum(h is not None for h in hits) >= need:
            return min(h for h in hits if h is not None)
    for b in _bolds(it.get("text")):                              # a name inside a bold phrase ("A.K. Gopalan")
        for w in sorted(re.findall(r"\b[A-Z][a-z]{4,}\b", b), key=len, reverse=True):
            if True:
                t = find(times, w, after)
                if t is not None:
                    return t
    return None


def schedule(times, items, ordered=True, first=0.8):
    """Appear times for a list of items, plus how many need a pause after the narration."""
    end = times[-1][2] if times else 1.0
    found = [item_time(times, it, 0.0) for it in items]
    out, prev, late = [], first - STEP, 0
    for k, t in enumerate(found):
        later_known = any(x is not None for x in found[k + 1:])
        if t is None and not ordered:
            t = (out[-1] if out else first - STEP) + 1.2
        elif t is None:
            if later_known:
                t = prev + STEP
            else:
                t = end + 0.3 + late * PAUSE_END; late += 1
        elif ordered:
            # come in at the start of the sentence that talks about it, unless something came in during that sentence
            s = next((x for x in times if x[1] - 0.01 <= t <= x[2] + 0.01), None)
            if s and s[1] > prev + STEP / 2:
                t = s[1]
            t = max(t - 0.15, prev + STEP)
        out.append(round(t, 2)); prev = max(prev, t) if ordered else prev
    return out, min(late, 2)


# ------------------------------------------------------------------ the in-page animation kit
KIT = r"""
window.A = [];
const EASE = 'cubic-bezier(.2,.8,.2,1)';
window.anim = (el, frames, start, dur, extra) => {
  if (!el) return null;
  const a = el.animate(frames, Object.assign({duration: dur * 1000, delay: Math.max(0, start) * 1000, fill: 'both',
                                              easing: EASE}, extra || {}));
  a.pause(); A.push(a); return a;
};
window.seek = (t) => { for (const a of A) a.currentTime = t * 1000; };
window.rise = (el, t, dy) => anim(el, [{opacity: 0, transform: `translateY(${dy || 46}px)`}, {opacity: 1, transform: 'none'}], t, .6);
window.dim = (el, t) => anim(el, [{opacity: 1}, {opacity: .5}], t, .5, {fill: 'forwards'});
window.pop = (el, t) => { if (!el) return; el.style.transformBox = 'fill-box'; el.style.transformOrigin = 'center';
  anim(el, [{transform: 'scale(0)'}, {transform: 'scale(1.18)', offset: .6}, {transform: 'scale(1)'}], t, .5); };
window.hl = (el, t, dur) => {
  if (!el) return;
  el.style.backgroundImage = 'linear-gradient(rgba(217,171,79,.45), rgba(217,171,79,.45))';
  el.style.backgroundRepeat = 'no-repeat'; el.style.backgroundPosition = '0 88%';
  el.style.boxDecorationBreak = 'clone'; el.style.webkitBoxDecorationBreak = 'clone';
  el.style.padding = '0 4px'; el.style.borderRadius = '4px';
  anim(el, [{backgroundSize: '0% 42%'}, {backgroundSize: '100% 42%'}], t, dur || 1.0, {easing: 'ease-in-out'});
};
window.shake = (t) => anim(document.querySelector('.main'), [{transform: 'translate(0,0)'}, {transform: 'translate(-5px,4px)'},
  {transform: 'translate(4px,-3px)'}, {transform: 'translate(0,0)'}], t, .22, {fill: 'none', composite: 'add'});
window.stamp = (parent, text, color, css, t, hold) => {
  const s = document.createElement('div');
  s.textContent = text;
  s.style.cssText = `position:absolute;font:800 40px D;letter-spacing:4px;color:${color};border:6px solid ${color};
    border-radius:10px;padding:6px 18px;white-space:nowrap;mix-blend-mode:screen;z-index:5;${css}`;
  parent.appendChild(s);
  const r = css.match(/rotate\((-?[0-9.]+)deg\)/); const rot = r ? r[1] : 0;
  const base = (css.match(/translate\([^)]*\)/) || [''])[0];
  anim(s, [{opacity: 0, transform: `${base} rotate(${rot}deg) scale(2.6)`},
           {opacity: 1, transform: `${base} rotate(${rot}deg) scale(.94)`, offset: .7},
           {opacity: .93, transform: `${base} rotate(${rot}deg) scale(1)`}], t, .32, {easing: 'ease-in'});
  if (hold) {                        // upright Shorts: lands, stays a moment, goes (no room to keep it)
    s.style.background = 'rgba(8,18,38,.92)'; s.style.mixBlendMode = 'normal';
    anim(s, [{opacity: .93}, {opacity: 0}], t + hold, .5, {fill: 'forwards', composite: 'replace'});
  }
  shake(t + .22);
};
window.prop = (label, t, portrait) => {
  const wrap = document.createElement('div');
  wrap.style.cssText = 'position:absolute;right:160px;top:96px;width:290px;height:340px;transform-origin:top right;z-index:4;';
  document.body.appendChild(wrap);
  const first = document.querySelector('.main .row, .main .cell, .main .tl, .main .quote');
  if (first) {                       // shrink it so it ends above the first point
    const room = first.getBoundingClientRect().top - 50 - 96 - 14;   // (the points are still 50px low here, before they rise)
    if (room < 340) wrap.style.transform = `scale(${Math.max(.5, room / 340)})`;
  }
  const p = document.createElement('div');
  p.style.cssText = `position:absolute;left:0;top:0;width:290px;height:340px;border-radius:14px;`;
  p.style.cssText += `background:linear-gradient(160deg,#24406b,#162a49);border:3px solid rgba(217,171,79,.8);
    box-shadow:0 20px 50px rgba(0,0,0,.5);display:flex;flex-direction:column;align-items:center;
    justify-content:flex-start;padding-top:${portrait ? 18 : 26}px;gap:10px;z-index:4;`;
  p.innerHTML = `<div style="width:${portrait ? 56 : 76}px;height:${portrait ? 56 : 76}px;border-radius:50%;border:4px solid #d9ab4f;
    display:flex;align-items:center;justify-content:center;font:800 30px D;color:#d9ab4f">✦</div>
    <div style="font:700 ${label.length > 9 ? 24 : 30}px T;letter-spacing:6px;color:#d9ab4f">${label}</div>`;
  wrap.appendChild(p);
  anim(p, [{opacity: 0, transform: 'translateX(140px) rotate(12deg)'}, {opacity: 1, transform: 'rotate(6deg)'}], t, .8);
  return p;
};
0;
"""


def _js(v):
    return json.dumps(v)


# ------------------------------------------------------------------ per-style plans
def plan(card, times, portrait=False):
    """-> (javascript, [(sound, t)], extra seconds after the narration)"""
    style = card.get("style", "holding")
    items = card.get("items") or []
    end = times[-1][2] if times else 1.0
    js, ev, extra = ["const M=document.querySelector('.main'); const h=M.querySelector('h1'); const sub=M.querySelector('.sub');",
                     "const top=document.querySelector('.top');",
                     "if (top) anim(top,[{opacity:0},{opacity:1}],0,.6);"], [], 0.0

    if style == "title":
        js.append("anim(h,[{opacity:0,transform:'scale(.92)'},{opacity:1,transform:'none'}],0.05,.8);"
                  "rise(sub,.5,30); const rl=M.querySelector('.rule'); anim(rl,[{transform:'scaleX(0)'},{transform:'scaleX(1)'}],.7,.6);"
                  "const S=[...M.querySelectorAll('.stat')];")
        ts, _ = schedule(times, items[:3], ordered=True, first=1.2)
        ts = [min(t, end - 0.3) for t in ts]
        for k, t in enumerate(ts):
            js.append(f"rise(S[{k}],{t},40);"); ev.append(("pop", t))

    elif style in ("law", "holding"):
        js.append("rise(h,.05,40); rise(sub,.45,30); const R=[...M.querySelectorAll('.row')];")
        ts, late = schedule(times, items[:5], ordered=True, first=0.9 if card.get("sub") else 0.7)
        for k, t in enumerate(ts):
            js.append(f"rise(R[{k}],{t},50); pop(R[{k}].querySelector('.num'),{t + .05});")
            ev.append(("pop", t + .05))
            if k:
                js.append(f"dim(R[{k - 1}],{t});")
            for j, b in enumerate(_bolds(items[k].get("text"))):
                tb = find(times, b, t - 0.2) if t <= end else None
                tb = max(tb, t + .3) if tb is not None else t + .5
                js.append(f"hl(R[{k}].querySelectorAll('.txt b')[{j}],{tb},{min(1.6, .25 + .05 * len(b))});")
        extra = late * PAUSE_END

    elif style == "timeline":
        js.append("rise(h,.05,40); const E=[...M.querySelectorAll('.ev')];"
                  "const tl=M.querySelector('.tl'); const line=document.createElement('div');"
                  "line.style.cssText='position:absolute;left:4%;right:4%;top:92px;height:5px;background:#d9ab4f;"
                  "transform-origin:left center;z-index:0'; tl.appendChild(line);"
                  "const css=document.createElement('style'); css.textContent='.tl:before{opacity:.15 !important}';"
                  "document.head.appendChild(css);")
        ts, late = schedule(times, items[:6], ordered=True, first=0.9)
        n = len(ts)
        js.append(f"anim(line,[{{transform:'scaleX(0)'}},{{transform:'scaleX({1 / n:.3f})'}}],{ts[0]},.6);")
        for k, t in enumerate(ts):
            if k:
                js.append(f"anim(line,[{{transform:'scaleX({k / n:.3f})'}},{{transform:'scaleX({(k + 1) / n:.3f})'}}],{t - .3},.6,"
                          f"{{fill:'forwards'}});")
            js.append(f"rise(E[{k}].querySelector('b'),{t},30); pop(E[{k}].querySelector('i'),{t + .1});"
                      f"rise(E[{k}].querySelector('span'),{t + .25},30);")
            ev.append(("pop", t + .1))
            if k:
                js.append(f"dim(E[{k - 1}],{t});")
        extra = late * PAUSE_END

    elif style == "exam":
        js.append("rise(h,.05,40); const C=[...M.querySelectorAll('.cell')];")
        ts, late = schedule(times, items[:6], ordered=False, first=0.8)
        for k, t in enumerate(ts):
            js.append(f"rise(C[{k}],{t},40);"
                      f"const tk{k}=document.createElement('div'); tk{k}.textContent='✓';"
                      f"tk{k}.style.cssText='position:absolute;right:18px;top:12px;font:800 40px D;color:#d9ab4f';"
                      f"C[{k}].style.position='relative'; C[{k}].appendChild(tk{k}); pop(tk{k},{t + .35});")
            ev.append(("pop", t + .35))
            for j, b in enumerate(_bolds(items[k].get("text"))):
                tb = find(times, b, t - 0.2)
                tb = max(tb, t + .4) if tb is not None else t + .6
                js.append(f"hl(C[{k}].querySelectorAll('span b')[{j}],{tb},{min(1.4, .25 + .05 * len(b))});")
        extra = late * PAUSE_END

    elif style == "quote":
        # the quote is there from the start, dim; its words light up as he says them
        q = _strip(card.get("heading"))
        t0 = find(times, q) or (times[min(1, len(times) - 1)][1] if times else 0.6)
        words = q.split()
        span = max(0.8, 0.32 * len(words))
        js.append("const Q=M.querySelector('.quote'); Q.innerHTML=Q.textContent.split(' ').map(w=>'<span>'+w+'</span>').join(' ');"
                  "const QW=[...Q.querySelectorAll('span')]; rise(Q,.05,30);"
                  "for (const w of QW) w.style.color='rgba(255,255,255,.35)';")
        for k in range(len(words)):
            t = t0 + span * k / len(words)
            js.append(f"anim(QW[{k}],[{{color:'rgba(255,255,255,.35)'}},{{color:'#ffffff'}}],{t:.2f},.3);")
        js.append(f"const rl=M.querySelector('.rule'); anim(rl,[{{transform:'scaleX(0)'}},{{transform:'scaleX(1)'}}],{t0 + span:.2f},.6);"
                  f"rise(M.querySelector('.sub'),{t0 + span + .3:.2f},20);")

    elif style == "triangle":
        js.append("""rise(h,.05,40);
const svg=M.querySelector('svg'); const poly=svg.querySelector('polygon'); const ns='http://www.w3.org/2000/svg';
const kids=[...svg.children].slice(1); const Cc=[0,1,2].map(i=>kids[i*3]), Lb=[0,1,2].map(i=>kids[i*3+1]), Ds=[0,1,2].map(i=>kids[i*3+2]);
const mark=(t,start,dur,color)=>{ const b=t.getBBox(); const r=document.createElementNS(ns,'rect');
  r.setAttribute('x',b.x-6); r.setAttribute('y',b.y+b.height*.52); r.setAttribute('width',b.width+12); r.setAttribute('height',b.height*.42);
  r.setAttribute('rx',4); r.setAttribute('fill',color||'rgba(217,171,79,.45)'); svg.insertBefore(r,t);
  r.style.transformBox='fill-box'; r.style.transformOrigin='left center';
  anim(r,[{transform:'scaleX(0)'},{transform:'scaleX(1)'}],start,dur,{easing:'ease-in-out'}); };
const per=poly.getTotalLength(); poly.style.strokeDasharray=per;""")
        ts, _ = schedule(times, items[:3], ordered=True, first=0.9)
        for k, t in enumerate(ts):
            js.append(f"pop(Cc[{k}],{t - .1}); anim(Lb[{k}],[{{opacity:0}},{{opacity:1}}],{t + .1},.3);"
                      f"anim(Ds[{k}],[{{opacity:0,transform:'translateY(20px)'}},{{opacity:1,transform:'none'}}],{t + .2},.5);")
            ev.append(("pop", t - .05))
        # the sides: the sentence after the corners appear (or right after the last corner)
        s_after = next((s for s in times if s[1] > ts[-1] + 0.2), None)
        d0 = s_after[1] if s_after else ts[-1] + .6
        d1 = max(d0 + 1.2, s_after[2] - .3) if s_after else d0 + 1.5
        js.append(f"anim(poly,[{{strokeDashoffset:per,fillOpacity:0}},{{strokeDashoffset:0,fillOpacity:0,offset:.85}},"
                  f"{{strokeDashoffset:0,fillOpacity:1}}],{d0},{d1 - d0 + .3},{{easing:'ease-in-out'}});")
        tg = find(times, "golden triangle")
        if tg is not None:
            js.append(f"""const g=document.createElementNS(ns,'text'); const bb=poly.getBBox();
g.setAttribute('x',bb.x+bb.width/2); g.setAttribute('y',bb.y+bb.height*.66); g.setAttribute('text-anchor','middle');
g.setAttribute('font-size',{36 if portrait else 40}); g.setAttribute('font-weight','800'); g.setAttribute('fill','#d9ab4f');
g.textContent='THE GOLDEN TRIANGLE'; svg.appendChild(g);
anim(g,[{{opacity:0,letterSpacing:'30px'}},{{opacity:1,letterSpacing:'{4 if portrait else 6}px'}}],{tg},.9);
anim(poly,[{{strokeWidth:6,fill:'rgba(217,171,79,.08)'}},{{strokeWidth:14,fill:'rgba(217,171,79,.25)',offset:.4}},
  {{strokeWidth:6,fill:'rgba(217,171,79,.14)'}}],{tg},1.6,{{composite:'replace'}});""")
            ev.append(("pop", tg))
        # "if a law fails Article X ... Article Y": X goes red, Y gets a cross
        labels = [re.findall(r"\d+", it.get("label", "")) for it in items[:3]]
        for text, a, b in times:
            if not re.search(r"\bfail", text, re.I):
                continue
            hits = [(m.start(), m.group(1)) for m in re.finditer(r"Articles?\s+(\d+)", text)]
            if len(hits) < 2:
                continue
            idx = lambda num: next((k for k, l in enumerate(labels) if num in l), None)
            k1, k2 = idx(hits[0][1]), idx(hits[-1][1])
            if k1 is None or k2 is None or k1 == k2:
                continue
            t1 = find([(text, a, b)], f"Article {hits[0][1]}")
            t2 = find([(text, a, b)], f"Article {hits[-1][1]}", t1 + .1)
            js.append(f"anim(Cc[{k1}],[{{fill:'#d9ab4f'}},{{fill:'#e5484d'}}],{t1},.4); mark(Ds[{k1}],{t1 + .4},.6,'rgba(229,72,77,.5)');"
                      f"""const x=document.createElementNS(ns,'text'); const c2=Cc[{k2}];
x.setAttribute('x',c2.getAttribute('cx')); x.setAttribute('y',+c2.getAttribute('cy')+40); x.setAttribute('text-anchor','middle');
x.setAttribute('font-size','150'); x.setAttribute('font-weight','800'); x.setAttribute('fill','#ffffff'); x.textContent='✕';
x.style.transformBox='fill-box'; x.style.transformOrigin='center'; svg.appendChild(x);
anim(Cc[{k2}],[{{fill:'#d9ab4f'}},{{fill:'#e5484d'}}],{t2},.4);
anim(x,[{{opacity:0,transform:'scale(2)'}},{{opacity:.95,transform:'scale(1)'}}],{t2 + .1},.35,{{easing:'ease-in'}});""")
            ev += [("thud", t1 + .1), ("thud", t2 + .3)]
            break

    else:   # chapter and anything else: a calm entrance
        js.append("rise(h,.05,40); const rl=M.querySelector('.rule'); if (rl) anim(rl,[{transform:'scaleX(0)'},{transform:'scaleX(1)'}],.5,.6);"
                  "if (sub) rise(sub,.7,24);")

    # props and stamps from the storyboard (for dramatic cards)
    stamps = card.get("stamps") or []
    end_all = end + extra
    if card.get("prop") and not portrait:
        tp = (items and schedule(times, items[:1])[0][0]) or 0.8
        tp = max(0.3, tp - 0.2)
        if not portrait:
            js.append(f"anim(document.querySelector('.top span:last-child'),[{{opacity:1}},{{opacity:0}}],{tp - .4},.4,{{composite:'replace'}});")
        js.append(f"const P=prop({_js(card['prop'].upper()[:14])},{tp},{str(portrait).lower()});")
    places = ([("left:-6px;top:132px;transform:rotate(-9deg);font-size:40px"), ("left:22px;top:204px;transform:rotate(5deg);font-size:32px"),
               ("left:14px;top:268px;transform:rotate(-4deg);font-size:32px")] if not portrait else
              [("left:-30px;top:70px;transform:rotate(-9deg);font-size:34px"), ("left:120px;top:110px;transform:rotate(5deg);font-size:28px"),
               ("left:-60px;top:140px;transform:rotate(-4deg);font-size:28px")])
    free = (["left:50%;top:75%;transform:translate(-50%,0) rotate(-6deg);font-size:40px",
             "left:8%;top:82%;transform:rotate(5deg);font-size:34px",
             "right:8%;top:82%;transform:rotate(-5deg);font-size:34px"] if portrait else
            ["left:50%;bottom:-40px;transform:translate(-50%,0) rotate(-6deg);font-size:46px",
             "left:8%;bottom:-30px;transform:rotate(5deg);font-size:40px",
             "right:8%;bottom:-30px;transform:rotate(-5deg);font-size:40px"])
    for k, s in enumerate(stamps[:3]):
        at = s.get("at", "end")
        t = (end_all - 0.9 if at == "end" else find(times, at))
        if t is None:
            continue
        color = {"red": "#e5484d", "green": "#3fbf7f", "gold": "#d9ab4f"}.get(s.get("color", "red"), "#e5484d")
        if portrait:
            js.append(f"stamp(M,{_js(s['text'].upper()[:28])},'{color}',"
                      f"'left:50%;top:42%;transform:translate(-50%,-50%) rotate(-7deg);font-size:46px',{t},2.6);")
        else:
            where, css = ("P", places[k]) if card.get("prop") else ("M", free[k])
            js.append(f"stamp({where},{_js(s['text'].upper()[:28])},'{color}',{_js(css)},{t});")
        ev.append(("thud", t + .2))
    return "\n".join(js), ev, round(extra, 2)


# ------------------------------------------------------------------ sounds
def sfx(kind, sr):
    n = int(sr * (0.35 if kind == "thud" else 0.12)); t = np.arange(n) / sr
    if kind == "thud":
        x = np.sin(2 * np.pi * (70 + 40 * np.exp(-t * 30)) * t) * np.exp(-t * 14) * 0.55
        x += np.random.default_rng(1).normal(0, 1, n) * np.exp(-t * 60) * 0.12
    else:
        x = np.sin(2 * np.pi * (900 - 2500 * t) * t) * np.exp(-t * 45) * 0.10
    return x


def add_sounds(pcm, events, sr):
    """int16 narration + [(kind, seconds)] -> int16 with the effects mixed in."""
    a = pcm.astype(np.float32) / 32768
    for kind, t in events:
        s = sfx(kind, sr); i = int(max(0, t) * sr); j = min(len(a), i + len(s))
        if j > i:
            a[i:j] += s[:j - i]
    return (np.clip(a, -1, 1) * 32767).astype(np.int16)


# ------------------------------------------------------------------ recording
def record(jobs, fps=30):
    """jobs: [(card, case, chapter, times, seconds, frames_dir, portrait, js)] -> JPEG frames f00000.jpg... in each dir."""
    if not jobs:
        return
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--allow-file-access-from-files"])
        pages = {False: b.new_page(viewport={"width": W, "height": H}), True: b.new_page(viewport={"width": PW, "height": PH})}
        for card, case, chapter, times, dur, fdir, portrait, js in jobs:
            pg = pages[portrait]
            shutil.rmtree(fdir, ignore_errors=True); os.makedirs(fdir)
            tmp = os.path.join(fdir, "card.html")
            open(tmp, "w", encoding="utf-8").write(card_html(card, case, chapter, portrait))
            pg.goto("file://" + os.path.abspath(tmp))
            pg.evaluate("document.fonts.ready"); pg.wait_for_timeout(150)
            pg.evaluate(KIT)
            pg.evaluate("() => {" + js + "\n}")
            for j in range(int(math.ceil(dur * fps)) + 2):
                pg.evaluate(f"seek({j / fps})")
                pg.screenshot(path=os.path.join(fdir, f"f{j:05d}.jpg"), type="jpeg", quality=93)
            os.remove(tmp)
        b.close()
