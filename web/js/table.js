// One table component for every list: search, filters, sortable columns, a count, and an empty state.
// Filter and sort choices are remembered per table while the app is open.
import { debounce, esc, highlight, selectMenu } from "./ui.js";

const memory = new Map();

/**
 * dataTable(container, {
 *   id: "inventory",                         // remembers search/filters/sort for this table
 *   rows: [...],
 *   columns: [{ key, label, align: "r", sort: (row) => value | false, render: (row) => html }],
 *   search: { placeholder, text: (row) => "searchable text" },
 *   filters: [{ key, label, options: [[value, label], ...], test: (row, value) => bool }],
 *   sort: { key, dir: 1 | -1 },              // initial sort
 *   rowAttrs: (row) => 'data-id="..." class="clickable"',
 *   onRow: (row, event) => {},               // click / Enter on a row
 *   empty: "No items match.",
 *   noun: ["item", "items"],
 * })
 */
export function dataTable(container, opts) {
  const st = memory.get(opts.id) || { q: "", filters: {}, sort: opts.sort?.key ?? null, dir: opts.sort?.dir ?? 1 };
  memory.set(opts.id, st);
  const cols = opts.columns;
  const noun = opts.noun || ["row", "rows"];

  container.innerHTML = `<div class="tbl-tools">
      ${opts.search ? `<label class="tbl-search"><span class="sr-only">Search</span>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>
        <input class="input" type="search" placeholder="${esc(opts.search.placeholder || "Search")}" value="${esc(st.q)}"></label>` : ""}
      <span class="tbl-filters"></span>
      <span class="tbl-count" aria-live="polite"></span>
      <button class="btn link tbl-clear" type="button" hidden>Clear</button>
    </div>
    <div class="table-wrap"><table class="t"><thead><tr></tr></thead><tbody></tbody></table></div>`;

  const thead = container.querySelector("thead tr");
  const tbody = container.querySelector("tbody");
  const countEl = container.querySelector(".tbl-count");
  const clearBtn = container.querySelector(".tbl-clear");

  function visibleRows() {
    const q = st.q.trim().toLowerCase();
    let list = opts.rows.filter((r) => {
      if (q && !String(opts.search.text(r)).toLowerCase().includes(q)) return false;
      for (const f of opts.filters || []) {
        const v = st.filters[f.key];
        if (v && !f.test(r, v)) return false;
      }
      return true;
    });
    const col = cols.find((c) => c.key === st.sort);
    if (col && col.sort !== false) {
      const get = col.sort || ((r) => r[col.key]);
      list = [...list].sort((a, b) => {
        const x = get(a), y = get(b);
        if (x == null && y == null) return 0;
        if (x == null) return 1;
        if (y == null) return -1;
        return (typeof x === "string" ? x.localeCompare(y) : x - y) * st.dir;
      });
    }
    return list;
  }

  function draw() {
    thead.innerHTML = cols.map((c) => {
      const sortable = c.sort !== false && c.label;
      const active = st.sort === c.key;
      const label = c.label || `<span class="sr-only">${esc(c.srLabel || "Actions")}</span>`;
      return `<th class="${c.align === "r" ? "r" : ""}" ${active ? `aria-sort="${st.dir > 0 ? "ascending" : "descending"}"` : ""}>${sortable
        ? `<button class="sort" type="button" data-sort="${esc(c.key)}" ${active ? 'aria-pressed="true"' : ""}>${esc(c.label)}<span aria-hidden="true">${active ? (st.dir > 0 ? " ↑" : " ↓") : " ↕"}</span></button>`
        : label}</th>`;
    }).join("");
    const list = visibleRows();
    tbody.innerHTML = list.length
      ? list.map((r, i) => `<tr ${opts.rowAttrs ? opts.rowAttrs(r) : ""} data-row="${i}">${cols.map((c) =>
          `<td class="${c.align === "r" ? "r" : ""} ${c.className || ""}">${c.render ? c.render(r) : esc(r[c.key] ?? "")}</td>`).join("")}</tr>`).join("")
      : `<tr><td colspan="${cols.length}"><div class="empty"><strong>${esc(opts.empty || "Nothing matches.")}</strong>${opts.rows.length ? "Try clearing the search or filters." : ""}</div></td></tr>`;
    const filtered = st.q.trim() || Object.values(st.filters).some(Boolean);
    countEl.textContent = filtered ? `${list.length} of ${opts.rows.length} ${opts.rows.length === 1 ? noun[0] : noun[1]}` : `${opts.rows.length} ${opts.rows.length === 1 ? noun[0] : noun[1]}`;
    clearBtn.hidden = !filtered;
    thead.querySelectorAll("[data-sort]").forEach((b) => (b.onclick = () => {
      if (st.sort === b.dataset.sort) st.dir = -st.dir;
      else { st.sort = b.dataset.sort; st.dir = cols.find((c) => c.key === b.dataset.sort)?.defaultDir || 1; }
      draw();
    }));
    if (opts.onRow) {
      tbody.querySelectorAll("tr[data-row]").forEach((tr) => {
        const row = list[Number(tr.dataset.row)];
        tr.addEventListener("click", (e) => { if (!e.target.closest("a, button, input, select")) opts.onRow(row, e); });
        tr.addEventListener("keydown", (e) => { if ((e.key === "Enter" || e.key === " ") && e.target === tr) { e.preventDefault(); opts.onRow(row, e); } });
      });
    }
    if (st.q.trim()) highlight(tbody, st.q);
    opts.afterDraw?.(tbody, list);
  }

  container.querySelector(".tbl-search input")?.addEventListener("input", debounce((e) => { st.q = e.target.value; draw(); }, 120));
  const menus = (opts.filters || []).map((f) => {
    const m = selectMenu({
      label: f.label, value: st.filters[f.key] || "",
      options: f.options.map(([v, l]) => [String(v), l, opts.rows.filter((r) => f.test(r, String(v))).length]),
      onChange: (v) => { st.filters[f.key] = v; draw(); },
    });
    container.querySelector(".tbl-filters").append(m);
    return m;
  });
  clearBtn.onclick = () => {
    st.q = ""; st.filters = {};
    container.querySelector(".tbl-search input") && (container.querySelector(".tbl-search input").value = "");
    menus.forEach((m) => m.setValue(""));
    draw();
  };
  draw();
}
