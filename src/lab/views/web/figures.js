// Figure renderer: spec (JSON from lab.fig) -> SVG/HTML.

const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const SLOTS = ["--s1", "--s2", "--s3"];
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const range = n => Array.from({ length: n }, (_, i) => i);
const lastAt = arr => arr.findLastIndex(Number.isFinite);

// Finite values only, without spreading (large arrays would overflow the call stack).
function extent(values) {
  let lo = Infinity, hi = -Infinity;
  for (const v of values) if (Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
  return lo <= hi ? [lo, hi] : [0, 1];
}
const padded = ([lo, hi], f = 0.08) => { const p = (hi - lo) * f || 1; return [lo >= 0 && lo - p < 0 ? 0 : lo - p, hi + p]; };
const symmetric = ([lo, hi]) => { const m = Math.max(Math.abs(lo), Math.abs(hi)) || 1; return [-m, m]; };

// The one place ranges are defaulted: specs carry data, and `domain` only when the author set it.
function withDomain(spec) {
  if (spec.domain) return spec;
  const set = domain => ({ ...spec, domain });
  switch (spec.type) {
    case "heatmap": { const e = extent(spec.z.flat()); return set(spec.diverging ? symmetric(e) : e); }
    case "tokens": { const e = extent(spec.rows.flatMap(r => r.values)); return set(spec.diverging ? symmetric(e) : [Math.min(0, e[0]), e[1]]); }
    case "dots": return set(padded(extent([...spec.items.flatMap(i => [i.lo, i.hi]), spec.reference?.value])));
    case "hist": return set(extent(spec.series.flatMap(s => s.values)));
    case "bars": return set([0, extent(spec.series.flatMap(s => s.values))[1] * 1.12]);
    case "multiples": return set(padded(extent(spec.panels.flatMap(p => p.series.flatMap(s => [...s.y, ...(s.lo || []), ...(s.hi || [])])))));
    default: return spec;
  }
}
const fmtN = (v, d = 2) => (v < 0 ? "−" : "") + Math.abs(v).toFixed(d);

let measureCtx;
function textWidth(s, size = 12) { measureCtx ||= document.createElement("canvas").getContext("2d"); measureCtx.font = `${size}px system-ui, -apple-system, sans-serif`; return measureCtx.measureText(s).width; }

function niceTicks(lo, hi, count = 5) {
  const span = hi - lo || 1, raw = span / count, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map(f => f * mag).find(s => span / s <= count) || mag * 10;
  const out = [];
  for (let t = Math.ceil(lo / step - 1e-9) * step; t <= hi + step * 1e-9; t += step) out.push(+t.toFixed(10));
  return out;
}
function tickFmt(ticks) {
  const step = ticks.length > 1 ? Math.abs(ticks[1] - ticks[0]) : 1;
  let d = 0; while (d < 6 && Math.abs(Math.round(step * 10 ** d) - step * 10 ** d) > 1e-6) d++;
  return t => fmtN(t, d).replace(/^−0(\.0+)?$/, "0");
}
function scale(d0, d1, r0, r1, log = false) {
  const f = log ? Math.log10 : v => v, a = f(d0), b = f(d1);
  return v => r0 + (r1 - r0) * (f(v) - a) / (b - a || 1);
}

// Colour mixing in OKLab so ramps stay perceptually even.
function hexToRgb(h) { h = h.replace("#", ""); if (h.length === 3) h = [...h].map(c => c + c).join(""); return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16) / 255); }
const lin = c => c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4, gam = c => c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055;
function toLab(hex) {
  const [r, g, b] = hexToRgb(hex).map(lin);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b), m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b), s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s, 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}
function fromLab([L, A, B]) {
  const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3, m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3, s = (L - 0.0894841775 * A - 1.291485548 * B) ** 3;
  const rgb = [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s, -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s];
  return "#" + rgb.map(c => Math.round(Math.max(0, Math.min(1, gam(c))) * 255).toString(16).padStart(2, "0")).join("");
}
const mix = (a, b, t) => { const A = toLab(a), B = toLab(b); return fromLab(A.map((v, i) => v + (B[i] - v) * t)); };
function ramp(spec) {
  const [lo, hi] = spec.domain;
  if (spec.diverging) {
    const neg = css("--div-neg"), mid = css("--div-mid"), pos = css("--div-pos"), m = Math.max(Math.abs(lo), Math.abs(hi));
    return v => v >= 0 ? mix(mid, pos, Math.min(1, v / m)) : mix(mid, neg, Math.min(1, -v / m));
  }
  const a = css("--seq-lo"), b = css("--seq-hi");
  return v => mix(a, b, Math.max(0, Math.min(1, (v - lo) / (hi - lo))));
}
function inkOn(hex) { const [r, g, b] = hexToRgb(hex).map(lin); return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.3 ? "#0b0b0b" : "#ffffff"; }
function scaleBar(spec, f) {
  const [lo, hi] = spec.domain, stops = range(11).map(i => f(lo + (hi - lo) * i / 10));
  return `<div class="lf-scale"><span class="num">${fmtN(lo, 1)}</span><i style="background:linear-gradient(90deg,${stops.join(",")})"></i><span class="num">${fmtN(hi, 1)}</span></div>`;
}

const swatch = (color, kind = "line") => kind === "dot"
  ? `<svg width="10" height="10"><circle cx="5" cy="5" r="4" fill="${color}"/></svg>`
  : `<svg width="14" height="4"><line x1="1" x2="13" y1="2" y2="2" stroke="${color}" stroke-width="2" stroke-linecap="round"/></svg>`;
function legend(items, kind) { return `<div class="lf-legend">${items.map(([name, color]) => `<span>${swatch(color, kind)}${esc(name)}</span>`).join("")}</div>`; }

function frame(spec, head = "") {
  return `<figure class="lf">
    ${spec.title ? `<div class="lf-title">${esc(spec.title)}</div>` : ""}${spec.sub ? `<div class="lf-sub">${esc(spec.sub)}</div>` : ""}
    ${head}<div class="lf-plot"></div>
    ${spec.caption ? `<p class="lf-caption">${esc(spec.caption)}</p>` : ""}
    ${spec.source ? `<div class="lf-source">Source: ${spec.source.map(r => `<a data-run="${esc(r)}" href="#${esc(r)}">${esc(r)}</a>`).join(", ")}</div>` : ""}
  </figure>`;
}

function tipFor(plot) {
  let el = plot.querySelector(".lf-tip");
  if (!el) { el = document.createElement("div"); el.className = "lf-tip"; plot.appendChild(el); }
  return {
    show(x, y, html) {
      el.innerHTML = html; el.classList.add("on");
      const w = el.offsetWidth, W = plot.clientWidth;
      el.style.left = (x + 14 + w > W ? Math.max(0, x - 14 - w) : x + 14) + "px";
      el.style.top = Math.max(0, y - 12) + "px";
    },
    hide() { el.classList.remove("on"); },
  };
}

function yAxis(ticks, y, x0, x1, fmt) {
  return ticks.map(t => `<line x1="${x0}" x2="${x1}" y1="${y(t)}" y2="${y(t)}" stroke="var(--grid)"/><text x="${x0 - 8}" y="${y(t) + 4}" text-anchor="end" fill="var(--muted)" font-size="11.5" class="num">${fmt(t)}</text>`).join("");
}
function xAxis(ticks, x, y0, fmt, label, x1, x0 = x(ticks[0])) {
  let s = `<line x1="${x0}" x2="${x1}" y1="${y0}" y2="${y0}" stroke="var(--axis)"/>`;
  s += ticks.map(t => `<text x="${x(t)}" y="${y0 + 17}" text-anchor="middle" fill="var(--muted)" font-size="11.5" class="num">${fmt(t)}</text>`).join("");
  if (label) s += `<text x="${x1}" y="${y0 + 34}" text-anchor="end" fill="var(--muted)" font-size="11.5">${esc(label)}</text>`;
  return s;
}
const logTicks = (lo, hi) => { const out = []; for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++) { const t = 10 ** e; if (t >= lo * 0.999 && t <= hi * 1.001) out.push(t); } return out; };
const fmtLog = t => t >= 1e4 || t < 1e-3 ? `1e${Math.round(Math.log10(t))}`.replace("-", "−") : String(t);

// ---------- line ----------
function drawLine(plot, spec, opts = {}) {
  const W = plot.clientWidth, H = opts.height || 260;
  const series = spec.series.map((s, i) => ({ ...s, color: s.muted ? "var(--muted)" : css(SLOTS[i % 3]) }));
  const xs = spec.x;
  const all = series.flatMap(s => [...s.y, ...(s.lo || []), ...(s.hi || [])]).filter(Number.isFinite);
  let [lo, hi] = opts.domain || spec.domain || extent(spec.logY ? all.filter(v => v > 0) : all);
  if (!spec.logY && !(opts.domain || spec.domain)) { const p = (hi - lo) * 0.08; lo = Math.max(lo - p, lo >= 0 ? 0 : -Infinity); hi += p; }
  if (spec.logY) { lo = 10 ** Math.floor(Math.log10(lo)); hi = hi * 1.25; }
  const direct = !opts.compact && series.length > 1;
  const ends = series.map(s => s.y[lastAt(s.y)]);
  const labelW = direct ? Math.max(...series.map(s => textWidth(s.name, 12))) + 16 : 0;
  const m = { l: opts.compact ? 30 : 44, r: 12 + labelW, t: 10, b: opts.compact ? 26 : 42 };
  const x = scale(xs[0], xs[xs.length - 1], m.l, W - m.r, spec.logX);
  const y = scale(lo, hi, H - m.b, m.t, spec.logY);
  const yT = spec.logY ? logTicks(lo, hi) : niceTicks(lo, hi, opts.compact ? 3 : 5);
  const yF = spec.logY ? fmtLog : tickFmt(yT);
  let xT = spec.logX ? xs : niceTicks(xs[0], xs[xs.length - 1], Math.max(3, Math.floor((W - m.l - m.r) / 90)));
  if (xs.every(Number.isInteger)) xT = xT.filter(Number.isInteger);  // steps and indices have no halves
  let s = yAxis(yT, y, m.l, W - m.r, yF) + xAxis(xT, x, H - m.b, t => t, opts.compact ? "" : spec.xLabel, W - m.r, m.l);
  if (spec.markX) s += `<line x1="${x(spec.markX.x)}" x2="${x(spec.markX.x)}" y1="${m.t}" y2="${H - m.b}" stroke="var(--axis)"/><text x="${x(spec.markX.x) + 6}" y="${H - m.b - 8}" fill="var(--ink-2)" font-size="11.5">${esc(spec.markX.label)}</text>`;
  const path = arr => { let pen = false; return arr.map((v, i) => { if (!Number.isFinite(v)) { pen = false; return ""; } const c = `${pen ? "L" : "M"}${x(xs[i]).toFixed(1)} ${y(v).toFixed(1)}`; pen = true; return c; }).join(""); };
  for (const ser of series) if (ser.lo) s += `<path d="${path(ser.lo)}${ser.hi.map((v, i) => `L${x(xs[ser.hi.length - 1 - i]).toFixed(1)} ${y(ser.hi[ser.hi.length - 1 - i]).toFixed(1)}`).join("")}Z" fill="${ser.color}" fill-opacity="0.12"/>`;
  for (const ser of [...series].reverse()) s += `<path d="${path(ser.y)}" fill="none" stroke="${ser.color}" stroke-width="${ser.muted ? 1.5 : 2}" stroke-linejoin="round" stroke-linecap="round"/>`;
  if (!opts.compact) for (const ser of series) { const n = lastAt(ser.y); if (n < 0) continue; s += `<circle cx="${x(xs[n])}" cy="${y(ser.y[n])}" r="4" fill="${ser.color}" stroke="var(--surface)" stroke-width="2"/>`; }
  if (direct) {
    // End labels only when they separate; otherwise the legend carries identity.
    const ys = ends.map(v => y(v)), order = ys.map((v, i) => [v, i]).sort((a, b) => a[0] - b[0]);
    const clear = order.every((p, k) => k === 0 || p[0] - order[k - 1][0] >= 14);
    if (clear) for (const [v, i] of order) s += `<text x="${W - m.r + 10}" y="${v + 4}" fill="var(--ink-2)" font-size="12">${esc(series[i].name)}</text>`;
  }
  s += `<line class="xh" x1="0" x2="0" y1="${m.t}" y2="${H - m.b}" stroke="var(--axis)" opacity="0"/><g class="hv"></g><rect class="hit" x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="transparent"/>`;
  plot.innerHTML = `<svg width="${W}" height="${H}" role="img" aria-label="${esc(spec.title || "")}">${s}</svg>`;
  const svg = plot.querySelector("svg"), tip = tipFor(plot), xh = svg.querySelector(".xh"), hv = svg.querySelector(".hv");
  svg.querySelector(".hit").addEventListener("pointermove", e => {
    const px = e.offsetX; let i = 0, best = Infinity;
    xs.forEach((v, k) => { const d = Math.abs(x(v) - px); if (d < best) { best = d; i = k; } });
    xh.setAttribute("x1", x(xs[i])); xh.setAttribute("x2", x(xs[i])); xh.setAttribute("opacity", 1);
    hv.innerHTML = series.filter(ser => Number.isFinite(ser.y[i])).map(ser => `<circle cx="${x(xs[i])}" cy="${y(ser.y[i])}" r="4" fill="${ser.color}" stroke="var(--surface)" stroke-width="2"/>`).join("");
    tip.show(x(xs[i]), e.offsetY, `<div class="h">${esc(spec.xLabel || "x")} ${esc(String(xs[i]))}</div>` + series.map(ser => `<div class="row">${swatch(ser.color)}<span class="m">${esc(ser.name)}</span><span class="v">${!Number.isFinite(ser.y[i]) ? "–" : spec.logY ? ser.y[i].toExponential(1) : ser.y[i].toFixed((spec.yFmt ?? 2) + 1)}</span></div>`).join(""));
  });
  svg.querySelector(".hit").addEventListener("pointerleave", () => { tip.hide(); xh.setAttribute("opacity", 0); hv.innerHTML = ""; });
}

// ---------- heatmap ----------
function drawHeatmap(plot, spec) {
  const W = plot.clientWidth, rows = spec.z.length, cols = spec.z[0].length, f = ramp(spec);
  const labW = Math.max(...spec.yLabels.map(l => textWidth(l, 11.5))) + 10;
  const m = { l: labW, r: 4, t: 4, b: 26 };
  const cw = (W - m.l - m.r) / cols, ch = Math.max(9, Math.min(13, cw * 0.5));
  const xw = Math.max(...spec.xLabels.map(l => textWidth(l, 12))), tilt = xw > cw - 6;
  if (tilt) m.b = xw * 0.72 + 14;
  const H = m.t + rows * ch + m.b;
  const every = ch < 12 ? 2 : 1;
  let s = "";
  spec.z.forEach((row, r) => row.forEach((v, c) => {
    // a missing value (NaN in the run, null here) is a gap, not the lowest colour
    s += `<rect x="${m.l + c * cw + 0.5}" y="${m.t + r * ch + 0.5}" width="${cw - 1}" height="${ch - 1}" fill="${Number.isFinite(v) ? f(v) : "none"}" rx="1.5"/>`;
  }));
  spec.yLabels.forEach((l, r) => { if (r % every === 0) s += `<text x="${m.l - 8}" y="${m.t + r * ch + ch / 2 + 4}" text-anchor="end" fill="var(--muted)" font-size="11.5" class="num">${esc(l)}</text>`; });
  spec.xLabels.forEach((l, c) => {
    const lx = m.l + c * cw + cw / 2, ly = m.t + rows * ch + 16;
    s += tilt
      ? `<text x="${lx + 3}" y="${ly - 4}" text-anchor="end" transform="rotate(-45 ${lx + 3} ${ly - 4})" fill="var(--ink-2)" font-size="12" class="mono">${esc(l.replace(/^ /, "␣"))}</text>`
      : `<text x="${lx}" y="${ly}" text-anchor="middle" fill="var(--ink-2)" font-size="12" class="mono">${esc(l.replace(/^ /, "␣"))}</text>`;
  });
  if (spec.annotate) { const a = spec.annotate; s += `<rect x="${m.l + a.col * cw}" y="${m.t + a.row * ch}" width="${cw}" height="${ch}" fill="none" stroke="var(--ink)" stroke-width="1.5" rx="2"/>`; }
  s += `<rect class="sel" fill="none" stroke="var(--ink)" stroke-width="1.5" rx="2" width="${cw}" height="${ch}" opacity="0"/>`;
  plot.innerHTML = `<svg width="${W}" height="${H}" role="img" aria-label="${esc(spec.title || "")}">${s}</svg>`;
  const svg = plot.querySelector("svg"), sel = svg.querySelector(".sel"), tip = tipFor(plot);
  svg.addEventListener("pointermove", e => {
    const c = Math.floor((e.offsetX - m.l) / cw), r = Math.floor((e.offsetY - m.t) / ch);
    if (c < 0 || c >= cols || r < 0 || r >= rows) { tip.hide(); sel.setAttribute("opacity", 0); return; }
    sel.setAttribute("x", m.l + c * cw); sel.setAttribute("y", m.t + r * ch); sel.setAttribute("opacity", 1);
    tip.show(e.offsetX, e.offsetY, `<div class="h">${esc(spec.yLabels[r])} · <span class="mono">${esc(spec.xLabels[c])}</span></div><div class="row"><span class="m">${esc(spec.valueLabel || "value")}</span><span class="v">${fmtN(spec.z[r][c], spec.fmt ?? 2)}</span></div>`);
  });
  svg.addEventListener("pointerleave", () => { tip.hide(); sel.setAttribute("opacity", 0); });
}

// ---------- tokens ----------
function drawTokens(plot, spec) {
  const f = ramp(spec);
  plot.innerHTML = `<div class="lf-tokens">${spec.rows.map(row => `<div class="lab">${esc(row.label)}</div><div class="txt">${row.tokens.map((t, i) => {
    const bg = f(row.values[i]); return `<span class="tok" data-v="${esc(String(row.values[i]))}" style="background:${bg};color:${inkOn(bg)}">${esc(t)}</span>`;
  }).join("")}</div>`).join("")}</div>`;
  const tip = tipFor(plot);
  plot.querySelectorAll(".tok").forEach(el => {
    el.addEventListener("pointerenter", () => { const b = el.getBoundingClientRect(), p = plot.getBoundingClientRect(); tip.show(b.left - p.left + b.width / 2, b.bottom - p.top + 6, `<div class="h mono">${esc(el.textContent.replace(/^ /, "␣"))}</div><div class="row"><span class="m">${esc(spec.valueLabel || "value")}</span><span class="v">${fmtN(+el.dataset.v, spec.fmt ?? 2)}</span></div>`); });
    el.addEventListener("pointerleave", () => tip.hide());
  });
}

// ---------- dots ----------
function drawDots(plot, spec) {
  const W = plot.clientWidth, widest = Math.max(...spec.items.map(it => textWidth(it.label, 12.5))) + 16;
  const stacked = widest > W * 0.42;  // narrow: each label sits above its row instead of beside it
  const rowH = stacked ? 44 : 30, labW = stacked ? 8 : widest;
  const m = { l: labW, r: 44, t: 8, b: 40 }, H = m.t + spec.items.length * rowH + m.b;
  const x = scale(spec.domain[0], spec.domain[1], m.l, W - m.r);
  const ticks = niceTicks(spec.domain[0], spec.domain[1], Math.max(3, Math.floor((W - m.l - m.r) / 120)));
  let s = ticks.map(t => `<line x1="${x(t)}" x2="${x(t)}" y1="${m.t}" y2="${H - m.b}" stroke="var(--grid)"/>`).join("");
  const ref = spec.reference;
  if (ref) {
    s += `<rect x="${x(ref.value - ref.noise)}" width="${x(ref.value + ref.noise) - x(ref.value - ref.noise)}" y="${m.t}" height="${H - m.b - m.t}" fill="var(--hover)"/>`;
    s += `<line x1="${x(ref.value)}" x2="${x(ref.value)}" y1="${m.t}" y2="${H - m.b}" stroke="var(--axis)" stroke-width="1.5"/>`;
  }
  s += xAxis(ticks, x, H - m.b, tickFmt(ticks), spec.xLabel, W - m.r);
  if (ref) {
    const text = `${ref.label} ± noise`, fits = x(ref.value) + 6 + textWidth(text, 11.5) <= W;
    s += `<text x="${x(ref.value) + (fits ? 6 : -6)}" y="${H - m.b - 6}" text-anchor="${fits ? "start" : "end"}" fill="var(--muted)" font-size="11.5">${esc(text)}</text>`;
  }
  spec.items.forEach((it, i) => {
    const cy = m.t + i * rowH + (stacked ? rowH - 12 : rowH / 2), c = it.highlight ? "var(--s1)" : "var(--ink-2)";
    s += stacked
      ? `<text x="${m.l}" y="${m.t + i * rowH + 14}" fill="${it.highlight ? "var(--ink)" : "var(--ink-2)"}" font-size="12.5" font-weight="${it.highlight ? 600 : 400}">${esc(it.label)}</text>`
      : `<text x="${m.l - 12}" y="${cy + 4}" text-anchor="end" fill="${it.highlight ? "var(--ink)" : "var(--ink-2)"}" font-size="12.5" font-weight="${it.highlight ? 600 : 400}">${esc(it.label)}</text>`;
    s += `<line x1="${x(it.lo)}" x2="${x(it.hi)}" y1="${cy}" y2="${cy}" stroke="${c}" stroke-width="2" stroke-linecap="round" opacity="${it.highlight ? 1 : 0.55}"/>`;
    s += `<circle cx="${x(it.mean)}" cy="${cy}" r="${it.highlight ? 5.5 : 4.5}" fill="${c}" stroke="var(--surface)" stroke-width="2"/>`;
    if (it.highlight && Number.isFinite(it.mean)) s += `<text x="${x(it.hi) + 8}" y="${cy + 4}" fill="var(--ink)" font-size="12" font-weight="600" class="num">${it.mean.toFixed(spec.fmt)}</text>`;
    s += `<rect class="row" data-i="${i}" x="0" y="${cy - rowH / 2}" width="${W}" height="${rowH}" fill="transparent"/>`;
  });
  plot.innerHTML = `<svg width="${W}" height="${H}" role="img" aria-label="${esc(spec.title || "")}">${s}</svg>`;
  const tip = tipFor(plot);
  plot.querySelectorAll(".row").forEach(r => {
    const num = v => Number.isFinite(v) ? v.toFixed(spec.fmt) : "–";  // NaN in the run arrives as null
    r.addEventListener("pointerenter", e => { const it = spec.items[+r.dataset.i]; r.setAttribute("fill", "var(--hover)"); tip.show(x(it.hi), +r.getAttribute("y") + 4, `<div class="h">${esc(it.label)}</div><div class="row"><span class="m">mean</span><span class="v">${num(it.mean)}</span></div><div class="row"><span class="m">${esc(spec.interval || "95% CI")}</span><span class="v">${num(it.lo)} – ${num(it.hi)}</span></div>${ref ? `<div class="row"><span class="m">vs ${esc(ref.label)}</span><span class="v">${fmtN(it.mean - ref.value, spec.fmt).replace(/^(?!−)/, "+")}</span></div>` : ""}`); });
    r.addEventListener("pointerleave", () => { r.setAttribute("fill", "transparent"); tip.hide(); });
  });
}

// ---------- scatter ----------
function drawScatter(plot, spec) {
  const W = plot.clientWidth, H = 300, m = { l: 40, r: 12, t: 10, b: 42 };
  const groups = spec.groups.map((g, i) => ({ ...g, color: css(SLOTS[i % 3]) }));
  const pts = groups.flatMap(g => g.points);
  const pad = (a, b) => [a - (b - a) * 0.06, b + (b - a) * 0.06];
  const [x0, x1] = pad(...extent(pts.map(p => p[0])));
  const [y0, y1] = pad(...extent(pts.map(p => p[1])));
  const x = scale(x0, x1, m.l, W - m.r), y = scale(y0, y1, H - m.b, m.t);
  const yt = niceTicks(y0, y1, 4), xt = niceTicks(x0, x1, 5);
  let s = yAxis(yt, y, m.l, W - m.r, tickFmt(yt)) + xAxis(xt, x, H - m.b, tickFmt(xt), spec.xLabel, W - m.r, m.l);
  s += `<text x="${m.l}" y="${m.t - 2}" fill="var(--muted)" font-size="11.5">${esc(spec.yLabel)}</text>`;
  groups.forEach(g => g.points.forEach(p => { s += `<circle cx="${x(p[0]).toFixed(1)}" cy="${y(p[1]).toFixed(1)}" r="3.6" fill="${g.color}" fill-opacity="0.78" stroke="var(--surface)" stroke-width="1.2"/>`; }));
  // Direct labels at each cloud's upper edge.
  const mean = ps => [ps.reduce((a, p) => a + p[0], 0) / ps.length, ps.reduce((a, p) => a + p[1], 0) / ps.length];
  const screen = pts.map(p => [x(p[0]), y(p[1])]);
  groups.forEach(g => {
    // Try each side of the cloud; keep the label box that covers the fewest points.
    const [cx, cy] = mean(g.points), gx = g.points.map(p => x(p[0])), gy = g.points.map(p => y(p[1]));
    const w = textWidth(g.name, 12) + 8, h = 16;
    const sides = [
      { lx: x(cx), ly: Math.min(...gy) - 10, anchor: "middle" },
      { lx: x(cx), ly: Math.max(...gy) + 18, anchor: "middle" },
      { lx: Math.max(...gx) + 8, ly: y(cy) + 4, anchor: "start" },
      { lx: Math.min(...gx) - 8, ly: y(cy) + 4, anchor: "end" },
    ].map(c => {
      const left = c.anchor === "middle" ? c.lx - w / 2 : c.anchor === "start" ? c.lx : c.lx - w;
      const inside = left >= m.l && left + w <= W - m.r && c.ly - h >= 0 && c.ly <= H - m.b;
      const hits = screen.filter(([px, py]) => px > left - 3 && px < left + w + 3 && py > c.ly - h && py < c.ly + 5).length;
      return { ...c, cost: hits + (inside ? 0 : 1e6) };
    });
    const best = sides.reduce((a, c) => c.cost < a.cost ? c : a);
    s += `<text x="${best.lx}" y="${best.ly}" text-anchor="${best.anchor}" fill="var(--ink)" font-size="12" font-weight="500" paint-order="stroke" stroke="var(--surface)" stroke-width="4">${esc(g.name)}</text>`;
  });
  s += `<circle class="hv" r="6" fill="none" stroke="var(--ink)" stroke-width="1.5" opacity="0"/>`;
  plot.innerHTML = `<svg width="${W}" height="${H}" role="img" aria-label="${esc(spec.title || "")}">${s}</svg>`;
  const svg = plot.querySelector("svg"), hv = svg.querySelector(".hv"), tip = tipFor(plot);
  svg.addEventListener("pointermove", e => {
    let best = 18 ** 2, hit = null;
    groups.forEach(g => g.points.forEach((p, i) => { const d = (x(p[0]) - e.offsetX) ** 2 + (y(p[1]) - e.offsetY) ** 2; if (d < best) { best = d; hit = [g, p, i]; } }));
    if (!hit) { hv.setAttribute("opacity", 0); tip.hide(); return; }
    const [g, p, i] = hit;
    hv.setAttribute("cx", x(p[0])); hv.setAttribute("cy", y(p[1])); hv.setAttribute("opacity", 1);
    tip.show(x(p[0]), y(p[1]), `<div class="row">${swatch(g.color, "dot")}<span class="h" style="margin:0">${esc(g.name)} #${i + 1}</span></div><div class="row"><span class="m">${esc(spec.xLabel || "x")}</span><span class="v">${fmtN(p[0])}</span></div><div class="row"><span class="m">${esc(spec.yLabel || "y")}</span><span class="v">${fmtN(p[1])}</span></div>`);
  });
  svg.addEventListener("pointerleave", () => { hv.setAttribute("opacity", 0); tip.hide(); });
}

// ---------- histogram ----------
function drawHist(plot, spec) {
  const W = plot.clientWidth, H = 260, m = { l: 40, r: 12, t: 10, b: 42 };
  const [d0, d1] = spec.domain, n = spec.bins, bw = (d1 - d0) / n;
  const series = spec.series.map((s, i) => {
    const counts = new Array(n).fill(0);
    for (const v of s.values) {
      if (!Number.isFinite(v) || v < d0 || v > d1) continue;  // missing values are not zeros
      counts[v === d1 ? n - 1 : Math.floor((v - d0) / bw)]++;  // the maximum belongs to the last bin
    }
    return { ...s, counts, color: css(SLOTS[i % 3]) };
  });
  const top = Math.max(...series.flatMap(s => s.counts));
  const x = scale(d0, d1, m.l, W - m.r), y = scale(0, top * 1.1, H - m.b, m.t);
  const xt = niceTicks(d0, d1, 6);
  let s = yAxis(niceTicks(0, top * 1.1, 4), y, m.l, W - m.r, t => t) + xAxis(xt, x, H - m.b, tickFmt(xt), spec.xLabel, W - m.r, m.l);
  for (const ser of series) {
    let d = `M${x(d0)} ${y(0)}`;
    ser.counts.forEach((c, b) => { d += `V${y(c)}H${x(d0 + (b + 1) * bw)}`; });
    d += `V${y(0)}`;
    s += `<path d="${d}Z" fill="${ser.color}" fill-opacity="0.1"/><path d="${d}" fill="none" stroke="${ser.color}" stroke-width="1.75" stroke-linejoin="round"/>`;
  }
  for (const ser of series) {
    const pk = ser.counts.indexOf(Math.max(...ser.counts));
    s += `<text x="${x(d0 + (pk + 0.5) * bw)}" y="${y(ser.counts[pk]) - 8}" text-anchor="middle" fill="var(--ink)" font-size="12" font-weight="500" paint-order="stroke" stroke="var(--surface)" stroke-width="4">${esc(ser.name)}</text>`;
  }
  s += `<rect class="hb" y="${m.t}" height="${H - m.t - m.b}" fill="var(--hover)" opacity="0"/>`;
  plot.innerHTML = `<svg width="${W}" height="${H}" role="img" aria-label="${esc(spec.title || "")}">${s}</svg>`;
  const svg = plot.querySelector("svg"), hb = svg.querySelector(".hb"), tip = tipFor(plot);
  svg.addEventListener("pointermove", e => {
    const b = Math.floor(((e.offsetX - m.l) / (W - m.l - m.r)) * n);
    if (b < 0 || b >= n) { hb.setAttribute("opacity", 0); tip.hide(); return; }
    hb.setAttribute("x", x(d0 + b * bw)); hb.setAttribute("width", x(d0 + bw) - x(d0)); hb.setAttribute("opacity", 1);
    tip.show(e.offsetX, e.offsetY, `<div class="h num">${fmtN(d0 + b * bw)} to ${fmtN(d0 + (b + 1) * bw)}</div>` + series.map(ser => `<div class="row">${swatch(ser.color)}<span class="m">${esc(ser.name)}</span><span class="v">${ser.counts[b]}</span></div>`).join(""));
  });
  svg.addEventListener("pointerleave", () => { hb.setAttribute("opacity", 0); tip.hide(); });
}

// ---------- bars ----------
function drawBars(plot, spec) {
  const W = plot.clientWidth, ns = spec.series.length, bar = 12, gap = 2, group = ns * bar + (ns - 1) * gap, rowH = group + 18;
  const labW = Math.max(...spec.categories.map(c => textWidth(c, 12.5))) + 14;
  const m = { l: labW, r: 44, t: 4, b: 30 }, H = m.t + spec.categories.length * rowH + m.b;
  const x = scale(spec.domain[0], spec.domain[1], m.l, W - m.r);
  const series = spec.series.map((s, i) => ({ ...s, color: css(SLOTS[i % 3]) }));
  const ticks = niceTicks(spec.domain[0], spec.domain[1], Math.max(3, Math.floor((W - m.l - m.r) / 80)));
  let s = ticks.map(t => `<line x1="${x(t)}" x2="${x(t)}" y1="${m.t}" y2="${H - m.b}" stroke="var(--grid)"/>`).join("") + xAxis(ticks, x, H - m.b, t => t, "", W - m.r);
  s += `<line x1="${x(0)}" x2="${x(0)}" y1="${m.t}" y2="${H - m.b}" stroke="var(--axis)"/>`;
  spec.categories.forEach((cat, ci) => {
    const gy = m.t + ci * rowH + (rowH - group) / 2;
    s += `<text x="${m.l - 12}" y="${gy + group / 2 + 4}" text-anchor="end" fill="var(--ink-2)" font-size="12.5">${esc(cat)}</text>`;
    series.forEach((ser, si) => {
      const v = ser.values[ci], by = gy + si * (bar + gap);
      if (!Number.isFinite(v)) {  // missing (NaN in the run): a dash where the bar would start
        s += `<text x="${x(0) + 6}" y="${by + bar - 2}" fill="var(--muted)" font-size="11.5" class="num">–</text>`;
        return;
      }
      const w = x(v) - x(0), r = Math.min(4, w);
      // Square at the baseline, 4px round at the data end.
      s += `<path class="b" data-c="${ci}" d="M${x(0)} ${by}H${x(v) - r}Q${x(v)} ${by} ${x(v)} ${by + r}V${by + bar - r}Q${x(v)} ${by + bar} ${x(v) - r} ${by + bar}H${x(0)}Z" fill="${ser.color}"/>`;
      s += `<text x="${x(v) + 6}" y="${by + bar - 2}" fill="var(--ink-2)" font-size="11.5" class="num">${v.toFixed(spec.fmt)}</text>`;
    });
    s += `<rect class="row" data-c="${ci}" x="0" y="${m.t + ci * rowH}" width="${W}" height="${rowH}" fill="transparent"/>`;
  });
  plot.innerHTML = legend(series.map(s => [s.name, s.color]), "dot") + `<svg width="${W}" height="${H}" style="margin-top:8px" role="img" aria-label="${esc(spec.title || "")}">${s}</svg>`;
  const tip = tipFor(plot);
  plot.querySelectorAll(".row").forEach(r => {
    const ci = +r.dataset.c;
    r.addEventListener("pointerenter", () => { r.setAttribute("fill", "var(--hover)"); const d = series.length === 2 ? series[1].values[ci] - series[0].values[ci] : null; tip.show(x(Math.max(...series.map(s => s.values[ci]))) + 30, +r.getAttribute("y") + 30, `<div class="h">${esc(spec.categories[ci])}</div>` + series.map(ser => `<div class="row">${swatch(ser.color, "dot")}<span class="m">${esc(ser.name)}</span><span class="v">${ser.values[ci].toFixed(spec.fmt)}</span></div>`).join("") + (d == null ? "" : `<div class="row"><span class="m">change</span><span class="v">${d >= 0 ? "+" : "−"}${Math.abs(d).toFixed(spec.fmt)}</span></div>`)); });
    r.addEventListener("pointerleave", () => { r.setAttribute("fill", "transparent"); tip.hide(); });
  });
}

// ---------- reliability ----------
function drawReliability(plot, spec) {
  const W = plot.clientWidth, m = { l: 40, r: 12, t: 10, b: 42 }, strip = 36, nb = spec.nbins || 10;
  const series = spec.series.map((s, i) => ({ ...s, color: css(SLOTS[i % 3]) }));
  const binAt = (ser, b) => ser.bins.find(bin => Math.floor(bin.conf * nb) === b);  // empty bins are not stored
  const plotH = 262;
  const x = scale(0, 1, m.l, W - m.r), y = scale(0, 1, m.t + plotH - strip - 12, m.t);
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  let s = yAxis(ticks, y, m.l, W - m.r, t => t.toFixed(2));
  s += `<line x1="${x(0)}" y1="${y(0)}" x2="${x(1)}" y2="${y(1)}" stroke="var(--axis)" stroke-width="1.5"/>`;
  s += `<text x="${x(0.62)}" y="${y(0.62) - 8}" fill="var(--muted)" font-size="11.5" transform="rotate(${-Math.atan2(y(0) - y(1), x(1) - x(0)) * 180 / Math.PI} ${x(0.62)} ${y(0.62) - 8})">perfect calibration</text>`;
  s += `<text x="${m.l}" y="${m.t - 2}" fill="var(--muted)" font-size="11.5">observed accuracy</text>`;
  for (const ser of series) {
    s += `<path d="${ser.bins.map((b, i) => `${i ? "L" : "M"}${x(b.conf)} ${y(b.acc)}`).join("")}" fill="none" stroke="${ser.color}" stroke-width="2" stroke-linejoin="round"/>`;
    s += ser.bins.map(b => `<circle cx="${x(b.conf)}" cy="${y(b.acc)}" r="4" fill="${ser.color}" stroke="var(--surface)" stroke-width="2"/>`).join("");
  }
  // Counts per bin, small grouped columns under the plot.
  const base = m.t + plotH, cmax = Math.max(...series.flatMap(s => s.bins.map(b => b.n))), colW = Math.min(10, (x(1 / nb) - x(0)) / (series.length + 1));
  series.forEach((ser, si) => ser.bins.forEach(b => {
    const h = strip * b.n / cmax, cx = x(b.conf) + (si - (series.length - 1) / 2) * (colW + 2) - colW / 2;
    s += `<rect x="${cx}" y="${base - h}" width="${colW}" height="${h}" fill="${ser.color}" fill-opacity="0.55" rx="1.5"/>`;
  }));
  s += `<line x1="${m.l}" x2="${W - m.r}" y1="${base}" y2="${base}" stroke="var(--axis)"/>`;
  s += ticks.map(t => `<text x="${x(t)}" y="${base + 17}" text-anchor="middle" fill="var(--muted)" font-size="11.5" class="num">${t.toFixed(2)}</text>`).join("");
  s += `<text x="${W - m.r}" y="${base + 34}" text-anchor="end" fill="var(--muted)" font-size="11.5">predicted confidence</text>`;
  s += `<rect class="hb" y="${m.t}" height="${plotH}" fill="var(--hover)" opacity="0"/>`;
  plot.innerHTML = legend(series.map(s => [`${s.name} · ECE ${s.ece.toFixed(3)}`, s.color])) + `<svg width="${W}" height="${base + 40}" style="margin-top:8px" role="img" aria-label="${esc(spec.title || "")}">${s}</svg>`;
  const svg = plot.querySelector("svg"), hb = svg.querySelector(".hb"), tip = tipFor(plot);
  svg.addEventListener("pointermove", e => {
    const b = Math.floor((e.offsetX - m.l) / (x(1 / nb) - x(0)));
    if (b < 0 || b >= nb) { hb.setAttribute("opacity", 0); tip.hide(); return; }
    hb.setAttribute("x", x(b / nb)); hb.setAttribute("width", x(1 / nb) - x(0)); hb.setAttribute("opacity", 1);
    tip.show(e.offsetX, e.offsetY + 30, `<div class="h num">confidence ${(b / nb).toFixed(2)}–${((b + 1) / nb).toFixed(2)}</div>` + series.map(ser => { const bin = binAt(ser, b); return `<div class="row">${swatch(ser.color)}<span class="m">${esc(ser.name)}</span><span class="v">${bin ? `${bin.acc.toFixed(2)} · n ${bin.n}` : "no items"}</span></div>`; }).join(""));
  });
  svg.addEventListener("pointerleave", () => { hb.setAttribute("opacity", 0); tip.hide(); });
}

// ---------- small multiples ----------
function drawMultiples(plot, spec) {
  const first = spec.panels[0].series.map((s, i) => [s.name, s.muted ? "var(--muted)" : css(SLOTS[i % 3])]);
  plot.innerHTML = legend(first) + `<div class="lf-multi" style="margin-top:12px">${spec.panels.map((p, i) => `<div><div class="pt" style="${p.highlight ? "color:var(--ink);font-weight:600" : ""}">${esc(p.title)}</div><div class="panel" data-i="${i}" style="position:relative"></div></div>`).join("")}</div>`;
  plot.querySelectorAll(".panel").forEach(el => {
    const p = spec.panels[+el.dataset.i];
    drawLine(el, { ...spec, title: p.title, x: p.x, series: p.series, markX: null }, { compact: true, height: 150, domain: spec.domain });
  });
}

// ---------- table ----------
function drawTable(plot, spec) {
  // columns: [{ key, label, kind: "text" | "num" | "bar" | "delta" | "run" | "money", fmt, lo, hi, optional }]
  const cols = spec.columns || Object.keys(spec.rows[0] || {}).filter(k => k !== "highlight").map(k => ({ key: k, label: k, kind: typeof spec.rows[0][k] === "number" ? "num" : "text" }));
  const barCol = cols.find(c => c.kind === "bar");
  const vals = barCol ? spec.rows.flatMap(r => [r[barCol.key], r[barCol.hi], r[barCol.lo]]).filter(Number.isFinite) : [];
  const [d0, d1] = spec.domain || [Math.min(0, extent(vals)[0]), extent(vals)[1] * 1.05];
  const pct = v => ((v - d0) / (d1 - d0) * 100).toFixed(2) + "%";
  const fmtC = (c, v) => v == null ? "–" : typeof v === "number" ? v.toFixed(c.fmt ?? spec.fmt ?? 2) : esc(v);
  const cell = (c, r) => {
    const v = r[c.key], opt = c.optional ? " opt" : "";
    switch (c.kind) {
      case "bar": {
        const ref = spec.reference != null ? `<div style="position:absolute;left:${pct(spec.reference)};top:-4px;bottom:-4px;width:1.5px;background:var(--axis)"></div>` : "";
        const ci = Number.isFinite(r[c.lo]) && Number.isFinite(r[c.hi]) ? `<div style="position:absolute;left:${pct(r[c.lo])};width:calc(${pct(r[c.hi])} - ${pct(r[c.lo])});top:6px;height:2px;background:var(--ink-2);border-radius:1px"></div>` : "";
        const pm = ci ? ` <span class="muted">± ${((r[c.hi] - r[c.lo]) / 2).toFixed(c.fmt ?? spec.fmt ?? 2)}</span>` : "";
        return `<td class="barc${opt}"><div style="position:relative;height:14px">${ref}<div style="position:absolute;left:0;top:3px;height:8px;width:${pct(v)};background:${r.highlight ? "var(--s1)" : "var(--axis)"};border-radius:0 4px 4px 0"></div>${ci}</div></td><td class="r num${opt}">${fmtC(c, v)}${pm}</td>`;
      }
      case "delta": return `<td class="r num${opt} ${v > 0 ? "good" : "muted"}">${v == null ? "–" : (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(c.fmt ?? spec.fmt ?? 2)}</td>`;
      case "run": return `<td class="r${opt}">${v ? `<a data-run="${esc(v)}" href="#${esc(v)}" style="color:var(--s1);text-decoration:none">${esc(v)}</a>` : "–"}</td>`;
      case "money": return `<td class="r num${opt} muted">${v == null ? "–" : "$" + v.toFixed(2)}</td>`;
      case "num": return `<td class="r num${opt}">${fmtC(c, v)}</td>`;
      default: return `<td class="${opt.trim()}">${fmtC(c, v)}</td>`;
    }
  };
  const head = cols.map(c => c.kind === "bar" ? `<th class="${c.optional ? "opt" : ""}">${esc(c.label)}</th><th class="r${c.optional ? " opt" : ""}"></th>` : `<th class="${["text", undefined].includes(c.kind) ? "" : "r"}${c.optional ? " opt" : ""}">${esc(c.label)}</th>`).join("");
  plot.innerHTML = `<table class="lf-table"><thead><tr>${head}</tr></thead><tbody>${spec.rows.map(r => `<tr class="${r.highlight ? "hl" : ""}">${cols.map(c => cell(c, r)).join("")}</tr>`).join("")}</tbody></table>`;
}

const DRAW = { line: drawLine, heatmap: drawHeatmap, tokens: drawTokens, dots: drawDots, scatter: drawScatter, hist: drawHist, bars: drawBars, reliability: drawReliability, multiples: drawMultiples, table: drawTable };
function heads(spec) {
  if (spec.type === "line" && spec.series.length > 1) return legend(spec.series.map((s, i) => [s.name, css(SLOTS[i % 3])]));
  if (spec.type === "heatmap" || spec.type === "tokens") return `<div style="margin-top:10px">${scaleBar(spec, ramp(spec))}</div>`;
  if (spec.type === "scatter" || spec.type === "hist") return legend((spec.groups || spec.series).map((g, i) => [g.name, css(SLOTS[i % 3])]), spec.type === "scatter" ? "dot" : "line");
  return "";
}

// Draw one figure spec into `el` (title, legend or scale, plot, caption, source).
function renderFigure(el, spec) {
  const s = withDomain(spec);
  el.innerHTML = frame(s, heads(s));
  DRAW[s.type](el.querySelector(".lf-plot"), s);
}
