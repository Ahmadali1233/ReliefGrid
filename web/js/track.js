// Public tracking page: anyone on the hub's network can check a waybill or a request, like a parcel.
// Read-only. Confirming a pick-up or delivery needs the QR on the printed waybill.
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const num = (x) => Number(x).toLocaleString("en-US");
const when = (iso) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }); };
const tick = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
const main = document.getElementById("main");
const form = document.getElementById("tf");
const input = document.getElementById("code");

async function track(code) {
  code = code.trim().toUpperCase();
  if (!code) return;
  input.value = code;
  if (location.hash.slice(1) !== code) history.replaceState(null, "", `#${encodeURIComponent(code)}`);
  main.innerHTML = `<section class="card"><p class="hint" style="margin:0">Looking up ${esc(code)}…</p></section>`;
  let t;
  try {
    const res = await fetch(`/api/track/${encodeURIComponent(code)}`);
    t = await res.json();
    if (!res.ok) throw new Error(t.error || "Couldn't look that up.");
  } catch (e) {
    main.innerHTML = `<div class="msg bad">${esc(e.message === "Failed to fetch" ? "Can't reach the hub. Check you're on the same Wi-Fi." : e.message)}</div>`;
    return;
  }
  const items = t.type === "waybill"
    ? `<ul class="items">${t.items.map((i) => `<li><span class="name">${esc(i.item)}</span><span class="qty">${num(i.quantity)} <small style="font-size:13px;font-weight:600;color:var(--muted)">${esc(i.unit || "")}</small></span></li>`).join("")}
       ${t.lost.map((l) => `<li><span class="name" style="color:#B3330F">${esc(l.item)} · missing</span><span class="qty" style="color:#B3330F">${num(l.quantity)}</span></li>`).join("")}</ul>`
    : t.shipments.length ? `<ul class="items">${t.shipments.map((s) => `<li><a class="name" href="#${encodeURIComponent(s.waybill)}">${esc(s.waybill)}<small>${esc({ loading: "being loaded", on_the_way: "on the way", delivered: `signed by ${s.received_by || "?"}` }[s.status])}</small></a><span class="qty">${num(s.quantity)}</span></li>`).join("")}</ul>` : "";
  const sub = t.type === "waybill"
    ? `${esc(t.from.name)} → ${esc(t.to.name)}`
    : `${esc(t.shelter.name)} · ${num(t.quantity)} ${esc(t.item.toLowerCase())} · ${esc(t.urgency)}`;
  main.innerHTML = `<section class="card">
      <span class="chip ${t.type === "waybill" ? t.status : ""}">${esc(t.number)}</span>
      <p class="headline" style="margin-top:10px">${esc(t.headline)}</p><p class="sub-line">${sub}</p>
      <ol class="tl">${t.steps.map((s) => `<li class="${s.done ? "done" : ""}"><span class="d">${s.done ? tick : ""}</span>
        <div><strong>${esc(s.label)}</strong>${s.done && s.at ? `<time>${when(s.at)}</time>` : ""}${s.detail ? `<p>${esc(s.detail)}</p>` : ""}</div></li>`).join("")}</ol>
    </section>
    ${items ? `<section class="card">${items}</section>` : ""}`;
}

form.onsubmit = (e) => { e.preventDefault(); track(input.value); };
window.addEventListener("hashchange", () => track(decodeURIComponent(location.hash.slice(1))));
if (location.hash.length > 1) track(decodeURIComponent(location.hash.slice(1)));
