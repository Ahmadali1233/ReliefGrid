// Log: two tabs.
//   Activity        everything that happened, newest first, grouped by day, searchable (matches highlighted)
//   Supply orders   what we asked HQ or suppliers for; tick it off when it arrives (all or part), undo a misclick
import { openSupplyRequest, openTrack, openWhy, refresh } from "../shared.js";
import { api, debounce, esc, highlight, icon, n, plural, selectMenu, toast, toastError } from "../ui.js";

const st = { tab: "activity", q: "", cat: "", who: "", when: "", shown: 150, oq: "", ostatus: "open", partFor: null };

// What happened, grouped the way a coordinator thinks about it.
const CATS = {
  requests: { label: "Requests", icon: icon.plus, kinds: ["request", "cancel"] },
  allocation: { label: "Stock reserved", icon: icon.box, kinds: ["allocation"] },
  stock: { label: "Stock arrived", icon: icon.download, kinds: ["restock"] },
  trucks: { label: "Trucks", icon: icon.truck, kinds: ["waybill", "dispatch", "delivered"] },
  orders: { label: "Supply orders", icon: icon.file, kinds: ["order"] },
  changes: { label: "Changes", icon: icon.sliders, kinds: ["rules", "shelter", "warehouse", "import", "undo", "system"] },
};
const catOf = (kind) => Object.keys(CATS).find((k) => CATS[k].kinds.includes(kind)) || "changes";
const WHEN = [["today", "Today"], ["24h", "Last 24 hours"], ["7d", "Last 7 days"]];
const dayKey = (d) => d.toISOString().slice(0, 10);
const clock = (d) => d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
function dayLabel(d) {
  const today = new Date(), y = new Date(); y.setDate(today.getDate() - 1);
  const date = d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
  if (d.toDateString() === today.toDateString()) return `Today · ${date}`;
  if (d.toDateString() === y.toDateString()) return `Yesterday · ${date}`;
  return d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
}
function ago(iso) {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (!(mins >= 0)) return "";
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)} h ago`;
  return `${Math.round(mins / 1440)} d ago`;
}
// Waybill, order and request numbers become links.
const linkify = (text) => esc(text).replace(/\b(WB-\d{4}-\d{3}|PO-\d{4}-\d{3}|REQ-[\w-]+)\b/g,
  (m) => `<button class="id-link" type="button" data-ref="${m}">${m}</button>`);
const amount = (q, unit, item) => {
  const u = (unit || "").toLowerCase(), it = item.toLowerCase();
  return !u || u === "units" || it.includes(u) ? `${n(q)} ${it}` : `${n(q)} ${u} of ${it}`;
};

export async function render(main, { params, firstVisit }) {
  if (firstVisit && params.tab) st.tab = params.tab === "orders" ? "orders" : "activity";
  const [events, sup] = await Promise.all([api("/api/events?limit=5000"), api("/api/supply/orders")]);
  const openOrders = sup.orders.filter((o) => o.status === "ordered" || o.status === "part");
  main.innerHTML = `<div class="page ${firstVisit ? "fade-in" : ""}">
    <div class="page-head"><div><h1>Log</h1><p>Everything that happened, and every supply order with what has arrived.</p></div>
      <div class="head-actions"></div></div>
    <section class="card log-card">
      <div class="tabs" role="tablist">
        <button role="tab" type="button" data-tab="activity" aria-selected="${st.tab === "activity"}">Activity<span class="count">${n(events.length)}</span></button>
        <button role="tab" type="button" data-tab="orders" aria-selected="${st.tab === "orders"}">Supply orders${openOrders.length ? `<span class="count hot">${openOrders.length} open</span>` : `<span class="count">${sup.orders.length}</span>`}</button>
      </div>
      <div id="log-body"></div>
    </section></div>`;
  main.querySelectorAll("[data-tab]").forEach((b) => (b.onclick = () => {
    st.tab = b.dataset.tab;
    history.replaceState(null, "", `#/log${st.tab === "orders" ? "?tab=orders" : ""}`);
    render(main, { params: {}, firstVisit: false });
  }));
  const body = main.querySelector("#log-body"), actions = main.querySelector(".head-actions");
  if (st.tab === "orders") drawOrders(body, actions, sup.orders);
  else drawActivity(body, actions, events);
  body.addEventListener("click", (e) => {
    const b = e.target.closest("[data-ref]");
    if (!b) return;
    const ref = b.dataset.ref;
    if (ref.startsWith("PO-")) { st.tab = "orders"; st.oq = ref; st.ostatus = "all"; render(main, { params: {}, firstVisit: false }); }
    else if (ref.startsWith("WB-")) openTrack(ref);
    else openWhy(ref);
  });
}

// ---------- Activity ----------
function drawActivity(body, actions, events) {
  const people = [...new Set(events.map((e) => e.actor).filter(Boolean))].sort();
  actions.innerHTML = `<button class="btn" type="button" data-export>${icon.download(17)}Export what's shown (CSV)</button>`;
  body.innerHTML = `<div class="tbl-tools log-tools">
      <label class="tbl-search"><span class="sr-only">Search the log</span>${icon.search(16)}
        <input class="input" type="search" placeholder="Search: shelter, item, waybill, person…" value="${esc(st.q)}"></label>
      <span class="menus" style="display:contents"></span>
      <span class="tbl-count" aria-live="polite"></span>
      <button class="btn link tbl-clear" type="button" hidden>Clear</button></div>
    <div class="feed-list"></div>`;
  const list = body.querySelector(".feed-list"), count = body.querySelector(".tbl-count"), clear = body.querySelector(".tbl-clear");
  const menus = [
    selectMenu({ label: "What", value: st.cat, options: Object.entries(CATS).map(([k, c]) => [k, c.label, events.filter((e) => catOf(e.kind) === k).length]).filter((o) => o[2] || o[0] === st.cat),
      onChange: (v) => { st.cat = v; st.shown = 150; draw(); } }),
    selectMenu({ label: "By", value: st.who, options: [["hub", "Hub (this computer)", events.filter((e) => !e.actor).length], ...people.map((p) => [p, `${p} (phone)`, events.filter((e) => e.actor === p).length])],
      onChange: (v) => { st.who = v; st.shown = 150; draw(); } }),
    selectMenu({ label: "When", value: st.when, allLabel: "Any time", options: WHEN, onChange: (v) => { st.when = v; st.shown = 150; draw(); } }),
  ];
  body.querySelector(".menus").append(...menus);

  const visible = () => {
    const q = st.q.trim().toLowerCase();
    const now = Date.now(), today = new Date().toDateString();
    return events.filter((e) => {
      const t = new Date(e.created_at);
      if (st.cat && catOf(e.kind) !== st.cat) return false;
      if (st.who === "hub" ? e.actor : st.who && e.actor !== st.who) return false;
      if (st.when === "today" && t.toDateString() !== today) return false;
      if (st.when === "24h" && now - t.getTime() > 864e5) return false;
      if (st.when === "7d" && now - t.getTime() > 7 * 864e5) return false;
      if (q && !`${e.message} ${e.actor || ""} ${CATS[catOf(e.kind)].label}`.toLowerCase().includes(q)) return false;
      return true;
    });
  };
  function draw() {
    const rows = visible();
    const filtered = st.q.trim() || st.cat || st.who || st.when;
    clear.hidden = !filtered;
    if (!rows.length) {
      list.innerHTML = `<div class="empty"><strong>${events.length ? "Nothing matches." : "Nothing has happened yet."}</strong>${events.length ? "Try a different word, or clear the filters." : ""}</div>`;
      count.textContent = "";
      return;
    }
    const page = rows.slice(0, st.shown);
    let html = "", day = null;
    for (const e of page) {
      const d = new Date(e.created_at), k = dayKey(d), cat = catOf(e.kind);
      if (k !== day) {
        if (day) html += "</ol></section>";
        day = k;
        html += `<section class="day"><h3 class="day-head">${esc(dayLabel(d))}<span>${rows.filter((x) => dayKey(new Date(x.created_at)) === k).length}</span></h3><ol>`;
      }
      html += `<li class="entry cat-${cat}">
          <time datetime="${esc(e.created_at)}" title="${esc(d.toLocaleString("en-GB"))}">${clock(d)}</time>
          <span class="dot">${CATS[cat].icon(15)}</span>
          <div class="what"><p>${linkify(e.message)}</p>
            <span class="meta">${esc(CATS[cat].label)} · ${e.actor ? `${icon.phone(12)} ${esc(e.actor)}` : "Hub"}</span></div></li>`;
    }
    html += "</ol></section>";
    if (rows.length > page.length) html += `<button class="btn more" type="button" data-more>Show ${n(Math.min(150, rows.length - page.length))} more of ${n(rows.length - page.length)}</button>`;
    list.innerHTML = html;
    const hits = st.q.trim() ? highlight(list, st.q) : 0;
    count.textContent = st.q.trim()
      ? `${plural(rows.length, "entry", "entries")} · ${plural(hits, "match", "matches")} highlighted`
      : filtered ? `${n(rows.length)} of ${plural(events.length, "entry", "entries")}` : plural(events.length, "entry", "entries");
    list.querySelector("[data-more]")?.addEventListener("click", () => { st.shown += 150; draw(); });
  }
  body.querySelector(".tbl-search input").addEventListener("input", debounce((e) => { st.q = e.target.value; st.shown = 150; draw(); }, 120));
  clear.onclick = () => {
    st.q = ""; st.cat = ""; st.who = ""; st.when = ""; st.shown = 150;
    body.querySelector(".tbl-search input").value = "";
    menus.forEach((m) => m.setValue(""));
    draw();
  };
  actions.querySelector("[data-export]").onclick = () => {
    const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const csv = ["time,what,message,by", ...visible().map((e) => [e.created_at, CATS[catOf(e.kind)].label, e.message, e.actor || "Hub"].map(q).join(","))].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `reliefgrid-log-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  draw();
}

// ---------- Supply orders ----------
const STATUS = {
  ordered: ["Ordered", "waiting"], part: ["Part arrived", "part"], arrived: ["Arrived", "done"],
  closed: ["Closed", "muted"], cancelled: ["Cancelled", "muted"],
};
const VIA = { whatsapp: ["WhatsApp", icon.chat], email: ["Gmail", icon.mail], copy: ["Copied", icon.copy] };

async function withUndo(promise, message, undo) {
  try {
    const r = await promise;
    toast(typeof message === "function" ? message(r) : message, undo ? {
      action: "Undo", onAction: async () => {
        try { await undo(r); toast("Undone."); refresh(); } catch (e) { toastError(e); }
      },
    } : {});
    refresh();
    return r;
  } catch (e) { toastError(e); throw e; }
}

function drawOrders(body, actions, orders) {
  actions.innerHTML = `<button class="btn primary" type="button" data-new>${icon.plus(17)}New supply order</button>`;
  actions.querySelector("[data-new]").onclick = async () => {
    const stock = await api("/api/inventory");
    openSupplyRequest(stock.filter((i) => i.to_order > 0).map((i) => ({ item: i.item, quantity: i.to_order, unit: i.unit, why: `${plural(i.waiting_requests, "request")} waiting` })));
  };
  const groups = {
    open: (o) => o.status === "ordered" || o.status === "part", arrived: (o) => o.status === "arrived",
    ended: (o) => o.status === "closed" || o.status === "cancelled", all: () => true,
  };
  const outstanding = orders.filter(groups.open).reduce((a, o) => a + o.outstanding_units, 0);
  body.innerHTML = `<div class="tbl-tools">
      <div class="chips" role="group" aria-label="Show">${[["open", "Waiting to arrive"], ["arrived", "Arrived"], ["ended", "Closed or cancelled"], ["all", "All"]].map(([k, l]) =>
        `<button class="chip" type="button" data-st="${k}" aria-pressed="${st.ostatus === k}">${l}<span class="count">${orders.filter(groups[k]).length}</span></button>`).join("")}</div>
      <label class="tbl-search"><span class="sr-only">Search orders</span>${icon.search(16)}
        <input class="input" type="search" placeholder="Order no., item or supplier" value="${esc(st.oq)}"></label>
      <span class="tbl-count">${outstanding ? `${n(outstanding)} units still expected` : ""}</span></div>
    <div class="orders"></div>`;
  const box = body.querySelector(".orders");

  function draw() {
    const q = st.oq.trim().toLowerCase();
    const list = orders.filter(groups[st.ostatus]).filter((o) => !q || `${o.id} ${o.supplier} ${o.summary} ${o.warehouse_name}`.toLowerCase().includes(q));
    if (!list.length) {
      box.innerHTML = `<div class="empty"><strong>${orders.length ? "No orders here." : "No supply orders yet."}</strong>${orders.length
        ? "Try another tab or clear the search." : "When stock runs short, press New supply order. It's sent by WhatsApp or Gmail and lands here, so you can tick it off when it arrives."}</div>`;
      return;
    }
    box.innerHTML = list.map(card).join("");
    if (q) highlight(box, st.oq);
  }
  function card(o) {
    const [label, tone] = STATUS[o.status];
    const [via, viaIcon] = VIA[o.sent_via] || VIA.copy;
    const isOpen = o.status === "ordered" || o.status === "part";
    const lines = o.lines.map((l) => {
      const pct = Math.min(100, Math.round((l.received / l.quantity) * 100));
      return `<li><div class="ol-top"><strong>${esc(l.item)}</strong>
          <span>${n(l.received)} of ${n(l.quantity)}${l.unit && l.unit !== "units" && !l.item.toLowerCase().includes(l.unit) ? ` ${esc(l.unit)}` : ""} arrived${l.outstanding ? ` · <b>${n(l.outstanding)} still expected</b>` : ""}</span></div>
        <span class="bar" role="img" aria-label="${pct}% arrived"><span style="width:${pct}%"></span></span></li>`;
    }).join("");
    const part = st.partFor === o.id && isOpen ? `<form class="part-form" data-part-form="${esc(o.id)}" novalidate>
        <p>How much arrived just now?</p>
        ${o.lines.filter((l) => l.outstanding).map((l) => `<label><span>${esc(l.item)} <small>${n(l.outstanding)} expected</small></span>
          <input class="input num" type="number" min="0" max="${l.outstanding}" step="1" inputmode="numeric" data-item="${esc(l.item)}" value="${l.outstanding}" aria-label="${esc(l.item)} arrived"></label>`).join("")}
        <div class="part-actions"><button class="btn primary small" type="submit">${icon.check(15)}Tick off</button><button class="btn small" type="button" data-part-cancel>Cancel</button></div></form>` : "";
    const history = o.receipts.length ? `<ul class="receipts">${o.receipts.map((r) => `<li class="${r.reversed_at ? "reversed" : ""}">
        ${r.reversed_at ? icon.undo(14) : icon.check(14)}<span>${Object.entries(r.lines).map(([i, q]) => amount(q, o.lines.find((l) => l.item === i)?.unit, i)).join(", ")} arrived at ${esc(r.warehouse_name)}
        · <time title="${esc(new Date(r.created_at).toLocaleString("en-GB"))}">${ago(r.created_at)}</time>${r.reversed_at ? ` · undone ${ago(r.reversed_at)}` : ""}</span>
        ${r.reversed_at ? "" : `<button class="btn link small" type="button" data-reverse="${r.id}">Undo</button>`}</li>`).join("")}</ul>` : "";
    return `<article class="order-card tone-${tone}" id="o-${esc(o.id)}">
      <header><span class="status ${tone}">${label}</span><strong class="po">${esc(o.id)}</strong>
        <span class="who">${viaIcon(14)} ${esc(o.supplier)} · ${via} · <time title="${esc(new Date(o.created_at).toLocaleString("en-GB"))}">${ago(o.created_at)}</time></span></header>
      <ul class="order-lines-view">${lines}</ul>
      <p class="deliver">${icon.pin(14)} Deliver to ${esc(o.warehouse_name)}</p>
      ${part}
      ${isOpen && st.partFor !== o.id ? `<div class="order-btns">
          <button class="btn primary small" type="button" data-all="${esc(o.id)}">${icon.check(15)}${o.status === "part" ? "The rest arrived" : "All arrived"}</button>
          <button class="btn small" type="button" data-part="${esc(o.id)}">Part arrived…</button>
          ${o.status === "ordered" ? `<button class="btn link small danger-link" type="button" data-cancel="${esc(o.id)}">Cancel order</button>`
            : `<button class="btn link small" type="button" data-close="${esc(o.id)}">Stop waiting for the rest</button>`}</div>` : ""}
      ${!isOpen && o.status !== "arrived" ? `<div class="order-btns"><button class="btn link small" type="button" data-reopen="${esc(o.id)}">Reopen</button></div>` : ""}
      ${history}
    </article>`;
  }

  body.querySelectorAll("[data-st]").forEach((b) => (b.onclick = () => {
    st.ostatus = b.dataset.st;
    body.querySelectorAll("[data-st]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    draw();
  }));
  body.querySelector(".tbl-search input").addEventListener("input", debounce((e) => { st.oq = e.target.value; draw(); }, 120));
  box.addEventListener("click", async (e) => {
    const t = e.target.closest("button");
    if (!t) return;
    const post = (path, b) => api(path, { method: "POST", body: b });
    if (t.dataset.all) {
      t.disabled = true;
      withUndo(post(`/api/supply/orders/${t.dataset.all}/receive`),
        (r) => `${r.id}: ${n(r.units)} units ticked off and put on the shelf.${r.requests_served ? ` ${plural(r.requests_served, "request")} allocated.` : ""}`,
        (r) => post(`/api/supply/receipts/${r.receipt}/reverse`)).catch(() => (t.disabled = false));
    } else if (t.dataset.part) {
      st.partFor = t.dataset.part; draw();
      box.querySelector("[data-part-form] input")?.select();
    } else if (t.hasAttribute("data-part-cancel")) {
      st.partFor = null; draw();
    } else if (t.dataset.cancel) {
      withUndo(post(`/api/supply/orders/${t.dataset.cancel}/cancel`), (r) => `${r.id} cancelled.`, (r) => post(`/api/supply/orders/${r.id}/reopen`)).catch(() => {});
    } else if (t.dataset.close) {
      withUndo(post(`/api/supply/orders/${t.dataset.close}/close`), (r) => `${r.id} closed. The rest is no longer expected.`, (r) => post(`/api/supply/orders/${r.id}/reopen`)).catch(() => {});
    } else if (t.dataset.reopen) {
      withUndo(post(`/api/supply/orders/${t.dataset.reopen}/reopen`), (r) => `${r.id} reopened.`).catch(() => {});
    } else if (t.dataset.reverse) {
      t.disabled = true;
      withUndo(post(`/api/supply/receipts/${t.dataset.reverse}/reverse`), (r) => `Tick on ${r.id} undone. Those units are off the shelf again.`).catch(() => (t.disabled = false));
    }
  });
  box.addEventListener("submit", (e) => {
    const f = e.target.closest("[data-part-form]");
    if (!f) return;
    e.preventDefault();
    const lines = {};
    let bad = false;
    f.querySelectorAll("[data-item]").forEach((inp) => {
      const v = Number(inp.value), ok = inp.value !== "" && Number.isInteger(v) && v >= 0 && v <= Number(inp.max);
      inp.classList.toggle("invalid", !ok);
      if (!ok) bad = true; else if (v) lines[inp.dataset.item] = v;
    });
    if (bad) return;
    if (!Object.keys(lines).length) { toast("Enter how much arrived.", { error: true }); return; }
    st.partFor = null;
    withUndo(api(`/api/supply/orders/${f.dataset.partForm}/receive`, { method: "POST", body: { lines } }),
      (r) => `${r.id}: ${n(r.units)} units ticked off. ${r.status === "arrived" ? "Everything has arrived." : "The rest is still expected."}`,
      (r) => api(`/api/supply/receipts/${r.receipt}/reverse`, { method: "POST" })).catch(() => {});
  });
  draw();
}
