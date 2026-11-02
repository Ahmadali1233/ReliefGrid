// Dispatch slips: one printable page per shelter for the truck driver.
// The QR code holds the load list as plain text, so any phone camera can read it with no internet.
import qrcode from "../vendor/qrcode.mjs";
import { api, esc, icon, n, plural } from "../ui.js";

let only = "";

const ascii = (s) => String(s).replace(/·/g, "-").replace(/[–—]/g, "-").replace(/[^\x20-\x7E\n]/g, "");

function qrSvg(text) {
  const qr = qrcode(0, "M");
  qr.addData(ascii(text));
  qr.make();
  return qr.createSvgTag({ cellSize: 3, margin: 2, scalable: true });
}

export async function render(main, { params, firstVisit }) {
  if (firstVisit) only = params.shelter || "";
  const [allocs, sh, inv] = await Promise.all([api("/api/allocations?limit=5000"), api("/api/shelters"), api("/api/inventory")]);
  const unitOf = Object.fromEntries(inv.map((i) => [i.item, i.unit]));
  const shelters = Object.fromEntries(sh.shelters.map((s) => [s.id, s]));

  // Group: shelter -> warehouse -> item -> quantity
  const groups = {};
  for (const a of allocs) {
    const g = (groups[a.shelter_id] ??= { shelter: shelters[a.shelter_id], loads: {} });
    const key = `${a.warehouse_id}|${a.item}`;
    const load = (g.loads[key] ??= { warehouse: a.warehouse_name, warehouse_id: a.warehouse_id, item: a.item, quantity: 0, km: a.distance_km, requests: new Set() });
    load.quantity += a.quantity;
    load.requests.add(a.request_id);
  }
  const list = Object.values(groups).filter((g) => g.shelter && (!only || g.shelter.id === only))
    .sort((a, b) => a.shelter.priority - b.shelter.priority || a.shelter.name.localeCompare(b.shelter.name));
  const today = new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

  const slip = (g) => {
    const s = g.shelter;
    const loads = Object.values(g.loads).sort((a, b) => a.warehouse_id.localeCompare(b.warehouse_id) || a.item.localeCompare(b.item));
    const byWh = {};
    loads.forEach((l) => (byWh[l.warehouse] ??= []).push(l));
    const text = [`RELIEFGRID DISPATCH SLIP`, `To: ${s.name} (${s.id}), priority ${s.priority}`,
      s.lat != null ? `Location: ${s.lat.toFixed(5)}, ${s.lon.toFixed(5)}` : "",
      ...Object.entries(byWh).flatMap(([wh, ls]) => [`From ${wh}:`, ...ls.map((l) => `- ${l.quantity} ${unitOf[l.item] || ""} ${l.item}`.replace(/\s+/g, " "))]),
      `Printed ${new Date().toLocaleString("en-GB")}`].filter(Boolean).join("\n");
    const total = loads.reduce((t, l) => t + l.quantity, 0);
    return `<article class="card slip" style="break-after:page;page-break-after:always">
      <div style="display:flex;gap:20px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap">
        <div style="flex:1 1 360px;min-width:0">
          <p class="eyebrow" style="color:var(--muted)">Dispatch slip · ${esc(today)}</p>
          <h2 style="font-size:26px;font-weight:800;letter-spacing:-.02em;margin:4px 0">${esc(s.name)}</h2>
          <p style="margin:0;color:var(--muted)">${esc(s.id)} · priority ${s.priority}${s.lat != null ? ` · ${s.lat.toFixed(4)}, ${s.lon.toFixed(4)}` : ""}</p>
        </div>
        <figure style="margin:0;text-align:center;width:132px">
          <div style="width:132px;height:132px;background:#fff;padding:4px;border-radius:10px;border:1px solid var(--line)">${qrSvg(text)}</div>
          <figcaption style="font-size:11px;color:var(--muted);margin-top:4px">Scan for the load list (no internet needed)</figcaption>
        </figure>
      </div>
      ${Object.entries(byWh).map(([wh, ls]) => `
        <h3 style="margin:18px 0 6px;font-size:15px;display:flex;gap:8px;align-items:center">${icon.truck(17)}Load at ${esc(wh)}${ls[0].km != null ? `<span style="color:var(--muted);font-weight:500">· ${ls[0].km} km to shelter</span>` : ""}</h3>
        <table class="t"><thead><tr><th style="width:40px"><span class="sr-only">Loaded</span></th><th>Item</th><th class="r">Quantity</th><th>For requests</th></tr></thead><tbody>
        ${ls.map((l) => `<tr><td><span style="display:inline-block;width:18px;height:18px;border:1.5px solid var(--input-line);border-radius:4px"></span></td>
          <td class="strong">${esc(l.item)}</td><td class="r num strong">${n(l.quantity)} ${esc(unitOf[l.item] || "")}</td>
          <td style="color:var(--muted);font-size:14px">${[...l.requests].map(esc).join(", ")}</td></tr>`).join("")}
        </tbody></table>`).join("")}
      <p style="margin:14px 0 0;font-weight:700">${plural(total, "unit")} in total</p>
      <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;margin-top:28px;font-size:13px;color:var(--muted)">
        ${["Loaded by", "Driver", "Received by (shelter)"].map((l) => `<div><div style="border-bottom:1.5px solid var(--input-line);height:30px"></div>${l} · time</div>`).join("")}
      </div></article>`;
  };

  main.innerHTML = `<div class="page ${firstVisit ? "fade-in" : ""}">
    <div class="page-head no-print"><div><h1>Dispatch slips</h1><p>One page per shelter for the driver: what to load, where, and a box to tick. Print them or save as PDF.</p></div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
        <label class="sr-only" for="slip-filter">Shelter</label>
        <select class="input" id="slip-filter" style="width:auto"><option value="">All shelters (${Object.keys(groups).length})</option>${Object.values(groups).filter((g) => g.shelter).map((g) =>
          `<option value="${esc(g.shelter.id)}" ${only === g.shelter.id ? "selected" : ""}>${esc(g.shelter.name)}</option>`).join("")}</select>
        <button class="btn primary" type="button" data-print>${icon.download(17)}Print${list.length > 1 ? ` ${list.length} slips` : ""}</button></div></div>
    ${list.length ? list.map(slip).join("") : `<div class="card empty"><strong>Nothing to deliver yet.</strong>Slips appear once stock has been allocated.</div>`}
  </div>`;

  main.querySelector("[data-print]").onclick = () => window.print();
  main.querySelector("#slip-filter").onchange = (e) => { only = e.target.value; render(main, { params: {}, firstVisit: false }); };
}
