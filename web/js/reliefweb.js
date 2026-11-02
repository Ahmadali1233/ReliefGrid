// The relief web: the whole operation drawn as a spider web.
//   centre      the warehouses (the hub)
//   rings       shelter priority: the most vulnerable shelters sit on the inner ring
//   spokes      one per shelter, placed in its real compass direction (north is up), evenly spaced
//   threads     loads from a warehouse to a shelter: moving = truck on the road, dashed = waiting for a truck,
//               solid = delivered. Thicker = more units.
//   node size   how many people are in the shelter
import { esc, n } from "./ui.js";

const W = 560, H = 440, CX = 280, CY = 214, R = 172;
const STATE_TEXT = {
  waiting: "still waiting for stock", to_load: "stock reserved, waiting for a truck",
  on_the_way: "truck on the way", delivered: "everything delivered", none: "no requests",
};

function polar(angle, r) { return [CX + r * Math.cos(angle), CY + r * Math.sin(angle)]; }
const f = (x) => x.toFixed(1);

export function drawReliefWeb(box, net) {
  const shelters = net.shelters.slice();
  if (!shelters.length) {
    box.innerHTML = `<div class="web-empty">Add shelters and the relief web draws itself here.</div>`;
    return;
  }
  // Compass direction of each shelter from the middle of all shelters; then spread evenly in that order.
  const located = shelters.filter((s) => s.lat != null && s.lon != null);
  const clat = located.reduce((a, s) => a + s.lat, 0) / (located.length || 1);
  const clon = located.reduce((a, s) => a + s.lon, 0) / (located.length || 1);
  const geo = (lat, lon) => Math.atan2(-(lat - clat), (lon - clon) * Math.cos((clat * Math.PI) / 180));
  shelters.forEach((s) => { s._geo = s.lat != null ? geo(s.lat, s.lon) : Math.PI * 4; });
  shelters.sort((a, b) => a._geo - b._geo);
  const step = (2 * Math.PI) / shelters.length;
  const start = located.length ? shelters[0]._geo : -Math.PI / 2;
  shelters.forEach((s, i) => { s._a = start + i * step; });

  const levels = [...new Set(shelters.map((s) => s.priority))].sort((a, b) => a - b);
  const ringR = (p) => (levels.length === 1 ? R * 0.78 : R * (0.4 + (0.6 * levels.indexOf(p)) / (levels.length - 1)));
  const maxPeople = Math.max(1, ...shelters.map((s) => s.people || 0));
  const nodeR = (s) => (s.people ? 5 + 11 * Math.sqrt(s.people / maxPeople) : 6);
  shelters.forEach((s) => { [s._x, s._y] = polar(s._a, ringR(s.priority)); s._r = nodeR(s); });

  // Warehouses in the hub, in their compass direction from the shelters' centre, spread so they never overlap.
  const nW = net.warehouses.length;
  const geoA = net.warehouses.map((w, i) => (w.lat != null ? geo(w.lat, w.lon) : (i / Math.max(nW, 1)) * 2 * Math.PI));
  const meanA = Math.atan2(geoA.reduce((a, x) => a + Math.sin(x), 0), geoA.reduce((a, x) => a + Math.cos(x), 0));
  const order = geoA.map((a, i) => [a, i]).sort((x, y) => x[0] - y[0]).map(([, i]) => i);
  const gap = Math.min((2 * Math.PI) / Math.max(nW, 1), (100 * Math.PI) / 180);
  const whs = net.warehouses.map((w, i) => {
    const slot = order.indexOf(i);
    const a = nW === 1 ? meanA : meanA + (slot - (nW - 1) / 2) * gap;
    const r = nW === 1 ? 0 : R * 0.2;
    const [x, y] = polar(a, r);
    return { ...w, _x: x, _y: y, _lx: x, _ly: y + 23, _short: (w.name.split("·")[1] || w.id).trim() };
  });
  const whById = Object.fromEntries(whs.map((w) => [w.id, w]));
  const shById = Object.fromEntries(shelters.map((s) => [s.id, s]));

  // The web itself: spokes, then sagging spiral threads between neighbouring spokes.
  let webPaths = "";
  for (const s of shelters) {
    const [x, y] = polar(s._a, R + 22);
    webPaths += `M${CX} ${CY}L${f(x)} ${f(y)}`;
  }
  const rings = [...new Set([R * 0.2, ...levels.map(ringR), R + 12, R * 0.56, R * 0.86])].sort((a, b) => a - b);
  for (const r of rings) {
    for (let i = 0; i < shelters.length; i++) {
      const a1 = shelters[i]._a, a2 = shelters[(i + 1) % shelters.length]._a + (i + 1 === shelters.length ? 2 * Math.PI : 0);
      const [x1, y1] = polar(a1, r), [x2, y2] = polar(a2, r), [qx, qy] = polar((a1 + a2) / 2, r * 0.9);
      webPaths += `M${f(x1)} ${f(y1)}Q${f(qx)} ${f(qy)} ${f(x2)} ${f(y2)}`;
    }
  }

  // Threads: one per warehouse-shelter pair, styled by the most active stage.
  const maxUnits = Math.max(1, ...net.links.map((l) => l.allocated + l.dispatched + l.delivered));
  const threads = net.links.map((l) => {
    const w = whById[l.warehouse_id], s = shById[l.shelter_id];
    if (!w || !s) return "";
    const units = l.allocated + l.dispatched + l.delivered;
    const width = 1.2 + 3.2 * Math.sqrt(units / maxUnits);
    const stage = l.dispatched ? "moving" : l.allocated ? "loading" : "done";
    const [ex, ey] = polar(s._a, ringR(s.priority) - s._r - 2);
    const mx = (w._x + ex) / 2, my = (w._y + ey) / 2;
    const [cx, cy] = [mx + (CX - mx) * 0.25, my + (CY - my) * 0.25];
    const what = [l.delivered && `${n(l.delivered)} delivered`, l.dispatched && `${n(l.dispatched)} on the road`,
      l.allocated && `${n(l.allocated)} waiting for a truck`].filter(Boolean).join(", ");
    return `<path class="thr ${stage}" data-sh="${esc(s.id)}" data-state="${stage === "moving" ? "on_the_way" : stage === "loading" ? "to_load" : "delivered"}" d="M${f(w._x)} ${f(w._y)}Q${f(cx)} ${f(cy)} ${f(ex)} ${f(ey)}" stroke-width="${f(width)}"><desc>${esc(w.name)} to ${esc(s.name)}: ${what}</desc></path>`;
  }).join("");

  const nodes = shelters.map((s) => {
    const label = s.name.replace(/\b(Community|Shelter|Centre|Center|Hall|School|Point|Camp|Relief|Sports|Youth|Mosque|Medical|Clinic|Government|Complex|Town)\b/g, "").replace(/\s+/g, " ").trim() || s.name;
    const out = ringR(s.priority) + s._r + 8;
    const [lx, ly] = polar(s._a, out);
    const cos = Math.cos(s._a);
    const anchor = cos > 0.3 ? "start" : cos < -0.3 ? "end" : "middle";
    const dy = Math.sin(s._a) > 0.5 ? 10 : Math.sin(s._a) < -0.5 ? -2 : 4;
    const people = s.people ? `${n(s.people)} people` : "headcount unknown";
    const waitingText = s.waiting ? ` · waiting for ${s.waiting_items.join(", ").toLowerCase()}` : "";
    return `<a href="#/shelters?id=${encodeURIComponent(s.id)}" class="node ${s.state}${s.waiting_critical ? " critical" : ""}" data-sh="${esc(s.id)}" data-state="${s.state}"
      aria-label="${esc(s.name)}, ${people}, priority ${s.priority}, ${STATE_TEXT[s.state]}${esc(waitingText)}">
      ${s.waiting_critical ? `<circle class="halo" cx="${f(s._x)}" cy="${f(s._y)}" r="${f(s._r + 5)}"/>` : ""}
      <circle class="dot${s.people ? "" : " unknown"}" cx="${f(s._x)}" cy="${f(s._y)}" r="${f(s._r)}"/>
      <text x="${f(lx)}" y="${f(ly + dy)}" text-anchor="${anchor}">${esc(label)}</text></a>`;
  }).join("");

  const hub = whs.map((w) => `<g class="wh" aria-label="${esc(w.name)}">
      <rect x="${f(w._x - 9)}" y="${f(w._y - 9)}" width="18" height="18" rx="5"/>
      <text x="${f(w._lx)}" y="${f(w._ly)}" text-anchor="middle">${esc(w._short)}</text></g>`).join("");

  // Ring names sit in the widest gap between spokes, so they never sit on top of a shelter.
  let gapAngle = -Math.PI / 2, widest = -1;
  shelters.forEach((sh, i) => {
    const next = shelters[(i + 1) % shelters.length]._a + (i + 1 === shelters.length ? 2 * Math.PI : 0);
    if (next - sh._a > widest) { widest = next - sh._a; gapAngle = (sh._a + next) / 2; }
  });
  const ringLabels = levels.map((p) => {
    const [x, y] = polar(gapAngle, ringR(p));
    return `<g class="ring-label" aria-label="Priority ${p} ring"><circle cx="${f(x)}" cy="${f(y)}" r="8.5"/>
      <text x="${f(x)}" y="${f(y + 3.5)}" text-anchor="middle">${p}</text></g>`;
  }).join("");
  const counts = { waiting: 0, to_load: 0, on_the_way: 0, delivered: 0, none: 0 };
  shelters.forEach((sh) => { counts[sh.state] += 1; });

  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Relief web: ${shelters.length} shelters around ${whs.length} warehouses. ${shelters.filter((s) => s.state === "waiting").length} still waiting for stock.">
      <path class="strands" d="${webPaths}"/>
      ${ringLabels}
      <g class="threads">${threads}</g>
      ${hub}
      <g class="nodes">${nodes}</g>
    </svg>
    <div class="web-card" role="tooltip" hidden></div>
    <div class="web-states" role="group" aria-label="Show shelters by state">
      ${[["waiting", "Waiting for stock"], ["to_load", "Waiting for a truck"], ["on_the_way", "Truck on the road"], ["delivered", "Delivered"]].map(([k, l]) =>
        `<button type="button" class="ws ${k}" data-state="${k}" aria-pressed="false" ${counts[k] ? "" : "disabled"}><span class="sw"></span><strong>${counts[k]}</strong>${l}</button>`).join("")}
    </div>
    <p class="web-help">Each dot is a shelter; bigger means more people. Rings are shelter priority: <span class="ring-key">1</span> inner, most vulnerable, to <span class="ring-key">${levels[levels.length - 1]}</span> outer. Lines are loads from the warehouses in the middle. Tap a state to pick those shelters out.</p>`;

  // Hover or focus a shelter: light up its loads, dim the rest, and show a card with the details.
  const svg = box.querySelector("svg"), card = box.querySelector(".web-card");
  const byId = Object.fromEntries(shelters.map((sh) => [sh.id, sh]));
  const linksOf = (id) => net.links.filter((l) => l.shelter_id === id);
  const showCard = (a) => {
    const sh = byId[a.dataset.sh];
    const ls = linksOf(sh.id);
    const sum = (k) => ls.reduce((t, l) => t + l[k], 0);
    const rows = [["Delivered", sum("delivered")], ["On the road", sum("dispatched")], ["Waiting for a truck", sum("allocated")]].filter(([, v]) => v);
    card.innerHTML = `<div class="wc-top"><strong>${esc(sh.name)}</strong><span class="wc-pri p${sh.priority}">Priority ${sh.priority}</span></div>
      <div class="wc-state ${sh.state}"><span class="sw"></span>${esc(STATE_TEXT[sh.state][0].toUpperCase() + STATE_TEXT[sh.state].slice(1))}</div>
      <dl>
        <div><dt>People</dt><dd>${sh.people != null ? n(sh.people) : "<em>unknown</em>"}</dd></div>
        <div><dt>Requests</dt><dd>${n(sh.requests)}${sh.waiting ? `, <b>${n(sh.waiting)} waiting</b>` : ""}</dd></div>
        ${sh.waiting ? `<div class="wide"><dt>Still needs</dt><dd>${esc(sh.waiting_items.join(", "))}${sh.waiting_critical ? ` <span class="crit">${sh.waiting_critical} critical</span>` : ""}</dd></div>` : ""}
        ${rows.map(([k, v]) => `<div><dt>${k}</dt><dd>${n(v)} units</dd></div>`).join("")}
      </dl><p class="wc-hint">Click to open this shelter</p>`;
    card.hidden = false;
    const fig = box.getBoundingClientRect(), dot = a.querySelector(".dot").getBoundingClientRect();
    const cw = card.offsetWidth, ch = card.offsetHeight;
    let left = dot.right - fig.left + 12, top = dot.top - fig.top + dot.height / 2 - ch / 2;
    if (left + cw > fig.width) left = dot.left - fig.left - cw - 12;
    if (left < 0) left = Math.max(0, Math.min(fig.width - cw, dot.left - fig.left - cw / 2));
    top = Math.max(0, Math.min(top, fig.height - ch));
    card.style.left = `${left}px`; card.style.top = `${top}px`;
  };
  const off = () => { svg.classList.remove("focus"); svg.querySelectorAll(".lit").forEach((el) => el.classList.remove("lit")); card.hidden = true; };
  box.querySelectorAll(".node").forEach((a) => {
    const on = () => { off(); svg.classList.add("focus"); svg.querySelectorAll(`[data-sh="${CSS.escape(a.dataset.sh)}"]`).forEach((el) => el.classList.add("lit")); showCard(a); };
    a.addEventListener("mouseenter", on); a.addEventListener("mouseleave", off);
    a.addEventListener("focus", on); a.addEventListener("blur", off);
  });
  // State buttons pick out every shelter (and load) in that state.
  box.querySelectorAll(".ws").forEach((b) => (b.onclick = () => {
    const on = b.getAttribute("aria-pressed") !== "true";
    box.querySelectorAll(".ws").forEach((x) => x.setAttribute("aria-pressed", "false"));
    svg.classList.toggle("only", on);
    svg.querySelectorAll(".picked").forEach((el) => el.classList.remove("picked"));
    if (on) {
      b.setAttribute("aria-pressed", "true");
      svg.querySelectorAll(`.node[data-state="${b.dataset.state}"]`).forEach((el) => {
        el.classList.add("picked");
        svg.querySelectorAll(`.thr[data-sh="${CSS.escape(el.dataset.sh)}"]`).forEach((t) => t.classList.add("picked"));
      });
    }
  }));
}
