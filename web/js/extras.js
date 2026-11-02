// Night shift mode, sitrep and the command bar (Ctrl+K).
import { applyCap, openIntegrity, openSupplyRequest, openTrack, openWhy, refresh, undo } from "./shared.js";
import { celebrate } from "./motion.js";
import { api, closeButton, closeOverlay, debounce, esc, icon, n, highlight, openModal, plural, toast, toastError } from "./ui.js";

// ---------- Night shift mode ----------
const THEME_KEY = "reliefgrid-theme";
function storedTheme() { try { return localStorage.getItem(THEME_KEY); } catch { return null; } }
export function applyTheme(theme = storedTheme() || "light") {
  document.documentElement.dataset.theme = theme;
  const btn = document.getElementById("theme-btn");
  if (btn) {
    const dark = theme === "dark";
    btn.innerHTML = dark
      ? `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>`
      : `<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>`;
    btn.insertAdjacentHTML("beforeend", dark ? "Day mode" : "Night shift mode");
    btn.setAttribute("aria-pressed", String(dark));
  }
}
export function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  try { localStorage.setItem(THEME_KEY, next); } catch {}
  applyTheme(next);
  toast(next === "dark" ? "Night shift mode on. Easier on the eyes at 3 a.m." : "Day mode on.");
}

// ---------- Sitrep ----------
export async function openSitrep() {
  const el = openModal(`<div style="display:flex;justify-content:space-between;gap:12px"><div><h2>Situation report</h2>
    <p style="margin:0;color:var(--muted)">Written from live data. Paste it into WhatsApp, email or a radio log.</p></div>${closeButton}</div>
    <div class="sitrep skeleton" style="height:180px"></div>`);
  try {
    const { text } = await api("/api/sitrep");
    el.querySelector(".sitrep").outerHTML = `<div class="sitrep" tabindex="0">${esc(text)}</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;justify-content:flex-end">
        <a class="btn" href="https://wa.me/?text=${encodeURIComponent(text)}" target="_blank" rel="noopener">Open in WhatsApp</a>
        <button class="btn primary" type="button" data-copy autofocus>${icon.copy(17)}Copy</button></div>`;
    el.querySelector("[data-copy]").onclick = async () => {
      try { await navigator.clipboard.writeText(text); toast("Sitrep copied. Paste it anywhere."); closeOverlay(); }
      catch { toast("Couldn't copy automatically. Select the text and copy it.", { error: true }); }
    };
  } catch (e) { toastError(e); }
}

// ---------- Command bar (Ctrl+K or /) ----------
// Type a question or an instruction in plain words. The hub works it out offline (no AI service, no internet):
// questions are answered straight away; changes are shown first and only happen when you press Enter.
const TYPE_ICON = { shelter: icon.pin, request: icon.file, item: icon.box, warehouse: icon.truck, waybill: icon.truck, order: icon.file };
const TYPE_LABEL = { shelter: "Shelter", request: "Request", item: "Item", warehouse: "Warehouse", waybill: "Waybill", order: "Supply order" };

export function openCommand() {
  const el = openModal(`<div class="cmd-input">${icon.search(20)}
      <label class="sr-only" for="qf">Ask a question or tell ReliefGrid what to do</label>
      <input id="qf" autocomplete="off" spellcheck="false" placeholder="Ask or do anything: “Johi Tent City needs 200 water”" autofocus
        role="combobox" aria-expanded="true" aria-controls="qf-out">
      <span class="kbd" style="border-color:var(--line);color:var(--muted)">Esc</span></div>
    <div class="cmd-result" id="qf-out" aria-live="polite"></div>`);
  el.classList.add("palette");
  const input = el.querySelector("#qf"), out = el.querySelector("#qf-out");
  let res = null, active = 0, seq = 0, busy = false, answeredFor = null;

  const go = (r) => {
    closeOverlay();
    if (r.track) openTrack(r.track);
    else if (r.why) openWhy(r.why);
    else if (r.order) openSupplyRequest();
    else location.hash = `#/${r.route || ""}`;
  };
  async function run() {
    if (!res || busy) return;
    if (res.type === "results") { if (res.results[active]) go(res.results[active]); return; }
    if (res.type === "navigate") { closeOverlay(); location.hash = `#/${res.route}`; return; }
    if (res.type === "open") {
      closeOverlay();
      if (res.what === "order") openSupplyRequest(res.prefill || []);
      else if (res.what === "sitrep") openSitrep();
      else if (res.what === "integrity") openIntegrity();
      return;
    }
    if (res.type === "answer" && res.links?.length) { go(res.links[0]); return; }
    if (res.type !== "action") return;
    if (res.kind === "cap") { closeOverlay(); applyCap(res.call.body.max_days_per_shelter); return; }
    if (res.call.path === "/api/undo") { closeOverlay(); undo(); return; }
    busy = true;
    const btn = out.querySelector("[data-run]"); if (btn) btn.disabled = true;
    try {
      const r = await api(res.call.path, { method: res.call.method, body: res.call.body });
      closeOverlay();
      celebrate();
      const msg = r && r.id && r.given != null ? `${r.id} added: ${n(r.given)} of ${n(r.requested)} reserved now.`
        : r && r.requests_served != null ? `${res.done} ${plural(r.requests_served, "waiting request")} served.` : res.done;
      toast(msg, { action: "Undo", onAction: undo });
      refresh();
    } catch (e) { busy = false; if (btn) btn.disabled = false; toastError(e); }
  }

  const linkBtn = (l, i) => `<button class="btn small" type="button" data-link="${i}">${esc(l.label)}</button>`;
  function draw() {
    if (!res) { out.innerHTML = ""; return; }
    if (res.type === "help") {
      out.innerHTML = `<p class="cmd-lead">Ask a question or say what to do, in plain words. Nothing changes until you press Enter.</p>
        <div class="cmd-chips">${res.examples.map((x) => `<button type="button" class="cmd-chip" data-ex="${esc(x)}">${esc(x)}</button>`).join("")}</div>
        <p class="cmd-hint">Works offline. Also finds any waybill, request, shelter or item.</p>`;
    } else if (res.type === "results") {
      out.innerHTML = `<p class="cmd-lead">${esc(res.title)}</p>` + (res.results.length ? `<ul class="cmd-examples" role="listbox">${res.results.map((r, i) => `<li><button type="button" role="option" aria-selected="${i === active}" data-i="${i}"
          style="${i === active ? "background:var(--line-soft);color:var(--ink)" : ""}">${(TYPE_ICON[r.type] || icon.search)(16)}
          <span style="flex:1;min-width:0"><strong style="font-weight:600">${esc(r.label)}</strong>
            <span style="display:block;font-size:13px;color:var(--muted)">${esc(r.detail)}</span></span>
          <span class="badge none">${TYPE_LABEL[r.type]}</span></button></li>`).join("")}</ul><p class="cmd-hint">↑ ↓ to move · Enter to open</p>`
        : `<div class="cmd-chips">${(res.examples || []).map((x) => `<button type="button" class="cmd-chip" data-ex="${esc(x)}">Try: ${esc(x)}</button>`).join("")}</div>`);
      if (res.results.length) highlight(out.querySelector("ul"), input.value);
    } else {
      const isAction = res.type === "action", primary = isAction ? res.confirm
        : res.type === "open" ? "Open" : res.type === "navigate" ? res.title : res.links?.[0]?.label;
      out.innerHTML = `<div class="cmd-card is-${res.type}">
          <span class="eyebrow">${isAction ? "Ready to do" : res.type === "answer" ? "Answer" : "Shortcut"}</span>
          <h3>${esc(res.title)}</h3>
          ${res.lines?.length ? `<ul class="cmd-lines">${res.lines.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>` : ""}
          <div class="cmd-actions">${primary ? `<button class="btn ${isAction ? "primary" : ""}" type="button" data-run>${esc(primary)} <kbd>Enter</kbd></button>` : ""}
            ${(res.links || []).slice(primary && res.type === "answer" ? 1 : 0).map((l, i) => linkBtn(l, i + (primary && res.type === "answer" ? 1 : 0))).join("")}</div>
        </div>${isAction ? `<p class="cmd-hint">Nothing has changed yet. Press Enter to do it, or keep typing to change it.</p>` : ""}`;
    }
    out.querySelectorAll("[data-ex]").forEach((b) => (b.onclick = () => { input.value = b.dataset.ex; input.focus(); ask(); }));
    out.querySelectorAll("[data-i]").forEach((b) => (b.onclick = () => go(res.results[Number(b.dataset.i)])));
    out.querySelectorAll("[data-link]").forEach((b) => (b.onclick = () => go(res.links[Number(b.dataset.link)])));
    out.querySelector("[data-run]")?.addEventListener("click", run);
  }
  async function ask() {
    const mine = ++seq, text = input.value.trim();
    try {
      const r = await api(`/api/ask?q=${encodeURIComponent(text)}`);
      if (mine === seq) { res = r; answeredFor = text; active = 0; busy = false; draw(); }
    } catch (e) { toastError(e); }
  }
  const later = debounce(ask, 160);
  input.addEventListener("input", later);
  input.addEventListener("keydown", async (e) => {
    if (res?.type === "results" && e.key === "ArrowDown") { e.preventDefault(); active = Math.min(active + 1, res.results.length - 1); draw(); }
    else if (res?.type === "results" && e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); draw(); }
    else if (e.key === "Enter") { e.preventDefault(); if (input.value.trim() !== answeredFor) await ask(); run(); }
  });
  ask();
}
