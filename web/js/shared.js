// Actions used from more than one screen: undo, "Why?" panel, record delivery, supply request, integrity, report menu.
import { api, closeButton, closeOverlay, debounce, esc, icon, n, openDrawer, openModal, plural,
         statusBadge, timeLabel, title, toast, toastError, urgencyTag } from "./ui.js";

let refreshFn = () => {};
export const onRefresh = (fn) => (refreshFn = fn);
export const refresh = () => refreshFn();

// ---------- Undo ----------
export async function undo() {
  try {
    const r = await api("/api/undo", { method: "POST" });
    toast(`Undone: ${r.undone}`);
    closeOverlay();
    refresh();
  } catch (e) { toastError(e); }
}

export async function updateUndoButton() {
  const btn = document.getElementById("undo-btn");
  try {
    const { label } = await api("/api/undo");
    btn.disabled = !label;
    btn.title = label ? `Undo: ${label} (Ctrl+Z)` : "Nothing to undo";
    btn.setAttribute("aria-label", label ? `Undo ${label}` : "Nothing to undo");
  } catch { btn.disabled = true; }
}

// Run a change, show a toast with Undo, refresh the screen.
export async function act(promise, message) {
  try {
    const result = await promise;
    toast(typeof message === "function" ? message(result) : message, { action: "Undo", onAction: undo });
    refresh();
    return result;
  } catch (e) {
    toastError(e);
    throw e;
  }
}

// ---------- Lookups (shelters, warehouses, items) ----------
export async function lookups() {
  const [sh, inv] = await Promise.all([api("/api/shelters"), api("/api/inventory")]);
  return { shelters: sh.shelters, warehouses: sh.warehouses, items: inv };
}

// ---------- Tracking (like a parcel): a waybill or a request ----------
const STEP_ICON = ["plus", "file", "truck", "check"];
export function timelineHtml(t) {
  return `<ol class="timeline">${t.steps.map((st, i) => `<li class="${st.done ? "done" : ""}">
      <span class="tl-dot">${st.done ? icon.check(13) : ""}</span>
      <div><strong>${esc(st.label)}</strong>${st.at && st.done ? `<time>${timeLabel(st.at)}</time>` : ""}
        ${st.detail ? `<p>${esc(st.detail)}</p>` : ""}</div></li>`).join("")}</ol>`;
}
export async function openTrack(code) {
  const el = openDrawer(`<div class="drawer-head"><span class="eyebrow" style="color:var(--muted)">Tracking · ${esc(code)}</span>${closeButton}</div>
    <div class="drawer-body"><div class="skeleton" style="height:28px;width:80%"></div><div class="skeleton" style="height:160px;margin-top:20px"></div></div>`);
  try {
    const t = await api(`/api/track/${encodeURIComponent(code)}`);
    const amount = (q, unit, item) => { const u = (unit || "").toLowerCase(), it = item.toLowerCase(); return !u || u === "units" || it.includes(u) ? `${n(q)} ${it}` : `${n(q)} ${u} of ${it}`; };
    const body = t.type === "waybill"
      ? `<p class="track-route">${icon.truck(16)}${esc(t.from.name)} → <strong>${esc(t.to.name)}</strong>${t.to.people != null ? ` · ${n(t.to.people)} people` : ""}</p>
        ${timelineHtml(t)}
        <h3 class="track-h">On this waybill</h3>
        <ul class="track-items">${t.items.map((i) => `<li><span>${esc(i.item)}</span><strong class="num">${n(i.quantity)} ${esc(i.unit || "")}</strong></li>`).join("")}
          ${t.lost.map((l) => `<li class="lost"><span>${esc(l.item)} · missing</span><strong class="num">${n(l.quantity)}</strong></li>`).join("")}</ul>
        <p class="track-foot">For ${t.requests.map((r) => `<button class="btn link" type="button" data-why="${esc(r)}">${esc(r)}</button>`).join(", ")}${t.drive_minutes != null ? ` · ${t.distance_km} km, about ${t.drive_minutes} min by road` : ""}</p>`
      : `<p class="track-route">${icon.pin(16)}<strong>${esc(t.shelter.name)}</strong> · ${amount(t.quantity, t.unit, t.item)} · ${esc(t.urgency)}</p>
        <div class="track-split">${[["Delivered", t.delivered], ["On the way", t.on_the_way], ["Reserved", t.reserved], ["Waiting", t.waiting]].map(([l, v]) => `<div><dt>${l}</dt><dd class="num">${n(v)}</dd></div>`).join("")}</div>
        ${timelineHtml(t)}
        ${t.shipments.length ? `<h3 class="track-h">Waybills</h3><ul class="track-items">${t.shipments.map((s) => `<li><button class="btn link" type="button" data-track="${esc(s.waybill)}">${esc(s.waybill)}</button>
          <span>${esc({ loading: "being loaded", on_the_way: s.eta ? `on the way, ~${new Date(s.eta).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}` : "on the way", delivered: `signed by ${s.received_by || "?"}` }[s.status])}</span>
          <strong class="num">${n(s.quantity)}</strong></li>`).join("")}</ul>` : ""}
        ${t.lost.length ? `<p class="track-foot" style="color:var(--bad-ink)">${t.lost.map((l) => `${n(l.quantity)} lost on ${esc(l.shipment_id || "a truck")}: ${esc(l.note || "")}`).join("; ")}. Put back in the queue.</p>` : ""}`;
    el.querySelector(".drawer-body").innerHTML = `<h2>${esc(t.headline)}</h2>${body}
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:22px">
        <button class="btn" type="button" data-copy>${icon.copy(16)}Copy status</button>
        ${t.type === "request" ? `<button class="btn" type="button" data-why="${esc(t.number)}">Why it got this</button>` : ""}</div>`;
    el.querySelectorAll("[data-track]").forEach((b) => (b.onclick = () => openTrack(b.dataset.track)));
    el.querySelectorAll("[data-why]").forEach((b) => (b.onclick = () => openWhy(b.dataset.why)));
    el.querySelector("[data-copy]").onclick = async () => {
      const text = [`${t.number}: ${t.headline}`, ...t.steps.filter((x) => x.done).map((x) => `- ${x.label}${x.at ? ` (${timeLabel(x.at)})` : ""}${x.detail ? `: ${x.detail}` : ""}`)].join("\n");
      try { await navigator.clipboard.writeText(text); toast("Status copied. Paste it into WhatsApp for the shelter."); }
      catch { toast("Couldn't copy. Select the text instead.", { error: true }); }
    };
  } catch (e) {
    el.querySelector(".drawer-body").innerHTML = `<p class="field-error">${esc(e.message)}</p>`;
  }
}

// ---------- "Why?" drawer ----------
export async function openWhy(id) {
  const el = openDrawer(`<div class="drawer-head"><span class="eyebrow" style="color:var(--muted)">Why? · ${esc(id)}</span>${closeButton}</div>
    <div class="drawer-body"><div class="skeleton" style="height:28px;width:80%"></div><div class="skeleton" style="height:120px;margin-top:20px"></div></div>`);
  try {
    const r = await api(`/api/requests/${encodeURIComponent(id)}`);
    const why = r.explanation || { headline: "This request hasn't been allocated yet.", steps: [] };
    const STAGE = { allocated: "reserved in", dispatched: "on the way from", delivered: "delivered from" };
    const from = r.allocations.length
      ? r.allocations.map((a) => `<li><strong>${n(a.quantity)}</strong> ${STAGE[a.status] || "from"} ${esc(a.warehouse_name)}${a.distance_km != null ? ` · ${a.distance_km} km` : ""}
          <span style="display:block;color:var(--muted);font-size:13px">${a.status === "delivered" ? `Signed by ${esc(a.received_by || "?")} · ${timeLabel(a.delivered_at)}`
            : a.status === "dispatched" ? `Left with ${esc(a.dispatched_by || "?")} · ${timeLabel(a.dispatched_at)}` : `Reserved ${timeLabel(a.created_at)} · waiting for a truck`}</span></li>`).join("")
      : "<li>Nothing allocated yet.</li>";
    const lost = (r.losses || []).map((l) => `<li style="color:var(--bad-ink)"><strong>${n(l.quantity)}</strong> lost on the way from ${esc(l.warehouse_id)}: ${esc(l.note || "no note")}
        <span style="display:block;color:var(--muted);font-size:13px">Reported by ${esc(l.reported_by || "?")} · ${timeLabel(l.created_at)} · put back in the queue</span></li>`).join("");
    el.querySelector(".drawer-body").innerHTML = `
      <h2>${esc(why.headline)}</h2>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">${statusBadge(r.status)} ${urgencyTag(r.urgency)}
        <span style="color:var(--muted);font-size:14px">· shelter priority ${r.shelter_priority}</span></div>
      <dl class="kv">
        <div><dt>Asked for</dt><dd class="num">${n(r.quantity)} ${esc(r.unit || "")}</dd></div>
        <div><dt>Allocated · delivered</dt><dd class="num">${n(r.allocated)} · ${n(r.delivered || 0)}</dd></div>
        <div><dt>Item</dt><dd>${esc(r.item)}</dd></div>
        <div><dt>Submitted</dt><dd>${timeLabel(r.created_at)}</dd></div>
      </dl>
      ${r.size_note ? `<p class="size-line ${r.size_warning ? "warn" : ""}">${r.size_warning ? icon.alert(16) : icon.users(16)}<span>${r.size_warning ? esc(r.size_warning) : `For the shelter's headcount: ${esc(r.size_note)}.`}</span></p>` : ""}
      ${why.steps.length ? `<ol class="steps">${why.steps.map((s) => `<li><span>${esc(s)}</span></li>`).join("")}</ol>` : ""}
      <h3 style="margin:24px 0 8px;font-size:15px">Where its stock is</h3>
      <ul style="margin:0;padding-left:18px;color:var(--ink-2);display:flex;flex-direction:column;gap:6px">${from}${lost}</ul>
      ${r.status !== "cancelled" ? `<details style="margin-top:22px;border:1px solid var(--line-soft);border-radius:12px;padding:12px 14px">
        <summary style="cursor:pointer;font-weight:600">Shelter called back? Change this request</summary>
        <form class="form" data-change style="margin-top:12px" novalidate>
          <label class="field narrow">Quantity<input class="input num" name="quantity" type="number" min="1" step="1" value="${r.quantity}"></label>
          <label class="field">Urgency<select class="input" name="urgency">${["critical", "high", "moderate"].map((u) => `<option value="${u}" ${u === r.urgency ? "selected" : ""}>${u[0].toUpperCase() + u.slice(1)}</option>`).join("")}</select></label>
          <button class="btn" type="submit">Save change</button>
          <p class="form-note" style="margin:0">${r.dispatched ? `${n(r.dispatched)} already left the warehouse, so it can't go below that.` : "Lowering it puts reserved stock back on the shelf for others."}</p>
        </form></details>` : ""}
      <div style="display:flex;flex-wrap:wrap;gap:10px;margin-top:22px">
        ${r.remaining > 0 ? `<button class="btn primary" data-ask>${icon.file(17)}Ask for ${n(r.remaining)} more</button>` : ""}
        <button class="btn" data-track-req>${icon.truck(16)}Track</button>
        <button class="btn" data-copy>${icon.copy(16)}Copy</button>
        ${r.status !== "cancelled" ? `<button class="btn danger" data-cancel>Cancel request</button>` : ""}
      </div>`;
    el.querySelector("[data-copy]").onclick = async () => {
      const text = [why.headline, ...why.steps.map((s, i) => `${i + 1}. ${s}`)].join("\n");
      try { await navigator.clipboard.writeText(text); toast("Explanation copied"); }
      catch { toast("Couldn't copy. Select the text instead.", { error: true }); }
    };
    el.querySelector("[data-track-req]").onclick = () => openTrack(id);
    el.querySelector("[data-ask]")?.addEventListener("click", () =>
      openSupplyRequest([{ item: r.item, quantity: r.remaining, unit: r.unit }]));
    el.querySelector("[data-change]")?.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const f = ev.target, body = {};
      if (Number(f.quantity.value) !== r.quantity) body.quantity = Number(f.quantity.value);
      if (f.urgency.value !== r.urgency) body.urgency = f.urgency.value;
      if (!Object.keys(body).length) { toast("Nothing changed."); return; }
      if (body.quantity !== undefined && !(Number.isInteger(body.quantity) && body.quantity > 0)) { f.quantity.classList.add("invalid"); return; }
      try {
        await act(api(`/api/requests/${encodeURIComponent(id)}`, { method: "PATCH", body }),
          (x) => `${id} changed.${x.released ? ` ${n(x.released)} back on the shelf.` : ""}${x.requests_served ? ` ${plural(x.requests_served, "other request")} re-allocated.` : ""}`);
        openWhy(id);
      } catch {}
    });
    el.querySelector("[data-cancel]")?.addEventListener("click", async (ev) => {
      ev.target.disabled = true;
      try {
        await act(api(`/api/requests/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
          (x) => `${id} cancelled. ${plural(x.returned, "unit")} back in stock.`);
        closeOverlay();
      } catch { ev.target.disabled = false; }
    });
  } catch (e) {
    el.querySelector(".drawer-body").innerHTML = `<p class="field-error">${esc(e.message)}</p>`;
  }
}

// ---------- Record a delivery (goods received) ----------
// Recording a delivery doesn't create stock: it records stock that has physically arrived, who sent it and the
// paperwork reference, so the warehouse count in the app matches the shelves.
export async function openRestock(prefill = {}) {
  const { warehouses, items } = await lookups().catch((e) => (toastError(e), {}));
  if (!warehouses) return;
  const openOrders = (await api("/api/supply/orders").catch(() => ({ orders: [] }))).orders.filter((o) => o.status === "ordered" || o.status === "part");
  const item = prefill.item || items[0]?.item || "";
  const el = openModal(`
    <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">
      <div><h2>Record a delivery</h2><p style="margin:0;color:var(--muted)">Stock that has physically arrived at a warehouse. Waiting requests get it straight away, most urgent first.</p></div>${closeButton}</div>
    <form class="form" style="margin-top:20px" novalidate>
      ${openOrders.length ? `<label class="field wide" style="flex-basis:100%">Is this for a supply order?
        <select class="input" name="order"><option value="">No: a donation or unplanned delivery</option>
          ${openOrders.map((o) => `<option value="${esc(o.id)}">${esc(o.id)} · ${esc(o.lines.filter((l) => l.outstanding).map((l) => `${n(l.outstanding)} ${l.item.toLowerCase()}`).join(", "))} expected</option>`).join("")}</select></label>` : ""}
      <label class="field wide">Item
        <input class="input" name="item" list="restock-items" value="${esc(item)}" required autocomplete="off">
        <datalist id="restock-items">${items.map((i) => `<option value="${esc(i.item)}">`).join("")}</datalist></label>
      <label class="field narrow">Quantity counted<input class="input num" name="quantity" type="number" min="1" step="1" inputmode="numeric" value="${esc(prefill.quantity || "")}" required autofocus></label>
      <label class="field wide">Arrived at
        <select class="input" name="warehouse_id">${warehouses.map((w) => `<option value="${esc(w.id)}">${esc(w.name)}</option>`).join("")}</select></label>
      <label class="field wide">From (donor, supplier or HQ)<input class="input" name="source" maxlength="80" placeholder="e.g. UAE Red Crescent" autocomplete="off"></label>
      <label class="field">Waybill / delivery note no.<input class="input" name="reference" maxlength="40" placeholder="e.g. WB-20431" autocomplete="off"></label>
      <p class="form-note" data-note></p>
      <div style="display:flex;gap:10px;width:100%;justify-content:flex-end;margin-top:6px">
        <button class="btn" type="button" data-close>Cancel</button>
        <button class="btn primary" type="submit">${icon.box(18)}Record delivery</button></div>
    </form>`);
  const form = el.querySelector("form");
  const note = el.querySelector("[data-note]");
  const orderSel = form.querySelector("[name=order]");
  const pickOrder = () => {
    const o = openOrders.find((x) => x.id === orderSel.value);
    form.querySelector("[name=source]").closest("label").hidden = !!o;
    form.querySelector("[name=reference]").closest("label").hidden = !!o;
    if (!o) return;
    const line = o.lines.find((l) => l.outstanding && l.item.toLowerCase() === form.item.value.trim().toLowerCase()) || o.lines.find((l) => l.outstanding);
    form.item.value = line.item;
    form.quantity.value = line.outstanding;
    form.warehouse_id.value = o.warehouse_id;
    update();
  };
  if (orderSel) {
    orderSel.onchange = pickOrder;
    const match = openOrders.find((o) => o.id === prefill.order) || openOrders.find((o) => o.lines.some((l) => l.outstanding && l.item.toLowerCase() === item.toLowerCase()));
    if (match) { orderSel.value = match.id; setTimeout(pickOrder); }
  }
  const update = debounce(async () => {
    const f = Object.fromEntries(new FormData(form));
    const q = parseInt(f.quantity, 10);
    if (!f.item.trim() || !q || q < 1) { note.className = "form-note"; note.textContent = "Enter the item and the quantity you counted."; return; }
    try {
      const p = await api(`/api/inventory/restock/preview?${new URLSearchParams({ item: f.item.trim(), quantity: q, warehouse_id: f.warehouse_id })}`);
      note.className = "form-note " + (p.requests ? "good" : "");
      note.innerHTML = p.requests
        ? `${icon.check(16)} ${plural(p.requests, "waiting request")} will be allocated${p.critical ? `, including ${p.critical} critical` : ""}. ${p.left_over ? `${n(p.left_over)} go on the shelf.` : ""}`
        : `${icon.info(16)} Nobody is waiting for this item. It goes on the shelf.`;
    } catch { note.textContent = ""; }
  }, 200);
  form.addEventListener("input", update);
  update();
  form.onsubmit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(form));
    if (!(Number(f.quantity) > 0)) { form.quantity.classList.add("invalid"); form.quantity.focus(); return; }
    const btn = form.querySelector("[type=submit]");
    btn.disabled = true;
    try {
      if (f.order) {
        await act(api(`/api/supply/orders/${encodeURIComponent(f.order)}/receive`, { method: "POST", body: { lines: { [f.item.trim()]: Number(f.quantity) }, warehouse_id: f.warehouse_id } }),
          (r) => `${r.id}: ${n(r.units)} ${f.item.trim().toLowerCase()} ticked off. ${r.status === "arrived" ? "Everything on the order has arrived." : "The rest is still expected."}${r.requests_served ? ` ${plural(r.requests_served, "request")} allocated.` : ""}`);
      } else {
        const { order, ...body } = f;
        await act(api("/api/inventory/restock", { method: "POST", body: { ...body, item: f.item.trim(), quantity: Number(f.quantity) } }),
          (r) => `Delivery recorded: ${n(r.quantity)} ${r.item.toLowerCase()}. ${r.requests_served ? `${plural(r.requests_served, "request")} allocated. Load them on the Dispatch screen.` : "Nobody was waiting."}`);
      }
      closeOverlay();
    } catch { btn.disabled = false; }
  };
}

// ---------- Order supplies: one click to WhatsApp or Gmail, and it's kept in Log → Supply orders ----------
const amountOf = (q, unit, item) => {
  const u = (unit || "").toLowerCase(), it = (item || "").toLowerCase();
  return !u || u === "units" || it.includes(u) ? `${n(q)} ${it}` : `${n(q)} ${u} of ${it}`;
};
const prettyPhone = (p) => (p ? p.replace(/^\+?971(\d{2})(\d{3})(\d{4})$/, "+971 $1 $2 $3") : "");
const initials = (name) => (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");

function orderMessage(number, lines, wh) {
  const map = wh && wh.lat != null ? `https://maps.google.com/?q=${wh.lat},${wh.lon}` : "";
  return [`*Supply request ${number}*`, "Please send:", ...lines.map((l) => `• ${amountOf(l.quantity, l.unit, l.item)}`),
    wh ? `Deliver to: ${wh.name}` : "", map ? `Location: ${map}` : "",
    `Please reply with when it will arrive, and quote ${number} on the delivery note.`, "Sent from ReliefGrid"].filter(Boolean).join("\n");
}

export async function openSupplyRequest(prefill = []) {
  let data;
  try {
    const [look, contact, ordersNow] = await Promise.all([lookups(), api("/api/supply/contact"), api("/api/supply/orders")]);
    data = { ...look, contact, orders: ordersNow.orders };
  } catch (e) { toastError(e); return; }
  const { warehouses, items } = data;
  let contact = data.contact;
  const unitOf = Object.fromEntries(items.map((i) => [i.item.toLowerCase(), i.unit]));
  let rows = (prefill.length ? prefill : [{ item: "", quantity: "" }]).map((l) => ({ item: l.item, quantity: l.quantity, unit: l.unit || unitOf[(l.item || "").toLowerCase()], why: l.why }));
  let whId = warehouses[0]?.id;
  const open = data.orders.filter((o) => o.status === "ordered" || o.status === "part");

  const el = openModal(`<div class="order-head"><div><p class="eyebrow" style="color:var(--muted)">Order supplies</p>
      <h2>What do you need?</h2></div>${closeButton}</div>
    <div class="order-to" data-to></div>
    <div class="order-lines" data-lines></div>
    <button class="btn link" type="button" data-add>${icon.plus(16)}Add an item</button>
    <label class="field wide" style="margin-top:14px">Deliver to
      <select class="input" data-wh>${warehouses.map((w) => `<option value="${esc(w.id)}">${esc(w.name)}</option>`).join("")}</select></label>
    <div class="bubble-wrap"><span class="eyebrow" style="color:var(--muted)">Message preview</span><div class="bubble" data-preview></div></div>
    ${open.length ? `<p class="order-open">${icon.info(15)}<span>Already on order: ${open.slice(0, 3).map((o) => `<strong>${esc(o.id)}</strong> (${esc(o.summary)})`).join(", ")}${open.length > 3 ? ` and ${open.length - 3} more` : ""}.</span></p>` : ""}
    <p class="field-error" data-err hidden></p>
    <div class="order-actions">
      <button class="btn wa" type="button" data-send="whatsapp">${icon.chat(18)}Send on WhatsApp</button>
      <button class="btn" type="button" data-send="email">${icon.mail(18)}Send by Gmail</button>
      <button class="btn" type="button" data-send="copy">${icon.copy(17)}Copy and save</button>
    </div>
    <p class="order-foot">Every order is kept in <a href="#/log?tab=orders" data-close>Log → Supply orders</a>, where you tick it off when it arrives.</p>`, { wide: true });

  const linesBox = el.querySelector("[data-lines]"), preview = el.querySelector("[data-preview]"), err = el.querySelector("[data-err]");
  const toBox = el.querySelector("[data-to]");
  const wh = () => warehouses.find((w) => w.id === whId);
  const clean = () => rows.filter((r) => (r.item || "").trim() && Number(r.quantity) > 0)
    .map((r) => ({ item: r.item.trim(), quantity: Number(r.quantity), unit: unitOf[r.item.trim().toLowerCase()] || r.unit }));
  const drawPreview = () => { preview.innerHTML = esc(orderMessage("PO-…", clean(), wh())).replace(/\*(.+?)\*/g, "<strong>$1</strong>"); };
  const drawTo = () => {
    toBox.innerHTML = `<span class="avatar">${esc(initials(contact.name))}</span>
      <div><strong>${esc(contact.name)}</strong><span>${esc([prettyPhone(contact.whatsapp), contact.email].filter(Boolean).join(" · ") || "No number or email saved")}</span></div>
      <button class="btn link" type="button" data-edit-to>Change</button>`;
    toBox.querySelector("[data-edit-to]").onclick = () => {
      toBox.innerHTML = `<form class="to-form" novalidate>
        <label>Name<input class="input" name="name" value="${esc(contact.name)}" maxlength="60"></label>
        <label>WhatsApp number<input class="input" name="whatsapp" value="${esc(contact.whatsapp)}" inputmode="tel" placeholder="+971…"></label>
        <label>Email<input class="input" name="email" type="email" value="${esc(contact.email)}"></label>
        <div style="display:flex;gap:8px;align-items:flex-end"><button class="btn primary small" type="submit">Save</button><button class="btn small" type="button" data-cancel-to>Cancel</button></div></form>`;
      toBox.querySelector("[data-cancel-to]").onclick = drawTo;
      toBox.querySelector("form").onsubmit = async (e) => {
        e.preventDefault();
        try { contact = await api("/api/supply/contact", { method: "PUT", body: Object.fromEntries(new FormData(e.target)) }); drawTo(); toast(`Supply requests now go to ${contact.name}.`); }
        catch (ex) { toastError(ex); }
      };
    };
  };
  const drawLines = () => {
    linesBox.innerHTML = rows.map((r, i) => `<div class="order-line" data-i="${i}">
        <input class="input" data-k="item" value="${esc(r.item || "")}" list="order-items" placeholder="Item" aria-label="Item">
        <input class="input num" data-k="quantity" type="number" min="1" step="1" inputmode="numeric" value="${esc(r.quantity ?? "")}" placeholder="0" aria-label="Quantity">
        <span class="unit">${esc(unitOf[(r.item || "").toLowerCase()] || r.unit || "")}</span>
        <button class="icon-btn" type="button" data-remove aria-label="Remove line" ${rows.length === 1 ? "disabled" : ""}>${icon.x(16)}</button>
        ${r.why ? `<span class="why">${esc(r.why)}</span>` : ""}</div>`).join("")
      + `<datalist id="order-items">${items.map((i) => `<option value="${esc(i.item)}">${i.to_order ? `${n(i.to_order)} still to order` : `${n(i.total)} on the shelf`}</option>`).join("")}</datalist>`;
    linesBox.querySelectorAll("[data-remove]").forEach((b) => (b.onclick = () => { rows.splice(Number(b.closest("[data-i]").dataset.i), 1); drawLines(); drawPreview(); }));
  };
  linesBox.addEventListener("input", (e) => {
    const line = e.target.closest("[data-i]");
    if (!line) return;
    rows[Number(line.dataset.i)][e.target.dataset.k] = e.target.value;
    if (e.target.dataset.k === "item") line.querySelector(".unit").textContent = unitOf[e.target.value.trim().toLowerCase()] || "";
    e.target.classList.remove("invalid");
    drawPreview();
  });
  el.querySelector("[data-add]").onclick = () => { rows.push({ item: "", quantity: "" }); drawLines(); linesBox.querySelector(".order-line:last-child input")?.focus(); };
  el.querySelector("[data-wh]").onchange = (e) => { whId = e.target.value; drawPreview(); };
  drawTo(); drawLines(); drawPreview();

  el.querySelectorAll("[data-send]").forEach((b) => (b.onclick = async () => {
    const via = b.dataset.send, lines = clean();
    err.hidden = true;
    if (!lines.length) { err.textContent = "Add at least one item and quantity."; err.hidden = false; return; }
    // Open the WhatsApp or Gmail tab now (still inside the click) so the browser doesn't block it.
    const win = via === "copy" ? null : window.open("", "_blank");
    el.querySelectorAll("[data-send]").forEach((x) => (x.disabled = true));
    try {
      const o = await api("/api/supply/orders", { method: "POST", body: { lines, warehouse_id: whId, sent_via: via } });
      const text = orderMessage(o.id, o.lines, wh());
      if (via === "whatsapp") {
        const to = (contact.whatsapp || "").replace(/\D/g, "");
        win.location = `https://wa.me/${to}?text=${encodeURIComponent(text)}`;
      } else if (via === "email") {
        const subject = `Supply request ${o.id}: ${o.lines.map((l) => amountOf(l.quantity, l.unit, l.item)).join(", ")}`;
        win.location = `https://mail.google.com/mail/?view=cm&fs=1&to=${encodeURIComponent(contact.email || "")}&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(text.replace(/\*/g, ""))}`;
      } else {
        try { await navigator.clipboard.writeText(text); } catch { /* still saved */ }
      }
      closeOverlay();
      toast(`${o.id} ${via === "copy" ? "copied and saved" : `sent to ${o.supplier}`}. Tick it off in Log → Supply orders when it arrives.`,
        { action: "View", onAction: () => { location.hash = "#/log?tab=orders"; } });
      refresh();
    } catch (e) {
      win?.close();
      el.querySelectorAll("[data-send]").forEach((x) => (x.disabled = false));
      err.textContent = e.message; err.hidden = false;
    }
  }));
}

// ---------- Integrity checks ----------
export async function openIntegrity() {
  const el = openModal(`<div style="display:flex;justify-content:space-between;gap:12px"><div><h2>Checking the maths</h2>
    <p style="margin:0;color:var(--muted)">Run live against the database every time you open this.</p></div>${closeButton}</div>
    <div class="skeleton" style="height:240px;margin-top:20px"></div>`);
  try {
    const r = await api("/api/integrity");
    el.querySelector(".skeleton").outerHTML = `<ul class="checks">${r.checks.map((c) => `
      <li><span class="${c.passed ? "ok" : "no"}">${c.passed ? icon.check(20) : icon.x(20)}</span>
        <div><strong>${esc(c.name)}</strong><span>${esc(c.detail)}</span></div></li>`).join("")}</ul>
      <p style="margin:16px 0 0;font-size:14px;color:var(--muted)">${r.passed} of ${r.total} passed. These also run in the automated tests and the stress test.</p>`;
  } catch (e) { toastError(e); }
}

// ---------- Report menu ----------
export function reportButton(label = "Export report") {
  return `<div class="menu-wrap"><button class="btn" type="button" data-report-toggle aria-haspopup="true" aria-expanded="false">${icon.download(17)}${label}</button>
    <div class="menu" role="menu" hidden>
      <a role="menuitem" href="/api/reports?format=pdf" download>PDF report <small>to print</small></a>
      <a role="menuitem" href="/api/reports?format=csv" download>CSV <small>for Excel</small></a>
      <a role="menuitem" href="/api/reports?format=json" download>JSON <small>for systems</small></a>
    </div></div>`;
}

document.addEventListener("click", (e) => {
  const toggle = e.target.closest("[data-report-toggle]");
  document.querySelectorAll(".menu-wrap .menu").forEach((m) => {
    if (!toggle || m !== toggle.nextElementSibling) { m.hidden = true; m.previousElementSibling?.setAttribute("aria-expanded", "false"); }
  });
  if (toggle) {
    const menu = toggle.nextElementSibling;
    menu.hidden = !menu.hidden;
    toggle.setAttribute("aria-expanded", String(!menu.hidden));
  }
});

export { title };
