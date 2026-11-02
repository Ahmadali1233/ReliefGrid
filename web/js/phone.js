// The phone page a delivery slip's QR code opens (python run.py --phones).
//   Driver:  checks the load and taps "Loaded, truck leaving now"     -> POST /api/handoff/.../pickup
//   Shelter: counts what arrived, notes anything missing, signs        -> POST /api/handoff/.../receive
// Missing or damaged units are recorded as a loss and go straight back in the queue for that shelter.
// The coordinator's screen updates within a few seconds. English, Arabic and Urdu.
import { celebrate } from "./motion.js";

const T = {
  en: {
    title: "Delivery slip", from: "From", to: "To", people: "{n} people",
    to_load: "Waiting to be loaded", on_the_way: "On the way", delivered: "Delivered", nothing: "Nothing to do",
    driver_h: "Driver: check the load", driver_hint: "Make sure every item below is on the truck.",
    driver_name: "Your name or truck", driver_btn: "Loaded: truck leaving now",
    shelter_h: "Shelter: count what arrived", shelter_hint: "Change a number if anything is missing or damaged.",
    sent: "sent {n}", note: "What happened to the missing items?", note_ph: "e.g. 2 cartons crushed",
    receiver: "Your name", receive_btn: "Sign for this delivery",
    done_pickup: "On the way. Drive safely.", done_pickup_sub: "The shelter scans the same code when it arrives.",
    done_receive: "Signed. Thank you, {name}.", lost: "{n} missing recorded. They go back in the queue for this shelter.",
    none_now: "This waybill is complete.", last: "Signed for by {name}, {time}.", track: "Track this waybill", back: "Back",
    bad_link: "This link isn't valid. Scan the QR code on the printed slip again.",
    offline: "Can't reach the hub. Check you're on the same Wi-Fi, then try again.", retry: "Try again",
    need_name: "Enter your name.", need_note: "Say what happened to the missing items.",
  },
  ar: {
    title: "إيصال التسليم", from: "من", to: "إلى", people: "عدد الأشخاص: {n}",
    to_load: "بانتظار التحميل", on_the_way: "في الطريق", delivered: "تم التسليم", nothing: "لا شيء مطلوب",
    driver_h: "السائق: تحقّق من الحمولة", driver_hint: "تأكّد أن كل صنف أدناه موجود على الشاحنة.",
    driver_name: "اسمك أو رقم الشاحنة", driver_btn: "تم التحميل: الشاحنة تغادر الآن",
    shelter_h: "المأوى: عُدّ ما وصل", shelter_hint: "غيّر الرقم إذا كان هناك شيء ناقص أو تالف.",
    sent: "المُرسَل {n}", note: "ماذا حدث للأصناف الناقصة؟", note_ph: "مثال: كرتونتان تالفتان",
    receiver: "اسمك", receive_btn: "وقّع على استلام هذه الشحنة",
    done_pickup: "الشحنة في الطريق. قُد بأمان.", done_pickup_sub: "يمسح المأوى الرمز نفسه عند الوصول.",
    done_receive: "تم التوقيع. شكرًا لك يا {name}.", lost: "تم تسجيل النقص ({n}). سيعود إلى قائمة الانتظار لهذا المأوى.",
    none_now: "اكتملت هذه الشحنة.", last: "وقّع على الاستلام {name}، {time}.", track: "تتبّع هذه الشحنة", back: "رجوع",
    bad_link: "هذا الرابط غير صالح. امسح رمز QR الموجود على الإيصال المطبوع مرة أخرى.",
    offline: "تعذّر الاتصال بالمركز. تأكّد أنك على شبكة الواي فاي نفسها ثم حاول مرة أخرى.", retry: "حاول مرة أخرى",
    need_name: "أدخل اسمك.", need_note: "اذكر ما حدث للأصناف الناقصة.",
  },
  ur: {
    title: "ڈیلیوری سلپ", from: "کہاں سے", to: "کہاں تک", people: "{n} افراد",
    to_load: "لوڈ ہونے کا انتظار", on_the_way: "راستے میں", delivered: "پہنچا دیا گیا", nothing: "کوئی کام نہیں",
    driver_h: "ڈرائیور: سامان چیک کریں", driver_hint: "یقینی بنائیں کہ نیچے دی گئی ہر چیز ٹرک پر موجود ہے۔",
    driver_name: "آپ کا نام یا ٹرک نمبر", driver_btn: "لوڈ ہو گیا: ٹرک روانہ ہو رہا ہے",
    shelter_h: "پناہ گاہ: جو پہنچا اسے گنیں", shelter_hint: "اگر کچھ کم یا خراب ہے تو تعداد بدل دیں۔",
    sent: "بھیجا گیا {n}", note: "کم سامان کے ساتھ کیا ہوا؟", note_ph: "مثلاً 2 کارٹن ٹوٹ گئے",
    receiver: "آپ کا نام", receive_btn: "اس ڈیلیوری پر دستخط کریں",
    done_pickup: "سامان روانہ ہو گیا۔ احتیاط سے چلائیں۔", done_pickup_sub: "پہنچنے پر پناہ گاہ یہی کوڈ اسکین کرے گی۔",
    done_receive: "دستخط ہو گئے۔ شکریہ، {name}۔", lost: "{n} کم درج کر لیے گئے۔ یہ اس پناہ گاہ کے لیے دوبارہ قطار میں شامل ہو گئے ہیں۔",
    none_now: "یہ ڈیلیوری مکمل ہو چکی ہے۔", last: "{name} نے وصولی پر دستخط کیے، {time}۔", track: "اس ڈیلیوری کو ٹریک کریں", back: "واپس",
    bad_link: "یہ لنک درست نہیں۔ پرنٹ شدہ سلپ پر موجود QR کوڈ دوبارہ اسکین کریں۔",
    offline: "مرکز سے رابطہ نہیں ہو سکا۔ یقینی بنائیں کہ آپ اسی وائی فائی پر ہیں، پھر دوبارہ کوشش کریں۔", retry: "دوبارہ کوشش کریں",
    need_name: "اپنا نام درج کریں۔", need_note: "بتائیں کہ کم سامان کے ساتھ کیا ہوا۔",
  },
};

const store = {
  get: (k) => { try { return localStorage.getItem(k) || ""; } catch { return ""; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};
let lang = store.get("reliefgrid-lang") || (navigator.language || "en").slice(0, 2);
if (!T[lang]) lang = "en";
const t = (key, vars = {}) => (T[lang][key] || T.en[key]).replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const num = (x) => Number(x).toLocaleString("en-US");
const when = (iso) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }); };

const [waybill, token] = location.hash.replace(/^#/, "").split("/").map(decodeURIComponent);
const base = `/api/handoff/${encodeURIComponent(waybill || "")}`;
const main = document.getElementById("main");
let data = null, result = null;

async function call(path, body, who) {
  const opts = { method: body ? "POST" : "GET", headers: {} };
  if (body) { opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
  if (who) opts.headers["X-Operator"] = encodeURIComponent(who);
  let res;
  try { res = await fetch(path, opts); } catch { throw Object.assign(new Error(t("offline")), { offline: true }); }
  const out = await res.json().catch(() => ({}));
  if (res.status === 403) throw new Error(t("bad_link"));
  if (!res.ok) throw new Error(out.error || t("offline"));
  return out;
}

async function load() {
  if (!waybill || !token) { showError(t("bad_link")); return; }
  try {
    data = await call(`${base}?t=${encodeURIComponent(token)}`);
    draw();
  } catch (e) { showError(e.message, e.offline); }
}

function showError(message, retry) {
  header();
  main.innerHTML = `<div class="msg bad">${esc(message)}</div>${retry ? `<button class="go secondary" type="button" id="retry">${t("retry")}</button>` : ""}`;
  document.getElementById("retry")?.addEventListener("click", load);
}

function header() {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "en" ? "ltr" : "rtl";
  document.title = `${t("title")} · ReliefGrid`;
  document.querySelectorAll("[data-lang]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === lang)));
  document.getElementById("title").textContent = data ? data.shelter.name : t("title");
  document.getElementById("route").innerHTML = data
    ? `<span class="wb">${esc(data.waybill)}</span> ${t("from")}: ${esc(data.warehouse.name)}${data.shelter.people != null ? ` · ${esc(t("people", { n: num(data.shelter.people) }))}` : ""}`
    : "";
}

function itemsList(load, counting) {
  return `<ul class="items">${load.items.map((i, idx) => `<li>
      <span class="name">${esc(i.item)}${counting ? `<small>${esc(t("sent", { n: num(i.quantity) }))} ${esc(i.unit || "")}</small>` : `<small>${esc(i.unit || "")}</small>`}</span>
      ${counting ? `<span class="stepper"><button type="button" data-dec="${idx}" aria-label="−">−</button>
        <input type="number" inputmode="numeric" min="0" max="${i.quantity}" value="${i.quantity}" data-count="${idx}" aria-label="${esc(i.item)}">
        <button type="button" data-inc="${idx}" aria-label="+">+</button></span>` : `<span class="qty">${num(i.quantity)}</span>`}</li>`).join("")}</ul>`;
}

function draw() {
  header();
  if (result) { drawDone(); return; }
  const chip = `<span class="chip ${data.stage}">${t(data.stage)}</span>`;
  const l = data.load;
  if (data.stage === "to_load" && l) {
    main.innerHTML = `<section class="card">${chip}<h2 style="margin-top:10px">${t("driver_h")}</h2><p class="hint">${t("driver_hint")}</p>
        ${itemsList(l, false)}
        <form id="f" novalidate><label class="field">${t("driver_name")}<input name="who" autocomplete="name" value="${esc(store.get("reliefgrid-driver"))}"></label>
        <p class="error-text" id="err"></p><button class="go" type="submit">${t("driver_btn")}</button></form></section>`;
    main.querySelector("#f").onsubmit = (e) => submit(e, "pickup", l);
  } else if (data.stage === "on_the_way" && l) {
    main.innerHTML = `<section class="card">${chip}<h2 style="margin-top:10px">${t("shelter_h")}</h2><p class="hint">${t("shelter_hint")}</p>
        <form id="f" novalidate>${itemsList(l, true)}
        <label class="field" id="note-wrap" hidden>${t("note")}<input name="note" maxlength="200" placeholder="${esc(t("note_ph"))}"></label>
        <label class="field">${t("receiver")}<input name="who" autocomplete="name" value="${esc(store.get("reliefgrid-receiver"))}"></label>
        <p class="error-text" id="err"></p><button class="go" type="submit">${t("receive_btn")}</button></form></section>`;
    const f = main.querySelector("#f");
    const sync = () => {
      let short = false;
      f.querySelectorAll("[data-count]").forEach((inp) => {
        const max = Number(inp.max), v = Number(inp.value);
        const ok = inp.value !== "" && Number.isInteger(v) && v >= 0 && v <= max;
        inp.classList.toggle("invalid", !ok);
        inp.classList.toggle("short", ok && v < max);
        if (ok && v < max) short = true;
      });
      f.querySelector("#note-wrap").hidden = !short;
    };
    f.addEventListener("input", sync);
    f.addEventListener("click", (e) => {
      const b = e.target.closest("[data-dec], [data-inc]");
      if (!b) return;
      const inp = f.querySelector(`[data-count="${b.dataset.dec ?? b.dataset.inc}"]`);
      inp.value = Math.min(Number(inp.max), Math.max(0, (Number(inp.value) || 0) + (b.dataset.inc != null ? 1 : -1)));
      sync();
    });
    f.onsubmit = (e) => submit(e, "receive", l);
  } else {
    main.innerHTML = `<section class="card">${chip}<p style="margin:12px 0 0">${t("none_now")}</p>
      ${data.received_by ? `<p class="hint" style="margin-top:8px">${esc(t("last", { name: data.received_by, time: when(data.delivered_at) }))}</p>` : ""}</section>
      <a class="go secondary link" href="track.html#${encodeURIComponent(data.waybill)}">${t("track")}</a>`;
  }
}

async function submit(e, kind, l) {
  e.preventDefault();
  const f = e.target, err = f.querySelector("#err"), btn = f.querySelector(".go");
  const who = f.who.value.trim().replace(/\s+/g, " ");
  f.who.classList.toggle("invalid", !who);
  if (!who) { err.textContent = t("need_name"); f.who.focus(); return; }
  let body;
  if (kind === "pickup") {
    store.set("reliefgrid-driver", who);
    body = { t: token, driver: who, upto_id: l.max_id };
  } else {
    store.set("reliefgrid-receiver", who);
    const received = {};
    let short = false, bad = false;
    f.querySelectorAll("[data-count]").forEach((inp) => {
      const v = Number(inp.value), max = Number(inp.max);
      if (inp.value === "" || !Number.isInteger(v) || v < 0 || v > max) { bad = true; inp.classList.add("invalid"); return; }
      received[l.items[Number(inp.dataset.count)].item] = v;
      if (v < max) short = true;
    });
    if (bad) return;
    const note = f.note.value.trim();
    if (short && !note) { err.textContent = t("need_note"); f.note.classList.add("invalid"); f.note.focus(); return; }
    body = { t: token, received_by: who, ...(short ? { received, note } : {}) };
  }
  btn.disabled = true;
  err.textContent = "";
  try {
    const r = await call(`${base}/${kind}`, body, who);
    result = { kind, who, ...r };
    draw();
    celebrate(main.querySelector(".tick"));
  } catch (ex) { err.textContent = ex.message; btn.disabled = false; }
}

function drawDone() {
  const r = result;
  main.innerHTML = `<section class="card done"><div class="tick"><svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></div>
      <h2>${esc(r.kind === "pickup" ? t("done_pickup") : t("done_receive", { name: r.who }))}</h2>
      <p>${esc(r.kind === "pickup" ? t("done_pickup_sub") : "")}</p>
      ${r.lost ? `<div class="msg warn" style="margin-top:14px">${esc(t("lost", { n: num(r.lost) }))}</div>` : ""}</section>
    <a class="go secondary link" href="track.html#${encodeURIComponent(result.waybill)}">${t("track")}</a>`;
}

document.querySelectorAll("[data-lang]").forEach((b) => (b.onclick = () => { lang = b.dataset.lang; store.set("reliefgrid-lang", lang); data ? draw() : header(); }));
header();
load();
window.addEventListener("hashchange", () => location.reload());
