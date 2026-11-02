// Import: drop in a CSV, JSON or XML file. Unknown column names get matched with you, bad rows are listed, good rows go in.
import { act } from "../shared.js";
import { api, esc, icon, n, plural, toastError } from "../ui.js";

const st = { file: null, preview: null, entity: null, mapping: null, result: null, busy: false };
const SAMPLES = [
  ["messy_requests.csv", "Messy CSV", "odd column names, bad rows"],
  ["requests_day2.xml", "Day-2 XML", "new format"],
  ["delivery_truck.json", "Delivery JSON", "stock arriving"],
];

async function runPreview(main) {
  const form = new FormData();
  form.append("file", st.file);
  if (st.entity) form.append("entity", st.entity);
  if (st.mapping) form.append("mapping", JSON.stringify(st.mapping));
  st.busy = true;
  try {
    st.preview = await api("/api/import/preview", { method: "POST", form });
    st.entity = st.preview.entity;
    st.mapping = st.preview.mapping;
  } catch (e) {
    toastError(e);
    st.file = null; st.preview = null;
  }
  st.busy = false;
  draw(main);
}

function pickFile(main, file) {
  if (!file) return;
  if (file.size > 5 * 1024 * 1024) { toastError(new Error("That file is over 5 MB. Split it into smaller files.")); return; }
  Object.assign(st, { file, preview: null, entity: null, mapping: null, result: null });
  runPreview(main);
}

function skippedCsv(issues) {
  const lines = ["row,problem", ...issues.map((i) => `${i.row},"${String(i.message).replace(/"/g, '""')}"`)];
  return URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
}

function draw(main) {
  const p = st.preview;
  const step = st.result ? 3 : p ? 2 : 1;
  const stepper = `<ol class="stepper" aria-label="Import steps">${["Choose file", "Match columns", "Check and import"].map((s, i) =>
    `<li class="${i + 1 < step || st.result ? "done" : i + 1 === step ? "now" : ""}" ${i + 1 === step ? 'aria-current="step"' : ""}><span class="n">${i + 1 < step || st.result ? icon.check(13) : i + 1}</span>${s}</li>`).join("")}</ol>`;

  let body;
  if (st.result) {
    const r = st.result;
    body = `<section class="card fade-in" style="text-align:center;padding:40px 24px">
      <div style="width:56px;height:56px;border-radius:50%;background:var(--good-soft);color:var(--good);display:inline-flex;align-items:center;justify-content:center">${icon.check(28)}</div>
      <h2 style="font-size:26px;margin:14px 0 6px">Imported ${plural(r.imported, "row")}</h2>
      <p style="color:var(--muted);margin:0">${r.skipped.length ? `${plural(r.skipped.length, "row")} skipped. ` : ""}${r.requests_served ? `${plural(r.requests_served, "request")} served straight away.` : "Allocation re-ran; nobody new could be served."}</p>
      <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-top:22px">
        <a class="btn primary" href="#/${r.entity === "inventory" ? "inventory" : r.entity === "requests" ? "requests" : "shelters"}">See the ${r.entity === "inventory" ? "stock" : r.entity}</a>
        <button class="btn" type="button" data-reset>Import another file</button></div></section>`;
  } else if (!p) {
    body = `<label class="drop" id="drop" tabindex="0">
        <input type="file" id="file-input" accept=".csv,.tsv,.txt,.json,.xml" class="sr-only">
        <span style="color:var(--teal)">${icon.upload(34)}</span>
        <strong>${st.busy ? "Reading the file…" : "Drop a file here, or click to choose"}</strong>
        <p>CSV, TSV, JSON or XML · requests, stock deliveries, shelters or warehouses · up to 5 MB</p>
      </label>
      <div class="sample-files"><span style="color:var(--muted);font-size:14px;align-self:center">Or try a sample:</span>
        ${SAMPLES.map(([f, l, d]) => `<button class="btn small" type="button" data-sample="${f}">${icon.file(15)}${l}<span style="color:var(--muted);font-weight:500">· ${d}</span></button>`).join("")}</div>`;
  } else {
    const requiredMissing = p.mapping_error;
    const fieldOptions = (col) => `<option value="">Skip this column</option>${p.fields.map((f) =>
      `<option value="${f.id}" ${st.mapping[col] === f.id ? "selected" : ""}>${esc(f.label)}${f.required ? "" : " (optional)"}</option>`).join("")}`;
    const examples = (col) => p.sample.map((r) => r[col]).filter((v) => v !== "").slice(0, 3).map((v) => esc(v)).join(" · ");
    body = `<div class="row">
      <section class="card grow">
        <div class="card-head" style="align-items:center"><h2>${esc(p.filename)} has ${plural(p.columns.length, "column")}</h2>
          <label style="display:flex;align-items:center;gap:8px;font-size:14px;color:var(--muted)">Contains
            <select class="input" id="entity" style="width:auto;min-height:38px">${Object.entries(p.entities).map(([k, l]) =>
              `<option value="${k}" ${k === p.entity ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label></div>
        <p class="hint" style="margin-top:-6px">${p.remembered ? "Matched the same way as last time." : requiredMissing ? "Some columns need you. Pick what each one means." : "Matched automatically. Change anything that looks wrong."}</p>
        ${p.columns.map((c) => `<div class="map-row ${!st.mapping[c] && requiredMissing ? "needs" : ""}">
          <code title="${esc(c)}">${esc(c)}</code><span aria-hidden="true" style="color:var(--faint)">→</span>
          <label><span class="sr-only">What is ${esc(c)}?</span><select class="input" data-col="${esc(c)}">${fieldOptions(c)}</select></label>
          ${examples(c) ? `<span class="ex">e.g. ${examples(c)}</span>` : ""}</div>`).join("")}
      </section>
      <aside class="card side">
        <h2>Check</h2>
        ${requiredMissing ? `<p class="form-note bad" style="margin:12px 0">${icon.alert(16)} ${esc(requiredMissing)}</p>` : `
          <div class="big-number">${n(p.ready)} <small>of ${n(p.row_count)} rows ready</small></div>
          <p style="margin:4px 0 16px;color:var(--muted)">${p.issues.length ? `${plural(p.issues.length, "row")} will be skipped. Nothing else changes.` : "Every row looks good."}</p>`}
        ${p.issues.length || p.warnings.length ? `<ul class="issues">
          ${p.issues.map((i) => `<li><strong>Row ${i.row}</strong> · ${esc(i.message)}</li>`).join("")}
          ${p.warnings.map((w) => `<li class="warn"><strong>Row ${w.row}</strong> · ${esc(w.message)}</li>`).join("")}</ul>` : ""}
        <div style="display:flex;flex-wrap:wrap;gap:10px;margin-top:20px">
          <button class="btn primary" type="button" data-commit ${requiredMissing || !p.ready ? "disabled" : ""}>${icon.upload(17)}Import ${plural(p.ready, "row")}</button>
          ${p.issues.length ? `<a class="btn" href="${skippedCsv(p.issues)}" download="skipped-rows.csv">${icon.download(16)}Skipped rows</a>` : ""}
          <button class="btn link" type="button" data-reset style="margin-left:auto">Choose another file</button></div>
      </aside></div>`;
  }

  main.innerHTML = `<div class="page">
    <div class="page-head"><div><h1>Import data</h1><p>New column names are fine. We match them with you, keep the good rows and tell you exactly what's wrong with the rest.</p></div></div>
    ${stepper}${body}</div>`;

  const input = main.querySelector("#file-input");
  const drop = main.querySelector("#drop");
  if (drop) {
    input.onchange = () => pickFile(main, input.files[0]);
    drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
    ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", (e) => pickFile(main, e.dataTransfer.files[0]));
  }
  main.querySelectorAll("[data-sample]").forEach((b) => (b.onclick = async () => {
    try {
      const res = await fetch(`/api/samples/${b.dataset.sample}`);
      pickFile(main, new File([await res.blob()], b.dataset.sample));
    } catch (e) { toastError(e); }
  }));
  main.querySelectorAll("[data-reset]").forEach((b) => (b.onclick = () => {
    Object.assign(st, { file: null, preview: null, entity: null, mapping: null, result: null });
    draw(main);
  }));
  main.querySelector("#entity")?.addEventListener("change", (e) => { st.entity = e.target.value; st.mapping = null; runPreview(main); });
  main.querySelectorAll("[data-col]").forEach((sel) => sel.addEventListener("change", () => {
    const col = sel.dataset.col;
    // One column per field: picking a field elsewhere frees it here.
    for (const k of Object.keys(st.mapping)) if (k !== col && sel.value && st.mapping[k] === sel.value) st.mapping[k] = null;
    st.mapping[col] = sel.value || null;
    runPreview(main);
  }));
  main.querySelector("[data-commit]")?.addEventListener("click", async (e) => {
    e.target.disabled = true;
    const form = new FormData();
    form.append("file", st.file);
    form.append("entity", st.entity);
    form.append("mapping", JSON.stringify(st.mapping));
    try {
      st.result = await act(api("/api/import/commit", { method: "POST", form }),
        (r) => `Imported ${plural(r.imported, "row")} from ${st.file.name}.`);
      draw(main);
    } catch { e.target.disabled = false; }
  });
}

export async function render(main) {
  draw(main);
}
