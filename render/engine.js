// Manzi Studio - video templates drawn on a canvas, frame by frame.
// R.setup(spec) once, then R.frame(t) draws time t and returns a "key": the same key means the same picture
// (so the renderer can reuse the previous frame), null means something is moving.
"use strict";
(() => {
const cv = document.getElementById("c"), ctx = cv.getContext("2d");
let S = null, ANIM = false, KEY = [];

// ------------------------------------------------------------------ helpers
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const prog = (t, a, b) => (b > a ? clamp((t - a) / (b - a), 0, 1) : (t >= b ? 1 : 0));
const an = (t, a, b) => { const p = prog(t, a, b); if (p > 0 && p < 1) ANIM = true; return p; };   // animated: marks the frame as moving
const eout = x => 1 - Math.pow(1 - clamp(x, 0, 1), 3);
const eback = x => { x = clamp(x, 0, 1); const c = 1.9; return 1 + (c + 1) * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2); };
const key = v => KEY.push(v);
const hi = () => S.lang === "hindi";
function F(w, size, fam = "D") { ctx.font = `${w} ${Math.round(size)}px "${fam}", "P"`; }
function rr(x, y, w, h, r) { ctx.beginPath(); ctx.roundRect(x, y, w, h, Math.min(r, w / 2, h / 2)); }
function T(s, x, y, color, align = "left", base = "middle") { ctx.fillStyle = color; ctx.textAlign = align; ctx.textBaseline = base; ctx.fillText(s, x, y); }
const tr = (en, hiText) => (hi() && hiText ? hiText : en);

// words of a beat with their spoken times (from the voice if known, otherwise shared by length)
function wordsOf(b) {
  if (b._w) return b._w;
  const raw = String(b.say || "").replace(/\*\*/g, "").split(/\s+/).filter(Boolean);
  if (b.words && b.words.length) { b._w = b.words.map(w => ({ w: w.w, a: w.t0, b: w.t1 })); return b._w; }
  const wt = raw.map(w => Math.max(1, w.replace(/[^\p{L}\p{N}]/gu, "").length / 3) + (/[,.;:?!।]$/.test(w) ? 1.2 : 0));
  const tot = wt.reduce((a, c) => a + c, 0) || 1; let acc = 0; const d = Math.max(0.1, b.t1 - b.t0);
  b._w = raw.map((w, i) => { const a = b.t0 + d * acc / tot; acc += wt[i]; return { w, a, b: b.t0 + d * acc / tot }; });
  return b._w;
}
// "**bold**" -> tokens {w, b}
function tokens(text) {
  const out = []; for (const part of String(text || "").split(/(\*\*[^*]+\*\*)/)) {
    const b = /^\*\*[^*]+\*\*$/.test(part); const s = b ? part.slice(2, -2) : part;
    for (const w of s.split(/\s+/).filter(Boolean)) {
      if (out.length && /^[.,;:!?)\]”’।]+$/.test(w)) { out[out.length - 1].w += w; continue; }
      out.push({ w, b });
    }
  }
  return out;
}
// lay out tokens in lines of max width; font(w) sets the font for a token
function layout(toks, maxw, setFont) {
  const lines = [[]]; let lw = 0; setFont(false); const sp = ctx.measureText(" ").width;
  for (const t of toks) {
    setFont(t.b); const w = ctx.measureText(t.w).width;
    if (lines[lines.length - 1].length && lw + sp + w > maxw) { lines.push([]); lw = 0; }
    const ln = lines[lines.length - 1]; t.x = lw + (ln.length ? sp : 0); t.ww = w; ln.push(t); lw = t.x + w;
  }
  return lines;
}
function wrapPlain(s, maxw) { return layout(tokens(String(s).replace(/\*\*/g, "")), maxw, () => {}).map(l => l.map(t => t.w).join(" ")); }
function fitLines(s, w, size, maxw, maxLines, fam = "D", min = 22) {
  for (;;) { F(w, size, fam); const L = wrapPlain(s, maxw); if (L.length <= maxLines || size <= min) return { lines: L, size }; size = Math.floor(size * 0.93); }
}
// how many of the words of beat b have been spoken at time t
function spoken(b, t) { if (!b || t < b.t0) return 0; const ws = wordsOf(b); let n = 0; for (const w of ws) if (w.a <= t) n++; return n; }

// ------------------------------------------------------------------ common pieces
function beatAt(t) { let i = 0; for (let k = 0; k < S.beats.length; k++) if (S.beats[k].t0 <= t) i = k; return i; }
const beats = k => S.beats.filter(b => b.k === k);
const firstOf = k => S.beats.find(b => b.k === k);
function brand(x, y, ink, chipBg, chipInk, size = 32) {
  rr(x, y, size * 1.75, size * 1.75, size * 0.42); ctx.fillStyle = chipBg; ctx.fill();
  F(900, size * 0.9); T("⚖", x + size * 0.875, y + size * 0.92, chipInk, "center");
  F(800, size); T(S.channel.toUpperCase(), x + size * 2.2, y + size * 0.9, ink);
}
function label(s, xr, y, bg, ink, size = 28) {
  F(800, size); const w = ctx.measureText(s).width + size * 1.3;
  rr(xr - w, y, w, size * 1.7, size * 0.35); ctx.fillStyle = bg; ctx.fill(); T(s, xr - w + size * 0.65, y + size * 0.88, ink);
}
// karaoke caption for spoken lines that are not already on screen
function caption(b, t, y, maxw = 900) {
  const ws = wordsOf(b); if (!ws.length || t < b.t0 || t > b.t1 + 0.3) return;
  let cur = 0; ws.forEach((w, i) => { if (w.a <= t) cur = i; });
  const start = Math.floor(cur / 4) * 4, chunk = ws.slice(start, start + 4); key("cap" + cur);
  const size = 62; F(900, size); const sp = ctx.measureText(" ").width;
  const widths = chunk.map(w => ctx.measureText(w.w).width); let tot = widths.reduce((a, c) => a + c, 0) + sp * (chunk.length - 1);
  const sc = tot > maxw ? maxw / tot : 1; ctx.save(); ctx.translate(S.W / 2, y); ctx.scale(sc, sc);
  let x = -tot / 2; ctx.lineJoin = "round";
  chunk.forEach((w, i) => {
    F(900, size); ctx.lineWidth = 14; ctx.strokeStyle = "rgba(0,0,0,0.85)"; ctx.textAlign = "left"; ctx.textBaseline = "middle"; ctx.strokeText(w.w, x, 0);
    ctx.fillStyle = start + i === cur ? "#ffd21f" : "#ffffff"; ctx.fillText(w.w, x, 0); x += widths[i] + sp;
  });
  ctx.restore();
}
function outro(t) {
  const b = firstOf("outro"); if (!b || t < b.t0) return;
  const a = eout(an(t, b.t0, b.t0 + 0.45)); key("outro");
  ctx.save(); ctx.globalAlpha = 0.55 * a; ctx.fillStyle = "#000"; ctx.fillRect(0, 0, S.W, S.H); ctx.restore();
  const y = S.H - 640 * a; ctx.save(); ctx.translate(0, 0);
  rr(50, y, S.W - 100, 520, 40); ctx.fillStyle = "#ffffff"; ctx.fill();
  F(900, 64); T(tr("Follow for a new", "हर दिन एक नया"), S.W / 2, y + 110, "#14161c", "center");
  T(tr("LLB question every day", "LLB प्रश्न"), S.W / 2, y + 190, "#14161c", "center");
  const pulse = 1 + 0.04 * Math.sin((t - b.t0) * 6); if (t < b.t1) ANIM = true;
  ctx.save(); ctx.translate(S.W / 2, y + 330); ctx.scale(pulse, pulse);
  F(800, 46); const s1 = tr("📌  Save this for your exam", "📌  परीक्षा के लिए सेव करें"); const w1 = ctx.measureText(s1).width + 80;
  rr(-w1 / 2, -48, w1, 96, 48); ctx.fillStyle = "#e62117"; ctx.fill(); T(s1, 0, 2, "#fff", "center"); ctx.restore();
  F(700, 36); T(S.channel, S.W / 2, y + 450, "#6b7280", "center");
  ctx.restore();
}
function shake(t, t0) { const p = prog(t, t0, t0 + 0.35); if (p > 0 && p < 1) { ANIM = true; const k = (1 - p) * 14; ctx.translate(Math.sin(t * 90) * k, Math.cos(t * 70) * k * 0.6); } }
function stamp(text, cx, cy, t, t0, color, size = 92, rot = -0.24) {
  if (t < t0) return; const p = an(t, t0, t0 + 0.28); const sc = 1 + 0.9 * (1 - eout(p));
  ctx.save(); ctx.translate(cx, cy); ctx.rotate(rot); ctx.scale(sc, sc); ctx.globalAlpha = 0.9 * Math.min(1, p * 2 + 0.2);
  F(900, size); const w = ctx.measureText(text).width + size * 0.8, h = size * 1.35;
  rr(-w / 2, -h / 2, w, h, size * 0.18); ctx.lineWidth = size * 0.11; ctx.strokeStyle = color; ctx.stroke();
  T(text, 0, 4, color, "center"); ctx.restore(); key("stamp" + text);
}
// rich paragraph that appears as it is spoken; bold words get a highlighter / colour
function richReveal(b, t, x, y, maxw, maxh, opt) {
  const toks = tokens(b.text || b.say); let size = opt.size, L;
  for (;;) { L = layout(toks, maxw, bold => F(bold ? opt.boldW : opt.w, size, opt.fam)); if (L.length * size * opt.lh <= maxh || size < 20) break; size = Math.floor(size * 0.93); }
  const n = opt.all ? 1e9 : Math.max(spoken(b, t), t >= b.t0 ? 1 : 0); const ws = wordsOf(b); let idx = 0; const lh = size * opt.lh;
  key("rv" + Math.min(n, toks.length));
  L.forEach((ln, i) => {
    for (const tk of ln) {
      const my = idx++; if (my >= n) continue;
      const cx = x + tk.x, cy = y + i * lh + lh / 2;
      if (tk.b && opt.marker) {
        const tw = ws[Math.min(my, ws.length - 1)]; const a0 = opt.all ? -1 : (tw ? tw.a : b.t0);
        const p = opt.all ? 1 : eout(an(t, a0, a0 + 0.35));
        ctx.fillStyle = opt.marker; rr(cx - 6, cy - size * 0.55, (tk.ww + 12) * p, size * 1.1, 8); ctx.fill();
      }
      F(tk.b ? opt.boldW : opt.w, size, opt.fam); T(tk.w, cx, cy, tk.b ? (opt.boldInk || opt.ink) : opt.ink);
    }
  });
  return L.length * lh;
}

// ------------------------------------------------------------------ SHORTS (1080 x 1920)
const SH = {};
SH.datadrop = t => {
  const W = S.W, m = S.meta; const g = ctx.createRadialGradient(W / 2, 560, 50, W / 2, 560, 1500); g.addColorStop(0, "#2b1d5a"); g.addColorStop(1, "#0d0820");
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, S.H); brand(72, 72, "#ffcf3f", "#ffcf3f", "#120b2b"); label(tr("EXAM ALERT", "परीक्षा अलर्ट"), W - 72, 76, "#ff4d4d", "#fff");
  const bi = firstOf("intro"), bn = firstOf("number"), bq = firstOf("question"), by = firstOf("years");
  if (t >= bi.t0) { const a = eout(an(t, bi.t0, bi.t0 + 0.4)); ctx.globalAlpha = a; F(700, 60); T(tr("This question came", "यह प्रश्न आया"), W / 2, 330 + (1 - a) * 30, "#cfc6f5", "center"); ctx.globalAlpha = 1; }
  if (bn && t >= bn.t0) {
    const p = an(t, bn.t0, bn.t0 + 0.7); const n = Math.round((m.hits || []).length * eout(p)); const sc = eback(an(t, bn.t0, bn.t0 + 0.5));
    ctx.save(); ctx.translate(W / 2, 640); ctx.scale(sc, sc); ctx.shadowColor = "rgba(255,207,63,0.45)"; ctx.shadowBlur = 80; F(900, 380); T(n + "×", 0, 0, "#ffcf3f", "center"); ctx.restore(); key("n" + n);
    const a = eout(an(t, bn.t0 + 0.4, bn.t0 + 0.8)); ctx.globalAlpha = a; F(800, 76);
    T(tr(`in the last ${m.span || (m.years || []).length} years`, `पिछले ${m.span || (m.years || []).length} सालों में`), W / 2, 900, "#ffffff", "center"); ctx.globalAlpha = 1;
  }
  if (bq && t >= bq.t0) richReveal({ ...bq, text: "“" + (m.question || bq.say) + "”" }, t, 100, 1000, W - 200, 300, { size: 48, w: 600, boldW: 800, fam: "T", lh: 1.3, ink: "#d9d2ff" });
  if (by && t >= by.t0) {
    const ys = m.years || [], hits = new Set(m.hits || []); F(800, 40); let ws = ys.map(y => ctx.measureText(y).width + 52), tot = ws.reduce((a, c) => a + c, 0) + 18 * (ys.length - 1);
    const sc = tot > W - 120 ? (W - 120) / tot : 1; ctx.save(); ctx.translate(W / 2 - tot * sc / 2, 1380); ctx.scale(sc, sc); let x = 0;
    ys.forEach((y, i) => {
      const on = hits.has(y), at = by.t0 + (i + 0.5) * (by.t1 - by.t0) / ys.length, p = on ? eback(an(t, at, at + 0.3)) : 0;
      rr(x, 0, ws[i], 80, 16);
      if (on && t >= at) { ctx.save(); ctx.translate(x + ws[i] / 2, 40); ctx.scale(p, p); rr(-ws[i] / 2, -40, ws[i], 80, 16); ctx.fillStyle = "#ffcf3f"; ctx.fill(); F(800, 40); T(y, 0, 2, "#120b2b", "center"); ctx.restore(); key("y" + i); }
      else { ctx.lineWidth = 3; ctx.strokeStyle = "#4a3d82"; ctx.stroke(); F(800, 40); T(y, x + ws[i] / 2, 42, "#6e62a8", "center"); }
      x += ws[i] + 18;
    });
    ctx.restore();
  }
};
SH.myth = t => {
  const W = S.W, bm = firstOf("myth"), bb = firstOf("bust"), bl = firstOf("law"), bs = firstOf("source");
  let g = ctx.createLinearGradient(0, 0, W, 960); g.addColorStop(0, "#4a0d12"); g.addColorStop(1, "#1d0507"); ctx.fillStyle = g; ctx.fillRect(0, 0, W, S.H);
  ctx.save(); if (bb) shake(t, bb.t0);
  brand(72, 72, "#fff", "#fff", "#111"); label(tr("MYTH vs LAW", "मिथक बनाम कानून"), W - 72, 76, "#ffffff", "#111");
  rr(72, 230, 220, 84, 16); ctx.fillStyle = "#ff3b3b"; ctx.fill(); F(900, 52); T(tr("MYTH", "मिथक"), 182, 274, "#fff", "center");
  const busted = bb && t >= bb.t0;
  let ms = 84, lines;
  for (;;) { lines = layout(tokens(bm.text || bm.say), W - 240, () => F(800, ms)); if (lines.length <= 5 || ms < 50) break; ms -= 4; }
  const lh = ms * 1.22, n = spoken(bm, t); let idx = 0; key("m" + n);
  lines.forEach((ln, i) => { for (const tk of ln) { if (idx++ < Math.max(n, 1)) { F(800, ms); T(tk.w, 72 + tk.x, 400 + i * lh, busted ? "#ffb3b3" : "#ffe1e1"); } } });
  if (busted) {
    lines.forEach((ln, i) => { const w = ln.length ? ln[ln.length - 1].x + ln[ln.length - 1].ww : 0; const p = eout(an(t, bb.t0 + i * 0.12, bb.t0 + i * 0.12 + 0.3));
      ctx.fillStyle = "#ff3b3b"; ctx.fillRect(66, 400 + i * lh - 5, (w + 12) * p, 10); });
    stamp("✕", W - 190, Math.min(850, 400 + lines.length * lh + 110), t, bb.t0 + 0.15, "#ff3b3b", 150, 0.1);
  }
  ctx.restore();
  if (bl && t >= bl.t0) {
    const p = eout(an(t, bl.t0, bl.t0 + 0.5)); const y0 = 960 + (1 - p) * 960;
    g = ctx.createLinearGradient(0, y0, W, S.H); g.addColorStop(0, "#0b3d24"); g.addColorStop(1, "#04140c"); ctx.fillStyle = g; ctx.fillRect(0, y0, W, S.H - y0);
    rr(72, y0 + 80, 200, 84, 16); ctx.fillStyle = "#2ee07a"; ctx.fill(); F(900, 52); T(tr("LAW", "कानून"), 172, y0 + 124, "#05170e", "center");
    richReveal({ ...bl, text: bl.text || bl.say }, t, 72, y0 + 200, W - 230, 330, { size: 62, w: 800, boldW: 900, fam: "D", lh: 1.22, ink: "#ffffff", boldInk: "#2ee07a" });
    if (t >= bl.t0 + 0.4) { const s = eback(an(t, bl.t0 + 0.4, bl.t0 + 0.75)); ctx.save(); ctx.translate(W - 160, y0 + 120); ctx.scale(s, s); F(900, 140); T("✓", 0, 0, "#2ee07a", "center"); ctx.restore(); key("ok"); }
    if (bs && t >= bs.t0) { const a = eout(an(t, bs.t0, bs.t0 + 0.4)); ctx.globalAlpha = a; F(700, 40); const s = "📖 " + (bs.text || bs.say);
      const w = Math.min(W - 144, ctx.measureText(s).width + 60); rr(72, 1520, w, 84, 42); ctx.fillStyle = "rgba(46,224,122,0.16)"; ctx.fill(); T(s, 102, 1563, "#bff5d6"); ctx.globalAlpha = 1; key("src"); }
  }
};
SH.quiz = t => {
  const W = S.W, q = firstOf("q"), bo = firstOf("opts"), bt = firstOf("timer"), br = firstOf("reveal"), be = firstOf("explain");
  const g = ctx.createLinearGradient(0, 0, 0, S.H); g.addColorStop(0, "#0c2340"); g.addColorStop(1, "#06111f"); ctx.fillStyle = g; ctx.fillRect(0, 0, W, S.H);
  brand(72, 72, "#ffcf3f", "#ffcf3f", "#0c2340"); label(tr(`QUIZ #${S.meta.qnum || 1}`, `क्विज़ #${S.meta.qnum || 1}`), W - 72, 76, "#ffcf3f", "#0c2340");
  richReveal({ ...q, text: q.text || q.say }, t, 80, 250, W - 160, 380, { size: 70, w: 800, boldW: 900, fam: "D", lh: 1.16, ink: "#ffffff", boldInk: "#ffcf3f" });
  const opts = S.meta.options || [], ans = S.meta.answer, letters = ["A", "B", "C", "D"];
  const revealed = br && t >= br.t0;
  // ring / explanation area
  if (be && t >= be.t0) {
    const a = eout(an(t, be.t0, be.t0 + 0.4)); ctx.globalAlpha = a;
    rr(80, 610, W - 160, 300, 26); ctx.fillStyle = "rgba(46,224,122,0.14)"; ctx.fill();
    richReveal({ ...be, text: be.text || be.say }, t, 120, 636, W - 240, 250, { size: 48, w: 600, boldW: 800, fam: "T", lh: 1.3, ink: "#d8ffe9", boldInk: "#2ee07a" });
    ctx.globalAlpha = 1;
  } else if (bt && t >= bt.t0) {
    const total = bt.t1 - bt.t0, left = clamp(bt.t1 - t, 0, total), p = revealed ? 1 : 1 - left / total; if (!revealed) ANIM = true;
    ctx.beginPath(); ctx.arc(W / 2, 760, 100, 0, Math.PI * 2); ctx.fillStyle = "#13325a"; ctx.fill();
    ctx.beginPath(); ctx.arc(W / 2, 760, 100, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * (1 - p)); ctx.lineWidth = 18; ctx.strokeStyle = revealed ? "#2ee07a" : "#ffcf3f"; ctx.stroke();
    const s = revealed ? "✓" : String(Math.max(1, Math.ceil(left))); const pop = 1 + 0.12 * (1 - (left % 1)); F(900, revealed ? 110 : 96 * pop); T(s, W / 2, 764, revealed ? "#2ee07a" : "#ffcf3f", "center");
  }
  opts.forEach((o, i) => {
    if (!bo || t < bo.t0) return; const at = bo.t0 + i * (bo.t1 - bo.t0) / opts.length; if (t < at) return;
    const a = eout(an(t, at, at + 0.3)), y = 940 + i * 148; const right = revealed && i === ans, dim = revealed && i !== ans;
    ctx.save(); ctx.globalAlpha = a * (dim ? 0.4 : 1); ctx.translate((1 - a) * -60, 0);
    const pop = right ? eback(an(t, br.t0, br.t0 + 0.35)) : 1; ctx.translate(W / 2, y + 60); ctx.scale(pop, pop); ctx.translate(-W / 2, -(y + 60));
    rr(80, y, W - 160, 120, 24); ctx.fillStyle = right ? "#0f5132" : "#13325a"; ctx.fill(); ctx.lineWidth = 4; ctx.strokeStyle = right ? "#2ee07a" : "#24507f"; ctx.stroke();
    ctx.beginPath(); ctx.arc(150, y + 60, 34, 0, Math.PI * 2); ctx.fillStyle = right ? "#2ee07a" : "#24507f"; ctx.fill(); F(900, 38); T(letters[i], 150, y + 62, right ? "#05170e" : "#fff", "center");
    const f = fitLines(o, 700, 46, W - 360, 1, "T", 28); F(700, f.size, "T"); T(f.lines[0], 210, y + 62, "#fff");
    ctx.restore(); key("o" + i + (right ? "r" : dim ? "d" : ""));
  });
  if (!revealed && bt && t >= bt.t0) { F(600, 36, "T"); T(tr("Comment your answer before the timer ends ⏱", "टाइमर खत्म होने से पहले जवाब कमेंट करें ⏱"), W / 2, 1560, "#9fb6d6", "center"); }
};
SH.case = t => {
  const W = S.W, bo = firstOf("open"), parts = ["facts", "issue", "held"].map(firstOf), bh = firstOf("held"), bp = firstOf("principle");
  ctx.fillStyle = "#33241a"; ctx.fillRect(0, 0, W, S.H);
  for (let i = 0; i < 40; i++) { ctx.fillStyle = `rgba(0,0,0,${0.03 + (i % 3) * 0.01})`; ctx.fillRect(0, i * 48, W, 2); }
  ctx.save(); if (bh) shake(t, bh.t0 + 0.6);
  brand(72, 72, "#e8cf9a", "#e8cf9a", "#3a2a1a"); label(tr("CASE FILE", "केस फ़ाइल"), W - 72, 76, "#c4161c", "#fff");
  const a = eout(an(t, bo.t0, bo.t0 + 0.6)); ctx.save(); ctx.translate(0, (1 - a) * 900);
  rr(50, 230, W - 100, 1360, 18); ctx.fillStyle = "#d9b979"; ctx.fill(); rr(90, 190, 340, 70, 14); ctx.fillStyle = "#e2c78e"; ctx.fill();
  ctx.save(); ctx.translate(W / 2, 900); ctx.rotate(-0.02); ctx.translate(-W / 2, -900);
  ctx.shadowColor = "rgba(0,0,0,0.3)"; ctx.shadowBlur = 24; ctx.fillStyle = "#fbf6ea"; ctx.fillRect(100, 300, W - 200, 1230); ctx.shadowBlur = 0;
  for (let y = 380; y < 1520; y += 62) { ctx.fillStyle = "#ebe1c9"; ctx.fillRect(100, y, W - 200, 2); }
  F(700, 46, "M"); T(tr(`CASE FILE № ${String(S.meta.qnum || 1).padStart(2, "0")}`, `केस फ़ाइल № ${String(S.meta.qnum || 1).padStart(2, "0")}`), 150, 360, "#2a2116");
  const nm = fitLines(S.meta.caseName || "", 700, 66, W - 320, 2, "L", 40); ctx.font = `italic 700 ${nm.size}px "L", "P"`;
  nm.lines.forEach((l, i) => T(l, 150, 450 + i * nm.size * 1.15, "#8c1616"));
  let y = 450 + nm.lines.length * nm.size * 1.15 + 30;
  // FACTS / ISSUE / HELD typed in
  const heads = { facts: tr("FACTS:", "तथ्य:"), issue: tr("ISSUE:", "मुद्दा:"), held: tr("HELD:", "निर्णय:") };
  let size = 38; const avail = 1480 - y;
  const blocks = ["facts", "issue", "held"].map(k => firstOf(k)).filter(Boolean);
  for (;;) { F(400, size, "M"); const need = blocks.reduce((s, b) => s + (wrapPlain(heads[b.k] + " " + (b.text || b.say), W - 320).length) * size * 1.5 + 14, 0); if (need <= avail || size < 24) break; size -= 2; }
  blocks.forEach(b => {
    if (t < b.t0) return; const toks = tokens(heads[b.k] + " " + (b.text || b.say)); const L = layout(toks, W - 320, () => F(400, size, "M"));
    const n = spoken(b, t) + 1; let idx = 0; key(b.k + n);
    L.forEach((ln, i) => { for (const tk of ln) { if (idx++ > n) continue; F(idx === 1 ? 700 : 400, size, "M"); T(tk.w, 150 + tk.x, y + i * size * 1.5 + size * 0.75, idx === 1 ? "#8c1616" : "#2a2116"); } });
    y += L.length * size * 1.5 + 14;
  });
  ctx.restore(); ctx.restore();
  if (bh && t >= bh.t0 + 0.6) stamp(tr("LANDMARK", "ऐतिहासिक"), W - 300, 1250, t, bh.t0 + 0.6, "#c4161c", 84);
  ctx.restore();
  if (bp && t >= bp.t0) {
    const p = eout(an(t, bp.t0, bp.t0 + 0.4)); ctx.save(); ctx.globalAlpha = p; ctx.translate(0, (1 - p) * 40);
    rr(70, 1380, W - 140, 220, 20); ctx.fillStyle = "#ffe14d"; ctx.fill();
    F(800, 30, "T"); T(tr("PRINCIPLE", "सिद्धांत"), 110, 1420, "#7a5b00");
    richReveal({ ...bp, text: bp.text || bp.say }, t, 110, 1445, W - 220, 140, { size: 40, w: 700, boldW: 800, fam: "T", lh: 1.25, ink: "#2a2100" });
    ctx.restore();
  }
};
SH.compare = t => {
  const W = S.W, m = S.meta, rows = beats("row"), bt = firstOf("title");
  ctx.fillStyle = "#f4f1ea"; ctx.fillRect(0, 0, W, S.H);
  brand(72, 72, "#13294b", "#13294b", "#fff"); label(tr("OLD vs NEW", "पुराना बनाम नया"), W - 72, 76, "#ff4d4d", "#fff");
  const a = eout(an(t, bt.t0, bt.t0 + 0.4)); ctx.globalAlpha = a; const f = fitLines(m.title || bt.say, 900, 84, W - 140, 2); F(900, f.size);
  f.lines.forEach((l, i) => T(l, W / 2, 250 + i * f.size * 1.1, "#1b1b1b", "center")); ctx.globalAlpha = 1;
  const top = 250 + f.lines.length * f.size * 1.1 + 40, colW = (W - 144) / 2;
  [["left", 60, "#e4e0d6", "#6b6457"], ["right", 84 + colW, "#13294b", "#ffffff"]].forEach(([side, x, bg, ink]) => {
    const p = eout(an(t, bt.t0 + (side === "left" ? 0.2 : 0.4), bt.t0 + (side === "left" ? 0.6 : 0.8)));
    ctx.save(); ctx.globalAlpha = p; ctx.translate(0, (1 - p) * 60);
    rr(x, top, colW, 1500 - top, 30); ctx.fillStyle = bg; ctx.fill();
    F(900, 64); T(m[side].name, x + 36, top + 100, ink); const sub = fitLines(m[side].sub || "", 600, 30, colW - 72, 2, "T", 20); F(600, sub.size, "T");
    sub.lines.forEach((l, i) => T(l, x + 36, top + 155 + i * sub.size * 1.2, ink));
    ctx.restore();
  });
  const rowH = Math.min(260, (1500 - top - 250) / Math.max(rows.length, 3));
  rows.forEach((b, i) => {
    if (t < b.t0) return; const y = top + 250 + i * rowH;
    const r = m.rows[b.i]; const pl = eout(an(t, b.t0, b.t0 + 0.3)), pr = eout(an(t, b.t0 + (b.t1 - b.t0) * 0.45, b.t0 + (b.t1 - b.t0) * 0.45 + 0.35));
    [[60, r.left, "#6b6457", pl, false], [84 + colW, r.right, "#ffcf3f", pr, true]].forEach(([x, val, ink, p, isNew]) => {
      if (p <= 0) return; ctx.save(); ctx.translate(x + colW / 2, y + rowH / 2); ctx.scale(1, p); ctx.translate(-(x + colW / 2), -(y + rowH / 2));
      F(600, 28, "T"); T(r.label, x + 36, y + 24, isNew ? "#9fb3d6" : "#8f877a");
      const v = fitLines(val, 800, 46, colW - 72, 2, "D", 26); F(800, v.size); v.lines.forEach((l, j) => T(l, x + 36, y + 76 + j * v.size * 1.12, isNew ? ink : "#4a443a"));
      ctx.restore();
    });
    key("row" + i + (pr >= 1 ? "r" : ""));
  });
  const pulse = 1 + 0.06 * Math.sin(t * 4); ctx.save(); ctx.translate(W / 2, top - 4); ctx.scale(pulse, pulse);
  ctx.beginPath(); ctx.arc(0, 0, 64, 0, Math.PI * 2); ctx.fillStyle = "#ff4d4d"; ctx.fill(); F(900, 50); T("VS", 0, 3, "#fff", "center"); ctx.restore(); ANIM = true;
  const bn = firstOf("note"); if (bn) caption(bn, t, 1620);
};
SH.flow = t => {
  const W = S.W, m = S.meta, st = beats("step"), bt = firstOf("title");
  const g = ctx.createLinearGradient(0, 0, 0, S.H); g.addColorStop(0, "#0f2a24"); g.addColorStop(1, "#071511"); ctx.fillStyle = g; ctx.fillRect(0, 0, W, S.H);
  brand(72, 72, "#3ddc97", "#3ddc97", "#0f2a24"); label(tr("STEP BY STEP", "क्रम से"), W - 72, 76, "#3ddc97", "#0f2a24");
  const f = fitLines(m.title || bt.say, 900, 80, W - 160, 2); F(900, f.size); f.lines.forEach((l, i) => T(l, 80, 260 + i * f.size * 1.1, "#eafff6"));
  const top = 260 + f.lines.length * f.size * 1.1 + 60, n = m.steps.length, gap = Math.min(190, (1540 - top) / n);
  let cur = -1; st.forEach((b, i) => { if (t >= b.t0) cur = b.i; }); key("cur" + cur);
  m.steps.forEach((s, i) => {
    const y = top + i * gap + 55, state = i < cur ? "done" : i === cur ? "now" : "next";
    if (i < n - 1) { const b = st.find(x => x.i === i + 1); const p = b ? eout(an(t, b.t0, b.t0 + 0.4)) : 0;
      ctx.fillStyle = "rgba(61,220,151,0.25)"; ctx.fillRect(132, y + 55, 6, gap - 110); ctx.fillStyle = "#3ddc97"; ctx.fillRect(132, y + 55, 6, (gap - 110) * p); }
    const b = st.find(x => x.i === i); const pop = b && t >= b.t0 ? eback(an(t, b.t0, b.t0 + 0.4)) : 1;
    ctx.save(); ctx.globalAlpha = state === "next" ? 0.35 : 1; ctx.translate(135, y); ctx.scale(pop, pop);
    if (state === "now") { ctx.beginPath(); ctx.arc(0, 0, 76, 0, Math.PI * 2); ctx.fillStyle = "rgba(255,207,63,0.18)"; ctx.fill(); }
    ctx.beginPath(); ctx.arc(0, 0, 52, 0, Math.PI * 2); ctx.fillStyle = state === "now" ? "#ffcf3f" : state === "done" ? "#3ddc97" : "#0f2a24"; ctx.fill();
    ctx.lineWidth = 6; ctx.strokeStyle = state === "now" ? "#ffcf3f" : "#3ddc97"; ctx.stroke();
    F(900, 50); T(state === "done" ? "✓" : String(i + 1), 0, 3, state === "next" ? "#3ddc97" : "#0f2a24", "center"); ctx.restore();
    ctx.save(); ctx.globalAlpha = state === "next" ? 0.38 : 1;
    const tf = fitLines(s.title, 800, state === "now" ? 60 : 52, W - 300, 1, "D", 30); F(800, tf.size); T(tf.lines[0], 230, y - (s.sub ? 18 : 0), state === "now" ? "#ffcf3f" : "#eafff6");
    if (s.sub) { const sf = fitLines(s.sub, 600, 34, W - 320, 1, "T", 22); F(600, sf.size, "T"); T(sf.lines[0], 230, y + 38, "#a8d8c3"); }
    ctx.restore();
  });
};

// ------------------------------------------------------------------ LONG VIDEO: "Topper's notes" (1920 x 1080)
const PAPER = "#fdfbf4", RULE = "#c9dcf0", INK = "#1d2433", BLUE = "#1d3b8a", RED = "#c0392b", MARK = "rgba(255,226,0,0.78)";
function notebook() {
  const W = S.W, H = S.H; ctx.fillStyle = PAPER; ctx.fillRect(0, 0, W, H);
  for (let y = 236; y < H; y += 64) { ctx.fillStyle = RULE; ctx.fillRect(0, y, W, 2); }
  ctx.fillStyle = "#f0a0a0"; ctx.fillRect(190, 0, 4, H);
  for (const y of [190, 540, 890]) { ctx.beginPath(); ctx.arc(92, y, 26, 0, Math.PI * 2); ctx.fillStyle = "#e7e2d4"; ctx.fill(); }
}
function header() {
  const m = S.meta; F(800, 26); const qs = `Q${m.qnum || 1}`; const qw = ctx.measureText(qs).width + 26;
  rr(250, 52, qw, 42, 10); ctx.fillStyle = BLUE; ctx.fill(); T(qs, 263, 74, "#fff");
  const f = fitLines(m.question || "", 600, 30, S.W - 250 - qw - 120, 2, "T", 20); F(600, f.size, "T");
  f.lines.forEach((l, i) => T(l, 250 + qw + 18, 74 + i * f.size * 1.3, "#5b6478"));
  F(700, 24, "T"); T(S.channel.toUpperCase(), S.W - 70, 150, "#9aa3b5", "right");
}
// a "page" is drawn whole for a given time; pages slide when they change
function pageOf(i) { const b = S.beats[i]; return b.page != null ? b.page : i; }
const PAGES = {};
PAGES.cover = (b, t) => {
  notebook(); const m = S.meta, W = S.W;
  F(700, 28, "T"); T([m.course, m.subject].filter(Boolean).join("  ·  "), 250, 150, "#7a8597");
  // circled question number, like a teacher's mark
  ctx.save(); ctx.translate(330, 340); ctx.rotate(-0.08); ctx.beginPath(); ctx.ellipse(0, 0, 86, 70, 0, 0, Math.PI * 2); ctx.lineWidth = 7; ctx.strokeStyle = RED; ctx.stroke();
  F(900, 72); T(`Q${m.qnum || 1}`, 0, 4, RED, "center"); ctx.restore();
  const f = fitLines(m.question, 700, 76, W - 520 - 250, 4, "P", 40); F(700, f.size, "P");
  const n = Math.max(1, spoken(b, t)); let shown = 0; const words = f.lines.map(l => l.split(" "));
  key("cov" + Math.min(n, 999));
  words.forEach((ws, i) => { let x = 470; for (const w of ws) { if (shown++ >= n + 2) break; F(700, f.size, "P"); T(w, x, 330 + i * f.size * 1.18, BLUE); x += ctx.measureText(w + " ").width; } });
  const yb = 330 + f.lines.length * f.size * 1.18 + 50; let x = 470;
  const chips = [m.marks ? (hi() ? `${m.marks} अंक` : `${m.marks} marks`) : "", (m.hits || []).length ? tr("Asked: ", "पूछा गया: ") + m.hits.join(", ") : ""].filter(Boolean);
  chips.forEach(c => { F(700, 30, "T"); const w = ctx.measureText(c).width + 40; rr(x, yb, w, 56, 28); ctx.lineWidth = 3; ctx.strokeStyle = BLUE; ctx.stroke(); T(c, x + 20, yb + 29, BLUE); x += w + 16; });
  stamp(tr("IMPORTANT", "ज़रूरी"), W - 330, 860, t, b.t0 + 0.6, "#c4161c", 70, -0.18);
};
PAGES.para = (b, t) => {
  notebook(); header(); const W = S.W;
  F(700, 52, "P"); T(b.section + (b.cont ? tr(" (contd.)", " (जारी)") : ""), 250, 200, BLUE);
  const hw = ctx.measureText(b.section).width; ctx.strokeStyle = BLUE; ctx.lineWidth = 4; ctx.beginPath();
  for (let x = 250; x < 250 + hw; x += 8) ctx.lineTo(x, 232 + Math.sin(x / 9) * 3); ctx.stroke();
  richReveal(b, t, 250, 268, W - 250 - 140, 64 * 11, { size: 46, w: 500, boldW: 700, fam: "P", lh: 64 / 44, ink: INK, marker: MARK });
};
PAGES.points = (b, t, i) => {
  notebook(); header(); const W = S.W, all = S.beats.filter(x => x.page === b.page && x.k === "point"), cur = all.indexOf(b);
  F(700, 52, "P"); T(b.section, 250, 200, BLUE);
  let y = 300; const n = all.length; const size = n > 6 ? 36 : 42;
  all.forEach((p, j) => {
    if (j > cur) return; const st = j < cur ? "done" : "now";
    F(800, size, "P"); T(`${j + 1}.`, 250, y, RED);
    const f = fitLines(p.title, 700, size, 760, 2, "P", 26);
    if (st === "now") { const sw = eout(an(t, p.t0, p.t0 + 0.5)); F(700, f.size, "P"); f.lines.forEach((l, k) => { const w = ctx.measureText(l).width; ctx.fillStyle = MARK; rr(302, y - f.size * 0.55 + k * f.size * 1.3, (w + 16) * sw, f.size * 1.1, 8); ctx.fill(); }); }
    F(700, f.size, "P"); f.lines.forEach((l, k) => T(l, 310, y + k * f.size * 1.3, st === "done" ? "#4a5466" : INK));
    y += Math.max(64, f.lines.length * f.size * 1.3 + 26);
  });
  key("pt" + cur);
  // the card on the right explains the current point
  const fl = eout(an(t, b.t0, b.t0 + 0.4)); ctx.save(); ctx.translate(1520, 560); ctx.rotate(0.012); ctx.scale(1, fl); ctx.translate(-1520, -560);
  ctx.shadowColor = "rgba(0,0,0,0.15)"; ctx.shadowBlur = 24; ctx.shadowOffsetY = 10; rr(1140, 270, 690, 640, 14); ctx.fillStyle = "#ffffff"; ctx.fill(); ctx.shadowColor = "transparent";
  ctx.fillStyle = "rgba(255,200,120,0.55)"; ctx.save(); ctx.translate(1180, 268); ctx.rotate(-0.3); ctx.fillRect(-40, -16, 120, 34); ctx.restore();
  ctx.fillStyle = BLUE; ctx.fillRect(1140, 270, 690, 10);
  const tf = fitLines(b.title, 700, 44, 610, 2, "P", 28); F(700, tf.size, "P"); tf.lines.forEach((l, k) => T(l, 1180, 340 + k * tf.size * 1.25, BLUE));
  richReveal({ ...b, text: b.text }, t, 1180, 340 + tf.lines.length * tf.size * 1.25 + 10, 610, 880 - (340 + tf.lines.length * tf.size * 1.25 + 10), { size: 34, w: 500, boldW: 700, fam: "P", lh: 1.45, ink: INK, marker: MARK });
  ctx.restore();
};
PAGES.case = (b, t) => {
  notebook(); header(); const W = S.W;
  F(700, 52, "P"); T(tr("Case Law", "केस लॉ"), 250, 200, BLUE);
  ctx.save(); ctx.translate(W / 2 + 60, 600); ctx.rotate(-0.012); ctx.translate(-(W / 2 + 60), -600);
  ctx.shadowColor = "rgba(0,0,0,0.18)"; ctx.shadowBlur = 30; ctx.shadowOffsetY = 12; ctx.fillStyle = "#fffef9"; ctx.fillRect(330, 270, 1400, 680); ctx.shadowColor = "transparent";
  for (let y = 380; y < 940; y += 56) { ctx.fillStyle = "#dfe9f5"; ctx.fillRect(330, y, 1400, 2); } ctx.fillStyle = "#e57373"; ctx.fillRect(330, 350, 1400, 3);
  ctx.fillStyle = "rgba(255,200,120,0.55)"; for (const [x, r] of [[380, -0.4], [1680, 0.4]]) { ctx.save(); ctx.translate(x, 275); ctx.rotate(r); ctx.fillRect(-60, -18, 120, 36); ctx.restore(); }
  const nf = fitLines(b.name, 700, 60, 1260, 2, "L", 36); ctx.font = `italic 700 ${nf.size}px "L", "P"`; nf.lines.forEach((l, k) => T("📌 ".repeat(k === 0 ? 0 : 0) + l, 390, 320 + k * nf.size * 1.15, "#8c1616"));
  richReveal({ ...b, text: b.text }, t, 390, 330 + nf.lines.length * nf.size * 1.15 + 20, 1270, 560 - nf.lines.length * nf.size * 1.15, { size: 40, w: 500, boldW: 700, fam: "P", lh: 1.4, ink: INK, marker: MARK });
  ctx.restore();
};
PAGES.end = (b, t) => {
  notebook(); const W = S.W; F(900, 84, "P"); T(tr("Thanks for watching! 🙏", "देखने के लिए धन्यवाद! 🙏"), 250, 230, BLUE);
  const items = [tr("Comment “NOTES” for the free PDF", "फ्री PDF के लिए “NOTES” कमेंट करें"), tr("Like & share with your classmates", "लाइक करें और दोस्तों को भेजें"), tr(`Subscribe to ${S.channel}`, `${S.channel} को सब्सक्राइब करें`)];
  items.forEach((s, i) => {
    const y = 400 + i * 128, at = b.t0 + 0.6 + i * 0.9; ctx.lineWidth = 5; ctx.strokeStyle = BLUE; rr(260, y - 34, 68, 68, 10); ctx.stroke();
    if (t >= at) { const p = eout(an(t, at, at + 0.3)); ctx.strokeStyle = "#1e9e55"; ctx.lineWidth = 10; ctx.beginPath(); ctx.moveTo(270, y); ctx.lineTo(270 + 22 * Math.min(1, p * 2), y + 22 * Math.min(1, p * 2));
      if (p > 0.5) ctx.lineTo(292 + 50 * (p - 0.5) * 2, y + 22 - 56 * (p - 0.5) * 2); ctx.stroke(); key("tick" + i); }
    F(700, 50, "P"); T(s, 370, y + 2, INK);
  });
};
function tipOverlay(b, t) {
  const p = an(t, b.t0, b.t0 + 0.35), sc = 1 + 0.35 * (1 - eout(p));
  ctx.save(); ctx.translate(1500, 700); ctx.rotate(0.05); ctx.scale(sc, sc); ctx.globalAlpha = Math.min(1, p * 2 + 0.1);
  ctx.shadowColor = "rgba(0,0,0,0.25)"; ctx.shadowBlur = 30; ctx.shadowOffsetY = 14; ctx.fillStyle = "#fff36b"; ctx.fillRect(-300, -230, 600, 460); ctx.shadowColor = "transparent";
  F(800, 34, "T"); T(tr("EXAM TIP ✍️", "परीक्षा टिप ✍️"), -255, -175, "#b45309");
  const L = layout(tokens(b.text || b.say), 510, bold => F(bold ? 700 : 600, 38, "P")); L.slice(0, 7).forEach((ln, i) => ln.forEach(tk => { F(tk.b ? 700 : 600, 38, "P"); T(tk.w, -255 + tk.x, -105 + i * 54, "#3d3200"); }));
  ctx.restore(); key("tip");
}
function popup(t, u) {   // subscribe reminder, u = seconds since it appeared
  const W = S.W, H = S.H; const a = u < 0.45 ? eout(u / 0.45) : u > 4.8 ? 1 - prog(u, 4.8, 5.2) : 1; ANIM = true;
  F(800, 30); const nw = ctx.measureText(S.channel).width; F(600, 22, "T"); const tag = tr("Important questions every week", "हर हफ्ते ज़रूरी प्रश्न"), tw = ctx.measureText(tag).width;
  F(800, 30); const bt = tr("SUBSCRIBE", "सब्सक्राइब"); const bw = ctx.measureText(bt).width + 96;
  const w = 14 + 70 + 18 + Math.max(nw, tw) + 24 + bw + 14, h = 98, x = W - 60 - w + (1 - a) * (w + 80), y = H - 60 - h;
  ctx.save(); ctx.shadowColor = "rgba(0,0,0,0.3)"; ctx.shadowBlur = 30; ctx.shadowOffsetY = 8; rr(x, y, w, h, h / 2); ctx.fillStyle = "#fff"; ctx.fill(); ctx.shadowColor = "transparent";
  ctx.beginPath(); ctx.arc(x + 49, y + h / 2, 35, 0, Math.PI * 2); ctx.fillStyle = BLUE; ctx.fill(); F(900, 32); T("⚖", x + 49, y + h / 2 + 1, "#fff", "center");
  F(800, 30); T(S.channel, x + 102, y + h / 2 - 15, "#14161c"); F(600, 22, "T"); T(tag, x + 102, y + h / 2 + 20, "#6b7280");
  const bx = x + w - 14 - bw, done = u > 2.5; rr(bx, y + h / 2 - 35, bw, 70, 35); ctx.fillStyle = done ? "#606060" : "#e62117"; ctx.fill();
  const wig = u > 0.6 && u < 1.6 ? Math.sin(u * 30) * 0.25 * (1.6 - u) : 0; ctx.save(); ctx.translate(bx + 38, y + h / 2); ctx.rotate(wig); F(600, 30, "T"); T("🔔", 0, 2, "#fff", "center"); ctx.restore();
  F(800, 30); T(done ? tr("SUBSCRIBED", "सब्सक्राइब्ड") : bt, bx + 66, y + h / 2 + 2, "#fff"); ctx.restore();
}
function drawPage(i, t) {
  const b = S.beats[i]; const kind = b.k === "point" ? "points" : b.k === "tip" ? null : b.k;
  if (b.k === "tip") { drawPage(i - 1, Math.min(t, S.beats[i - 1].t1 + 10)); tipOverlay(b, t); return; }
  PAGES[kind](b, t, i);
}
function long(t) {
  const i = beatAt(t), b = S.beats[i];
  // find where the current page started, and the page before it
  let s = i; while (s > 0 && pageOf(s - 1) === pageOf(i)) s--;
  const start = S.beats[s].t0, dt = t - start;
  if (s > 0 && dt < 0.55 && S.beats[i].k !== "tip") {
    const p = eout(an(t, start, start + 0.55)); ctx.save(); ctx.translate(-S.W * p * 0.35, 0); drawPage(s - 1, start); ctx.restore();
    ctx.save(); ctx.translate(S.W * (1 - p), 0); ctx.shadowColor = "rgba(0,0,0,0.3)"; ctx.shadowBlur = 40; ctx.fillStyle = PAPER; ctx.fillRect(0, 0, S.W, S.H); ctx.shadowColor = "transparent"; drawPage(i, t); ctx.restore();
  } else drawPage(i, t);
  key("b" + i);
  for (const p of S.pops || []) if (t >= p && t < p + 5.2) popup(t, t - p);
  ctx.fillStyle = BLUE; ctx.fillRect(0, S.H - 8, S.W * Math.floor(t * 2) / 2 / S.duration, 8); key("pb" + Math.floor(t * 2));
}

// ------------------------------------------------------------------ thumbnails
function thumbLong() {
  S.W = 1280; S.H = 720; cv.width = 1280; cv.height = 720; ctx.save(); ctx.scale(1280 / 1920, 720 / 1080); S.W = 1920; S.H = 1080; notebook(); ctx.restore();
  S.W = 1280; S.H = 720; const m = S.meta;
  F(800, 30); rr(150, 40, 56, 56, 12); ctx.fillStyle = BLUE; ctx.fill(); F(900, 28); T("⚖", 178, 70, "#fff", "center"); F(800, 30); T(S.channel.toUpperCase(), 222, 69, BLUE);
  const title = m.topic || m.question; const f = fitLines(title, 900, 100, 1020, 3, "P", 50); F(900, f.size, "P");
  const words = title.split(" "); const k = Math.min(3, Math.ceil(words.length / 3));
  f.lines.forEach((l, i) => { const y = 235 + i * f.size * 1.12; const lw = ctx.measureText(l).width; const isLast = i === f.lines.length - 1;
    if (isLast) { ctx.fillStyle = MARK; rr(146, y - f.size * 0.55, lw + 20, f.size * 1.1, 10); ctx.fill(); } T(l, 156, y, isLast ? INK : BLUE); });
  const yb = 235 + f.lines.length * f.size * 1.12 + 30; let x = 156;
  [`Q${m.qnum || 1}`, m.marks ? (hi() ? `${m.marks} अंक` : `${m.marks} MARKS`) : "", m.course].filter(Boolean).forEach((c, i) => { F(800, 32); const w = ctx.measureText(c).width + 44; rr(x, Math.min(620, yb), w, 62, 14); if (i === 0) { ctx.fillStyle = RED; ctx.fill(); T(c, x + 22, Math.min(620, yb) + 32, "#fff"); } else { ctx.lineWidth = 3; ctx.strokeStyle = BLUE; ctx.stroke(); T(c, x + 22, Math.min(620, yb) + 32, BLUE); } x += w + 14; });
  ctx.save(); ctx.translate(1110, 78); ctx.rotate(0.06); F(900, 40); const lab = tr("IMPORTANT", "ज़रूरी"); const lw = ctx.measureText(lab).width + 50; rr(-lw / 2, -40, lw, 80, 14); ctx.fillStyle = "#e23642"; ctx.fill(); T(lab, 0, 2, "#fff", "center"); ctx.restore();
}
function thumbShort() {
  const m = S.meta, W = 1080, H = 1920; cv.width = W; cv.height = H; S.W = W; S.H = H; const tmpl = S.template;
  const bg = { datadrop: ["#2b1d5a", "#0d0820", "#ffcf3f"], myth: ["#4a0d12", "#0b3d24", "#2ee07a"], quiz: ["#0c2340", "#06111f", "#ffcf3f"], case: ["#5a4128", "#2a1d12", "#e8cf9a"], compare: ["#13294b", "#0a1730", "#ffcf3f"], flow: ["#0f2a24", "#071511", "#3ddc97"] }[tmpl] || ["#1d3354", "#0a1220", "#f2c94c"];
  const g = ctx.createLinearGradient(0, 0, 0, H); g.addColorStop(0, bg[0]); g.addColorStop(1, bg[1]); ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  brand(72, 90, bg[2], bg[2], bg[1]);
  const kicker = { datadrop: tr(`ASKED ${(m.hits || []).length}× IN EXAMS`, `${(m.hits || []).length}× पूछा गया`), myth: tr("MYTH vs LAW", "मिथक बनाम कानून"), quiz: tr("CAN YOU ANSWER?", "क्या आप जवाब दे सकते हैं?"), case: tr("LANDMARK CASE", "ऐतिहासिक केस"), compare: tr("OLD LAW vs NEW LAW", "पुराना बनाम नया कानून"), flow: tr("STEP BY STEP", "क्रम से") }[tmpl] || "";
  ctx.save(); ctx.translate(W / 2, 600); ctx.rotate(-0.03); F(900, 52); const kw = ctx.measureText(kicker).width + 70; rr(-kw / 2, -48, kw, 96, 16); ctx.fillStyle = "#e23642"; ctx.fill(); T(kicker, 0, 3, "#fff", "center"); ctx.restore();
  const title = S.thumbTitle || m.topic || m.question; const f = fitLines(title, 900, 116, W - 130, 6, "D", 50); F(900, f.size);
  const y0 = 720; f.lines.forEach((l, i) => T(l, W / 2, y0 + i * f.size * 1.1 + f.size / 2, i === f.lines.length - 1 ? bg[2] : "#ffffff", "center"));
  F(700, 40, "T"); T(tr("📌 Save for your exam", "📌 परीक्षा के लिए सेव करें"), W / 2, 1640, "rgba(255,255,255,0.75)", "center");
}

// ------------------------------------------------------------------ API used by the renderer
window.R = {
  setup(spec) {
    S = spec; S.W = spec.format === "long" ? 1920 : 1080; S.H = spec.format === "long" ? 1080 : 1920; cv.width = S.W; cv.height = S.H;
    S.beats.forEach(b => { delete b._w; });
    // load every font face before the first frame (fonts otherwise load lazily and the first frames use a fallback)
    const faces = [];
    for (const w of [600, 700, 800, 900]) faces.push(`${w} 40px "D"`);
    for (const w of [500, 600, 700]) faces.push(`${w} 40px "T"`);
    for (const w of [400, 500, 700]) faces.push(`${w} 40px "P"`);
    faces.push(`400 40px "L"`, `italic 700 40px "L"`, `400 40px "M"`, `700 40px "M"`);
    return Promise.all(faces.map(f => document.fonts.load(f, "Aaक"))).then(() => document.fonts.ready).then(() => true);
  },
  frame(t) {
    ANIM = false; KEY = []; ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.globalAlpha = 1;
    if (S.format === "long") long(t); else {
      (SH[S.template])(t);
      for (const b of S.beats) if (b.cap) caption(b, t, 1520);
      outro(t);
    }
    return ANIM ? null : KEY.join("|");
  },
  thumb() { if (S.format === "long") thumbLong(); else thumbShort(); },
  jpeg(q) { return cv.toDataURL("image/jpeg", q || 0.9).split(",")[1]; },
  png() { return cv.toDataURL("image/png").split(",")[1]; },
};
})();
