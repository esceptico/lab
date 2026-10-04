const DATA = JSON.parse(document.getElementById("data").textContent);

function drawFigure(el) {
  const f = DATA.figures[+el.dataset.f], i = +(el.dataset.i || 0), spec = f.options[i].spec;
  const sw = f.options.length > 1
    ? `<div>${f.label ? `<span class="switch-label">${esc(f.label)}</span>` : ""}<div class="switch" role="group">${f.options.map((o, n) =>
        `<button aria-pressed="${n === i}" data-n="${n}">${esc(o.label)}</button>`).join("")}</div></div>` : "";
  el.innerHTML = sw + "<div></div>";
  renderFigure(el.lastElementChild, spec);
}
function drawAll() { document.querySelectorAll(".rfig").forEach(drawFigure); }

document.addEventListener("click", e => {
  const b = e.target.closest(".switch button");
  if (b) { const el = b.closest(".rfig"); el.dataset.i = b.dataset.n; drawFigure(el); }
});

const card = document.getElementById("card");
function fmt(v) { return v == null ? "–" : v.toFixed(DATA.fmt); }
document.addEventListener("pointerover", e => {
  const a = e.target.closest("a[data-run]");
  if (!a || !DATA.runs[a.dataset.run]) return;
  const r = DATA.runs[a.dataset.run];
  const inside = r.change === "within_noise";
  card.innerHTML = `<div class="t">${r.id} <span>${esc(r.exp)} · ${r.status === "ok" ? DATA.labels[r.verdict || "none"] : r.status}</span></div>
    <dl><dt>Hypothesis</dt><dd>${esc(r.hyp || "not stated")}</dd>
    <dt>Predicted</dt><dd>${esc(r.pred || "not stated")}</dd>
    <dt>${esc(DATA.metric)}</dt><dd class="num">${fmt(r.value)}${r.delta != null ? ` <span class="${r.change === "better" ? "good" : "muted"}">${r.delta >= 0 ? "+" : "−"}${fmt(Math.abs(r.delta))} vs ${r.parent}${inside ? ", inside noise" : ""}</span>` : ""}</dd>
    ${r.note ? `<dt>Verdict</dt><dd>${esc(r.note)}</dd>` : ""}</dl>`;
  const box = a.getBoundingClientRect(), w = card.offsetWidth;
  card.style.left = Math.max(12, Math.min(scrollX + box.left, scrollX + innerWidth - w - 12)) + "px";
  card.style.top = scrollY + box.bottom + 8 + "px";
  card.classList.add("on");
});
document.addEventListener("pointerout", e => { if (e.target.closest("a[data-run]")) card.classList.remove("on"); });

const THEMES = ["auto", "light", "dark"]; let theme = 0;
document.getElementById("theme").addEventListener("click", () => {
  theme = (theme + 1) % 3; const t = THEMES[theme];
  if (t === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
  document.getElementById("theme").textContent = t[0].toUpperCase() + t.slice(1);
  drawAll();
});
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", drawAll);
let lastW = 0;
new ResizeObserver(() => { const w = document.querySelector("article").clientWidth; if (w !== lastW) { lastW = w; drawAll(); } }).observe(document.querySelector("article"));
