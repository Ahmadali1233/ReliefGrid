// ReliefGrid front end: a tiny hash router. Each screen lives in js/views/ and exports render(main).
import { onRefresh, undo, updateUndoButton } from "./shared.js";
import { closeOverlay, esc, toastError } from "./ui.js";
import { applyTheme, openCommand, toggleTheme } from "./extras.js";
import * as dashboard from "./views/dashboard.js";
import * as requests from "./views/requests.js";
import * as inventory from "./views/inventory.js";
import * as shelters from "./views/shelters.js";
import * as log from "./views/log.js";
import * as importer from "./views/importer.js";
import * as rules from "./views/rules.js";
import * as dispatch from "./views/dispatch.js";

const ROUTES = {
  "": { view: dashboard, title: "Dashboard" },
  requests: { view: requests, title: "Requests" },
  inventory: { view: inventory, title: "Inventory" },
  shelters: { view: shelters, title: "Shelters" },
  log: { view: log, title: "Log" },
  import: { view: importer, title: "Import" },
  rules: { view: rules, title: "Rules" },
  dispatch: { view: dispatch, title: "Dispatch" },
  slips: { view: dispatch, title: "Dispatch" },
};

const main = document.getElementById("main");
const heroSlot = document.getElementById("hero-slot");
let currentKey = null;

function parseHash() {
  const [path, query = ""] = location.hash.replace(/^#\/?/, "").split("?");
  return { key: path.split("/")[0], params: Object.fromEntries(new URLSearchParams(query)) };
}

async function render({ keepScroll = false } = {}) {
  const { key, params } = parseHash();
  const route = ROUTES[key] || ROUTES[""];
  const changed = key !== currentKey;
  currentKey = key;
  document.title = `${route.title} · ReliefGrid`;
  document.querySelectorAll(".nav a, .menu [data-route]").forEach((a) => {
    const target = a.getAttribute("href").replace(/^#\/?/, "");
    a.toggleAttribute("aria-current", target === key);
    if (target === key) a.setAttribute("aria-current", "page");
  });
  if (changed) heroSlot.innerHTML = "";
  const scroll = window.scrollY;
  try {
    await route.view.render(main, { params, heroSlot, firstVisit: changed });
  } catch (e) {
    main.innerHTML = `<div class="page"><div class="card empty"><strong>That didn't load.</strong>${esc(e.message)}</div></div>`;
    toastError(e);
  }
  if (keepScroll) window.scrollTo(0, scroll);
  else if (changed) window.scrollTo(0, 0);
  updateUndoButton();
  markSeen();
}

onRefresh(() => render({ keepScroll: true }));
window.addEventListener("hashchange", () => { closeOverlay(); render(); });
document.getElementById("undo-btn").addEventListener("click", undo);
document.getElementById("cmd-btn").addEventListener("click", openCommand);
document.getElementById("theme-btn").addEventListener("click", () => { toggleTheme(); closeMenu(); });

// ---------- More menu (Import, Rules, Night mode, API docs) ----------
const moreBtn = document.getElementById("more-btn"), moreMenu = document.getElementById("more-menu");
function closeMenu() { moreMenu.hidden = true; moreBtn.setAttribute("aria-expanded", "false"); }
moreBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  const open = moreMenu.hidden;
  moreMenu.hidden = !open;
  moreBtn.setAttribute("aria-expanded", String(open));
  if (open) moreMenu.querySelector("a, button")?.focus();
});
moreMenu.addEventListener("click", (e) => { if (e.target.closest("a")) closeMenu(); });
document.addEventListener("click", (e) => { if (!moreMenu.hidden && !e.target.closest(".menu-wrap")) closeMenu(); });
moreMenu.addEventListener("keydown", (e) => {
  const items = [...moreMenu.querySelectorAll("a, button")];
  const i = items.indexOf(document.activeElement);
  if (e.key === "Escape") { closeMenu(); moreBtn.focus(); }
  if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length].focus(); }
  if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
});

// ---------- Live updates: another coordinator, or a driver's phone, changed something ----------
// The server's change fingerprint is checked every few seconds. If it moved and you're not in the middle of
// typing or a dialog, the screen refreshes in place; otherwise a small "Updated" button waits for you.
let seenVersion = null;
async function markSeen() {
  try { seenVersion = (await (await fetch("/api/changes")).json()).version; } catch { /* offline: try later */ }
}
const busy = () => document.querySelector("#overlay-root > *") ||
  document.activeElement?.matches?.("input:not([type=range]), textarea, select") || !moreMenu.hidden;
async function poll() {
  if (document.hidden) return;
  let v;
  try { v = (await (await fetch("/api/changes")).json()).version; } catch { return; }
  if (seenVersion === null || v === seenVersion) return;
  if (busy()) { showUpdatedPill(); return; }
  seenVersion = v;
  hideUpdatedPill();
  render({ keepScroll: true });
}
function showUpdatedPill() {
  if (document.getElementById("updated-pill")) return;
  const b = document.createElement("button");
  b.id = "updated-pill"; b.type = "button"; b.className = "updated-pill";
  b.textContent = "New activity · refresh";
  b.onclick = () => { hideUpdatedPill(); render({ keepScroll: true }); };
  document.body.appendChild(b);
}
function hideUpdatedPill() { document.getElementById("updated-pill")?.remove(); }
setInterval(poll, 4000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
applyTheme();

// Shortcuts: Ctrl/Cmd+K or / opens the command bar; Ctrl/Cmd+Z undoes (except while typing).
document.addEventListener("keydown", (e) => {
  const typing = e.target.closest("input, textarea, select, [contenteditable]");
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openCommand(); return; }
  if (e.key === "/" && !typing) { e.preventDefault(); openCommand(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !e.shiftKey && !typing) {
    e.preventDefault();
    if (!document.getElementById("undo-btn").disabled) undo();
  }
});

// If the interface is newer than the server (e.g. files updated while an old server kept running), say so plainly.
const API_LEVEL = 7;
fetch("/api/version").then((r) => (r.ok ? r.json() : null)).catch(() => null).then((v) => {
  if (v && v.api_level >= API_LEVEL) return;
  const bar = document.createElement("div");
  bar.setAttribute("role", "alert");
  bar.style.cssText = "background:var(--bad-soft);color:var(--bad-ink);padding:12px 24px;font-weight:600;text-align:center;border-bottom:1px solid var(--line)";
  bar.textContent = v === null
    ? "Can't reach the ReliefGrid server, or an older version is running. Close any old ReliefGrid window and run: python run.py"
    : "An older ReliefGrid server is running. Close its window (Ctrl+C) and run: python run.py";
  document.body.prepend(bar);
});

render();
