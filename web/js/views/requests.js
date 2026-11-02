// Requests: add one in seconds (with a live preview of what it will get), then filter, search and ask "Why?".
import { act, lookups, openWhy, reportButton } from "../shared.js";
import { api, debounce, esc, gotCell, highlight, icon, n, plural, selectMenu, statusBadge, title, urgencyTag } from "../ui.js";

const URG_RANK = { critical: 0, high: 1, moderate: 2 };
const state = { status: "all", urgency: "", item: "", q: "", sort: null, dir: 1, flag: "" };
const draft = { shelter_id: "", item: "", quantity: "", urgency: "critical" };

export async function render(main, { params, firstVisit }) {
  if (firstVisit && params.status) state.status = params.status;
  if (firstVisit && params.shelter) draft.shelter_id = params.shelter;
  if (firstVisit && params.item) state.item = params.item;
  if (firstVisit) state.flag = params.flag === "size" ? "size" : "";
  if (firstVisit && params.flag === "size") state.status = "all";
  const [all, { shelters, items }] = await Promise.all([api("/api/requests"), lookups()]);
  if (!draft.shelter_id && shelters[0]) draft.shelter_id = shelters[0].id;

  const live = all.filter((r) => r.status !== "cancelled");
  const counts = {
    all: live.length,
    waiting: live.filter((r) => r.remaining > 0).length,
    fulfilled: live.filter((r) => r.status === "fulfilled").length,
    cancelled: all.length - live.length,
    size: live.filter((r) => r.size_warning).length,
  };
  const itemNames = [...new Set(all.map((r) => r.item).concat(items.map((i) => i.item)))].sort();
  const stockOf = Object.fromEntries(items.map((i) => [i.item, i.total]));
  const unitOf = Object.fromEntries(items.map((i) => [i.item.toLowerCase(), i.unit]));

  main.innerHTML = `<div class="page ${firstVisit ? "fade-in" : ""}">
    <div class="page-head"><div><h1>Requests</h1>
      <p>${plural(live.length, "request")} from ${plural(new Set(live.map((r) => r.shelter_id)).size, "shelter")}, served in priority order.</p></div>
      ${reportButton()}</div>

    <section class="card" aria-labelledby="new-req">
      <h2 id="new-req">New request</h2><p class="hint">For a request phoned or messaged in by a shelter. Stock is reserved the moment you press Add.</p>
      <form class="form" id="req-form" novalidate>
        <label class="field wide">Shelter
          <select class="input" name="shelter_id">${shelters.map((s) =>
            `<option value="${esc(s.id)}" ${s.id === draft.shelter_id ? "selected" : ""}>${esc(s.name)} · priority ${s.priority}${s.people != null ? ` · ${n(s.people)} people` : ""}</option>`).join("")}</select></label>
        <label class="field wide">Item
          <input class="input" name="item" list="item-list" placeholder="e.g. Water" value="${esc(draft.item)}" autocomplete="off" required>
          <datalist id="item-list">${itemNames.map((i) => `<option value="${esc(i)}">${n(stockOf[i] || 0)} in stock</option>`).join("")}</datalist></label>
        <label class="field narrow"><span>Quantity <span id="req-unit" style="color:var(--ink);font-weight:600"></span></span>
          <input class="input num" name="quantity" type="number" min="1" step="1" inputmode="numeric" placeholder="0" value="${esc(draft.quantity)}" required></label>
        <fieldset class="field wide" style="border:0;margin:0;padding:0"><legend style="margin-bottom:6px">Urgency</legend>
          <div class="seg" role="group" aria-label="Urgency">${["critical", "high", "moderate"].map((u) =>
            `<button type="button" data-urgency="${u}" aria-pressed="${draft.urgency === u}"><span class="dot ${u}"></span>${title(u)}</button>`).join("")}</div></fieldset>
        <button class="btn primary" type="submit">${icon.plus(18)}Add request</button>
        <p class="form-note" id="req-note" aria-live="polite"></p>
      </form>
    </section>

    <section class="card">
      <div class="card-head" style="align-items:center">
        <div class="chips" role="group" aria-label="Show">${[["all", "All"], ["waiting", "Waiting for stock"], ["fulfilled", "Fully allocated"], ["cancelled", "Cancelled"]].map(([k, l]) =>
          `<button class="chip" type="button" data-status="${k}" aria-pressed="${state.status === k && !state.flag}">${l}<span class="count">${counts[k]}</span></button>`).join("")}
          ${counts.size ? `<button class="chip warn" type="button" data-flag="size" aria-pressed="${state.flag === "size"}" title="Requests that look too big for the shelter's headcount">${icon.alert(14)}Size looks off<span class="count">${counts.size}</span></button>` : ""}</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;flex:1 1 360px;justify-content:flex-end">
          <span id="f-menus" style="display:contents"></span>
          <label style="position:relative;flex:1 1 200px;max-width:260px"><span class="sr-only">Search</span>
            <span style="position:absolute;left:11px;top:11px;color:var(--faint)">${icon.search(17)}</span>
            <input class="input" id="f-q" type="search" placeholder="Shelter, item or ID" value="${esc(state.q)}" style="min-height:40px;padding-left:36px"></label>
        </div>
      </div>
      <div class="table-wrap"><table class="t" id="req-table">
        <thead><tr>${[["id", "ID"], ["shelter", "Shelter"], ["item", "Item"], ["urgency", "Urgency"], ["got", "Got", "r"], [null, "Status"]].map(([k, l, c]) =>
          `<th class="${c || ""}">${k ? `<button class="sort" type="button" data-sort="${k}" ${state.sort === k ? `aria-sort="${state.dir > 0 ? "ascending" : "descending"}"` : ""}>${l}${state.sort === k ? (state.dir > 0 ? " ↑" : " ↓") : ""}</button>` : l}</th>`).join("")}</tr></thead>
        <tbody></tbody></table></div>
      <p id="req-count" style="margin:12px 0 0;font-size:13px;color:var(--muted)"></p>
    </section>
  </div>`;

  const tbody = main.querySelector("#req-table tbody");
  const countLine = main.querySelector("#req-count");

  function drawTable() {
    const q = state.q.trim().toLowerCase();
    let list = all.filter((r) => {
      if (state.status === "waiting" && !(r.remaining > 0)) return false;
      if (state.status === "fulfilled" && r.status !== "fulfilled") return false;
      if (state.status === "cancelled" && r.status !== "cancelled") return false;
      if (state.status === "all" && r.status === "cancelled") return false;
      if (state.flag === "size" && !r.size_warning) return false;
      if (state.urgency && r.urgency !== state.urgency) return false;
      if (state.item && r.item !== state.item) return false;
      if (q && ![r.id, r.item, r.shelter_name, r.shelter_id].some((v) => String(v).toLowerCase().includes(q))) return false;
      return true;
    });
    if (state.sort) {
      const key = { id: (r) => r.id, shelter: (r) => r.shelter_name, item: (r) => r.item,
                    urgency: (r) => URG_RANK[r.urgency], got: (r) => r.allocated / r.quantity }[state.sort];
      list = [...list].sort((a, b) => (key(a) > key(b) ? 1 : key(a) < key(b) ? -1 : 0) * state.dir);
    }
    tbody.innerHTML = list.length ? list.map((r) => `<tr class="clickable" tabindex="0" data-id="${esc(r.id)}">
        <td class="strong num">${esc(r.id)}</td>
        <td><span class="strong">${esc(r.shelter_name)}</span><span class="sub">priority ${r.shelter_priority}</span></td>
        <td>${esc(r.item)}${r.size_note ? `<span class="sub ${r.size_warning ? "size-warn" : ""}" ${r.size_warning ? `title="${esc(r.size_warning)}"` : ""}>${r.size_warning ? icon.alert(13) : ""}${esc(r.size_note)}</span>` : ""}</td><td>${urgencyTag(r.urgency)}</td><td class="r">${gotCell(r)}</td><td>${statusBadge(r.status)}</td></tr>`).join("")
      : `<tr><td colspan="6"><div class="empty"><strong>No requests match.</strong>Try clearing the search or filters.</div></td></tr>`;
    if (q) highlight(tbody, q);
    countLine.textContent = list.length ? `Showing ${plural(list.length, "request")}${state.sort ? "" : " in the order they're served"} · click one to see why it got what it got` : "";
  }
  drawTable();

  tbody.addEventListener("click", (e) => { const tr = e.target.closest("tr[data-id]"); if (tr) openWhy(tr.dataset.id); });
  tbody.addEventListener("keydown", (e) => { const tr = e.target.closest("tr[data-id]"); if (tr && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openWhy(tr.dataset.id); } });
  main.querySelectorAll("[data-status], [data-flag]").forEach((b) => (b.onclick = () => {
    if (b.dataset.flag) { state.flag = state.flag ? "" : "size"; state.status = "all"; }
    else { state.status = b.dataset.status; state.flag = ""; }
    main.querySelectorAll("[data-status]").forEach((x) => x.setAttribute("aria-pressed", String(!state.flag && x.dataset.status === state.status)));
    main.querySelector("[data-flag]")?.setAttribute("aria-pressed", String(!!state.flag));
    drawTable();
  }));
  const live2 = all.filter((r) => r.status !== "cancelled");
  main.querySelector("#f-menus").append(
    selectMenu({ label: "Urgency", value: state.urgency, allLabel: "Any",
      options: ["critical", "high", "moderate"].map((u) => [u, title(u), live2.filter((r) => r.urgency === u).length]),
      onChange: (v) => { state.urgency = v; drawTable(); } }),
    selectMenu({ label: "Item", value: state.item, allLabel: "Any",
      options: itemNames.map((i) => [i, i, live2.filter((r) => r.item === i).length]),
      onChange: (v) => { state.item = v; drawTable(); } }),
  );
  main.querySelector("#f-q").addEventListener("input", debounce((e) => { state.q = e.target.value; drawTable(); }, 120));
  main.querySelectorAll("[data-sort]").forEach((b) => (b.onclick = () => {
    if (state.sort === b.dataset.sort) { if (state.dir === 1) state.dir = -1; else { state.sort = null; state.dir = 1; } }
    else { state.sort = b.dataset.sort; state.dir = 1; }
    render(main, { params: {}, firstVisit: false });
  }));

  // ----- New request form -----
  const form = main.querySelector("#req-form");
  const note = main.querySelector("#req-note");
  form.querySelectorAll("[data-urgency]").forEach((b) => (b.onclick = () => {
    draft.urgency = b.dataset.urgency;
    form.querySelectorAll("[data-urgency]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    preview();
  }));
  const preview = debounce(async () => {
    const f = Object.fromEntries(new FormData(form));
    Object.assign(draft, { shelter_id: f.shelter_id, item: f.item, quantity: f.quantity });
    const unit = unitOf[f.item.trim().toLowerCase()];
    main.querySelector("#req-unit").textContent = unit && unit !== "units" ? `(${unit})` : "";
    const q = Number(f.quantity);
    form.quantity.classList.toggle("invalid", f.quantity !== "" && !(Number.isInteger(q) && q > 0));
    if (!f.item.trim() || !q) { note.className = "form-note"; note.textContent = ""; return; }
    if (!Number.isInteger(q) || q < 1) { note.className = "form-note bad"; note.innerHTML = `${icon.alert(16)} Quantity must be a whole number, 1 or more.`; return; }
    try {
      const p = await api(`/api/requests/preview?${new URLSearchParams({ ...f, item: f.item.trim(), urgency: draft.urgency })}`);
      const dup = p.open_duplicates?.[0];
      const dupNote = dup ? ` <strong style="color:var(--warn-ink)">This shelter already has an open ${esc(f.item.trim().toLowerCase())} request (${esc(dup.id)}, ${n(dup.allocated)} of ${n(dup.quantity)}).</strong> If it's the same need, change ${esc(dup.id)} instead.` : "";
      if (p.would_get >= q) { note.className = "form-note good"; note.innerHTML = `${icon.check(16)} In stock: all ${n(q)} will be reserved straight away.${dupNote}`; }
      else if (p.would_get > 0) { note.className = "form-note warn"; note.innerHTML = `${icon.info(16)} Only ${n(p.would_get)} available for it now. Those are reserved; it waits for the other ${n(q - p.would_get)}.${dupNote}`; }
      else if (p.in_stock === 0) { note.className = "form-note bad"; note.innerHTML = `${icon.alert(16)} None on the shelf. It will wait and be allocated as soon as ${esc(f.item.trim().toLowerCase())} arrives.${dupNote}`; }
      else { note.className = "form-note warn"; note.innerHTML = `${icon.info(16)} ${plural(p.ahead, "more urgent request")} ${p.ahead === 1 ? "gets" : "get"} the ${n(p.in_stock)} on the shelf first.${dupNote}`; }
      if (p.size?.warning) note.insertAdjacentHTML("beforeend", ` <span class="size-check warn">${icon.alert(15)}${esc(p.size.warning)}</span>`);
      else if (p.size?.text) note.insertAdjacentHTML("beforeend", ` <span class="size-check">${icon.users(15)}That's ${esc(p.size.text)}.</span>`);
      note.style.flexWrap = "wrap";
    } catch { note.textContent = ""; }
  }, 200);
  form.addEventListener("input", preview);
  preview();
  form.onsubmit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(form));
    if (!f.item.trim()) { form.item.focus(); form.item.classList.add("invalid"); return; }
    const btn = form.querySelector("[type=submit]");
    btn.disabled = true;
    try {
      await act(api("/api/requests", { method: "POST", body: { ...f, item: f.item.trim(), quantity: Number(f.quantity), urgency: draft.urgency } }),
        (r) => `${r.id} added. ${n(r.given)} of ${n(r.requested)} ${r.item.toLowerCase()} reserved for ${r.shelter}.`);
      draft.item = ""; draft.quantity = "";
    } catch { btn.disabled = false; }
  };
}
