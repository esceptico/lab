const DATA = JSON.parse(document.getElementById("data").textContent);
const LABELS = DATA.labels;
const campaigns = DATA.campaigns.map(c => {
  c.byId = new Map(c.runs.map(r => [r.id, r]));
  c.best = c.byId.get(c.best) || null;
  c.kids = new Map(c.runs.map(r => [r.id, c.runs.filter(x => x.parent === r.id)]));
  // Tree depth counts only real branches: a straight chain stays flat, a parent with several children indents them.
  const depth = r => { const p = r.parent && c.byId.get(r.parent); return p ? depth(p) + (c.kids.get(p.id).length > 1 ? 1 : 0) : 0; };
  c.runs.forEach(r => { r.depth = depth(r); });
  return c;
});

/* ---------- formatting ---------- */
// Halves round up on the decimal value, as the CLI does (toFixed rounds the binary one: 1.0005 → 1.000).
const round = (v, n) => Number(Math.round(Number(`${Math.abs(v)}e${n}`)) + `e-${n}`) * Math.sign(v);
const fv = (c, v) => v == null ? "–" : round(v, c.fmt).toFixed(c.fmt);
function fd(c, d) {
  if (d == null) return "";
  const r = round(d, c.fmt);
  return (r === 0 ? "±" : r > 0 ? "+" : "−") + Math.abs(r).toFixed(c.fmt);
}
function dur(s) {
  if (s == null) return null;
  if (s < 60) return `${Math.max(1, Math.round(s))}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  return `${Math.floor(s / 3600)}h${String(Math.round(s % 3600 / 60)).padStart(2, "0")}m`;
}
const size = b => b < 1024 ? `${b} B` : b < 1048576 ? `${(b / 1024).toFixed(1)} KB` : `${(b / 1048576).toFixed(1)} MB`;
const rid = id => `<a class="rid" data-run="${id}">${id}</a>`;
const kind = r => r.status === "running" ? "running" : r.verdict || (r.status === "failed" ? "failed" : "none");  // the verdict column of lab ls
const comparable = (a, b) => a.epoch === b.epoch && a.comparable && b.comparable;  // the same accepted eval
const onLane = r => r.value == null || r.status === "failed";  // no comparable result: plotted under the axis
const money = v => v ? `$${v.toFixed(2)}` : "–";  // 0 means no cost was recorded, as lab ls prints it
// Display only; Copy keeps the raw command. A word joiner keeps "--" from becoming a dash.
const home = t => String(t)
  .replace(/\/Users\/[^/\s]+/g, "~")
  .replace(/@\d{1,3}(\.\d{1,3}){3}/g, "@‹host›")
  .replace(/--port \d+/g, "--port ‹port›")
  .replace(/(^|\s)--/g, "$1-\u2060-");
// Effect over the noise floor, signed so positive means better: ≥2× likely real, 1–2× marginal, <1× within noise.
function xnoise(c, d) {
  if (d == null || !c.noise) return null;
  const gain = c.goal === "min" ? -d : d, x = gain / c.noise;
  // The tier comes from the size alone; a direction is named only once the change clears the noise floor.
  const ax = Math.abs(x), cls = ax >= 2 ? "real" : ax >= 1 ? "marg" : "noise";
  return { x, cls, t: `${ax.toFixed(1)}×` };
}

/* status marks: a shape per verdict; green only for kept, red only for failed; an earlier lock is grey */
function glyph(k, x, y, old) {
  if (old && k === "keep") return `<circle cx="${x}" cy="${y}" r="4.5" fill="var(--muted)"/>`;
  switch (k) {
    case "keep": return `<circle cx="${x}" cy="${y}" r="4.5" fill="var(--good)"/>`;
    case "revert": return `<circle cx="${x}" cy="${y}" r="4" fill="var(--panel)" stroke="var(--muted)" stroke-width="1.5"/>`;
    case "inconclusive": return `<circle cx="${x}" cy="${y}" r="4.5" fill="var(--panel)" stroke="var(--muted)" stroke-width="1.5" stroke-dasharray="2 2"/>`;
    case "failed": return `<path d="M${x - 3} ${y - 3}l6 6M${x + 3} ${y - 3}l-6 6" stroke="var(--bad)" stroke-width="1.6" stroke-linecap="round"/>`;
    case "running": return `<circle cx="${x}" cy="${y}" r="4.5" fill="none" stroke="var(--ink)" stroke-width="1.5"><animate attributeName="stroke-opacity" values="1;0.25;1" dur="1.6s" repeatCount="indefinite"/></circle><circle cx="${x}" cy="${y}" r="1.8" fill="var(--ink)"/>`;
    default: return `<circle cx="${x}" cy="${y}" r="2" fill="var(--muted)"/>`;
  }
}
const ico = (k, old) => `<svg class="st" width="14" height="14" viewBox="0 0 14 14" aria-label="${LABELS[k]}">${glyph(k, 7, 7, old)}</svg>`;
const mark = (c, r) => ico(kind(r), r.epoch !== c.epoch);
const val = (c, r) => onLane(r) ? '<span class="mut">–</span>' : fv(c, r.value);
const runOpts = (c, sel, skip) => c.runs.filter(x => x !== skip).map(x => `<option value="${x.id}" ${x === sel ? "selected" : ""}>${x.id} · ${esc(x.exp)}</option>`).join("");
const campOpts = () => campaigns.map((x, i) => `<option value="${i}" ${i === S.ci ? "selected" : ""}>${esc(x.name)}</option>`).join("");
const ORDER = ["keep", "revert", "inconclusive", "none", "failed", "running"];
const ICONS = {
  next: '<path d="M2.5 7h8.5M8 4l3 3-3 3"/>',
  chart: '<path d="M1.5 9.5l3-3.5 2.5 2 5-5.5"/><path d="M1.5 12.5h11"/>',
  runs: '<path d="M5 3.5h7.5M5 7h7.5M5 10.5h7.5"/><circle cx="2.25" cy="3.5" r=".6"/><circle cx="2.25" cy="7" r=".6"/><circle cx="2.25" cy="10.5" r=".6"/>',
  findings: '<path d="M7 1.75a3.75 3.75 0 0 0-2.1 6.86V10h4.2V8.61A3.75 3.75 0 0 0 7 1.75z"/><path d="M5.25 12.25h3.5"/>',
  claim: '<path d="M5.25 1.75h3.5M6 1.75v3.5L2.4 11.1a.9.9 0 0 0 .78 1.4h7.64a.9.9 0 0 0 .78-1.4L8 5.25v-3.5"/><path d="M3.9 8.75h6.2"/>',
  compare: '<rect x="1.75" y="2.25" width="4.5" height="9.5" rx="1"/><rect x="7.75" y="2.25" width="4.5" height="9.5" rx="1"/>',
  lineage: '<circle cx="3.5" cy="3" r="1.25"/><circle cx="3.5" cy="11" r="1.25"/><circle cx="10.5" cy="5" r="1.25"/><path d="M3.5 4.25v5.5M10.5 6.25c0 2.25-2 2.75-4 3.25-1.2.3-2 .6-2.5 1"/>',
  files: '<path d="M8 1.75H3.75a1 1 0 0 0-1 1v8.5a1 1 0 0 0 1 1h6.5a1 1 0 0 0 1-1V5z"/><path d="M8 1.75V5h3.25"/>',
  details: '<circle cx="7" cy="7" r="5.25"/><path d="M7 6.25V10M7 4.25v.01"/>',
  command: '<rect x="1.75" y="2.25" width="10.5" height="9.5" rx="1.5"/><path d="M4.25 5.5l1.75 1.5-1.75 1.5M7.5 8.75h2.25"/>',
  changes: '<path d="M4 1.75v6.5M1.75 5h4.5M8 10.25h4.25"/><path d="M8.5 1.75l3 0"/>',
  curves: '<path d="M1.5 11c2-6 4-8 5.5-3s3.5 3 5.5-5"/>',
};
const I = k => `<svg class="ic" width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[k]}</svg>`;
// colour a change only when it is likely real (≥2× noise): green the goal's way, red the other
const tone = (c, d) => { const n = xnoise(c, d); return n && n.cls === "real" ? (n.x > 0 ? "up" : "down") : ""; };
const change = (c, d) => d == null ? "" : `<span class="dv ${tone(c, d)}">${fd(c, d)}</span>${c.noise ? `<span class="xn">${xnoise(c, d).t} noise</span>` : ""}`;
// The run page and the run panel: the change from the parent (or why there is none), the gap to the best, Compare.
const deltaLine = (c, r, p) => r.delta != null ? `<span class="m ${tone(c, r.delta)}">${fd(c, r.delta)}</span><span class="mut">vs ${p.id}${c.noise ? ` · ${xnoise(c, r.delta).t} noise` : ""}</span>`
  : p && p.epoch !== r.epoch ? `<span class="mut">vs ${p.id} · other lock</span>` : "";
const vsBest = (c, r, p) => c.best && r !== c.best && c.best !== p && !onLane(r) ? r.value - c.best.value : null;
const cmpBtn = (c, r, p) => p ? `<a class="btn" href="#cmp/${c.name}/${r.id}/${p.id}" title="c">Compare with ${p.id}</a>` : "";

/* ---------- state, kept in the address: #r/<campaign>/<run> board, #run/… expanded, #cmp/…/<a>/<b>, #term/…, #notes ---------- */
const S = { view: "board", ci: 0, sel: null, other: null, a: null, b: null, diffOnly: true, full: false, tail: false, shut: new Set(),
  tab: "runs", chart: "result", order: "newest", vf: "all", q: "", open: new Set() };
try { S.shut = new Set(JSON.parse(localStorage.getItem("lab.shut") || "[]")); } catch (e) {}
const C = () => campaigns[S.ci];
function readHash() {
  const [v, camp, x, y] = decodeURIComponent(location.hash.slice(1)).split("/");
  const i = campaigns.findIndex(c => c.name === camp);
  if (i >= 0 && i !== S.ci) { S.ci = i; S.sel = null; }
  const c = C();
  if (!c) return;  // no campaigns yet
  S.full = v === "run" && c.byId.has(x);
  if (v === "cmp" && c.byId.has(x) && c.byId.has(y)) { S.view = "cmp"; S.a = x; S.b = y; }
  else if (v === "term") { S.view = "term"; if (c.byId.has(x)) S.sel = x; }
  else if (v === "notes") S.view = "notes";
  else { S.view = "board"; if ((v === "r" || v === "run") && c.byId.has(x)) { S.sel = x; S.other = c.byId.get(x).parent; } }
}
function go(hash) { if (location.hash !== hash) location.hash = hash; else { readHash(); render(); } }
addEventListener("hashchange", () => { readHash(); render(); });

/* ---------- top bar ---------- */
function renderBar(c) {
  document.getElementById("camp").innerHTML = campOpts();
  const r = S.sel, other = S.other || c.byId.get(r).parent || (c.best && c.best.id !== r ? c.best.id : c.runs[0].id);
  document.getElementById("views").innerHTML = [
    ["Board", `#r/${c.name}/${r}`, S.view === "board"], ["Compare", `#cmp/${c.name}/${r}/${other}`, S.view === "cmp"],
    ["Terminal", `#term/${c.name}/${r}`, S.view === "term"], ["Guide", "#notes", S.view === "notes"],
  ].map(([t, h, on]) => `<a href="${h}" ${on ? 'aria-current="page"' : ""}>${t}</a>`).join("");
  const parts = S.full ? [`<span class="sl">/</span><span>${r}</span>`] : S.view === "cmp" ? [`<span class="sl">/</span><span>${S.a} vs ${S.b}</span>`] : [];
  document.getElementById("crumbs").innerHTML = parts.join("");
}

/* ---------- board: header, Next, chart, runs and findings ---------- */
function header(c) {
  const running = c.runs.filter(r => kind(r) === "running");
  const pills = [
    `<span class="pill">${running.length ? `<span class="d" style="background:var(--ink)"></span>${running.length} running` : `<span class="d"></span>Idle · last run ${esc(c.updated || "–")}`}</span>`,
    `<span class="pill m">${esc(c.metric)} ${c.goal === "min" ? "↓" : "↑"}</span>`,
    c.noise ? `<span class="pill m">noise ±${fv(c, c.noise)}</span>` : "",
    c.target != null ? `<span class="pill m">target ${fv(c, c.target)}${c.toGo != null ? (c.toGo === 0 ? " · reached" : ` · ${fv(c, c.toGo)} to go`) : ""}</span>` : "",
    `<span class="pill m">$${c.spent.toFixed(2)}${c.budget ? ` of $${c.budget}` : ""}</span>`,
  ].join("");
  return `<section class="hd"><div class="hd-top"><h1>${esc(c.name)}</h1>${pills}</div><p class="q">${esc(c.question)}</p></section>
  ${c.next.length ? `<section class="next card"><h2 class="hh">${I("next")}Next</h2><ul>${c.next.map(([t, refs]) => `<li><p>${t}</p><span class="refs">${refs.map(rid).join("")}</span></li>`).join("")}</ul></section>` : ""}`;
}
function chartCard(c) {
  return `<section class="card" id="ccard">
    <div class="ch"><h2 class="hh">${I("chart")}${S.chart === "result" ? (c.best ? "Best kept" : "Results") : "Spend"}</h2><span class="seg" role="group" aria-label="Chart"><button type="button" data-chart="result" aria-pressed="${S.chart === "result"}">Result</button><button type="button" data-chart="spend" aria-pressed="${S.chart === "spend"}">Spend</button></span></div>
    <div class="chart" id="chart"></div><div class="legend" id="legend"></div>
  </section>`;
}
// One line (best kept so far), every run as a mark, failed and unscored runs on a lane under the axis.
// Earlier eval locks are grey; the noise band sits on the best; the target is dashed. Selecting moves a ring only.
function drawChart(c) {
  const host = document.getElementById("chart"); if (!host) return;
  const W = Math.max(300, host.clientWidth - 32), H = 220, m = { t: 14, r: 84, b: 24, l: 44 };
  const n = c.runs.length, x = i => m.l + (i + 0.5) * (W - m.l - m.r) / n, hit = Math.min(9, (W - m.l - m.r) / n / 2);
  let svg = "", legend = "";
  host.pos = new Map();
  if (S.chart === "result") {
    const vals = c.runs.filter(r => !onLane(r)).map(r => r.value).concat(c.target != null ? [c.target] : []);
    const [lo, hi] = vals.length ? padded([Math.min(...vals), Math.max(...vals)]) : [0, 1];
    const lane = H - m.b - 4, y = v => m.t + (lane - 16 - m.t) * (1 - (v - lo) / (hi - lo));
    const ticks = niceTicks(lo, hi, 4).filter(t => t >= lo && t <= hi);
    const f = tickFmt(ticks);
    for (const t of ticks) svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(t)}" y2="${y(t)}" stroke="var(--rule)"/><text x="${m.l - 8}" y="${y(t) + 4}" text-anchor="end" font-size="11" fill="var(--muted)" font-family="var(--mono)">${f(t)}</text>`;
    svg += `<text x="${m.l - 8}" y="${lane + 4}" text-anchor="end" font-size="10.5" fill="var(--muted)">none</text>`;
    for (const e of c.epochs) {
      const i = c.runs.findIndex(r => r.id === e.at); if (i <= 0) continue;
      const ex = (x(i) + x(i - 1)) / 2;
      svg += `<line x1="${ex}" x2="${ex}" y1="${m.t - 6}" y2="${lane + 8}" stroke="var(--line)"/><text x="${ex + 6}" y="${m.t}" font-size="10.5" fill="var(--muted)"><title>${esc(e.note)}</title>eval lock ${e.epoch}</text>`;
    }
    if (c.target != null) svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(c.target)}" y2="${y(c.target)}" stroke="var(--ink-2)" stroke-dasharray="4 4"/><text x="${W - m.r + 8}" y="${y(c.target) + 4}" font-size="11" fill="var(--ink-2)">target</text>`;
    const b = c.best, bi = b ? c.runs.indexOf(b) : -1;
    if (b && c.noise) svg += `<rect x="${x(bi)}" y="${y(b.value + c.noise)}" width="${W - m.r - x(bi)}" height="${y(b.value - c.noise) - y(b.value + c.noise)}" fill="var(--band)"/>`;
    let d = "", prev = null;
    c.runs.forEach((r, i) => { const v = r.bestSoFar; if (v == null) { prev = null; return; } d += prev == null ? `M${x(i)},${y(v)}` : `H${x(i)}V${y(v)}`; prev = v; });
    if (d) svg += `<path d="${d}H${W - m.r}" fill="none" stroke="var(--ink)" stroke-width="1.75"/>`;
    if (b) {
      svg += `<text x="${W - m.r + 8}" y="${y(b.value) - 2}" font-size="15" font-weight="500" fill="var(--ink)" font-family="var(--mono)">${fv(c, b.value)}</text><text x="${W - m.r + 8}" y="${y(b.value) + 14}" font-size="11" fill="var(--muted)">${b.id}</text>`;
      if (c.gain) svg += `<text x="${W - m.r + 8}" y="${y(b.value) + 28}" font-size="11" fill="var(--${tone(c, c.gain.delta) === "up" ? "good" : "muted"})" font-family="var(--mono)">${fd(c, c.gain.delta)}</text><text x="${W - m.r + 8}" y="${y(b.value) + 41}" font-size="11" fill="var(--muted)">since ${c.gain.from}</text>`;
    }
    c.runs.forEach((r, i) => {
      const cy = onLane(r) ? lane : y(r.value); host.pos.set(r.id, [x(i), cy]);
      svg += `<g class="pt" data-run="${r.id}"><circle cx="${x(i)}" cy="${cy}" r="${hit}" fill="transparent"/>${glyph(kind(r), x(i), cy, r.epoch !== c.epoch)}</g>`;
    });
    const has = k => c.runs.some(r => kind(r) === k);
    legend = ORDER.filter(has).map(k => `<span>${ico(k)}${LABELS[k]}</span>`).join("") + (b ? lineKey("Best kept", "var(--ink)") : "") + (b && c.noise ? `<span><svg width="16" height="10"><rect x="1" y="1" width="14" height="8" fill="var(--band)"/></svg>Noise</span>` : "") + (c.target != null ? lineKey("Target", "var(--ink-2)", "3 3") : "");
  } else {
    let acc = 0; const cum = c.runs.map(r => (acc += r.cost || 0)), top = Math.max(c.budget || 0, acc, 1) * 1.05;
    const y = v => m.t + (H - m.b - m.t) * (1 - v / top);
    for (const t of niceTicks(0, top, 4).filter(t => t <= top)) svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(t)}" y2="${y(t)}" stroke="var(--rule)"/><text x="${m.l - 8}" y="${y(t) + 4}" text-anchor="end" font-size="11" fill="var(--muted)" font-family="var(--mono)">$${t}</text>`;
    if (c.budget) svg += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(c.budget)}" y2="${y(c.budget)}" stroke="var(--muted)" stroke-dasharray="4 4"/><text x="${W - m.r + 8}" y="${y(c.budget) + 4}" font-size="11" fill="var(--muted)">budget</text>`;
    svg += `<path d="M${x(0)},${y(0)}${cum.map((v, i) => `H${x(i)}V${y(v)}`).join("")}" fill="none" stroke="var(--ink)" stroke-width="1.75"/>`;
    svg += `<text x="${W - m.r + 8}" y="${y(acc) + 4}" font-size="13" font-weight="500" fill="var(--ink)" font-family="var(--mono)">$${acc.toFixed(2)}</text>`;
    c.runs.forEach((r, i) => { host.pos.set(r.id, [x(i), y(cum[i])]); svg += `<g class="pt" data-run="${r.id}"><circle cx="${x(i)}" cy="${y(cum[i])}" r="${hit}" fill="transparent"/>${r.cost ? `<circle cx="${x(i)}" cy="${y(cum[i])}" r="2.5" fill="var(--ink)"/>` : ""}</g>`; });
    legend = lineKey("Spend so far", "var(--ink)") + (c.budget ? lineKey("Budget", "var(--muted)", "3 3") : "");
  }
  const every = Math.ceil(n * 44 / (W - m.l - m.r));
  c.runs.forEach((r, i) => { if (i % every === 0) svg += `<text x="${x(i)}" y="${H - 4}" text-anchor="middle" font-size="10.5" fill="var(--muted)" font-family="var(--mono)">${r.id}</text>`; });
  svg += `<circle id="ring" r="8.5" fill="none" stroke="var(--ink)" stroke-width="1.5"/>`;
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${S.chart === "result" ? "Results by run, with the best kept so far" : "Spend by run"}">${svg}</svg><div class="tip" id="tip"></div>`;
  host.dataset.w = host.clientWidth;
  document.getElementById("legend").innerHTML = legend;
  moveRing();
  const tip = document.getElementById("tip");
  host.querySelectorAll(".pt").forEach(el => {
    el.addEventListener("mouseenter", () => {
      const r = c.byId.get(el.dataset.run), [px, py] = host.pos.get(r.id);
      tip.innerHTML = `<div><b class="m">${r.id}</b> <span class="mut">${esc(r.exp)}</span> · ${LABELS[kind(r)]}</div><div class="m">${fv(c, r.value)} ${r.delta != null ? `<span class="${tone(c, r.delta)}">${fd(c, r.delta)}</span>` : ""}</div><div class="h">${esc(r.hyp)}</div>`;
      tip.style.left = Math.max(0, Math.min(px + 28, host.clientWidth - 290)) + "px"; tip.style.top = Math.max(0, py - 30) + "px"; tip.classList.add("on");
    });
    el.addEventListener("mouseleave", () => tip.classList.remove("on"));
  });
}
// A legend entry for a line: solid lines are drawn at 1.75, dashed ones at 1.
const lineKey = (label, stroke, dash) => `<span><svg width="16" height="10"><path d="M1 5H15" stroke="${stroke}" ${dash ? `stroke-dasharray="${dash}"` : 'stroke-width="1.75"'}/></svg>${label}</span>`;
function moveRing() { const host = document.getElementById("chart"), ring = document.getElementById("ring"), p = host?.pos?.get(S.sel); if (ring && p) { ring.setAttribute("cx", p[0]); ring.setAttribute("cy", p[1]); } }

function visibleRuns(c) {
  const q = S.q.trim().toLowerCase();
  return c.runs.filter(r => (S.vf === "all" || kind(r) === S.vf) && (!q || `${r.id} ${r.exp} ${r.hyp} ${r.note} ${r.tags.join(" ")}`.toLowerCase().includes(q)));
}
function treeOrder(c) { const out = [], walk = r => { out.push(r); c.kids.get(r.id).forEach(walk); }; c.runs.filter(r => !r.parent || !c.byId.has(r.parent)).forEach(walk); return out; }
function runRows(c) {
  const list = new Set(visibleRuns(c)), byExp = S.order === "exp";
  const row = r => `<tr class="r" data-run="${r.id}" aria-selected="${r.id === S.sel}" tabindex="0"><td class="c-st">${mark(c, r)}</td><td class="c-id">${r.id}</td>${byExp ? "" : `<td class="c-ex"><span class="tag">${esc(r.exp)}</span></td>`}<td class="c-hy"${S.order === "tree" && r.depth ? ` style="--d:${Math.min(r.depth, 8)}"` : ""}>${esc(r.hyp) || '<span class="mut">–</span>'}</td><td class="c-v ${r === c.best ? "best" : ""}">${val(c, r)}</td><td class="c-d">${change(c, r.delta)}</td><td class="c-c">${r.cost ? money(r.cost) : ""}</td></tr>`;
  const cols = byExp ? 6 : 7;
  let body = "";
  if (byExp) {
    const groups = new Map(); [...c.runs].reverse().filter(r => list.has(r)).forEach(r => { groups.has(r.exp) || groups.set(r.exp, []); groups.get(r.exp).push(r); });
    for (const [e, rs] of groups) body += `<tr class="g"><td colspan="${cols}">${esc(e)}<i>${rs.length}</i></td></tr>` + rs.map(row).join("");
  } else if (S.order === "tree") body = treeOrder(c).filter(r => list.has(r)).map(row).join("");
  else [...c.runs].reverse().forEach(r => {
    if (list.has(r)) body += row(r);
    const ep = c.epochs.find(e => e.at === r.id);
    if (ep && S.vf === "all" && !S.q) body += `<tr class="ep"><td colspan="${cols}" title="${esc(ep.note)}"><span>Eval lock ${r.epoch} · not comparable with the runs below</span></td></tr>`;
  });
  return `<table class="runs"><thead><tr><th class="c-st"></th><th class="c-id">Run</th>${byExp ? "" : `<th class="c-ex">Experiment</th>`}<th class="c-hy">Hypothesis</th><th class="c-v">Result</th><th class="c-d">Δ parent</th><th class="c-c">Cost</th></tr></thead><tbody>${body || `<tr><td colspan="${cols}" class="mut" style="padding:14px 16px">No runs match</td></tr>`}</tbody></table>`;
}
function findingRows(c) {
  return `<ul class="flist">${c.findings.map(([t, refs], i) => `<li class="${S.open.has(i) ? "open" : ""}" data-note="${i}"><span class="n">${i + 1}</span><p>${t}</p><span class="refs">${refs.slice(0, 2).map(rid).join("")}${refs.length > 2 ? `<span class="rid">+${refs.length - 2}</span>` : ""}</span></li>`).join("")}</ul>`;
}
function tableCard(c) {
  const counts = Object.fromEntries(ORDER.map(k => [k, c.runs.filter(r => kind(r) === k).length]));
  const tabs = [["runs", I("runs") + "Runs", c.runs.length], ["findings", I("findings") + "Findings", c.findings.length]];
  return `<section class="card" id="tcard">
    <div class="tbar" role="tablist">${tabs.map(([k, t, n]) => `<button class="tt" type="button" role="tab" data-tab="${k}" aria-selected="${S.tab === k}">${t}<i>${n}</i></button>`).join("")}
      ${S.tab === "runs" ? `<div class="tools">
        <span class="seg" role="group" aria-label="Order"><button type="button" data-order="newest" aria-pressed="${S.order === "newest"}">Newest</button><button type="button" data-order="tree" aria-pressed="${S.order === "tree"}">Tree</button><button type="button" data-order="exp" aria-pressed="${S.order === "exp"}">By experiment</button></span>
        <select class="vsel" id="vf" aria-label="Verdict"><option value="all">All verdicts</option>${ORDER.filter(k => counts[k]).map(k => `<option value="${k}" ${S.vf === k ? "selected" : ""}>${LABELS[k]} · ${counts[k]}</option>`).join("")}</select>
        <input class="filter" id="q" type="search" placeholder="Filter" value="${esc(S.q)}" aria-label="Filter runs"></div>` : ""}</div>
    <div id="tbody">${S.tab === "runs" ? runRows(c) : findingRows(c)}</div>
  </section>`;
}

/* ---------- run panel: essentials only, docked beside the chart and the list ---------- */
// Ancestors down to this run, then its children, as a small graph: one row per run, the status mark is the node.
function lineage(c, r) {
  const anc = []; let n = r.parent && c.byId.get(r.parent);
  while (n) { anc.unshift(n); n = n.parent && c.byId.get(n.parent); }
  const early = anc.length > 2 ? anc.splice(0, anc.length - 2) : [], ks = c.kids.get(r.id);
  const row = (x, cls) => `<div class="lr ${cls}" data-run="${x.id}"><span class="nd">${mark(c, x)}</span><b>${x.id}</b><span class="ex">${esc(x.exp)}</span><span class="vl">${fv(c, x.value)}</span></div>`;
  return `<div class="lin">
    ${early.length ? `<div class="lr anc fold" data-run="${early[0].id}"><span class="nd"><svg class="st" viewBox="0 0 14 14"><circle cx="7" cy="7" r="1.6" fill="var(--muted)"/></svg></span><span class="ex">${early.length} earlier · from ${early[0].id}</span></div>` : ""}
    ${anc.map(x => row(x, "anc")).join("")}${row(r, "now" + (ks.length ? " anc" : ""))}${ks.map((k, i) => row(k, "kid" + (i < ks.length - 1 ? " sib" : ""))).join("")}
  </div>`;
}
function renderInspector(c) {
  const r = c.byId.get(S.sel), p = r.parent && c.byId.get(r.parent), vb = vsBest(c, r, p);
  document.getElementById("insp").innerHTML = `
    <div class="ph">
      <div class="ph-t"><b>${r.id}</b><span>${esc(r.exp)}</span><button class="x" type="button" id="close" aria-label="Close">✕</button></div>
      <div class="ph-v"><span class="big">${val(c, r)}</span>${deltaLine(c, r, p)}</div>
    </div>
    <dl class="props">
      <dt>Status</dt><dd>${mark(c, r)}${LABELS[kind(r)]}${r === c.best ? ' <span class="pill">Best</span>' : ""}${r.status === "failed" && kind(r) !== "failed" ? ' <span class="pill">run failed</span>' : ""}</dd>
      ${vb != null ? `<dt>vs best</dt><dd class="m">${fd(c, vb)}</dd>` : ""}
      <dt>Started</dt><dd>${esc(r.started)}${dur(r.dur) ? ` · ${dur(r.dur)}` : ""}</dd>
      ${r.cost ? `<dt>Cost</dt><dd class="m">${money(r.cost)}</dd>` : ""}
      ${r.tags.length ? `<dt>Tags</dt><dd>${r.tags.map(esc).join(", ")}</dd>` : ""}
    </dl>
    <div class="blk"><h4>Lineage</h4>${lineage(c, r)}</div>
    <div class="blk"><h4>Hypothesis</h4><p>${esc(r.hyp) || '<span class="mut">–</span>'}</p></div>
    <div class="blk"><h4>Verdict</h4><p>${esc(r.note) || '<span class="mut">–</span>'}</p></div>
    <div class="acts"><a class="btn pri" href="#run/${c.name}/${r.id}" title="Enter">Open run</a>${cmpBtn(c, r, p)}</div>`;
}

function stepSeries(runs) {
  const steps = [...new Set(runs.flatMap(r => r.curve.x))].sort((a, b) => a - b);
  return { x: steps, ys: runs.map(r => { const m = new Map(r.curve.x.map((s, i) => [s, r.curve.y[i]])); return steps.map(s => m.has(s) ? m.get(s) : null); }) };
}
// Long run-together tokens break between a word and a number or after punctuation, never inside a number.
// Only tokens too long for a line get break points, so short ones like FP32 stay whole.
const soft = t => esc(t).replace(/\S{24,}/g, w => w.replace(/([a-z%])(\d)/gi, "$1<wbr>$2").replace(/([/,=;])(?=\S)/g, "$1<wbr>")).replace(/(\d+(?:\.\d+)?e-\d+)/gi, '<span class="nw">$1</span>');
const said = t => t ? soft(t) : `<span class="mut">–</span>`;

/* ---------- the expanded run: everything lab records about one run ---------- */
const chev = `<svg class="chev" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M3 4.5l3 3 3-3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
// A card whose header folds it; which cards are folded is remembered.
const fold = (id, title, body, aside = "", icon = id) => `<section class="card fc${S.shut.has(id) ? " shut" : ""}" data-sec="${id}"><button class="sec-t sh" type="button" aria-expanded="${!S.shut.has(id)}">${ICONS[icon] ? I(icon) : ""}<h2>${title}</h2>${aside ? `<span class="sh-a">${aside}</span>` : ""}${chev}</button><div class="fold-w"><div class="sec-b">${body}</div></div></section>`;
function renderRunPage(c) {
  const r = c.byId.get(S.sel), p = r.parent && c.byId.get(r.parent), X = r.record;
  const vb = vsBest(c, r, p);
  const meta = [esc(r.started), dur(r.dur), r.cost ? money(r.cost) : null, esc(X.host || r.backend)].filter(Boolean).join(" · ");
  const head = `<section class="card rh">
      <div class="rh-t"><h1 class="m">${r.id}</h1><span class="rh-e">${esc(r.exp)}</span><span class="pill">${mark(c, r)}${LABELS[kind(r)]}</span>${r === c.best ? '<span class="pill">Best</span>' : ""}</div>
      <span class="acts2">${cmpBtn(c, r, p)}<a class="btn" href="#term/${c.name}/${r.id}">Raw JSON</a></span>
      <div class="rh-v"><span class="big m">${val(c, r)}</span>
        ${deltaLine(c, r, p)}
        ${vb != null ? `<span class="mut">· ${fd(c, vb)} vs best</span>` : ""}</div>
      <p class="rh-m">${meta}</p>
    </section>`;
  const claim = fold("claim", "Claim", `<dl class="kv">
      <dt>Hypothesis</dt><dd>${said(r.hyp)}</dd><dt>Predicted</dt><dd>${said(r.pred)}</dd><dt>Verdict</dt><dd>${said(r.note)}</dd>
      ${r.tags.length ? `<dt>Tags</dt><dd>${r.tags.map(esc).join(", ")}</dd>` : ""}</dl>`);
  const cmp = fold("compare", "Compare", `<div id="cmp"></div>`);
  const figs = r.figures.length ? fold("figures", "Figures", r.figures.map((f, i) => `<div class="fig" data-i="${i}"></div>`).join("")) : "";
  const lin = fold("lineage", "Lineage", lineage(c, r));
  const files = fold("files", "Files", `<div class="fl">
      ${X.files.map(f => `<div class="fr"><span class="m">${f.name}</span><span class="sz m">${size(f.size)}</span>${f.name === "stdout.log" && X.tail ? `<button class="btn sm" id="tailbtn" type="button">${S.tail ? "Hide tail" : "Tail"}</button>` : "<span></span>"}</div>`).join("")}
      ${r.artifacts.map(a => `<div class="fr"><a class="m" href="${esc(a.href)}" title="${esc(a.title)}">${esc(a.path).replace(/\//g, "/<wbr>")}</a><span class="sz m">${X.artSizes[a.path] != null ? size(X.artSizes[a.path]) : "missing"}</span><span></span></div>`).join("")}
    </div>${S.tail ? `<pre class="code tail">${esc(home(X.tail))}</pre>` : ""}`, `${X.files.length + r.artifacts.length}`);
  const prov = fold("details", "Details", `<dl class="kv tight">
      <dt>Folder</dt><dd class="m">${X.dir.replace(/\//g, "/<wbr>")}/</dd><dt>Eval lock</dt><dd><span class="m">${X.lock.slice(0, 8)}</span> · ${r.epoch}</dd>
      ${X.lib ? `<dt>lib/</dt><dd class="m">${X.lib.slice(0, 8)}</dd>` : ""}<dt>Host</dt><dd>${esc(X.host || r.backend)}</dd><dt>Exit</dt><dd class="m">${X.exit ?? "–"}</dd></dl>`);
  const cmd = fold("command", "Command", `<div class="codebox"><button class="btn sm copy" id="copy" type="button">Copy</button><pre class="code">${esc(home(r.command))}</pre></div>`);
  document.getElementById("mainin").innerHTML = `<div class="pg">${head}<div class="cols"><div class="stack">${claim}${cmp}${figs}</div><div class="stack">${lin}${files}${prov}${cmd}</div></div></div>`;
  renderCompare(c);
  document.querySelectorAll(".fig").forEach(el => renderFigure(el, r.figures[+el.dataset.i]));
}

/* ---------- comparing two runs: one table, numbers right-aligned under right-aligned headers ---------- */
// numbers, durations, costs, run ids and hashes share one mono face; prose stays in the sans
const isNum = v => /^[+−±$-]?\d[\d.,]*(\s?[a-z%]{0,3})?$|^[+−-]?–$|^–$|^r\d+$|^\d+ · [0-9a-f]{6,}$|^[0-9a-f]{7,}$/.test(String(v).trim());
// Attributes come in three groups: the metrics, the run, its setup. A label shows only while one of its rows does.
const GROUPS = { Verdict: "Run", Backend: "Setup" };
function groupLabel(rows, i) {
  const name = i === 0 ? "Metrics" : GROUPS[rows[i].k];
  if (!name) return "";
  const end = rows.findIndex((y, j) => j > i && GROUPS[y.k]), part = rows.slice(i, end < 0 ? rows.length : end);
  return `<tr class="grp${part.every(y => y.same) ? " same" : ""}"><th colspan="4">${name}</th></tr>`;
}
function attrTable(c, a, b) {
  const rows = attrRows(c, a, b), nsame = rows.filter(x => x.same).length;
  return `<div class="at-h"><span class="mut">${rows.length - nsame} of ${rows.length} differ</span>${nsame ? `<label class="chk"><input type="checkbox" id="diffonly" ${S.diffOnly ? "checked" : ""}>Differences only</label>` : ""}</div>
  <div class="at-w"><table class="at${S.diffOnly ? " only" : ""}"><colgroup><col class="k"><col><col><col class="d"></colgroup>
    <thead><tr><th></th><th>${a.id}</th><th>${b.id}</th><th class="r">Δ</th></tr></thead>
    <tbody>${rows.map((x, i) => groupLabel(rows, i) + `<tr class="${x.same ? "same" : ""}${x.key ? " key" : ""}"><th scope="row">${esc(x.k).replace(/_/g, "_<wbr>")}</th><td class="${isNum(x.a) ? "m" : ""}">${x.a}</td><td class="${isNum(x.b) ? "m" : ""}">${x.b}</td><td class="r m ${x.key && comparable(a, b) ? tone(c, a.metrics[x.k] - b.metrics[x.k]) : ""}">${x.d}</td></tr>`).join("")}</tbody>
  </table></div>`;
}
const diffs = ch => (ch.command ? cmdDiff(ch.command) : "") + (ch.diff ? diffHtml(ch.diff) : "");
function changesBody({ ch, linked }) {
  let h = !ch.command && !ch.diff ? `<p class="mut">${linked ? "Same code and command." : "Same command."}</p>` : diffs(ch);
  if (!linked) h += `<p class="mut note2">Code is diffed only between a parent and its child; each run's own change is below.</p>`;
  return h;
}
// Inside the run: this run against its parent, the best run, or any other.
function renderCompare(c) {
  const r = c.byId.get(S.sel), o = S.other && c.byId.get(S.other), p = r.parent && c.byId.get(r.parent);
  const quick = [p && ["parent", p.id], c.best && c.best.id !== r.id && c.best.id !== r.parent && ["best", c.best.id]].filter(Boolean);
  let h = `<div class="cbar">${quick.length ? `<span class="seg">${quick.map(([w, id]) => `<button type="button" data-other="${id}" aria-pressed="${S.other === id}">${id} · ${w}</button>`).join("")}</span>` : ""}
    <label class="pk"><select id="other" aria-label="Compare with any run"><option value="">Other run…</option>${runOpts(c, quick.some(q => q[1] === S.other) ? null : o, r)}</select>${chev}</label>
    ${o ? `<a class="btn" href="#cmp/${c.name}/${r.id}/${o.id}">Full compare</a>` : ""}</div>`;
  if (o) h += attrTable(c, r, o);
  if (r.curve) h += `<div class="sub">${curveBlock(c, r, o)}</div>`;
  if (o) { const x = changes(c, r, o); h += `<div class="sub"><h3>Changes ${x.from.id} → ${x.to.id}</h3>${changesBody(x)}</div>`; }
  document.getElementById("cmp").innerHTML = h;
  drawCurve(c);
}
function attrRows(c, a, b) {
  const num = v => v == null ? "–" : Number.isInteger(v) ? String(v) : v.toFixed(Math.max(c.fmt, 3));
  const keys = [...new Set([c.metric, ...Object.keys(a.metrics), ...Object.keys(b.metrics)])].filter(k => a.metrics[k] != null || b.metrics[k] != null);
  const rows = keys.map(k => {
    const x = a.metrics[k], y = b.metrics[k], dd = x != null && y != null && comparable(a, b) ? x - y : null;
    return { k, a: num(x), b: num(y), d: dd == null ? "–" : (dd > 0 ? "+" : dd < 0 ? "−" : "±") + num(Math.abs(dd)), same: x === y, key: k === c.metric };
  });
  const add = (k, x, y) => rows.push({ k, a: x, b: y, d: "", same: x === y });
  add("Verdict", LABELS[kind(a)], LABELS[kind(b)]);
  add("Δ parent", fd(c, a.delta) || "–", fd(c, b.delta) || "–");
  add("Parent", a.parent || "–", b.parent || "–");
  add("Experiment", esc(a.exp), esc(b.exp));
  add("Hypothesis", esc(a.hyp), esc(b.hyp));
  add("Backend", esc(a.backend), esc(b.backend));
  add("Host", esc(a.record.host || "–"), esc(b.record.host || "–"));
  add("Duration", dur(a.dur) || "–", dur(b.dur) || "–");
  add("Cost", money(a.cost), money(b.cost));
  add("Eval lock", `${a.epoch} · ${a.record.lock.slice(0, 8)}`, `${b.epoch} · ${b.record.lock.slice(0, 8)}`);
  add("lib/ hash", (a.record.lib || "–").slice(0, 8), (b.record.lib || "–").slice(0, 8));
  add("Command", a.command === b.command ? "same" : "differs", a.command === b.command ? "same" : "differs");
  add("Tags", esc(a.tags.join(", ") || "–"), esc(b.tags.join(", ") || "–"));
  return rows;
}
function curveBlock(c, r, o) {
  return `<div class="eyebrow">${esc(r.curve.key)} by step${r.status === "running" ? " · live" : ""}</div><div class="curve-legend"></div><div class="lf-plot curve" data-a="${r.id}" data-b="${o ? o.id : ""}"></div>`;
}
function drawCurve(c) {
  document.querySelectorAll(".curve").forEach(el => {
    const r = c.byId.get(el.dataset.a), o = el.dataset.b && c.byId.get(el.dataset.b);
    const both = o && o.curve && o.curve.key === r.curve.key;
    const { x, ys } = stepSeries(both ? [r, o] : [r]);
    const series = [{ name: r.id, y: ys[0] }];
    if (both) { series.push({ name: o.id, y: ys[1], muted: true }); el.previousElementSibling.innerHTML = legend(series.map(s => [s.name, s.muted ? "var(--muted)" : css("--s1")])); }
    drawLine(el, { title: r.curve.key, x, series, xLabel: "step" }, { height: 150 });
  });
}
function changes(c, a, b) {
  // The record keeps code diffs between a parent and its child; any other pair compares the commands only.
  const aParent = b.id === a.parent, bParent = a.id === b.parent;
  const [from, to] = bParent ? [a, b] : [b, a];
  const ch = aParent ? a.changes : bParent ? b.changes : { command: a.command !== b.command ? [b.command, a.command] : null, diff: null };
  return { from, to, ch, linked: aParent || bParent };
}
function diffHtml(diff) { return `<pre class="diff">${diff.split("\n").map(l => `<span class="${l.startsWith("+") ? "a" : l.startsWith("-") ? "r" : l.startsWith("@@") ? "h" : ""}">${esc(l)}</span>`).join("")}</pre>`; }
// A command change shows once: the shared start and end muted, only the tokens that changed marked.
function cmdDiff([before, after]) {
  const A = home(before).split(" "), B = home(after).split(" ");
  let i = 0; while (i < A.length && i < B.length && A[i] === B[i]) i++;
  let j = 0; while (j < A.length - i && j < B.length - i && A[A.length - 1 - j] === B[B.length - 1 - j]) j++;
  const keep = t => `<span class="same">${esc(t.join(" "))}</span>`;
  const head = A.slice(0, i), tail = A.slice(A.length - j), was = A.slice(i, A.length - j), now = B.slice(i, B.length - j);
  return `<div class="cmddiff">${head.length ? keep(head) + " " : ""}${was.length ? `<del>${esc(was.join(" "))}</del> ` : ""}${now.length ? `<ins>${esc(now.join(" "))}</ins>` : ""}${tail.length ? " " + keep(tail) : ""}</div>`;
}

/* ---------- full compare page: A against B, head to head; B is the reference ---------- */
function renderComparePage(c) {
  const a = c.byId.get(S.a), b = c.byId.get(S.b);
  const same = comparable(a, b), d = same && !onLane(a) && !onLane(b) ? a.value - b.value : null, xn = xnoise(c, d);
  const pick = (id, k, v) => `<label class="pk big"><span class="k">${k}</span><select id="${id}" aria-label="Run ${k}">${runOpts(c, v)}</select>${chev}</label>`;
  const side = (r, k) => `<div class="vs-s"><div class="vs-t"><span class="k">${k}</span><a class="rid" data-run="${r.id}" href="#run/${c.name}/${r.id}">${r.id}</a><span class="mut">${esc(r.exp)}</span></div>
    <div class="vs-v m">${val(c, r)}</div><div class="vs-l">${mark(c, r)}${LABELS[kind(r)]}${r === c.best ? " · best" : ""}</div></div>`;
  const verdict = !same ? "Different eval locks, not comparable" : d == null ? "No comparable result" : !xn ? "Noise not measured" : xn.cls === "noise" ? "Within noise" : `${xn.cls === "real" ? "Likely real" : "Marginal"}, A ${xn.x > 0 ? "better" : "worse"}`;
  const mid = `<div class="vs-d"><span class="k">A − B</span><span class="vs-dv m ${tone(c, d)}">${d == null ? "–" : fd(c, d)}</span><span class="vs-l">${verdict}${xn && xn.cls !== "noise" ? ` · ${xn.t} noise` : ""}</span></div>`;
  const own = r => {
    const p = r.parent && c.byId.get(r.parent), ch = r.changes;
    const body = !p ? `<p class="mut">Root run.</p>` : !ch.command && !ch.diff ? `<p class="mut">Same code and command as ${p.id}.</p>` : diffs(ch);
    return fold(`own-${r === a ? "a" : "b"}`, `${r.id}'s own change`, body, p ? `vs ${p.id}` : "", "changes");
  };
  const x = changes(c, a, b);
  document.getElementById("mainin").innerHTML = `<div class="pg">
    <div class="pbar">${pick("selA", "A", a)}<button class="btn icon" id="swap" type="button" title="Swap A and B (s)" aria-label="Swap A and B"><svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M4 2.5L1.5 5 4 7.5M1.5 5h9M10 6.5l2.5 2.5L10 11.5M12.5 9h-9" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></button>${pick("selB", "B", b)}</div>
    <section class="card vs">${side(a, "A")}${mid}${side(b, "B")}</section>
    <div class="cols">
      <div class="stack"><section class="card"><div class="sh">${I("compare")}<h2>Attributes</h2></div><div class="pad">${attrTable(c, a, b)}</div></section></div>
      <div class="stack">
        ${a.curve ? `<section class="card"><div class="sh">${I("curves")}<h2>Curves</h2></div><div class="pad">${curveBlock(c, a, b)}</div></section>` : ""}
        ${fold("changes", `Changes ${x.from.id} → ${x.to.id}`, changesBody(x))}
        ${x.linked ? "" : own(a) + own(b)}
      </div>
    </div></div>`;
  drawCurve(c);
}

/* ---------- terminal: the real output of lab ls and lab show --json on these records ---------- */
function renderTerminal(c) {
  const r = c.byId.get(S.sel);
  const term = (title, cmd, out, tools = "") => `<section class="card tw"><div class="sh">${I("command")}<h2>${title}</h2>${tools}</div><pre class="tty"><span class="p">$</span> ${cmd}\n${esc(home(out))}</pre></section>`;
  document.getElementById("mainin").innerHTML = `<div class="pg">
    ${term("Runs", `lab -c ${esc(c.name)} ls`, c.ls)}
    ${term("Run record", `lab -c ${esc(c.name)} show ${r.id} --json`, r.record.show, `<label class="pk sm-pk"><select id="termrun" aria-label="Run to show">${runOpts(c, r)}</select>${chev}</label>`)}
  </div>`;
}

/* ---------- notes ---------- */
function renderNotes() {
  const rows = [
    ["Header", "The campaign, its state, metric and direction, noise floor, target and spend. Under it, the question and Next in full."],
    ["Chart", "Every run in start order. The line is the best kept result so far, labelled at its end with the value, the run, and the gain since the first comparable result. Earlier eval locks are grey; runs with no comparable result sit on the none lane. The band is ± noise; dashed is the target. Spend switches to cumulative cost against the budget. Selecting a run moves the ring and never redraws the chart."],
    ["Δ parent", "A run's change from its own parent, with its size in noise units. Coloured only at 2× noise or more (likely real): green the goal's way, red the other."],
    ["Runs", "Newest first, Tree (a run steps in only where its parent has several children), or by experiment. Filter by text or verdict."],
    ["Run panel", "Beside the chart and the list: result and change, status, lineage, hypothesis and verdict. Open run shows everything; Compare opens the full compare."],
    ["Compare", "A against B head to head; attributes grouped as metrics, run and setup, differences only by default. A command change marks only the words that changed; code is diffed between a parent and its child."],
    ["Terminal", "The output of lab ls and lab show --json for these records, captured when the page was built."],
  ];
  const keys = [["j", "next run"], ["k", "previous run"], ["↵", "open the selected run"], ["c", "compare with its parent"], ["/", "filter runs"], ["d", "differences only, on compare"], ["s", "swap A and B, on compare"], ["esc", "close or go back"]];
  document.getElementById("mainin").innerHTML = `<div class="pg guide">
    <h1 class="gt">How to read this board</h1>
    <section class="card"><div class="sh">${I("details")}<h2>Marks</h2></div><div class="pad marks">${ORDER.map(k => `<span>${ico(k)}${LABELS[k]}</span>`).join("")}</div></section>
    <section class="card"><div class="sh">${I("runs")}<h2>Parts</h2></div><div class="pad"><dl class="kv wide">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl></div></section>
    <section class="card"><div class="sh">${I("command")}<h2>Keys</h2></div><div class="pad keys2">${keys.map(([k, v]) => `<span><kbd class="kb">${k}</kbd>${v}</span>`).join("")}</div></section>
  </div>`;
}

/* ---------- render ---------- */
// A new lab, or a campaign without runs yet: say what to do instead of an empty frame.
function renderEmpty(c) {
  document.getElementById("camp").innerHTML = campOpts();
  document.getElementById("views").innerHTML = "";
  document.getElementById("body").classList.add("page");
  const what = c ? `${esc(c.question)}</p><p class="mut">No runs yet. From an experiment folder: <code>lab run -H "hypothesis" -P "prediction" -- &lt;command&gt;</code>, then <code>lab board</code> again.`
    : `Create one with <code>lab new campaign &lt;name&gt; --metric &lt;metric&gt; --goal min|max</code>.`;
  document.getElementById("mainin").innerHTML = `<div class="pg guide"><h1 class="gt">${c ? esc(c.name) : "No campaigns yet"}</h1><p class="q">${what}</p></div>`;
}
const narrow = matchMedia("(max-width: 1100px)");
let lastView = null;
function render() {
  const c = C();
  if (!c || !c.runs.length) { renderEmpty(c); return; }
  if (!S.sel || !c.byId.has(S.sel)) { S.sel = (c.best || c.runs.at(-1)).id; S.other = c.byId.get(S.sel).parent; }
  renderBar(c);
  const board = S.view === "board" && !S.full, key = `${S.view}.${S.full}.${S.ci}`;
  document.getElementById("body").classList.toggle("page", !board);
  if (board) {
    document.getElementById("mainin").innerHTML = header(c) + chartCard(c) + tableCard(c);
    drawChart(c); renderInspector(c);
  } else if (S.view === "board") renderRunPage(c);
  else if (S.view === "cmp") renderComparePage(c);
  else if (S.view === "term") renderTerminal(c);
  else renderNotes();
  if (key !== lastView) {  // a new view fades up once; selection and re-renders inside a view never animate
    document.getElementById("main").scrollTop = 0;
    const mi = document.getElementById("mainin"); mi.classList.remove("enter"); void mi.offsetWidth; if (lastView) mi.classList.add("enter");
  }
  lastView = key;
  panel(false);
}
const panel = on => { document.getElementById("insp").classList.toggle("open", on); document.getElementById("scrim").classList.toggle("on", on); };
function select(id, open = true) {
  const c = C();
  S.sel = id; S.other = c.byId.get(id).parent; S.tail = false;
  if (S.full) { go(`#run/${c.name}/${id}`); return; }  // inside the expanded run, a lineage row opens that run expanded
  if (S.view !== "board") { go(`#r/${c.name}/${id}`); return; }
  try { history.replaceState(null, "", `#r/${c.name}/${id}`); } catch (e) {}
  renderBar(c);
  document.querySelectorAll("tr.r").forEach(tr => tr.setAttribute("aria-selected", tr.dataset.run === id));
  moveRing(); renderInspector(c);
  if (narrow.matches && open) panel(true);
}
const retable = c => { document.getElementById("tcard").outerHTML = tableCard(c); };
const refilter = () => { document.getElementById("tbody").innerHTML = runRows(C()); };
function toggleDiff(c, on = !S.diffOnly) { S.diffOnly = on; S.view === "cmp" ? renderComparePage(c) : renderCompare(c); }

/* ---------- events ---------- */
document.addEventListener("click", e => {
  const c = C(), t = e.target;
  if (t.closest("#close, #scrim")) { panel(false); return; }
  const ch = t.closest("[data-chart]"); if (ch) { S.chart = ch.dataset.chart; document.getElementById("ccard").outerHTML = chartCard(c); drawChart(c); return; }
  const tb = t.closest("[data-tab]"); if (tb) { S.tab = tb.dataset.tab; retable(c); return; }
  const ob = t.closest("[data-order]"); if (ob) { S.order = ob.dataset.order; retable(c); return; }
  const st = t.closest(".sec-t");
  if (st) {
    const box = st.parentElement, id = box.dataset.sec, shut = !S.shut.has(id);
    shut ? S.shut.add(id) : S.shut.delete(id);
    box.classList.toggle("shut", shut); st.setAttribute("aria-expanded", !shut);
    try { localStorage.setItem("lab.shut", JSON.stringify([...S.shut])); } catch (err) {}
    return;
  }
  const note = t.closest("[data-note]");
  if (note && !t.closest(".rid")) { const k = +note.dataset.note; S.open.has(k) ? S.open.delete(k) : S.open.add(k); note.classList.toggle("open"); return; }
  if (t.closest("#tailbtn")) { S.tail = !S.tail; const box = document.getElementById("main"), y = box.scrollTop; renderRunPage(c); box.scrollTop = y; return; }
  if (t.closest("#swap")) { go(`#cmp/${c.name}/${S.b}/${S.a}`); return; }
  const other = t.closest("[data-other]"); if (other) { S.other = other.dataset.other; renderCompare(c); return; }
  if (t.closest("#copy")) {
    const b = t.closest("#copy");
    navigator.clipboard?.writeText(c.byId.get(S.sel).command).then(() => { b.textContent = "Copied"; setTimeout(() => b.textContent = "Copy", 1200); }, () => {});
    return;
  }
  const hit = t.closest("[data-run]");
  if (hit && c.byId.has(hit.dataset.run)) { e.preventDefault(); document.getElementById("tip")?.classList.remove("on"); select(hit.dataset.run); }
});
document.addEventListener("input", e => { if (e.target.id === "q") { S.q = e.target.value; refilter(); } });
document.addEventListener("change", e => {
  const c = C(), id = e.target.id;
  if (id === "camp") { const n = campaigns[+e.target.value]; go(`#r/${n.name}/${n.runs.length ? (n.best || n.runs.at(-1)).id : ""}`); }
  if (id === "vf") { S.vf = e.target.value; refilter(); }
  if (id === "other") { S.other = e.target.value || null; renderCompare(c); }
  if (id === "diffonly") toggleDiff(c, e.target.checked);
  if (id === "selA") go(`#cmp/${c.name}/${e.target.value}/${S.b}`);
  if (id === "selB") go(`#cmp/${c.name}/${S.a}/${e.target.value}`);
  if (id === "termrun") go(`#term/${c.name}/${e.target.value}`);
});
document.addEventListener("keydown", e => {
  const t = e.target, typing = t && /^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName), c = C();
  if (e.key === "Escape") {
    if (typing) { t.blur(); return; }
    if (document.getElementById("insp").classList.contains("open")) { panel(false); return; }
    if (S.view === "cmp") { go(`#r/${c.name}/${S.a}`); return; }
    if (S.view !== "board" || S.full) go(`#r/${c.name}/${S.sel}`);
    return;
  }
  if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
  if (S.view === "cmp") {
    if (e.key === "d") toggleDiff(c);
    if (e.key === "s") go(`#cmp/${c.name}/${S.b}/${S.a}`);
    return;
  }
  if (S.view !== "board") return;
  if (e.key === "/" && document.getElementById("q")) { e.preventDefault(); document.getElementById("q").focus(); return; }
  if ((e.key === "j" || e.key === "k") && !S.full) {
    e.preventDefault();
    const ids = [...document.querySelectorAll("tr.r")].map(tr => tr.dataset.run); if (!ids.length) return;
    let i = ids.indexOf(S.sel); i = i < 0 ? 0 : Math.max(0, Math.min(ids.length - 1, i + (e.key === "j" ? 1 : -1)));
    select(ids[i], false); document.querySelector(`tr.r[data-run="${ids[i]}"]`)?.scrollIntoView({ block: "nearest" }); return;
  }
  if (e.key === "Enter") { e.preventDefault(); go(`#${S.full ? "r" : "run"}/${c.name}/${S.sel}`); return; }
  if (e.key === "c") { const r = c.byId.get(S.sel); if (r.parent) go(`#cmp/${c.name}/${r.id}/${r.parent}`); }
  if (e.key === "d" && document.getElementById("diffonly")) toggleDiff(c);
});
narrow.addEventListener("change", () => panel(false));
const THEMES = [null, "light", "dark"]; let th = 0;
document.getElementById("theme").addEventListener("click", () => {
  th = (th + 1) % 3; THEMES[th] ? document.documentElement.setAttribute("data-theme", THEMES[th]) : document.documentElement.removeAttribute("data-theme");
  if (S.view === "board" && !S.full) drawChart(C());
});
new ResizeObserver(() => { const h = document.getElementById("chart"); if (h && +h.dataset.w !== h.clientWidth) drawChart(C()); }).observe(document.getElementById("main"));
readHash(); render();
