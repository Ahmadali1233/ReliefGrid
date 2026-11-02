// Night shift mode, sitrep and Quick find (Ctrl+K).
import { openTrack, openWhy } from "./shared.js";
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

// ---------- Quick find (Ctrl+K or /) ----------
// Plain search over shelters, requests, items and warehouses. It never guesses or acts on your behalf:
// it finds things and takes you to them.
const TYPE_ICON = { shelter: icon.pin, request: icon.file, item: icon.box, warehouse: icon.truck, waybill: icon.truck, order: icon.file };
const TYPE_LABEL = { shelter: "Shelter", request: "Request", item: "Item", warehouse: "Warehouse", waybill: "Waybill", order: "Supply order" };

export function openCommand() {
  const el = openModal(`<div class="cmd-input">${icon.search(20)}
      <label class="sr-only" for="qf">Find a shelter, request or item</label>
      <input id="qf" autocomplete="off" spellcheck="false" placeholder="Waybill, request ID, shelter or item…" autofocus
        role="combobox" aria-expanded="true" aria-controls="qf-list" aria-autocomplete="list">
      <span class="kbd" style="border-color:var(--line);color:var(--muted)">Esc</span></div>
    <div class="cmd-result"><ul class="cmd-examples" id="qf-list" role="listbox"></ul>
      <p class="cmd-hint">↑ ↓ to move · Enter to open</p></div>`);
  el.classList.add("palette");
  const input = el.querySelector("#qf"), list = el.querySelector("#qf-list");
  let results = [], active = 0, seq = 0;
  const open = (r) => {
    closeOverlay();
    if (r.track) openTrack(r.track);
    else if (r.why) openWhy(r.why);
    else location.hash = `#/${r.route}`;
  };
  const draw = () => {
    if (!input.value.trim()) {
      list.innerHTML = `<li style="padding:8px 10px;color:var(--muted)">Type a waybill (WB-…), a request (REQ-…), a shelter or an item.</li>`;
      return;
    }
    list.innerHTML = results.length ? results.map((r, i) => `<li><button type="button" role="option" aria-selected="${i === active}" data-i="${i}"
        style="${i === active ? "background:var(--line-soft);color:var(--ink)" : ""}">${(TYPE_ICON[r.type] || icon.search)(16)}
        <span style="flex:1;min-width:0"><strong style="font-weight:600">${esc(r.label)}</strong>
          <span style="display:block;font-size:13px;color:var(--muted)">${esc(r.detail)}</span></span>
        <span class="badge none">${TYPE_LABEL[r.type]}</span></button></li>`).join("")
      : `<li style="padding:8px 10px;color:var(--muted)">Nothing matches "${esc(input.value.trim())}".</li>`;
    list.querySelectorAll("[data-i]").forEach((b) => (b.onclick = () => open(results[Number(b.dataset.i)])));
    if (results.length) highlight(list, input.value);
  };
  const search = debounce(async () => {
    const mine = ++seq;
    if (!input.value.trim()) { results = []; draw(); return; }
    try {
      const r = await api(`/api/search?q=${encodeURIComponent(input.value.trim())}`);
      if (mine === seq) { results = r.results; active = 0; draw(); }
    } catch (e) { toastError(e); }
  }, 100);
  input.addEventListener("input", search);
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(active + 1, results.length - 1); draw(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); draw(); }
    else if (e.key === "Enter" && results[active]) { e.preventDefault(); open(results[active]); }
  });
  draw();
}
