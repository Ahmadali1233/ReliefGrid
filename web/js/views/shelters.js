// Shelters: a real street map (OpenStreetMap) with every shelter, warehouse and supply route,
// plus a searchable, sortable list. If there's no internet, positions and routes still show without streets.
import { act } from "../shared.js";
import { dataTable } from "../table.js";
import { api, esc, gotCell, icon, n, plural, toast, urgencyTag } from "../ui.js";

let selected = null;
let map = null;
const STATUS = { served: "All allocated", partial: "Partly allocated", waiting: "Waiting for stock", none: "No requests" };
const COLOR_VAR = { served: "--good", partial: "--warn", waiting: "--bad", none: "--faint" };
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim() || "#888";

const dayText = (d) => (d === 0 ? "none" : d < 1 ? `${Math.max(1, Math.round(d * 24))} h` : `${d < 10 ? d.toFixed(1).replace(/\.0$/, "") : Math.round(d)} days`);
function coverageHtml(s) {
  const rows = (s.coverage || []).filter((c) => c.days != null || c.share != null);
  if (!s.people) return `<p class="cov-empty">Add today's headcount to see how far its supplies go per person.</p>`;
  if (!rows.length) return "";
  return `<ul class="cov">${rows.map((c) => {
    const flag = s.short_items?.includes(c.item) ? "under" : s.above_items?.includes(c.item) ? "over" : "";
    const val = c.days != null ? `${dayText(c.days)} of ${esc(c.item.toLowerCase())}` : `${esc(c.item)} for ${c.share}% of people`;
    const why = flag === "under" ? "well under an even share" : flag === "over" ? "far above an even share" : "";
    return `<li class="${flag}"><span>${val}</span>${why ? `<small>${why}</small>` : ""}</li>`;
  }).join("")}</ul>`;
}

function km(a, b) {
  if ([a.lat, a.lon, b.lat, b.lon].some((v) => v == null)) return null;
  const r = Math.PI / 180, dLat = (b.lat - a.lat) * r, dLon = (b.lon - a.lon) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLon / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(h));
}

export async function render(main, { params, firstVisit }) {
  if (firstVisit && params.id) selected = params.id;
  const { shelters, warehouses } = await api("/api/shelters");
  if (!selected || !shelters.some((s) => s.id === selected)) {
    selected = (shelters.find((s) => s.status === "waiting") || shelters.find((s) => s.status === "partial") || shelters[0])?.id || null;
  }

  main.innerHTML = `<div class="page ${firstVisit ? "fade-in" : ""}">
    <div class="page-head"><div><h1>Shelters</h1><p>Every shelter and warehouse on the map. Lines show where each shelter's stock is coming from.</p></div>
      <a class="btn" href="#/dispatch">${icon.truck(17)}Dispatch</a></div>
    <div class="row">
      <section class="card grow">
        <div class="map-legend">${["served", "partial", "waiting"].map((k) => `<span><span class="dot" style="background:var(${COLOR_VAR[k]})"></span>${STATUS[k]}</span>`).join("")}
          <span><span class="dot" style="background:var(--ink);border-radius:2px"></span>Warehouse (rings at 10 and 20 km)</span></div>
        <div id="map" class="street-map" role="application" aria-label="Map of shelters and warehouses"></div>
        <p class="map-note" id="map-note">Distances are straight-line; drive times on the Dispatch screen allow for roads.</p>
      </section>
      <aside class="card side" id="shelter-panel" aria-live="polite"></aside>
    </div>
    <section class="card"><div class="card-head"><h2>All shelters</h2><span style="color:var(--muted);font-size:14px">Priority 1 = most vulnerable, served first when urgency is equal</span></div>
      <div id="sh-table"></div></section>
    <section class="card"><h2>Add a shelter</h2><p class="hint">Coordinates put it on the map and let the app choose its nearest warehouse. Tip: right-click a place in Google Maps to copy its coordinates.</p>
      <form class="form" id="sh-form" novalidate>
        <label class="field narrow">ID<input class="input" name="id" placeholder="SH-15" required></label>
        <label class="field wide">Name<input class="input" name="name" placeholder="Al Nahda Community Hall" required></label>
        <label class="field narrow">Priority<select class="input" name="priority"><option value="1">1 · most vulnerable</option><option value="2" selected>2</option><option value="3">3</option></select></label>
        <label class="field narrow">People<input class="input num" name="people" type="number" min="0" step="1" placeholder="e.g. 250"></label>
        <label class="field narrow">Latitude<input class="input num" name="lat" type="number" step="any" placeholder="25.29"></label>
        <label class="field narrow">Longitude<input class="input num" name="lon" type="number" step="any" placeholder="55.37"></label>
        <button class="btn" type="submit">${icon.plus(17)}Add shelter</button>
      </form></section>
  </div>`;

  // ----- Map -----
  const layers = {};
  if (window.L) {
    if (map) { map.remove(); map = null; }
    map = L.map(main.querySelector("#map"), { scrollWheelZoom: false, zoomControl: true });
    let tileFailures = 0;
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).on("tileerror", () => {
      if (++tileFailures === 3) main.querySelector("#map-note").textContent =
        "No internet, so the street map can't load. Shelter positions, warehouses and routes are still accurate.";
    }).addTo(map);
    const whById = Object.fromEntries(warehouses.map((w) => [w.id, w]));
    const maxQ = Math.max(1, ...shelters.flatMap((s) => s.routes.map((r) => r.quantity)));
    for (const w of warehouses.filter((w) => w.lat != null)) {
      [10000, 20000].forEach((m) => L.circle([w.lat, w.lon], { radius: m, color: css("--faint"), weight: 1, dashArray: "3 6", fill: false, interactive: false }).addTo(map));
      L.marker([w.lat, w.lon], { icon: L.divIcon({ className: "", html: '<div class="wh-icon"></div>', iconSize: [18, 18], iconAnchor: [9, 9] }), title: w.name, keyboard: false })
        .bindTooltip(esc(w.name), { direction: "top", offset: [0, -10] }).addTo(map);
    }
    layers.routes = [];
    for (const s of shelters.filter((s) => s.lat != null)) {
      for (const r of s.routes) {
        const w = whById[r.warehouse_id];
        if (!w || w.lat == null) continue;
        const line = L.polyline([[w.lat, w.lon], [s.lat, s.lon]], { color: css("--route"), weight: 1.5 + 4 * Math.sqrt(r.quantity / maxQ), opacity: 0.8, interactive: false }).addTo(map);
        layers.routes.push({ line, shelter: s.id, weight: line.options.weight });
      }
    }
    layers.pins = {};
    for (const s of shelters.filter((s) => s.lat != null)) {
      const pin = L.circleMarker([s.lat, s.lon], { radius: 8, color: css("--surface"), weight: 2, fillColor: css(COLOR_VAR[s.status]), fillOpacity: 1 })
        .bindTooltip(`${esc(s.name)} · ${STATUS[s.status]}`, { direction: "top", offset: [0, -8] })
        .on("click", () => select(s.id, false)).addTo(map);
      layers.pins[s.id] = pin;
    }
    const pts = [...shelters, ...warehouses].filter((p) => p.lat != null).map((p) => [p.lat, p.lon]);
    if (pts.length) map.fitBounds(pts, { padding: [30, 30], maxZoom: 13 }); else map.setView([26.74, 67.79], 10);
  } else {
    main.querySelector("#map").innerHTML = `<div class="empty"><strong>Map library didn't load.</strong>The list below still works.</div>`;
  }

  // ----- Selection: update the panel and the map without redrawing the page -----
  async function select(id, pan = true) {
    selected = id;
    const s = shelters.find((x) => x.id === id);
    const panel = main.querySelector("#shelter-panel");
    if (!s) { panel.innerHTML = `<div class="empty"><strong>No shelters yet.</strong>Add one below.</div>`; return; }
    for (const r of layers.routes || []) r.line.setStyle(r.shelter === id
      ? { color: css("--pink-ink"), opacity: 1, dashArray: "8 6", weight: Math.max(3, r.weight) }
      : { color: css("--route"), opacity: 0.45, dashArray: null, weight: r.weight });
    for (const [pid, pin] of Object.entries(layers.pins || {})) {
      pin.setStyle({ radius: pid === id ? 12 : 8, color: pid === id ? css("--pink-ink") : css("--surface"), weight: pid === id ? 3 : 2 });
      if (pid === id) pin.bringToFront();
    }
    if (pan && map && s.lat != null) map.panTo([s.lat, s.lon]);
    const nearest = warehouses.map((w) => ({ w, d: km(s, w) })).filter((x) => x.d != null).sort((a, b) => a.d - b.d)[0];
    panel.innerHTML = `
      <p class="eyebrow" style="color:var(--muted)">${esc(s.id)} · priority ${s.priority}${s.priority === 1 ? " (most vulnerable)" : ""}</p>
      <h2 style="font-size:24px;margin:4px 0 6px;font-weight:800;letter-spacing:-.02em">${esc(s.name)}</h2>
      <span class="urg"><span class="dot" style="background:var(${COLOR_VAR[s.status]})"></span>${STATUS[s.status]}</span>
      <form class="headcount" data-people novalidate>
        <label>${icon.users(18)}<span>People today</span>
          <input class="input num" name="people" type="number" min="0" step="1" inputmode="numeric" value="${s.people ?? ""}" placeholder="unknown" aria-label="Headcount"></label>
        <button class="btn small" type="submit">Update</button></form>
      ${coverageHtml(s)}
      <dl class="kv">
        <div><dt>Allocated</dt><dd class="num">${n(s.units_received)} of ${n(s.units_requested)}</dd></div>
        <div><dt>Delivered</dt><dd class="num">${n(s.units_delivered)}</dd></div>
        <div style="grid-column:span 2"><dt>Location</dt><dd class="num" style="font-weight:600">${s.lat != null ? `${s.lat.toFixed(4)}, ${s.lon.toFixed(4)}` : "No coordinates"}
          ${nearest ? `<span style="display:block;font-weight:500;color:var(--muted);font-size:13px">Nearest: ${esc(nearest.w.name)}, ${nearest.d.toFixed(1)} km straight-line</span>` : ""}</dd></div>
      </dl>
      <div id="shelter-reqs"><div class="skeleton" style="height:100px"></div></div>
      <div style="display:flex;gap:8px;margin-top:16px;flex-wrap:wrap">
        <a class="btn" style="flex:1" href="#/requests?shelter=${encodeURIComponent(s.id)}">${icon.plus(17)}New request</a>
        <a class="btn" style="flex:1" href="#/dispatch?shelter=${encodeURIComponent(s.name)}">${icon.truck(17)}Its deliveries</a></div>`;
    main.querySelectorAll("#sh-table tr[data-id]").forEach((tr) => tr.classList.toggle("selected", tr.dataset.id === id));
    panel.querySelector("[data-people]").onsubmit = async (e) => {
      e.preventDefault();
      const raw = e.target.people.value.trim();
      const v = Number(raw);
      if (raw !== "" && !(Number.isInteger(v) && v >= 0)) { e.target.people.classList.add("invalid"); return; }
      if (raw === "" ? s.people == null : v === s.people) { toast("Nothing changed."); return; }
      try {
        await act(api(`/api/shelters/${encodeURIComponent(s.id)}`, { method: "PATCH", body: raw === "" ? { clear_people: true } : { people: v } }),
          (r) => `${s.name}: headcount ${r.people == null ? "cleared" : `now ${n(r.people)}`}.`);
      } catch {}
    };
    const reqs = (await api(`/api/requests?shelter_id=${encodeURIComponent(s.id)}`)).filter((r) => r.status !== "cancelled");
    const box = main.querySelector("#shelter-reqs");
    if (box && selected === id) box.innerHTML = reqs.length ? `<table class="t" style="font-size:14px"><tbody>${reqs.map((r) =>
      `<tr><td style="padding-left:0">${esc(r.item)}<span class="sub">${urgencyTag(r.urgency)} · ${esc(r.id)}</span></td><td class="r" style="padding-right:0">${gotCell(r)}</td></tr>`).join("")}</tbody></table>`
      : `<p style="color:var(--muted);margin:0">No requests from this shelter yet.</p>`;
  }

  // ----- List -----
  dataTable(main.querySelector("#sh-table"), {
    id: "shelters", rows: shelters, noun: ["shelter", "shelters"],
    search: { placeholder: "Search shelters", text: (s) => `${s.name} ${s.id}` },
    filters: [
      { key: "status", label: "Status", options: Object.entries(STATUS), test: (s, v) => s.status === v },
      { key: "priority", label: "Priority", options: [["1", "1 · most vulnerable"], ["2", "2"], ["3", "3"]], test: (s, v) => String(s.priority) === v },
      { key: "map", label: "Location", options: [["yes", "On the map"], ["no", "No coordinates"]], test: (s, v) => (v === "yes") === (s.lat != null) },
      { key: "fair", label: "Fair share", options: [["under", "Well under an even share"], ["over", "Far above an even share"], ["unknown", "No headcount"]],
        test: (s, v) => (v === "under" ? s.short_items.length > 0 : v === "over" ? s.above_items.length > 0 : s.people == null) },
    ],
    sort: { key: "priority", dir: 1 },
    rowAttrs: (s) => `class="clickable ${s.id === selected ? "selected" : ""}" tabindex="0" data-id="${esc(s.id)}"`,
    onRow: (s) => { select(s.id); main.querySelector("#map")?.scrollIntoView({ behavior: "smooth", block: "center" }); },
    columns: [
      { key: "name", label: "Shelter", render: (s) => `<span class="strong">${esc(s.name)}</span><span class="sub">${esc(s.id)}</span>` },
      { key: "priority", label: "Priority", align: "r", render: (s) => `<span class="num">${s.priority}</span>` },
      { key: "people", label: "People", align: "r", defaultDir: -1, sort: (s) => s.people ?? -1,
        render: (s) => (s.people != null ? `<span class="num">${n(s.people)}</span>` : `<span style="color:var(--faint)">unknown</span>`) },
      { key: "requests", label: "Requests", align: "r", render: (s) => `<span class="num">${s.requests}</span>` },
      { key: "waiting", label: "Waiting", align: "r", defaultDir: -1, render: (s) => s.waiting ? `<span class="num" style="color:var(--bad-ink);font-weight:700">${s.waiting}</span>` : `<span style="color:var(--faint)">0</span>` },
      { key: "units_received", label: "Allocated", align: "r", sort: (s) => (s.units_requested ? s.units_received / s.units_requested : 1),
        render: (s) => `<span class="num">${n(s.units_received)} / ${n(s.units_requested)}</span>` },
      { key: "units_delivered", label: "Delivered", align: "r", render: (s) => `<span class="num">${n(s.units_delivered)}</span>` },
      { key: "status", label: "Status", sort: (s) => ({ waiting: 0, partial: 1, served: 2, none: 3 })[s.status],
        render: (s) => `<span class="urg"><span class="dot" style="background:var(${COLOR_VAR[s.status]})"></span>${STATUS[s.status]}</span>` },
    ],
    empty: "No shelters yet. Add one below or import a shelters file.",
  });

  if (selected) select(selected, false); else main.querySelector("#shelter-panel").innerHTML = `<div class="empty"><strong>No shelters yet.</strong>Add one below.</div>`;

  const form = main.querySelector("#sh-form");
  form.onsubmit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(form));
    const body = { id: f.id.trim(), name: f.name.trim(), priority: Number(f.priority), people: f.people === "" ? null : Number(f.people),
                   lat: f.lat === "" ? null : Number(f.lat), lon: f.lon === "" ? null : Number(f.lon) };
    try { await act(api("/api/shelters", { method: "POST", body }), `${body.name} added.`); selected = body.id; } catch {}
  };
}
