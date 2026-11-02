// Dashboard: one sentence that says what matters, then the numbers behind it.
import { openSitrep } from "../extras.js";
import { act, openIntegrity, openRestock, openSupplyRequest, openWhy, reportButton } from "../shared.js";
import { drawReliefWeb } from "../reliefweb.js";
import { api, countUp, debounce, esc, gotCell, icon, n, pct, plural, timeLabel, title, urgencyTag } from "../ui.js";

const hours = (h) => (h == null ? "" : h < 1 ? `~${Math.max(1, Math.round(h * 60))} min` : `~${h < 10 ? h.toFixed(1).replace(/\.0$/, "") : Math.round(h)} h`);
const days = (d) => (d == null ? "" : d === 0 ? "none" : d < 1 / 24 ? "under an hour" : d < 1 ? `${Math.round(d * 24)} h` : `${d < 10 ? d.toFixed(1).replace(/\.0$/, "") : Math.round(d)} day${d >= 1 && d < 1.05 ? "" : "s"}`);
let whatIfItem = null;

const FEED_ICON = { allocation: icon.truck, restock: icon.box, request: icon.plus, import: icon.upload,
                    undo: icon.undo, cancel: icon.x, rules: icon.sliders, system: icon.info, waybill: icon.file,
                    dispatch: icon.truck, delivered: icon.check, shelter: icon.users };

export async function render(main, { heroSlot, firstVisit }) {
  if (firstVisit) {
    heroSlot.innerHTML = `<section class="hero"><div class="hero-inner"><div class="hero-text">
      <div class="skeleton" style="height:16px;width:300px;opacity:.15"></div>
      <div class="skeleton" style="height:50px;width:70%;margin-top:14px;opacity:.15"></div></div></div></section>`;
    main.innerHTML = `<div class="page"><div class="kpis">${'<div class="card skeleton" style="height:120px"></div>'.repeat(4)}</div></div>`;
  }
  const [s, net] = await Promise.all([api("/api/summary"), api("/api/network")]);
  const k = s.kpis;
  const short = s.stock.find((i) => i.item === s.short_item);
  const integrityOk = s.integrity.passed === s.integrity.total;
  const today = new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "short" });
  const ppl = s.people;
  const unfair = s.fairness.find((f) => f.short.length && f.above.length);
  const ruleDays = s.rules.max_days_per_shelter;
  const heldCrit = s.held_by_rule.filter((h) => h.urgency === "critical");

  const notes = [];
  if (unfair && !ruleDays) {
    const hi = unfair.above[0], lo = unfair.short[0];
    const shortPeople = unfair.short.reduce((a, c) => a + (c.people || 0), 0);
    notes.push(`<div class="hero-note warn"><span class="ic">${icon.scale(18)}</span><p><strong>${esc(unfair.item)} isn't shared fairly.</strong>
      ${esc(hi.shelter_name)} has ${days(hi.days)} for ${n(hi.people)} people, while ${unfair.short.length === 1 ? esc(lo.shelter_name) : `${unfair.short.length} shelters`} with ${n(shortPeople)} people ${unfair.short.length === 1 ? "has" : "have"} ${days(lo.days) === "none" ? "none" : `under ${days(unfair.fair_days / 2)}`}.
      Strict priority order did that.</p><button class="btn small on-dark" type="button" data-fair>Cap at 7 days per shelter</button></div>`);
  } else if (ruleDays && s.held_by_rule.length) {
    const who = [...new Set(s.held_by_rule.map((h) => h.shelter_name))];
    notes.push(`<div class="hero-note"><span class="ic">${icon.scale(18)}</span><p><strong>${ruleDays}-day rule is on.</strong>
      ${who.slice(0, 2).map(esc).join(" and ")}${who.length > 2 ? ` and ${who.length - 2} more` : ""} already ${who.length === 1 ? "has" : "have"} ${ruleDays} days of supply for ${who.length === 1 ? "its" : "their"} headcount, so ${plural(s.held_by_rule.length, "request")} ${s.held_by_rule.length === 1 ? "waits" : "wait"} while others are served.</p>
      <a class="btn small on-dark" href="#/rules">Rules</a></div>`);
  }
  const oversized = (await api("/api/requests")).filter((r) => r.size_warning && r.dispatched < r.quantity);
  if (oversized.length) {
    const sh = [...new Set(oversized.map((r) => r.shelter_name))];
    notes.push(`<div class="hero-note"><span class="ic">${icon.info(18)}</span><p><strong>${plural(oversized.length, "request")} look${oversized.length === 1 ? "s" : ""} too big for ${sh.length === 1 ? `${esc(sh[0])}'s headcount` : `their shelters' headcounts`}.</strong>
      ${esc(oversized[0].size_warning)}</p><a class="btn small on-dark" href="#/requests?flag=size">Check</a></div>`);
  }

  heroSlot.innerHTML = `<section class="hero">
    <div class="hero-inner">
      <div class="hero-text">
        <p class="eyebrow">${esc(today)} · ${ppl.people ? `<strong>${n(ppl.people)} people</strong> in ` : ""}${plural(s.counts.shelters, "shelter")} · ${plural(s.counts.requests, "request")} · ${plural(s.counts.warehouses, "warehouse")}</p>
        <h1>${esc(s.headline)}</h1>
        <p class="sub">${esc(s.subline)}${heldCrit.length ? ` ${plural(heldCrit.length, "critical request")} ${heldCrit.length === 1 ? "is" : "are"} at the ${ruleDays}-day limit.` : ""}</p>
        <button type="button" class="pill-check ${integrityOk ? "" : "fail"}" data-integrity>
          <span class="pulse"></span>${integrityOk ? `All ${s.integrity.total} integrity checks passed` : `${s.integrity.passed} of ${s.integrity.total} checks passed`}
          <span style="opacity:.7;font-weight:500">· see the maths</span></button>
        ${notes.length ? `<div class="hero-notes">${notes.join("")}</div>` : ""}
        <div class="hero-actions">
          ${s.stock.some((i) => i.to_order > 0)
            ? `<button class="btn primary" type="button" data-ask>${icon.chat(17)}Order supplies</button>`
            : short ? `<a class="btn primary" href="#/log?tab=orders">${icon.file(17)}Track supply orders</a>`
            : `<a class="btn primary" href="#/requests">${icon.plus(18)}New request</a>`}
          <button class="btn on-dark" type="button" data-delivery title="Stock has arrived at a warehouse">${icon.box(17)}Record delivery</button>
          <button class="btn on-dark" type="button" data-sitrep title="A situation report you can paste into WhatsApp">${icon.file(17)}Sitrep</button>
          ${reportButton("Report").replace('class="btn"', 'class="btn on-dark"')}
        </div>
      </div>
      <figure class="relief-web" aria-labelledby="web-cap"><figcaption id="web-cap">The relief web · live</figcaption><div id="web-box"></div></figure>
    </div></section>`;
  drawReliefWeb(heroSlot.querySelector("#web-box"), net);
  heroSlot.querySelector("[data-fair]")?.addEventListener("click", (e) => {
    e.currentTarget.disabled = true;
    act(api("/api/rules", { method: "PUT", body: { max_days_per_shelter: 7 } }),
      (r) => `7-day rule on. ${n(r.released)} units released from over-supplied shelters and ${plural(r.requests_served, "request")} served.`);
  });

  const crit = k.critical_total;
  const stockRows = s.stock.map((i) => {
    const segs = i.warehouses.map((w, idx) => {
      const width = i.received ? (w.quantity / i.received) * 100 : 0;
      const color = i.status === "low" ? "var(--warn)" : idx === 0 ? "var(--ink)" : "#6B7186";
      return `<span style="width:${width}%;background:${color}"></span>`;
    }).join("");
    const cover = i.status === "out" ? "" : i.days_on_shelf != null ? `${days(i.days_on_shelf)} for everyone`
      : i.hours_of_cover != null ? `${hours(i.hours_of_cover)} at today's pace` : "";
    const tip = i.warehouses.map((w) => `${w.name}: ${n(w.quantity)}`).join(" · ") + (cover ? ` · lasts ${cover}` : "");
    const amt = i.status === "out" ? "Out" : `<strong>${n(i.total)}</strong>${cover ? `<small> · ${cover}</small>` : i.status === "low" ? " low" : ""}`;
    return `<div class="stock-row ${i.status}" title="${esc(tip)}">
      <span>${esc(i.item)}</span><span class="track" aria-hidden="true">${segs}</span>
      <span class="amt">${amt}</span></div>`;
  }).join("");

  const fairRows = s.fairness.map((fr) => {
    const scale = Math.max(fr.fair_days * 2, 7);
    const list = [...fr.above.slice(0, 2), ...fr.short.slice(0, 3)];
    const rows = (list.length ? list : [fr.lowest, fr.highest]).map((c) => {
      const cls = fr.above.includes(c) ? "over" : fr.short.includes(c) ? "under" : "";
      return `<a class="fair-row ${cls}" href="#/shelters?id=${encodeURIComponent(c.shelter_id)}">
        <span class="name">${esc(c.shelter_name)}<small>${n(c.people)} people</small></span>
        <span class="track"><span style="width:${Math.min(c.days / scale, 1) * 100}%"></span><i style="left:${(fr.fair_days / scale) * 100}%" title="Even share: ${days(fr.fair_days)}"></i></span>
        <span class="val">${days(c.days)}</span></a>`;
    }).join("");
    return `<div class="fair-item"><div class="fair-head"><strong>${esc(fr.item)}</strong>
      <span>even share ${days(fr.fair_days)} each${list.length ? "" : " · shared evenly"}</span></div>${rows}</div>`;
  }).join("");

  const next = s.next_in_line.length
    ? `<div class="table-wrap"><table class="t"><thead><tr><th>Shelter</th><th>Item</th><th>Urgency</th><th class="r">Got</th><th><span class="sr-only">Explain</span></th></tr></thead><tbody>
      ${s.next_in_line.map((r) => `<tr class="clickable" data-why="${esc(r.id)}">
        <td><span class="strong">${esc(r.shelter_name)}</span><span class="sub">${esc(r.id)}</span></td>
        <td>${esc(r.item)}</td><td>${urgencyTag(r.urgency)}</td><td class="r">${gotCell(r)}</td>
        <td class="r"><button class="btn link" type="button" data-why="${esc(r.id)}">Why?</button></td></tr>`).join("")}
      </tbody></table></div>`
    : `<div class="empty"><strong>Nobody is waiting.</strong>Every request has been filled.</div>`;

  const feed = s.events.map((e) => `<li><span class="ic ${esc(e.kind)}">${(FEED_ICON[e.kind] || icon.info)(15)}</span>
      <span>${esc(e.message)}</span><time datetime="${esc(e.created_at)}">${timeLabel(e.created_at)}</time></li>`).join("");

  main.innerHTML = `<div class="page ${firstVisit ? "fade-in" : ""}">
    <section class="kpis" aria-label="Key numbers">
      <a class="card kpi" href="#/shelters" style="text-decoration:none;color:inherit"><div class="label">People in shelters</div>
        <div class="value"><span data-count="${ppl.people}">${n(ppl.people)}</span></div>
        <div class="foot">${ppl.waiting_critical ? `<strong style="color:var(--bad-ink)">${n(ppl.waiting_critical)}</strong> still waiting on something critical` : "nobody waiting on anything critical"}${ppl.shelters_without_headcount ? ` · ${ppl.shelters_without_headcount} without a headcount` : ""}</div></a>
      <div class="card kpi"><div class="label">Critical requests covered</div>
        <div class="value"><span data-count="${k.critical_fulfilled}">${n(k.critical_fulfilled)}</span><small>/${n(crit)}</small></div>
        <div class="foot">${crit - k.critical_fulfilled ? `${crit - k.critical_fulfilled} short${heldCrit.length ? `, ${heldCrit.length} of them at the ${ruleDays}-day limit` : ""}` : "none waiting"}</div>
        <span class="badge teal tag">${pct(k.critical_fulfilled, crit)}%</span></div>
      <a class="card kpi" href="#/dispatch" style="text-decoration:none;color:inherit"><div class="label">Delivered to shelters</div>
        <div class="value"><span data-count="${k.units_delivered}">${n(k.units_delivered)}</span><small> units</small></div>
        <div class="foot">${n(k.units_on_the_way)} on the road · ${n(k.units_to_load)} waiting for a truck</div></a>
      <a class="card kpi" href="#/requests?status=waiting" style="text-decoration:none;color:inherit"><div class="label">Requests still waiting</div>
        <div class="value"><span data-count="${k.waiting}">${k.waiting}</span></div>
        <div class="foot">${k.waiting_by_urgency.critical} critical · ${k.waiting_by_urgency.high} high · ${k.waiting_by_urgency.moderate} moderate</div></a>
    </section>
    <div class="row">
      <section class="card half"><div class="card-head"><h2>Fair share per person</h2><a href="#/shelters">All shelters</a></div>
        <p class="hint">Days of supply each shelter was given for its headcount, against an even share of what's been handed out.</p>
        ${fairRows || `<div class="empty"><strong>Nothing to compare yet.</strong>Add headcounts on the Shelters screen and planning figures under Rules.</div>`}</section>
      <section class="card half"><h2>Stock on the shelf</h2><p class="hint">Not yet reserved for anyone. How long it would last everyone sheltered, by the planning figures.</p>
        <div class="stock-list">${stockRows}</div></section>
    </div>
    <div class="row">
      <section class="card half" id="whatif"><h2>How much should we ask for?</h2><p class="hint">Drag to see what a delivery of that size would cover. Then send it as a supply request.</p>
        <div class="form">
          <label class="field">Item<select class="input" id="wi-item">${s.stock.map((i) => `<option value="${esc(i.item)}" data-short="${i.short_by}" data-unit="${esc(i.unit)}" ${i.item === (whatIfItem || s.short_item || s.stock[0]?.item) ? "selected" : ""}>${esc(i.item)}${i.short_by ? ` · ${n(i.short_by)} short` : ""}</option>`).join("")}</select></label>
          <label class="field">Delivered to<select class="input" id="wi-wh"></select></label>
        </div>
        <div style="margin-top:18px"><label for="wi-range" style="display:flex;justify-content:space-between;font-size:14px;color:var(--muted)"><span>If this much arrived</span><strong id="wi-qty" class="num" style="color:var(--ink);font-size:16px"></strong></label>
          <input type="range" id="wi-range" min="0" step="10" style="margin-top:8px"></div>
        <dl class="whatif-out" aria-live="polite">
          <div><dt>Critical covered</dt><dd id="wi-crit">–</dd></div>
          <div><dt>Still waiting</dt><dd id="wi-wait">–</dd></div>
          <div><dt>Requests served</dt><dd id="wi-served">–</dd></div></dl>
        <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:16px">
          <button class="btn primary" type="button" id="wi-go" style="flex:1" disabled>${icon.file(17)}Send as supply request</button>
          <button class="btn" type="button" id="wi-arrived">It's arrived: record it</button></div>
      </section>
      <section class="card half"><div class="card-head"><h2>Activity</h2><a href="#/log">Full log</a></div><ul class="feed">${feed}</ul></section>
    </div>
    <section class="card"><div class="card-head"><h2>Next in line</h2><a href="#/requests?status=waiting">All ${k.waiting} waiting</a></div>${next}</section>
    <footer class="foot"><span>Saved automatically · works offline · Ctrl+Z undoes your last change (within 10 minutes)</span><span>Built by Team FEAST · RIT Dubai 2026</span></footer>
  </div>`;

  if (firstVisit) countUp(main);
  heroSlot.querySelector("[data-integrity]").onclick = openIntegrity;
  heroSlot.querySelector("[data-sitrep]").onclick = openSitrep;
  setupWhatIf(main, s);
  heroSlot.querySelector("[data-delivery]").onclick = () => openRestock({ item: short?.item });
  heroSlot.querySelector("[data-ask]")?.addEventListener("click", () => openSupplyRequest(s.stock.filter((i) => i.to_order > 0).map((i) => ({
    item: i.item, quantity: i.to_order, unit: i.unit,
    why: `${plural(i.waiting_requests, "request")} waiting`,
  }))));
  main.querySelectorAll("[data-why]").forEach((el) => el.addEventListener("click", (e) => {
    e.stopPropagation();
    openWhy(el.dataset.why);
  }));
}

// ---------- What if more arrives? ----------
async function setupWhatIf(main, s) {
  const itemSel = main.querySelector("#wi-item"), whSel = main.querySelector("#wi-wh");
  const range = main.querySelector("#wi-range"), qtyOut = main.querySelector("#wi-qty"), go = main.querySelector("#wi-go");
  if (!itemSel || !s.stock.length) { main.querySelector("#whatif")?.remove(); return; }
  const { warehouses } = await api("/api/shelters");
  whSel.innerHTML = warehouses.map((w) => `<option value="${esc(w.id)}">${esc(w.name)}</option>`).join("");
  const crit0 = s.kpis.critical_fulfilled, critT = s.kpis.critical_total, wait0 = s.kpis.waiting;
  const setRange = () => {
    const opt = itemSel.selectedOptions[0];
    const short = Number(opt.dataset.short || 0);
    range.max = String(Math.max(100, Math.ceil((short * 1.5) / 10) * 10));
    range.value = String(short || Math.round(Number(range.max) / 4 / 10) * 10);
  };
  const unitLabel = () => {
    const opt = itemSel.selectedOptions[0];
    const unit = opt.dataset.unit, item = opt.value.toLowerCase();
    return !unit || unit === "units" || item.includes(unit) ? item : `${unit} of ${item}`;
  };
  const update = debounce(async () => {
    const q = Number(range.value);
    qtyOut.textContent = `${n(q)} ${unitLabel()}`;
    if (!q) {
      main.querySelector("#wi-crit").innerHTML = `${crit0}<span class="from">/${critT}</span>`;
      main.querySelector("#wi-wait").textContent = wait0;
      main.querySelector("#wi-served").textContent = "0";
      go.disabled = true; return;
    }
    try {
      const p = await api(`/api/inventory/restock/preview?${new URLSearchParams({ item: itemSel.value, quantity: q, warehouse_id: whSel.value })}`);
      const c = main.querySelector("#wi-crit"), w = main.querySelector("#wi-wait");
      c.innerHTML = p.critical_covered_after !== crit0 ? `<span class="from">${crit0} →</span> ${p.critical_covered_after}<span class="from">/${critT}</span>` : `${crit0}<span class="from">/${critT}</span>`;
      c.className = p.critical_covered_after > crit0 ? "up" : "";
      w.innerHTML = p.waiting_after !== wait0 ? `<span class="from">${wait0} →</span> ${p.waiting_after}` : String(wait0);
      w.className = p.waiting_after < wait0 ? "up" : "";
      main.querySelector("#wi-served").textContent = p.requests;
      go.disabled = false;
    } catch { /* preview is best-effort */ }
  }, 60);
  setRange(); update();
  itemSel.onchange = () => { whatIfItem = itemSel.value; setRange(); update(); };
  whSel.onchange = update;
  range.oninput = update;
  go.onclick = () => openSupplyRequest([{ item: itemSel.value, quantity: Number(range.value), unit: itemSel.selectedOptions[0].dataset.unit }]);
  main.querySelector("#wi-arrived").onclick = () => openRestock({ item: itemSel.value, quantity: Number(range.value) || "" });
}
