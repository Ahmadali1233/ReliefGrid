// Small helpers shared by every screen: API calls, formatting, icons, toasts, drawers and dialogs.


export async function api(path, { method = "GET", body, form } = {}) {
  const opts = { method, headers: {} };
  if (form) opts.body = form;
  else if (body !== undefined) {
    opts.body = JSON.stringify(body);
    opts.headers["Content-Type"] = "application/json";
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch {
    throw new Error("Can't reach the ReliefGrid server. Is it still running?");
  }
  const type = res.headers.get("content-type") || "";
  const data = type.includes("json") ? await res.json() : await res.text();
  if (res.status === 404 && path.startsWith("/api/") && !(data && data.error)) {
    throw new Error("The server running is an older version of ReliefGrid. Close its window (or press Ctrl+C there) and run: python run.py");
  }
  if (!res.ok) throw new Error((data && data.error) || `Something went wrong (${res.status}).`);
  return data;
}

const HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]);
export const n = (v) => Number(v || 0).toLocaleString("en-US");
export const plural = (count, word, many = word + "s") => `${n(count)} ${count === 1 ? word : many}`;
export const title = (s) => (s ? s[0].toUpperCase() + s.slice(1) : "");
export const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0);

export function timeLabel(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const today = new Date();
  const hm = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return hm;
  return `${d.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}, ${hm}`;
}

export function debounce(fn, ms = 250) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

const svg = (paths, size = 18, extra = "") =>
  `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${paths}</svg>`;

export const icon = {
  check: (s) => svg('<path d="M5 12l5 5 9-10"/>', s),
  x: (s) => svg('<path d="M6 6l12 12M18 6L6 18"/>', s),
  box: (s) => svg('<path d="M3 7l9-4 9 4-9 4-9-4z"/><path d="M3 7v10l9 4 9-4V7"/><path d="M12 11v10"/>', s),
  download: (s) => svg('<path d="M12 4v11"/><path d="M7 10l5 5 5-5"/><path d="M5 20h14"/>', s),
  upload: (s) => svg('<path d="M12 16V4"/><path d="M7 9l5-5 5 5"/><path d="M5 20h14"/>', s),
  plus: (s) => svg('<path d="M12 5v14M5 12h14"/>', s),
  search: (s) => svg('<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>', s),
  undo: (s) => svg('<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>', s),
  scale: (s) => svg('<path d="M12 3v18"/><path d="M7 21h10"/><path d="M5 7h14"/><path d="M5 7l-3 7a3 3 0 0 0 6 0z"/><path d="M19 7l-3 7a3 3 0 0 0 6 0z"/>', s),
  phone: (s) => svg('<rect x="6" y="2" width="12" height="20" rx="3"/><path d="M11 18h2"/>', s),
  users: (s) => svg('<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7"/><path d="M18 14a6.5 6.5 0 0 1 3.5 6"/>', s),
  chat: (s) => svg('<path d="M20 11.5a8 8 0 0 1-11.8 7L4 20l1.5-4.1A8 8 0 1 1 20 11.5z"/><path d="M9 10.5c.5 1.8 2 3.3 3.8 3.8l1.2-1.1 1.8.8-.4 1.6c-3.4.3-7-3.3-6.7-6.7l1.6-.4.8 1.8z"/>', s),
  mail: (s) => svg('<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M3.5 7l8.5 6 8.5-6"/>', s),
  info: (s) => svg('<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><path d="M12 7.5h.01"/>', s),
  alert: (s) => svg('<path d="M12 3l10 18H2L12 3z"/><path d="M12 10v5"/><path d="M12 18h.01"/>', s),
  truck: (s) => svg('<path d="M3 6h11v10H3z"/><path d="M14 10h4l3 3v3h-7"/><circle cx="7" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>', s),
  pin: (s) => svg('<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/>', s),
  file: (s) => svg('<path d="M14 3H6v18h12V7z"/><path d="M14 3v4h4"/>', s),
  sliders: (s) => svg('<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>', s),
  bolt: (s) => svg('<path d="M13 3L4 14h7l-1 7 9-11h-7z"/>', s),
  shield: (s) => svg('<path d="M12 3l8 3v6c0 4.5-3.4 8.4-8 9-4.6-.6-8-4.5-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>', s),
  copy: (s) => svg('<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M4 16V6a2 2 0 0 1 2-2h10"/>', s),
};

export const urgencyTag = (u) => `<span class="urg"><span class="dot ${esc(u)}"></span>${esc(title(u))}</span>`;
// "Allocated" = stock reserved for the shelter. Delivery is tracked separately on the Dispatch screen.
const STATUS_TEXT = { fulfilled: "Allocated", partial: "Part allocated", unfilled: "Waiting for stock", cancelled: "Cancelled" };
export const statusBadge = (s) => `<span class="badge ${esc(s)}">${STATUS_TEXT[s] || esc(title(s))}</span>`;

export function gotCell(r) {
  const p = pct(r.allocated, r.quantity);
  const cls = r.status === "partial" ? "partial" : "";
  const delivered = r.delivered != null && r.allocated
    ? `<span class="sub" style="text-align:right">${r.delivered >= r.allocated ? "all delivered" : r.dispatched > r.delivered ? `${n(r.dispatched - r.delivered)} on the way` : r.delivered ? `${n(r.delivered)} delivered` : "in warehouse"}</span>` : "";
  return `<div class="got"><span class="num">${n(r.allocated)} of ${n(r.quantity)}${delivered}</span>
    <span class="mini-bar ${cls}" aria-hidden="true"><span style="width:${r.status === "cancelled" ? 0 : p}%"></span></span></div>`;
}

// ---------- Toasts ----------
export function toast(message, { action, onAction, error = false, ms = 6000 } = {}) {
  const box = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = "toast" + (error ? " error" : "");
  el.setAttribute("role", error ? "alert" : "status");
  el.innerHTML = `<span aria-hidden="true">${error ? icon.alert(18) : icon.check(18)}</span><span class="msg">${esc(message)}</span>`;
  if (action) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = action;
    b.onclick = () => { el.remove(); onAction?.(); };
    el.appendChild(b);
  }
  box.appendChild(el);
  while (box.children.length > 3) box.firstElementChild.remove();
  setTimeout(() => el.remove(), ms);
}
export const toastError = (e) => toast(e.message || String(e), { error: true, ms: 8000 });

// ---------- Drawer and modal ----------
let current = null;

export function closeOverlay() {
  if (!current) return;
  const { el, scrim, returnFocus } = current;
  el.classList.remove("show");
  scrim.classList.remove("show");
  setTimeout(() => { el.remove(); scrim.remove(); }, 250);
  current = null;
  returnFocus?.focus?.();
}

function openOverlay(kind, innerHTML) {
  closeOverlay();
  const root = document.getElementById("overlay-root");
  const scrim = document.createElement("div");
  scrim.className = "scrim";
  const el = document.createElement("div");
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-modal", "true");
  if (kind === "drawer") {
    el.className = "drawer";
    el.innerHTML = innerHTML;
  } else {
    el.className = "modal";
    el.innerHTML = `<div class="modal-box">${innerHTML}</div>`;
    el.addEventListener("click", (e) => { if (e.target === el) closeOverlay(); });
  }
  scrim.onclick = closeOverlay;
  root.append(scrim, el);
  current = { el, scrim, returnFocus: document.activeElement };
  requestAnimationFrame(() => { scrim.classList.add("show"); el.classList.add("show"); });
  el.querySelectorAll("[data-close]").forEach((b) => (b.onclick = closeOverlay));
  setTimeout(() => (el.querySelector("[autofocus]") || el.querySelector("button, input, select, a"))?.focus(), 60);
  return el;
}

export const openDrawer = (html) => openOverlay("drawer", html);
export const openModal = (html) => openOverlay("modal", html);
export const closeButton = `<button class="close" type="button" data-close aria-label="Close">${icon.x(16)}</button>`;

document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeOverlay(); });

// Animate a number from 0 when it first appears (respects reduced motion).
export function countUp(root) {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  root.querySelectorAll("[data-count]").forEach((el) => {
    const target = Number(el.dataset.count);
    if (reduce || !target) { el.textContent = n(target); return; }
    const start = performance.now();
    const step = (t) => {
      const k = Math.min((t - start) / 700, 1);
      el.textContent = n(Math.round(target * (1 - Math.pow(1 - k, 3))));
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

// ---------- Highlight search matches (like Ctrl+F) ----------
// Wraps every match of `query` inside `root`'s text in <mark class="hit">, skipping buttons' icons and inputs.
export function highlight(root, query) {
  const q = (query || "").trim();
  if (!root || !q) return 0;
  const needle = q.toLowerCase();
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => (!node.nodeValue.trim() || node.parentElement.closest("mark, script, style, textarea, input, select, .sr-only, svg")
      ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  let count = 0;
  for (const node of nodes) {
    const text = node.nodeValue, lower = text.toLowerCase();
    let i = lower.indexOf(needle);
    if (i < 0) continue;
    const frag = document.createDocumentFragment();
    let last = 0;
    while (i >= 0) {
      frag.append(text.slice(last, i));
      const m = document.createElement("mark");
      m.className = "hit";
      m.textContent = text.slice(i, i + needle.length);
      frag.append(m);
      count += 1;
      last = i + needle.length;
      i = lower.indexOf(needle, last);
    }
    frag.append(text.slice(last));
    node.replaceWith(frag);
  }
  return count;
}

// ---------- Dropdown menu (replaces the browser's native <select> for filters) ----------
// selectMenu({ label: "Type", options: [[value, label, count?]], value, onChange, allLabel }) -> <div> to insert.
let openMenu = null;
function closeOpenMenu() { if (openMenu) { openMenu(); openMenu = null; } }
document.addEventListener("click", (e) => { if (openMenu && !e.target.closest(".dd")) closeOpenMenu(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && openMenu) { e.stopPropagation(); closeOpenMenu(); } }, true);

export function selectMenu({ label, options, value = "", onChange, allLabel = "All" }) {
  const wrap = document.createElement("div");
  wrap.className = "dd";
  const all = [["", allLabel], ...options];
  let current = value ?? "";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "dd-btn";
  btn.setAttribute("aria-haspopup", "listbox");
  btn.setAttribute("aria-expanded", "false");
  const paint = () => {
    const opt = all.find(([v]) => String(v) === String(current)) || all[0];
    btn.classList.toggle("set", current !== "");
    btn.innerHTML = `<span class="dd-label">${esc(label)}</span><span class="dd-value">${esc(opt[1])}</span>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>`;
    btn.setAttribute("aria-label", `${label}: ${opt[1]}`);
  };
  paint();
  wrap.append(btn);
  const open = () => {
    closeOpenMenu();
    const list = document.createElement("ul");
    list.className = "dd-list";
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-label", label);
    list.innerHTML = all.map(([v, l, c], i) => `<li role="option" tabindex="-1" data-i="${i}" aria-selected="${String(v) === String(current)}">
        <span class="dd-check" aria-hidden="true">${String(v) === String(current) ? icon.check(15) : ""}</span>
        <span class="dd-text">${esc(l)}</span>${c != null ? `<span class="dd-count">${esc(n(c))}</span>` : ""}</li>`).join("");
    wrap.append(list);
    // Keep the list on screen: open upwards or to the left when there's no room.
    const r = list.getBoundingClientRect();
    if (r.right > window.innerWidth - 8) list.classList.add("right");
    if (r.bottom > window.innerHeight - 8 && btn.getBoundingClientRect().top > r.height + 16) list.classList.add("up");
    btn.setAttribute("aria-expanded", "true");
    const items = [...list.children];
    const pick = (i) => {
      current = all[i][0];
      paint();
      closeOpenMenu();
      btn.focus();
      onChange?.(current);
    };
    items.forEach((li) => li.addEventListener("click", () => pick(Number(li.dataset.i))));
    list.addEventListener("keydown", (e) => {
      const at = items.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { e.preventDefault(); items[(at + 1) % items.length].focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); items[(at - 1 + items.length) % items.length].focus(); }
      else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (at >= 0) pick(at); }
      else if (e.key === "Tab") closeOpenMenu();
    });
    (items.find((li) => li.getAttribute("aria-selected") === "true") || items[0]).focus();
    openMenu = () => { list.remove(); btn.setAttribute("aria-expanded", "false"); };
  };
  btn.addEventListener("click", (e) => { e.stopPropagation(); if (btn.getAttribute("aria-expanded") === "true") closeOpenMenu(); else open(); });
  btn.addEventListener("keydown", (e) => { if (e.key === "ArrowDown") { e.preventDefault(); open(); } });
  wrap.setValue = (v) => { current = v ?? ""; paint(); };
  return wrap;
}
