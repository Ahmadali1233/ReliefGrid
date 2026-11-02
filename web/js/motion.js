// Small, purposeful motion. Each one shows something true about the data, never decoration:
//   truckStrip / runTruck   where a waybill is right now, between its warehouse and its shelter, with time to go
//   openCapResult           what a days cap actually changed, shelter by shelter (bars move from before to after)
//   celebrate               a tick where you clicked when work is really done (order sent, delivery signed)
// Everything respects "reduce motion" in the operating system.
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const num = (x) => Number(x).toLocaleString("en-US");
export const calm = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

// ---------- Tick burst ----------
// Remember where the person last clicked or pressed Enter, so the tick appears where their attention is.
let lastPoint = null;
addEventListener("pointerdown", (e) => { lastPoint = { x: e.clientX, y: e.clientY, t: Date.now() }; }, true);
addEventListener("keydown", (e) => {
  if (e.key !== "Enter" && e.key !== " ") return;
  const r = document.activeElement?.getBoundingClientRect?.();
  if (r && r.width) lastPoint = { x: r.left + r.width / 2, y: r.top + r.height / 2, t: Date.now() };
}, true);

export function celebrate(target) {
  if (calm()) return;
  let x = innerWidth / 2, y = innerHeight / 2;
  if (!target && lastPoint && Date.now() - lastPoint.t < 10000) ({ x, y } = lastPoint);
  if (target instanceof Element && target.isConnected) {
    const r = target.getBoundingClientRect();
    x = r.left + r.width / 2; y = r.top + r.height / 2;
  } else if (target && typeof target.x === "number") ({ x, y } = target);
  const el = document.createElement("div");
  el.className = "burst";
  el.style.left = `${x}px`; el.style.top = `${y}px`;
  el.innerHTML = `<svg viewBox="-60 -60 120 120" width="120" height="120" aria-hidden="true"><circle class="b-ring" r="20"/>
    ${[...Array(8)].map((_, i) => `<g transform="rotate(${i * 45 + 22.5})"><line class="b-ray" x1="0" y1="-24" x2="0" y2="-36"/></g>`).join("")}
    <g class="b-tick"><circle r="16"/><path d="M-7 0.5l4.5 4.5 9-9" pathLength="1"/></g></svg>`;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 1100);
}

// ---------- Truck on its route ----------
const TRUCK = `<svg viewBox="0 0 70 40" width="70" height="40" aria-hidden="true">
  <g class="tr-body"><rect x="2" y="4" width="40" height="24" rx="4" class="tr-box"/><rect x="2" y="21" width="40" height="3" class="tr-stripe"/>
  <path d="M44 28V12a2 2 0 0 1 2-2h9l8 8.5V28z" class="tr-cab"/><path d="M47 13h7l5.5 5.5H47z" class="tr-win"/></g>
  <g class="tr-wheel" style="transform-origin:14px 31px"><circle cx="14" cy="31" r="6"/><path d="M14 26.5v9M9.5 31h9"/></g>
  <g class="tr-wheel" style="transform-origin:32px 31px"><circle cx="32" cy="31" r="6"/><path d="M32 26.5v9M27.5 31h9"/></g>
  <g class="tr-wheel" style="transform-origin:55px 31px"><circle cx="55" cy="31" r="6"/><path d="M55 26.5v9M50.5 31h9"/></g></svg>`;

export function truckStrip(t) {
  if (!t || t.type !== "waybill") return "";
  const left = (t.steps.find((s) => s.label === "Left the warehouse") || {}).at || "";
  return `<div class="truck-strip ${t.status}" data-status="${esc(t.status)}" data-left="${esc(left)}" data-eta="${esc(t.eta || "")}" style="--p:${t.status === "delivered" ? 1 : 0}">
    <div class="ts-road"><span class="ts-fill"></span></div>
    <span class="ts-pin ts-from" aria-hidden="true"></span><span class="ts-pin ts-to" aria-hidden="true"></span>
    <div class="ts-truck">${TRUCK}</div>
    <div class="ts-labels"><span>${esc(t.from.name)}</span><strong class="ts-eta" aria-live="polite"></strong><span>${esc(t.to.name)}</span></div></div>`;
}

export function runTruck(root) {
  const box = root.querySelector(".truck-strip");
  if (!box) return;
  const update = () => {
    if (!box.isConnected) { clearInterval(timer); return; }
    const s = box.dataset.status;
    let p = s === "delivered" ? 1 : 0, text = s === "delivered" ? "Delivered" : "Being loaded";
    if (s === "on_the_way") {
      const a = Date.parse(box.dataset.left), b = Date.parse(box.dataset.eta), now = Date.now();
      if (a && b && b > a) {
        p = Math.min(0.96, Math.max(0.04, (now - a) / (b - a)));
        const mins = Math.round((b - now) / 60000);
        text = mins <= 0 ? "Arriving now" : mins < 60 ? `About ${mins} min to go` : `About ${Math.floor(mins / 60)} h ${mins % 60} min to go`;
      } else { p = 0.5; text = "On the way"; }
    }
    box.style.setProperty("--p", p);
    box.querySelector(".ts-eta").textContent = text;
  };
  // Start from the warehouse so the truck visibly drives to where it is now.
  requestAnimationFrame(() => requestAnimationFrame(update));
  const timer = setInterval(update, 5000);
}

// ---------- Fair share: what a days cap changed ----------
// before/after: /api/shelters shelters (with coverage). Shows the shelters whose days of supply moved the most.
export function capChanges(before, after) {
  const key = (c) => `${c.shelter_id}|${c.item}`;
  const was = new Map(before.flatMap((s) => (s.coverage || []).filter((c) => c.days != null).map((c) => [key(c), c])));
  const rows = [];
  for (const s of after) for (const c of s.coverage || []) {
    if (c.days == null) continue;
    const b = was.get(key(c));
    if (b && Math.abs(b.days - c.days) >= 0.05) rows.push({ name: s.name, item: c.item, people: s.people, before: b.days, after: c.days });
  }
  return rows.sort((x, y) => Math.abs(y.after - y.before) - Math.abs(x.after - x.before)).slice(0, 6);
}

export function capBarsHtml(rows, days) {
  if (!rows.length) return `<p class="hint">Nothing had more than ${days} days, so nothing moved.</p>`;
  const max = Math.max(days * 1.6, ...rows.map((r) => Math.max(r.before, r.after)));
  const pct = (v) => `${Math.max(1.2, (v / max) * 100)}%`;
  return `<div class="cap-bars" style="--cap:${days / max}">
    <span class="cap-line" data-label="${days}-day cap"></span>
    ${rows.map((r) => `<div class="cap-row">
      <div class="cap-name"><strong>${esc(r.name)}</strong><span>${esc(r.item)}${r.people ? ` · ${num(r.people)} people` : ""}</span></div>
      <div class="cap-track"><span class="cap-bar ${r.after < r.before ? "down" : "up"}" style="width:${pct(r.before)}" data-to="${pct(r.after)}"></span></div>
      <div class="cap-val"><span class="cap-num" data-from="${r.before}" data-to="${r.after}">${fmt(r.before)}</span> days</div></div>`).join("")}</div>`;
}
const fmt = (d) => (d >= 10 ? Math.round(d) : Math.round(d * 10) / 10).toString();

export function playCapBars(root) {
  const bars = root.querySelectorAll(".cap-bar"), nums = root.querySelectorAll(".cap-num");
  const go = () => {
    bars.forEach((b) => { b.style.width = b.dataset.to; b.classList.add("moved"); });
    if (calm()) { nums.forEach((x) => (x.textContent = fmt(Number(x.dataset.to)))); return; }
    const t0 = performance.now(), D = 1200;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / D), e = 1 - Math.pow(1 - k, 3);
      nums.forEach((x) => { const a = Number(x.dataset.from), b = Number(x.dataset.to); x.textContent = fmt(a + (b - a) * e); });
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };
  setTimeout(go, calm() ? 0 : 450);
}
