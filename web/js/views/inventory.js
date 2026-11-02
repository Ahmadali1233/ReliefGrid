// Inventory: what's on the shelves, what's reserved for shelters, what's still needed.
import { act, openRestock, openSupplyRequest } from "../shared.js";
import { dataTable } from "../table.js";
import { api, esc, icon, n, plural } from "../ui.js";

const lasts = (h) => (h < 1 ? `~${Math.max(1, Math.round(h * 60))} min` : h < 48 ? `~${h < 10 ? h.toFixed(1).replace(/\.0$/, "") : Math.round(h)} h` : `~${Math.round(h / 24)} days`);
const STATUS = { ok: "In stock", low: "Running low", out: "Out of stock" };

export async function render(main, { firstVisit }) {
  const [items, sh] = await Promise.all([api("/api/inventory"), api("/api/shelters")]);
  const warehouses = sh.warehouses;
  const short = items.filter((i) => i.to_order > 0);
  const shortTotal = short.reduce((a, i) => a + i.to_order, 0);

  main.innerHTML = `<div class="page ${firstVisit ? "fade-in" : ""}">
    <div class="page-head"><div><h1>Inventory</h1>
      <p>${plural(items.length, "item")} across ${plural(warehouses.length, "warehouse")}. ${shortTotal ? `${n(shortTotal)} units still need ordering for waiting requests.` : "Nothing left to order: stock and open orders cover every waiting request."}</p></div>
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        ${short.length ? `<button class="btn" type="button" data-ask-all>${icon.chat(17)}Order what's missing</button>` : ""}
        <button class="btn primary" type="button" data-delivery="">${icon.box(18)}Record delivery</button></div></div>
    <section class="card" id="inv-table"></section>
    <p style="margin:-8px 0 0;font-size:13px;color:var(--muted)">
      <strong>On shelf</strong> is free stock. <strong>Reserved</strong> is allocated to shelters but not yet loaded on a truck.
      <strong>Lasts</strong> is an estimate at the request rate of the last 6 hours. Stock can never go below zero: the database refuses it.</p>
    <div class="row">
      <section class="card half"><h2>Warehouses</h2><p class="hint">Requests are sent from the nearest warehouse that has stock.</p>
        <ul style="list-style:none;margin:0;padding:0">${warehouses.map((w) => `<li style="display:flex;gap:12px;align-items:center;padding:10px 0;border-top:1px solid var(--line-soft)">
          <span style="color:var(--ink-2)">${icon.box(18)}</span><span style="flex:1"><span class="strong">${esc(w.name)}</span>
          <span style="display:block;font-size:13px;color:var(--muted)">${esc(w.id)}${w.lat != null ? ` · ${w.lat.toFixed(4)}, ${w.lon.toFixed(4)}` : " · no coordinates"}</span></span></li>`).join("")}</ul></section>
      <section class="card half"><h2>Add a warehouse</h2><p class="hint">Give it coordinates so the nearest-warehouse rule can use it.</p>
        <form class="form" id="wh-form" novalidate>
          <label class="field narrow">ID<input class="input" name="id" placeholder="WH-C" required></label>
          <label class="field wide">Name<input class="input" name="name" placeholder="Warehouse C · Ras Al Khor" required></label>
          <label class="field narrow">Latitude<input class="input num" name="lat" type="number" step="any" placeholder="25.19"></label>
          <label class="field narrow">Longitude<input class="input num" name="lon" type="number" step="any" placeholder="55.35"></label>
          <button class="btn" type="submit">${icon.plus(17)}Add warehouse</button>
        </form></section>
    </div>
  </div>`;

  dataTable(main.querySelector("#inv-table"), {
    id: "inventory", rows: items, noun: ["item", "items"],
    search: { placeholder: "Search items", text: (i) => i.item },
    filters: [
      { key: "status", label: "Status", options: Object.entries(STATUS), test: (i, v) => i.status === v },
      { key: "need", label: "Shortage", options: [["yes", "Short for waiting requests"], ["no", "Enough stock"]], test: (i, v) => (v === "yes" ? i.short_by > 0 : i.short_by === 0) },
    ],
    sort: { key: "status", dir: 1 },
    columns: [
      { key: "item", label: "Item", render: (i) => `<span class="strong">${esc(i.item)}</span><span class="sub">${esc(i.unit)}</span>` },
      ...warehouses.map((w) => ({
        key: `wh_${w.id}`, label: `${w.name.split("·")[0].trim()}`, align: "r",
        sort: (i) => i.warehouses.find((x) => x.id === w.id)?.quantity ?? -1,
        render: (i) => { const x = i.warehouses.find((y) => y.id === w.id); return x ? `<span class="num">${n(x.quantity)}</span>` : `<span style="color:var(--faint)">—</span>`; },
      })),
      { key: "total", label: "On shelf", align: "r", render: (i) => `<span class="num strong">${n(i.total)}</span>` },
      { key: "reserved", label: "Reserved", align: "r", render: (i) => i.reserved ? `<a class="num" href="#/dispatch">${n(i.reserved)}</a>` : `<span style="color:var(--faint)">0</span>` },
      { key: "hours_of_cover", label: "Lasts", align: "r", sort: (i) => (i.status === "out" ? 0 : i.hours_of_cover),
        render: (i) => i.status === "out" ? `<span style="color:var(--bad-ink);font-weight:700">Out</span>` : i.hours_of_cover != null ? `<span class="num" title="At ${n(i.rate_per_hour)} an hour (last 6 hours of requests)">${lasts(i.hours_of_cover)}</span>` : `<span style="color:var(--faint)">—</span>` },
      { key: "short_by", label: "Short by", align: "r", defaultDir: -1,
        render: (i) => i.short_by ? `<a class="num" style="color:var(--bad-ink);font-weight:700" href="#/requests?status=waiting&item=${encodeURIComponent(i.item)}">${n(i.short_by)}</a>` : `<span style="color:var(--faint)">0</span>` },
      { key: "on_order", label: "On order", align: "r", defaultDir: -1,
        render: (i) => i.on_order ? `<a class="num" href="#/log?tab=orders" title="Still expected from open supply orders">${n(i.on_order)}</a>` : `<span style="color:var(--faint)">0</span>` },
      { key: "status", label: "Status", sort: (i) => ({ out: 0, low: 1, ok: 2 })[i.status] * 1000 + i.percent_left,
        render: (i) => `<span class="badge ${i.status}">${STATUS[i.status]}</span>` },
      { key: "act", label: "", sort: false, srLabel: "Actions", align: "r",
        render: (i) => `<div style="display:flex;gap:6px;justify-content:flex-end">${i.to_order ? `<button class="btn small" type="button" data-ask="${esc(i.item)}" title="Order from HQ or a supplier">Order ${n(i.to_order)}</button>` : ""}
          <button class="btn small" type="button" data-delivery="${esc(i.item)}">${icon.box(15)}Delivery</button></div>` },
    ],
    empty: "No stock yet. Record a delivery or import a delivery file.",
    afterDraw: (tbody) => {
      tbody.querySelectorAll("[data-delivery]").forEach((b) => (b.onclick = () => openRestock({ item: b.dataset.delivery })));
      tbody.querySelectorAll("[data-ask]").forEach((b) => (b.onclick = () => {
        const i = items.find((x) => x.item === b.dataset.ask);
        openSupplyRequest([{ item: i.item, quantity: i.to_order, unit: i.unit, why: `${plural(i.waiting_requests, "request")} waiting${i.on_order ? `, ${n(i.on_order)} already on order` : ""}` }]);
      }));
    },
  });

  main.querySelector(".page-head [data-delivery]").onclick = () => openRestock({});
  main.querySelector("[data-ask-all]")?.addEventListener("click", () => openSupplyRequest(short.map((i) => ({
    item: i.item, quantity: i.to_order, unit: i.unit, why: `${plural(i.waiting_requests, "request")} waiting${i.on_order ? `, ${n(i.on_order)} already on order` : ""}` }))));
  const form = main.querySelector("#wh-form");
  form.onsubmit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(form));
    const body = { id: f.id.trim(), name: f.name.trim(), lat: f.lat === "" ? null : Number(f.lat), lon: f.lon === "" ? null : Number(f.lon) };
    try { await act(api("/api/warehouses", { method: "POST", body }), `${body.name} added.`); } catch {}
  };
}
