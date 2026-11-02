// Rules: who goes first, the optional rules a coordinator can switch on, data checks, and demo data.
import { act, openIntegrity, refresh } from "../shared.js";
import { api, closeButton, closeOverlay, esc, icon, openModal, toast, toastError } from "../ui.js";

const figRow = (f = { item: "", per_person: "", per: "day", basis: "" }) => `<tr>
  <td><input class="input" name="item" value="${esc(f.item)}" placeholder="e.g. Water" aria-label="Item"></td>
  <td class="r"><input class="input num" name="per_person" type="number" min="0" step="any" value="${f.per_person}" style="width:100px;text-align:right" aria-label="Per person"></td>
  <td><select class="input" name="per" aria-label="How often"><option value="day" ${f.per === "day" ? "selected" : ""}>per day</option><option value="stay" ${f.per === "stay" ? "selected" : ""}>once per stay</option></select></td>
  <td><input class="input" name="basis" value="${esc(f.basis || "")}" placeholder="Source or reasoning" aria-label="Where the figure comes from"></td>
  <td class="r"><button class="btn link" type="button" data-remove aria-label="Remove">${icon.x(16)}</button></td></tr>`;

export async function render(main, { firstVisit }) {
  const [rules, figs] = await Promise.all([api("/api/rules"), api("/api/figures")]);
  main.innerHTML = `<div class="page ${firstVisit ? "fade-in" : ""}">
    <div class="page-head"><div><h1>Rules</h1><p>Who goes first, and the optional rules a coordinator can switch on. Every change re-runs allocation and is logged with your name.</p></div></div>
    <div class="row">
      <section class="card half"><h2>Who goes first</h2><p class="hint">A fixed order. Ties are always broken, so the same data always gives the same answer.</p>
        <ol class="order">
          <li><div><strong>Urgency</strong><span>Critical, then High, then Moderate</span></div></li>
          <li><div><strong>Shelter priority</strong><span>Priority 1 (most vulnerable) before 2 and 3</span></div></li>
          <li><div><strong>Time submitted</strong><span>Earlier requests first</span></div></li>
          <li><div><strong>Request ID</strong><span>Alphabetical, as a final tie-break</span></div></li>
        </ol>
        <p style="margin:18px 0 0;font-size:14px;color:var(--muted)">Stock is reserved from the nearest warehouse that has the item; if it runs short, the next nearest tops it up.
          Reserved stock that is already on a truck is never taken back.</p>
      </section>
      <section class="card half"><h2>Optional rules</h2><p class="hint">Off by default. Turn one on and allocation re-runs straight away.</p>
        <form id="rules-form">
          <div class="rule"><div><h3>Reserve for Critical</h3><p>Hold back a share of each item that only Critical requests can use, for emergencies reported later.</p></div>
            <div class="ctl"><output for="r1" id="o1">${rules.reserve_for_critical_pct}%</output>
              <input id="r1" type="range" name="reserve_for_critical_pct" min="0" max="50" step="5" value="${rules.reserve_for_critical_pct}" aria-label="Reserve percentage"></div></div>
          <div class="rule"><div><h3>Days of supply per shelter</h3><p>Most days of a daily item (water, meals) a shelter can get for its headcount while others wait. Stops a 50-person point taking weeks of water while 400 people next door have none. Stock above the cap that hasn't left the warehouse goes back on the shelf. 0 = off.</p></div>
            <div class="ctl"><input class="input num" type="number" min="0" max="365" step="1" name="max_days_per_shelter" value="${rules.max_days_per_shelter}" aria-label="Days of supply per shelter"></div></div>
          <div class="rule"><div><h3>Cap per shelter</h3><p>Most units of one item a single shelter can receive in total, so one large request can't take everything. 0 = no cap.</p></div>
            <div class="ctl"><input class="input num" type="number" min="0" step="10" name="max_per_shelter_per_item" value="${rules.max_per_shelter_per_item}" aria-label="Cap per shelter"></div></div>
          <div class="rule"><div><h3>Low-stock alert</h3><p>Flag an item when less than this share of everything received is left.</p></div>
            <div class="ctl"><output for="r3" id="o3">${rules.low_stock_pct}%</output>
              <input id="r3" type="range" name="low_stock_pct" min="5" max="50" step="5" value="${rules.low_stock_pct}" aria-label="Low stock percentage"></div></div>
          <div style="display:flex;justify-content:flex-end;gap:10px;margin-top:10px">
            <button class="btn primary" type="submit">${icon.sliders(17)}Apply rules</button></div>
        </form>
      </section>
    </div>
    <section class="card"><div class="card-head"><h2>Planning figures</h2><span style="color:var(--muted);font-size:14px">${figs.people.people.toLocaleString()} people in ${figs.people.shelters} shelters${figs.people.shelters_without_headcount ? ` · ${figs.people.shelters_without_headcount} without a headcount` : ""}</span></div>
      <p class="hint">How much one person needs. With each shelter's headcount, this turns units into days and people: it checks request sizes, shows fair share, and powers the days-of-supply rule. Leave an item out if no figure makes sense (e.g. first aid kits).</p>
      <form id="fig-form" novalidate><div class="table-wrap"><table class="t fig-table">
        <thead><tr><th>Item</th><th class="r">Per person</th><th>How often</th><th>Where the figure comes from</th><th><span class="sr-only">Remove</span></th></tr></thead>
        <tbody>${figs.items.map(figRow).join("")}</tbody></table></div>
        <div style="display:flex;justify-content:space-between;gap:10px;margin-top:12px;flex-wrap:wrap">
          <button class="btn" type="button" data-add-fig>${icon.plus(16)}Add an item</button>
          <button class="btn primary" type="submit">Save figures</button></div></form>
    </section>
    <div class="row">
      <section class="card half"><h2>Data checks</h2>
        <p class="hint">Seven checks run against the database every time the dashboard loads: stock adds up, nothing below zero, no request over-filled, whole units only, priority order kept, same result on re-run, and every load that left is on a signed waybill.</p>
        <div style="display:flex;gap:10px;flex-wrap:wrap">
          <button class="btn" type="button" data-integrity>${icon.shield(17)}Run the checks now</button>
          <a class="btn" href="/docs" target="_blank" rel="noopener">${icon.file(17)}API documentation</a></div>
      </section>
      <section class="card half"><h2>Demo data</h2>
        <p class="hint">For training and demos. Replaces everything in this database, including the log. Cannot be undone.</p>
        <div style="display:flex;gap:10px;flex-wrap:wrap">
          <button class="btn danger" type="button" data-reset="sample">Load sample data</button>
          <button class="btn danger" type="button" data-reset="empty">Start empty</button></div>
      </section>
    </div>
  </div>`;

  const form = main.querySelector("#rules-form");
  form.r1.oninput = () => (main.querySelector("#o1").textContent = `${form.r1.value}%`);
  form.r3.oninput = () => (main.querySelector("#o3").textContent = `${form.r3.value}%`);
  form.onsubmit = async (e) => {
    e.preventDefault();
    const body = Object.fromEntries([...new FormData(form)].map(([k, v]) => [k, Number(v)]));
    try {
      await act(api("/api/rules", { method: "PUT", body }),
        (r) => `Rules applied.${r.released ? ` ${r.released.toLocaleString()} units released from over-supplied shelters.` : ""} ${r.requests_served ? `${r.requests_served} requests re-allocated.` : "Nothing changed hands."}`);
    } catch {}
  };
  const figForm = main.querySelector("#fig-form");
  const tbody = figForm.querySelector("tbody");
  figForm.querySelector("[data-add-fig]").onclick = () => { tbody.insertAdjacentHTML("beforeend", figRow()); tbody.lastElementChild.querySelector("input").focus(); };
  tbody.addEventListener("click", (e) => { if (e.target.closest("[data-remove]")) e.target.closest("tr").remove(); });
  figForm.onsubmit = async (e) => {
    e.preventDefault();
    const items = [...tbody.querySelectorAll("tr")].map((tr) => ({
      item: tr.querySelector("[name=item]").value.trim(), per_person: Number(tr.querySelector("[name=per_person]").value),
      per: tr.querySelector("[name=per]").value, basis: tr.querySelector("[name=basis]").value.trim(),
    })).filter((x) => x.item);
    try { await act(api("/api/figures", { method: "PUT", body: { items } }), `Planning figures saved for ${items.length} items.`); } catch {}
  };
  main.querySelector("[data-integrity]").onclick = openIntegrity;
  main.querySelectorAll("[data-reset]").forEach((b) => (b.onclick = () => {
    const sample = b.dataset.reset === "sample";
    const el = openModal(`<div style="display:flex;justify-content:space-between;gap:12px"><div><h2>${sample ? "Load sample data" : "Start empty"}?</h2>
      <p style="margin:0;color:var(--muted)">This deletes every request, delivery, dispatch and log entry in this database${sample ? " and loads the 48 sample requests" : ""}. It cannot be undone.</p></div>${closeButton}</div>
      <form class="form" style="margin-top:18px" novalidate>
        <label class="field wide">Type RESET to confirm<input class="input" name="confirm" autocomplete="off" autofocus></label>
        <button class="btn danger" type="submit">${sample ? "Replace with sample data" : "Delete everything"}</button></form>`);
    el.querySelector("form").onsubmit = async (e) => {
      e.preventDefault();
      if (e.target.confirm.value.trim() !== "RESET") { e.target.confirm.classList.add("invalid"); return; }
      try {
        await api("/api/reset", { method: "POST", body: { confirm: "RESET", sample } });
        closeOverlay();
        toast(sample ? "Sample data loaded." : "Database is empty. Add warehouses, shelters and stock to begin.");
        location.hash = sample ? "#/" : "#/inventory";
        refresh();
      } catch (err) { toastError(err); }
    };
  }));
}
