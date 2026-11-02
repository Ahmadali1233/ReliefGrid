// Log: two tabs.
//   Activity        everything that happened. Sublogs on the left (requests, trucks, stock, orders, changes, undo),
//                   filters for shelter, item, person and time, five ways to sort, search with highlights.
//                   Click any WB-/REQ-/PO- number to follow that one thing's whole story. The latest change has Undo.
//   Supply orders   what we asked HQ or suppliers for; tick it off when it arrives (all or part), undo a misclick
import { openNotice, openSupplyRequest, openTrack, openWhy, refresh, undo as undoLast } from "../shared.js";
import { api, debounce, esc, highlight, icon, n, plural, selectMenu, toast, toastError } from "../ui.js";

const st = { tab: "activity", q: "", group: "", shelter: "", item: "", who: "", when: "", sort: "new", ref: "", shown: 120,
  open: new Set(), oq: "", ostatus: "open", partFor: null };

// The sublogs: what happened, grouped the way a coordinator thinks about it.
const GROUPS = {
  requests: { label: "Requests", icon: icon.plus },
  trucks: { label: "Trucks & deliveries", icon: icon.truck },
  stock: { label: "Stock arrivals", icon: icon.download },
  orders: { label: "Supply orders", icon: icon.file },
  settings: { label: "Rules & settings", icon: icon.sliders },
  undo: { label: "Undo history", icon: icon.undo || icon.sliders },
  system: { label: "System", icon: icon.box },
};
const WHEN = [["1h", "Last hour"], ["today", "Today"], ["24h", "Last 24 hours"], ["7d", "Last 7 days"]];
const SORTS = [["new", "Newest first"], ["old", "Oldest first"], ["shelter", "By shelter"], ["item", "By item"], ["who", "By person"]];
const dayKey = (d) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
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
// Waybill, order and request numbers become links that open that thing's own sublog.
const linkify = (text) => esc(text).replace(/\b(WB-\d{4}-\d{3}|PO-\d{4}-\d{3}|REQ-\d{3,})\b/g,
  (m) => `<button class="id-link" type="button" data-ref="${m}" title="Show everything about ${m}">${m}</button>`);
const amount = (q, unit, item) => {
  const u = (unit || "").toLowerCase(), it = item.toLowerCase();
  return !u || u === "units" || it.includes(u) ? `${n(q)} ${it}` : `${n(q)} ${u} of ${it}`;
};
const initials = (who) => (who || "?").replace(/\(.*\)/, "").split(/[\s·]+/).filter(Boolean).slice(-1)[0]?.[0]?.toUpperCase() || "?";

export async function render(main, { params, firstVisit }) {
  if (firstVisit && params.tab) st.tab = params.tab === "orders" ? "orders" : "activity";
  if (firstVisit && params.q) { if (st.tab === "orders") { st.oq = params.q; st.ostatus = "all"; } else st.ref = params.q; }
  if (firstVisit && params.ref) { st.tab = "activity"; st.ref = params.ref; }
  const [events, sup, last, look] = await Promise.all([api("/api/events?limit=5000"), api("/api/supply/orders"), api("/api/undo"),
    api("/api/shelters")]);
  const openOrders = sup.orders.filter((o) => o.status === "ordered" || o.status === "part");
  main.innerHTML = `<div class="page ${firstVisit ? "fade-in" : ""}">
    <div class="page-head"><div><h1>Log</h1><p>Everything that happened, who did it, and every supply order with what has arrived.</p></div>
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
  else drawActivity(body, actions, events, last, look.shelters);
  body.addEventListener("click", (e) => {
    const b = e.target.closest("[data-ref]");
    if (!b) return;
    e.stopPropagation();
    const ref = b.dataset.ref;
    if (st.tab === "orders" && ref.startsWith("PO-")) return;
    if (b.dataset.go === "track") { if (ref.startsWith("REQ-")) openWhy(ref); else openTrack(ref); return; }
    if (b.dataset.go === "orders") { st.tab = "orders"; st.oq = ref; st.ostatus = "all"; render(main, { params: {}, firstVisit: false }); return; }
    st.ref = ref; st.shown = 120;
    render(main, { params: {}, firstVisit: false });
  });
}

// ---------- Activity ----------
function drawActivity(body, actions, events, last, shelters) {
  const shName = Object.fromEntries(shelters.map((s) => [s.id, s.name]));
  const people = [...new Set(events.map((e) => e.actor || "Hub"))].sort();
  const items = [...new Set(events.flatMap((e) => e.items))].sort();
  const usedShelters = [...new Set(events.flatMap((e) => e.shelters))].sort((a, b) => (shName[a] || a).localeCompare(shName[b] || b));
  const undoable = last.label ? events.filter((e) => e.created_at >= last.at && e.kind !== "undo" && !e.undone) : [];
  const undoIds = new Set(undoable.map((e) => e.id));
  let threadRefs = new Set([st.ref]);   // a waybill's sublog also shows its requests, and a request's its waybills
  actions.innerHTML = `<button class="btn" type="button" data-export>${icon.download(17)}Export what's shown (CSV)</button>`;
  body.innerHTML = `<div class="log-grid">
      <nav class="log-rail" aria-label="Sublogs"></nav>
      <div class="log-main">
        ${last.label ? `<div class="undo-bar" role="status"><span class="undo-ico">${icon.undo ? icon.undo(18) : "↶"}</span>
          <div><strong>Last change:</strong> ${esc(last.label)} <span class="muted">· ${esc(ago(last.at))}</span>
          <span class="undo-left">Undo is available for ${Math.max(1, Math.ceil(last.seconds_left / 60))} more min</span></div>
          <button class="btn small primary" type="button" data-undo>Undo</button></div>` : ""}
        <div class="thread"></div>
        <div class="tbl-tools log-tools">
          <label class="tbl-search"><span class="sr-only">Search the log</span>${icon.search(16)}
            <input class="input" type="search" placeholder="Search anything: shelter, item, WB-…, person…" value="${esc(st.q)}"></label>
          <span class="menus" style="display:contents"></span></div>
        <div class="chips-row"><span class="active-chips"></span><span class="tbl-count" aria-live="polite"></span>
          <button class="btn link tbl-clear" type="button" hidden>Clear all</button></div>
        <div class="feed-list"></div>
      </div></div>`;
  const rail = body.querySelector(".log-rail"), list = body.querySelector(".feed-list"), count = body.querySelector(".tbl-count");
  const clear = body.querySelector(".tbl-clear"), chips = body.querySelector(".active-chips"), thread = body.querySelector(".thread");
  const opt = (arr, key, label) => arr.map((v) => [v, label ? label(v) : v, events.filter((e) => key(e, v)).length]);
  const menus = {
    shelter: selectMenu({ label: "Shelter", value: st.shelter, options: opt(usedShelters, (e, v) => e.shelters.includes(v), (v) => shName[v] || v),
      onChange: (v) => set({ shelter: v }) }),
    item: selectMenu({ label: "Item", value: st.item, options: opt(items, (e, v) => e.items.includes(v)), onChange: (v) => set({ item: v }) }),
    who: selectMenu({ label: "Person", value: st.who, options: opt(people, (e, v) => (e.actor || "Hub") === v), onChange: (v) => set({ who: v }) }),
    when: selectMenu({ label: "When", value: st.when, allLabel: "Any time", options: WHEN, onChange: (v) => set({ when: v }) }),
    sort: selectMenu({ label: "Sort", value: st.sort === "new" ? "" : st.sort, allLabel: "Newest first", options: SORTS.slice(1), onChange: (v) => set({ sort: v || "new" }) }),
  };
  body.querySelector(".menus").append(...Object.values(menus));
  function set(change) { Object.assign(st, change, { shown: 120 }); draw(); }

  const match = (e, skip = "") => {
    const t = new Date(e.created_at).getTime(), now = Date.now(), q = st.q.trim().toLowerCase();
    if (skip !== "group" && st.group && e.group !== st.group) return false;
    if (st.ref && !e.refs.some((r) => threadRefs.has(r))) return false;
    if (st.shelter && !e.shelters.includes(st.shelter)) return false;
    if (st.item && !e.items.includes(st.item)) return false;
    if (st.who && (e.actor || "Hub") !== st.who) return false;
    if (st.when === "1h" && now - t > 36e5) return false;
    if (st.when === "today" && new Date(t).toDateString() !== new Date().toDateString()) return false;
    if (st.when === "24h" && now - t > 864e5) return false;
    if (st.when === "7d" && now - t > 7 * 864e5) return false;
    if (q && !`${e.message} ${e.actor || "Hub"} ${GROUPS[e.group]?.label || ""} ${e.shelters.map((s) => shName[s]).join(" ")}`.toLowerCase().includes(q)) return false;
    return true;
  };

  function drawRail() {
    const base = events.filter((e) => match(e, "group"));
    const row = (key, label, ic, c) => `<button type="button" class="rail-item" data-group="${key}" aria-pressed="${st.group === key}">
      <span class="rail-ico">${ic(16)}</span><span class="rail-label">${label}</span><span class="rail-count">${n(c)}</span></button>`;
    rail.innerHTML = `<p class="rail-title">Sublogs</p>${row("", "All activity", icon.search, base.length)}`
      + Object.entries(GROUPS).map(([k, g]) => [k, g, base.filter((e) => e.group === k).length])
        .filter(([k, , c]) => c || st.group === k).map(([k, g, c]) => row(k, g.label, g.icon, c)).join("");
    rail.querySelectorAll("[data-group]").forEach((b) => (b.onclick = () => set({ group: b.dataset.group })));
  }

  async function drawThread() {
    if (!st.ref) { thread.innerHTML = ""; return; }
    const kind = st.ref.startsWith("WB-") ? "Waybill" : st.ref.startsWith("PO-") ? "Supply order" : "Request";
    thread.innerHTML = `<div class="thread-card"><div class="thread-top"><span class="eyebrow">${kind} sublog</span>
        <button class="btn link" type="button" data-close-thread>${icon.x ? icon.x(14) : "✕"} Back to all activity</button></div>
      <h3>${esc(st.ref)}</h3><p class="thread-head muted">Everything that happened to it, in order.</p>
      <div class="thread-actions">${st.ref.startsWith("PO-")
        ? `<button class="btn small" type="button" data-ref="${st.ref}" data-go="orders">Open in Supply orders</button>`
        : `<button class="btn small" type="button" data-ref="${st.ref}" data-go="track">${st.ref.startsWith("WB-") ? "Track it" : "Why? and tracking"}</button>`}</div></div>`;
    thread.querySelector("[data-close-thread]").onclick = () => { set({ ref: "" }); drawThread(); };
    if (!st.ref.startsWith("PO-")) {
      try {
        const t = await api(`/api/track/${encodeURIComponent(st.ref)}`);
        const h = thread.querySelector(".thread-head"); if (h) h.textContent = t.headline;
        threadRefs = new Set([st.ref, ...(t.requests || []), ...(t.shipments || []).map((x) => x.waybill)]);
        draw();
      } catch { /* old or removed */ }
    }
  }

  function drawChips() {
    const c = [];
    if (st.group) c.push(["group", GROUPS[st.group].label]);
    if (st.shelter) c.push(["shelter", shName[st.shelter] || st.shelter]);
    if (st.item) c.push(["item", st.item]);
    if (st.who) c.push(["who", st.who]);
    if (st.when) c.push(["when", WHEN.find((w) => w[0] === st.when)[1]]);
    if (st.q.trim()) c.push(["q", `“${st.q.trim()}”`]);
    chips.innerHTML = c.map(([k, label]) => `<button type="button" class="fchip" data-clear="${k}">${esc(label)}<span aria-hidden="true">✕</span><span class="sr-only">Remove filter</span></button>`).join("");
    chips.querySelectorAll("[data-clear]").forEach((b) => (b.onclick = () => {
      const k = b.dataset.clear;
      if (k === "q") body.querySelector(".tbl-search input").value = "";
      if (menus[k]) menus[k].setValue("");
      set({ [k]: "" });
    }));
    clear.hidden = !c.length;
  }

  const entryHtml = (e) => {
    const d = new Date(e.created_at), g = GROUPS[e.group] || GROUPS.system, who = e.actor || "Hub", open = st.open.has(e.id);
    const related = e.refs.filter((r) => r !== st.ref);
    return `<li class="entry grp-${e.group}${open ? " open" : ""}${undoIds.has(e.id) ? " undoable" : ""}${e.undone ? " was-undone" : ""}" data-id="${e.id}">
        <time datetime="${esc(e.created_at)}" title="${esc(d.toLocaleString("en-GB"))}">${clock(d)}</time>
        <span class="dot">${g.icon(15)}</span>
        <div class="what"><p>${linkify(e.message)}</p>
          <span class="meta">${e.undone ? `<span class="undone-tag">Undone</span>` : ""}<span class="who" title="${esc(who)}"><i>${esc(initials(who))}</i>${esc(who)}</span> · ${esc(g.label)} · ${esc(ago(e.created_at))}</span>
          ${open ? `<div class="entry-more">
            ${e.shelters.length ? `<span>Shelter: ${e.shelters.map((s) => `<button type="button" class="tag" data-pick-shelter="${s}">${esc(shName[s] || s)}</button>`).join(" ")}</span>` : ""}
            ${e.items.length ? `<span>Item: ${e.items.map((i) => `<button type="button" class="tag" data-pick-item="${esc(i)}">${esc(i)}</button>`).join(" ")}</span>` : ""}
            ${related.length ? `<span>Follow: ${related.map((r) => `<button type="button" class="tag strong" data-ref="${r}">${r} →</button>`).join(" ")}</span>` : ""}
            <span class="muted">${esc(d.toLocaleString("en-GB", { dateStyle: "full", timeStyle: "short" }))}</span></div>` : ""}</div>
        ${undoIds.has(e.id) ? `<button class="btn small undo-one" type="button" data-undo title="Undo: ${esc(last.label)}">Undo</button>` : ""}</li>`;
  };

  function draw() {
    drawRail(); drawChips();
    let rows = events.filter((e) => match(e));
    if (st.sort === "old") rows = rows.slice().reverse();
    const filtered = st.q.trim() || st.group || st.shelter || st.item || st.who || st.when || st.ref;
    if (!rows.length) {
      list.innerHTML = `<div class="empty"><strong>${events.length ? "Nothing matches." : "Nothing has happened yet."}</strong>${events.length ? "Try a different word, or remove a filter." : ""}</div>`;
      count.textContent = "";
      return;
    }
    const page = rows.slice(0, st.shown);
    let html = "";
    if (st.sort === "new" || st.sort === "old") {
      let day = null;
      for (const e of page) {
        const d = new Date(e.created_at), k = dayKey(d);
        if (k !== day) {
          if (day) html += "</ol></section>";
          day = k;
          html += `<section class="day"><h3 class="day-head">${esc(dayLabel(d))}<span>${rows.filter((x) => dayKey(new Date(x.created_at)) === k).length}</span></h3><ol>`;
        }
        html += entryHtml(e);
      }
      html += "</ol></section>";
    } else {
      const keyOf = { shelter: (e) => e.shelters[0] || "", item: (e) => e.items[0] || "", who: (e) => e.actor || "Hub" }[st.sort];
      const label = { shelter: (k) => shName[k] || "Not about one shelter", item: (k) => k || "Not about one item", who: (k) => k }[st.sort];
      const groups = new Map();
      for (const e of page) { const k = keyOf(e); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(e); }
      [...groups.entries()].sort((a, b) => b[1].length - a[1].length || label(a[0]).localeCompare(label(b[0]))).forEach(([k, es]) => {
        html += `<section class="day"><h3 class="day-head">${esc(label(k))}<span>${es.length}</span></h3><ol>${es.map(entryHtml).join("")}</ol></section>`;
      });
    }
    if (rows.length > page.length) html += `<button class="btn more" type="button" data-more>Show ${n(Math.min(120, rows.length - page.length))} more of ${n(rows.length - page.length)}</button>`;
    list.innerHTML = html;
    const hits = st.q.trim() ? highlight(list, st.q) : 0;
    count.textContent = st.q.trim()
      ? `${plural(rows.length, "entry", "entries")} · ${plural(hits, "match", "matches")} highlighted`
      : filtered ? `${n(rows.length)} of ${plural(events.length, "entry", "entries")}` : plural(events.length, "entry", "entries");
    list.querySelector("[data-more]")?.addEventListener("click", () => { st.shown += 120; draw(); });
  }

  list.addEventListener("click", (ev) => {
    const t = ev.target;
    if (t.closest("[data-ref]") || t.closest("[data-undo]")) return;
    const sh = t.closest("[data-pick-shelter]"), it = t.closest("[data-pick-item]");
    if (sh) { menus.shelter.setValue(sh.dataset.pickShelter); set({ shelter: sh.dataset.pickShelter }); return; }
    if (it) { menus.item.setValue(it.dataset.pickItem); set({ item: it.dataset.pickItem }); return; }
    const li = t.closest(".entry");
    if (!li || window.getSelection()?.toString()) return;
    const id = Number(li.dataset.id);
    if (st.open.has(id)) st.open.delete(id); else st.open.add(id);
    draw();
  });
  body.addEventListener("click", async (ev) => {
    if (!ev.target.closest("[data-undo]")) return;
    await undoLast();
  });
  body.querySelector(".tbl-search input").addEventListener("input", debounce((e) => set({ q: e.target.value }), 120));
  clear.onclick = () => {
    threadRefs = new Set();
    Object.assign(st, { q: "", group: "", shelter: "", item: "", who: "", when: "", ref: "" });
    body.querySelector(".tbl-search input").value = "";
    ["shelter", "item", "who", "when"].forEach((k) => menus[k].setValue(""));
    set({}); drawThread();
  };
  actions.querySelector("[data-export]").onclick = () => {
    const q = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const csv = ["time,sublog,message,by,shelters,items,numbers", ...events.filter((e) => match(e)).map((e) => [e.created_at, GROUPS[e.group]?.label, e.message,
      e.actor || "Hub", e.shelters.map((s) => shName[s] || s).join("; "), e.items.join("; "), e.refs.join("; ")].map(q).join(","))].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `reliefgrid-log-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };
  drawThread();
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
      withUndo(post(`/api/supply/orders/${t.dataset.cancel}/cancel`), (r) => `${r.id} cancelled.`,
        async (r) => { const back = await post(`/api/supply/orders/${r.id}/reopen`); openNotice(back.notify); })
        .then((r) => openNotice(r.notify)).catch(() => {});
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
