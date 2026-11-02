// Dispatch: waybills, trucks and proof of delivery, the way aid logistics and parcel carriers work.
//   To load      stock reserved for a shelter, still on the shelf -> print the waybill (its number is the tracking number)
//   On the way   the truck left with a driver                        -> the shelter counts what arrived and signs
//   Delivered    signed for; anything missing or damaged went back in the queue
// With `python run.py --phones`, the waybill's QR opens a page on the driver's or shelter's phone to confirm.
import qrcode from "../vendor/qrcode.mjs";
import { act, openTrack } from "../shared.js";
import { dataTable } from "../table.js";
import { api, closeButton, esc, highlight, icon, n, openModal, plural, selectMenu, timeLabel, toastError } from "../ui.js";

const st = { tab: "allocated", warehouse: "", q: "" };
let phoneBase = null;   // set when the server runs with --phones
const TABS = [["allocated", "To load"], ["dispatched", "On the way"], ["delivered", "Delivered"]];

const phoneLink = (waybill, token) => (phoneBase && token ? `${phoneBase}/m.html#${encodeURIComponent(waybill)}/${token}` : null);
const ascii = (s) => String(s).replace(/·/g, "-").replace(/[^\x20-\x7E\n]/g, "");
function qrSvg(text) {
  const qr = qrcode(0, "M");
  qr.addData(ascii(text));
  qr.make();
  return qr.createSvgTag({ cellSize: 3, margin: 2, scalable: true });
}
const qty = (i) => `${n(i.quantity)} ${esc(i.unit && i.unit !== "units" && !i.item.toLowerCase().includes(i.unit) ? i.unit : "")}`.trim();
const mins = (m) => (m < 60 ? `${m} min` : `${(m / 60).toFixed(1)} h`);
const drive = (l) => (l.drive_minutes != null ? `${l.distance_km} km · about ${mins(l.drive_minutes)} by road` : "no coordinates");
const clock = (iso) => (iso ? new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : "");

function manifestText(l, waybill) {
  return [`RELIEFGRID WAYBILL ${waybill}`, `From: ${l.warehouse_name}`, `To: ${l.shelter_name} (${l.shelter_id})`,
    ...l.items.map((i) => `- ${i.quantity} ${i.unit || ""} ${i.item}`.replace(/\s+/g, " ")),
    `Requests: ${l.requests.join(", ")}`].join("\n");
}

function card(l) {
  const key = `data-wh="${esc(l.warehouse_id)}" data-sh="${esc(l.shelter_id)}" data-wb="${esc(l.waybill || "")}"`;
  const items = `<ul>${l.items.map((i) => `<li><span>${esc(i.item)}</span><strong class="num">${qty(i)}</strong></li>`).join("")}</ul>`;
  const bill = l.waybill
    ? `<button class="waybill-no" type="button" data-track="${esc(l.waybill)}" title="Track ${esc(l.waybill)}">${icon.file(14)}${esc(l.waybill)}</button>`
    : `<span class="waybill-no none">No waybill yet</span>`;
  const top = `<div class="load-top">
      <div style="min-width:0">${bill}<h3>${esc(l.shelter_name)}</h3>
        <div class="route-line">${icon.truck(15)}<span>${esc(l.warehouse_name)} → ${esc(l.shelter_id)} · priority ${l.priority}${l.people != null ? ` · ${n(l.people)} people` : ""}</span></div>
        <div class="route-line">${icon.pin(15)}<span>${esc(drive(l))}</span></div></div>
      <span class="badge ${l.status === "allocated" ? "low" : l.status === "dispatched" ? "teal" : "ok"}">${plural(l.total, "unit")}</span></div>`;
  if (l.status === "allocated") {
    const stale = l.waybill && l.off_waybill > 0;
    return `<article class="card load" ${key}>${top}${items}
      <p class="load-meta">Reserved ${timeLabel(l.allocated_at)} · for ${l.requests.map(esc).join(", ")}${l.printed_at ? ` · waybill printed ${timeLabel(l.printed_at)}` : ""}</p>
      ${stale ? `<p class="load-warn">${icon.alert(15)}${n(l.off_waybill)} more reserved since ${esc(l.waybill)} was printed. Reprint to add them to this truck, or they wait for the next one.</p>` : ""}
      <form data-dispatch ${key} novalidate>
        <label class="sr-only" for="drv-${esc(l.warehouse_id)}-${esc(l.shelter_id)}">Driver or vehicle</label>
        <input class="input" id="drv-${esc(l.warehouse_id)}-${esc(l.shelter_id)}" name="driver" placeholder="Driver or vehicle, e.g. Truck 7 · Ahmed" autocomplete="off">
        <button class="btn primary small" type="submit">${icon.truck(15)}Truck left</button></form>
      <div class="actions"><button class="btn small" type="button" data-print ${key}>${icon.download(15)}${l.waybill ? (stale ? "Reprint waybill" : "Print waybill") : "Print waybill"}</button>
        ${phoneBase ? `<button class="btn small" type="button" data-qr ${key}>${icon.phone(15)}Phone QR</button>` : ""}</div>
    </article>`;
  }
  if (l.status === "dispatched") {
    return `<article class="card load" ${key}>${top}${items}
      <p class="load-meta">Left ${timeLabel(l.dispatched_at)} with <strong style="color:var(--ink)">${esc(l.dispatched_by || "?")}</strong>${l.eta ? ` · expected around <strong style="color:var(--ink)">${clock(l.eta)}</strong>` : ""}</p>
      <form data-deliver ${key} novalidate>
        <label class="sr-only" for="rcv-${esc(l.waybill)}">Received by</label>
        <input class="input" id="rcv-${esc(l.waybill)}" name="received_by" placeholder="Received by (name at the shelter)" autocomplete="off">
        <button class="btn primary small" type="submit">${icon.check(15)}Delivered</button>
        <details class="short-box"><summary>Something missing or damaged?</summary>
          <p>Enter what actually arrived. The rest is recorded as lost and goes back in the queue for this shelter.</p>
          ${l.items.map((i) => `<label class="count-row"><span>${esc(i.item)} <small>sent ${n(i.quantity)}</small></span>
            <input class="input num" type="number" min="0" max="${i.quantity}" step="1" data-item="${esc(i.item)}" value="${i.quantity}" aria-label="${esc(i.item)} received"></label>`).join("")}
          <label class="count-row wide"><span>What happened</span><input class="input" name="note" maxlength="200" placeholder="e.g. 2 cartons crushed in transit"></label>
        </details></form>
      ${phoneBase ? `<div class="actions"><button class="btn small" type="button" data-qr ${key}>${icon.phone(15)}Phone QR</button></div>` : ""}
    </article>`;
  }
  return "";
}

function printWaybill(l, waybill, token) {
  const link = phoneLink(waybill, token);
  const box = document.createElement("div");
  box.className = "page print-sheet";
  box.innerHTML = `<article class="card slip print-me" style="max-width:760px;margin:0 auto">
    <div style="display:flex;justify-content:space-between;gap:16px">
      <div><p class="eyebrow" style="color:#555">ReliefGrid waybill · printed ${new Date().toLocaleString("en-GB")}</p>
        <div style="font:800 30px/1.1 var(--font);letter-spacing:.02em;margin:6px 0 10px">${esc(waybill)}</div>
        <h2 style="font-size:22px;margin:0">${esc(l.shelter_name)}</h2>
        <p style="margin:2px 0 0;color:#555">${esc(l.shelter_id)} · priority ${l.priority}${l.people != null ? ` · ${n(l.people)} people` : ""}${l.lat != null ? ` · ${l.lat.toFixed(4)}, ${l.lon.toFixed(4)}` : ""}</p>
        <p style="margin:8px 0 0"><strong>Load at:</strong> ${esc(l.warehouse_name)} · ${esc(drive(l))}</p></div>
      <figure style="margin:0;width:140px;text-align:center"><div style="width:140px;height:140px">${qrSvg(link || manifestText(l, waybill))}</div>
        <figcaption style="font-size:10px;color:#555">${link ? "Driver: scan when loaded. Shelter: scan on arrival to count and sign." : "Scan for the load list"}</figcaption></figure></div>
    <table class="t" style="margin-top:16px"><thead><tr><th style="width:36px">✓</th><th>Item</th><th class="r">Sent</th><th class="r" style="width:120px">Received</th></tr></thead>
      <tbody>${l.items.map((i) => `<tr><td>☐</td><td><strong>${esc(i.item)}</strong></td><td class="r"><strong>${n(i.quantity)} ${esc(i.unit || "")}</strong></td><td class="r" style="border-bottom:1px solid #999"></td></tr>`).join("")}</tbody></table>
    <p style="margin:12px 0 0">${plural(l.total, "unit")} · for requests ${l.requests.map(esc).join(", ")} · track at the hub with ${esc(waybill)}</p>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-top:36px;font-size:12px;color:#555">
      ${["Loaded by · time", "Driver / vehicle · time out", "Received by (shelter) · signature · time"].map((t) => `<div><div style="border-bottom:1px solid #999;height:34px"></div>${t}</div>`).join("")}</div>
  </article>`;
  document.body.appendChild(box);
  document.body.classList.add("print-one");
  const done = () => { box.remove(); document.body.classList.remove("print-one"); window.removeEventListener("afterprint", done); };
  window.addEventListener("afterprint", done);
  window.print();
  setTimeout(() => { if (document.body.contains(box)) done(); }, 1500);
}

export async function render(main, { params, firstVisit }) {
  if (firstVisit && params.tab) st.tab = params.tab;
  if (firstVisit) st.q = params.shelter || params.q || "";
  const [data, ver] = await Promise.all([api("/api/dispatch"), api("/api/version").catch(() => ({}))]);
  phoneBase = ver.phone_url || null;
  const c = data.counts;
  const warehouses = [...new Map(data.loads.map((l) => [l.warehouse_id, l.warehouse_name])).entries()];
  const text = (l) => `${l.waybill || ""} ${l.shelter_name} ${l.shelter_id} ${l.items.map((i) => i.item).join(" ")} ${l.dispatched_by || ""} ${l.requests.join(" ")}`.toLowerCase();
  const shown = data.loads.filter((l) => l.status === st.tab && (!st.warehouse || l.warehouse_id === st.warehouse) &&
    (!st.q || text(l).includes(st.q.toLowerCase())));

  main.innerHTML = `<div class="page ${firstVisit ? "fade-in" : ""}">
    <div class="page-head"><div><h1>Dispatch</h1>
      <p>Every truckload travels on a numbered waybill. The number is its tracking number, and the shelter signs for what actually arrived.</p></div>
      <span class="phone-state ${phoneBase ? "on" : ""}" title="${phoneBase ? `Phones on the same Wi-Fi open ${esc(phoneBase)}` : "Start with: python run.py --phones"}">${icon.phone(16)}${phoneBase ? "Phone scanning on" : "Phone scanning off · <code>python run.py --phones</code>"}</span></div>
    <div class="kpis">
      <div class="card kpi"><div class="label">To load</div><div class="value">${n(c.allocated.units)}<small> units</small></div><div class="foot">${plural(c.allocated.loads, "route")} with stock reserved</div></div>
      <div class="card kpi"><div class="label">On the way</div><div class="value">${n(c.dispatched.units)}<small> units</small></div><div class="foot">${plural(c.dispatched.loads, "truck")} out</div></div>
      <div class="card kpi"><div class="label">Delivered and signed for</div><div class="value">${n(c.delivered.units)}<small> units</small></div><div class="foot">on ${plural(c.delivered.loads, "waybill")}</div></div>
    </div>
    <section class="card">
      <div class="tabs" role="tablist">${TABS.map(([k, l]) => `<button role="tab" type="button" data-tab="${k}" aria-selected="${st.tab === k}">${l}<span class="count">${c[k].loads}</span></button>`).join("")}</div>
      <div id="tab-body" style="margin-top:14px"></div>
    </section>
  </div>`;

  const body = main.querySelector("#tab-body");
  main.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => { st.tab = b.dataset.tab; render(main, { params: {}, firstVisit: false }); }));

  if (st.tab === "delivered") {
    const rows = data.loads.filter((l) => l.status === "delivered");
    dataTable(body, {
      id: "delivered", rows, noun: ["waybill", "waybills"],
      search: { placeholder: "Waybill, shelter, item, driver or receiver", text: (l) => `${l.waybill} ${l.shelter_name} ${l.items.map((i) => i.item).join(" ")} ${l.dispatched_by} ${l.received_by}` },
      filters: [
        { key: "wh", label: "Warehouse", options: warehouses, test: (l, v) => l.warehouse_id === v },
        { key: "lost", label: "Condition", options: [["ok", "Arrived complete"], ["lost", "Something missing"]], test: (l, v) => (v === "lost") === (l.lost.length > 0) },
      ],
      sort: { key: "delivered_at", dir: -1 },
      rowAttrs: (l) => `class="clickable" tabindex="0" data-track="${esc(l.waybill)}"`,
      onRow: (l) => openTrack(l.waybill),
      columns: [
        { key: "waybill", label: "Waybill", render: (l) => `<span class="strong num">${esc(l.waybill)}</span>` },
        { key: "delivered_at", label: "Delivered", defaultDir: -1, render: (l) => `<span class="num">${timeLabel(l.delivered_at)}</span>` },
        { key: "shelter_name", label: "Shelter", render: (l) => `<span class="strong">${esc(l.shelter_name)}</span><span class="sub">from ${esc(l.warehouse_name.split("·")[0].trim())}</span>` },
        { key: "items", label: "What arrived", sort: (l) => l.items.map((i) => i.item).join(), render: (l) => l.items.map((i) => `${qty(i)} ${esc(i.item.toLowerCase())}`).join(", ")
          + (l.lost.length ? `<span class="sub" style="color:var(--bad-ink)">Missing: ${l.lost.map((x) => `${n(x.quantity)} ${esc(x.item.toLowerCase())}`).join(", ")}</span>` : "") },
        { key: "dispatched_by", label: "Driver", render: (l) => esc(l.dispatched_by || "") },
        { key: "received_by", label: "Signed by", render: (l) => `<span class="strong">${esc(l.received_by || "")}</span>` },
      ],
      empty: "Nothing delivered yet.",
    });
    return;
  }

  body.innerHTML = `<div class="tbl-tools">
      <label class="tbl-search"><span class="sr-only">Search</span>${icon.search(16)}
        <input class="input" id="d-q" type="search" placeholder="Waybill, shelter, item${st.tab === "dispatched" ? " or driver" : ""}" value="${esc(st.q)}"></label>
      <span id="d-wh" style="display:contents"></span>
      <span class="tbl-count">${shown.length} of ${plural(data.loads.filter((l) => l.status === st.tab).length, st.tab === "allocated" ? "route" : "truck")} · most vulnerable shelters first</span>
    </div>
    ${shown.length ? `<div class="load-grid">${shown.map(card).join("")}</div>`
      : `<div class="empty"><strong>${st.tab === "allocated" ? "Nothing waiting to be loaded." : "No trucks on the way."}</strong>${st.q || st.warehouse ? "Try clearing the search or filter." : ""}</div>`}`;

  const q = body.querySelector("#d-q");
  q.addEventListener("input", () => { st.q = q.value; clearTimeout(q._t); q._t = setTimeout(() => { render(main, { params: {}, firstVisit: false }).then(() => { const el = main.querySelector("#d-q"); el.focus(); el.setSelectionRange(el.value.length, el.value.length); }); }, 200); });
  body.querySelector("#d-wh").append(selectMenu({ label: "Warehouse", value: st.warehouse,
    options: warehouses.map(([id, name]) => [id, name, data.loads.filter((l) => l.status === st.tab && l.warehouse_id === id).length]),
    onChange: (v) => { st.warehouse = v; render(main, { params: {}, firstVisit: false }); } }));
  if (st.q) highlight(body.querySelector(".load-grid"), st.q);
  const find = (el) => data.loads.find((l) => l.warehouse_id === el.dataset.wh && l.shelter_id === el.dataset.sh && l.status === st.tab &&
    (st.tab === "allocated" || l.waybill === el.dataset.wb));
  body.querySelectorAll("[data-track]").forEach((b) => (b.onclick = () => openTrack(b.dataset.track)));

  // Printing (or showing the QR) puts everything reserved on the route onto its waybill first.
  const ensureWaybill = async (l) => {
    if (l.status !== "allocated") return { waybill: l.waybill, token: l.token };
    if (l.waybill && !l.off_waybill) return { waybill: l.waybill, token: l.token };
    return api("/api/dispatch/waybill", { method: "POST", body: { warehouse_id: l.warehouse_id, shelter_id: l.shelter_id } });
  };
  body.querySelectorAll("[data-print]").forEach((b) => (b.onclick = async () => {
    const l = find(b);
    try {
      const w = await ensureWaybill(l);
      printWaybill(l, w.waybill, w.token);
      if (w.waybill !== l.waybill || l.off_waybill) render(main, { params: {}, firstVisit: false });
    } catch (e) { toastError(e); }
  }));
  body.querySelectorAll("[data-qr]").forEach((b) => (b.onclick = async () => {
    const l = find(b);
    try {
      const w = await ensureWaybill(l);
      const link = phoneLink(w.waybill, w.token);
      openModal(`<div style="display:flex;justify-content:space-between;gap:12px"><div><p class="eyebrow" style="color:var(--muted)">${esc(w.waybill)}</p><h2>${esc(l.shelter_name)}</h2>
        <p style="margin:0;color:var(--muted)">${l.status === "allocated" ? "The driver scans this when the truck is loaded. The shelter scans the same code to count what arrived and sign." : "The shelter scans this to count what arrived and sign for it."}</p></div>${closeButton}</div>
        <div class="qr-big">${qrSvg(link)}</div>
        <p style="margin:0;font-size:13px;color:var(--muted);word-break:break-all;text-align:center">${esc(link)}</p>`);
      if (w.waybill !== l.waybill) render(main, { params: {}, firstVisit: false });
    } catch (e) { toastError(e); }
  }));
  body.querySelectorAll("form[data-dispatch]").forEach((f) => (f.onsubmit = async (e) => {
    e.preventDefault();
    const driver = f.driver.value.trim();
    if (!driver) { f.driver.classList.add("invalid"); f.driver.focus(); return; }
    const l = find(f);
    f.querySelector("button").disabled = true;
    try {
      await act(api("/api/dispatch/dispatched", { method: "POST", body: l.waybill
        ? { waybill: l.waybill, driver, upto_id: l.max_id }
        : { warehouse_id: l.warehouse_id, shelter_id: l.shelter_id, driver, upto_id: l.max_id } }),
        (r) => `${r.waybill}: ${n(r.units)} units on the way to ${r.shelter} with ${r.driver}.`);
    } catch { f.querySelector("button").disabled = false; }
  }));
  body.querySelectorAll("form[data-deliver]").forEach((f) => (f.onsubmit = async (e) => {
    e.preventDefault();
    const name = f.received_by.value.trim();
    if (!name) { f.received_by.classList.add("invalid"); f.received_by.focus(); return; }
    const received = {};
    let bad = false, short = false;
    f.querySelectorAll("[data-item]").forEach((inp) => {
      const v = Number(inp.value), max = Number(inp.max);
      const ok = inp.value !== "" && Number.isInteger(v) && v >= 0 && v <= max;
      inp.classList.toggle("invalid", !ok);
      if (!ok) bad = true; else { received[inp.dataset.item] = v; if (v < max) short = true; }
    });
    if (bad) { f.querySelector("details").open = true; return; }
    const note = f.note.value.trim();
    if (short && !note) { f.querySelector("details").open = true; f.note.classList.add("invalid"); f.note.focus(); return; }
    f.querySelector("button").disabled = true;
    try {
      await act(api("/api/dispatch/delivered", { method: "POST", body: { waybill: f.dataset.wb, received_by: name, ...(short ? { received, note } : {}) } }),
        (r) => `${r.waybill} signed for by ${r.received_by}: ${n(r.units)} units.${r.lost ? ` ${n(r.lost)} missing went back in the queue${r.requests_served ? " and were re-allocated" : ""}.` : ""}`);
    } catch { f.querySelector("button").disabled = false; }
  }));
}
