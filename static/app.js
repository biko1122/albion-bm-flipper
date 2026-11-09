"use strict";
const $ = (s, el = document) => el.querySelector(s);
const CATS = { weapons: "سلاح", head: "خوذة", armors: "درع", shoes: "جزمة", offhands: "أوف هاند", capes: "كيب", bags: "شنطة", gathering: "لبس جمع" };
const QN = { 1: "Normal", 2: "Good", 3: "Outstanding", 4: "Excellent", 5: "Masterpiece" };
const QA = { 1: "عادي", 2: "كويس", 3: "ممتاز", 4: "رائع", 5: "تحفة" };
const TIER = { 4: "Adept", 5: "Expert", 6: "Master", 7: "Grandmaster", 8: "Elder" };
const BM = "Black Market";
const fmt = n => (n == null ? "—" : Math.round(n).toLocaleString("en-US"));
const icon = (id, q = 1, size = 64) => `https://render.albiononline.com/v1/item/${encodeURIComponent(id)}.png?quality=${q}&size=${size}`;
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const DEFAULTS = {
  premium: false, mode: "instant", age: 6, cities: null, tiers: [4, 5, 6, 7, 8], ench: [0, 1, 2, 3, 4],
  cats: Object.keys(CATS), minprofit: 5000, minmargin: 5, maxbuy: "", minsold: 0, best: true, sort: "total",
};
let S = load();
let rows = [], cities = [], filtered = [], limit = 150, polling = null, tab = "list", lastSeen = "";

function load() {
  try {
    const s = { ...DEFAULTS, ...JSON.parse(localStorage.getItem("bm-settings") || "{}") };
    if (!Object.keys(CATS).every(c => s.cats.includes(c)) && !localStorage.getItem("bm-v2")) s.cats = Object.keys(CATS);
    if (!localStorage.getItem("bm-v2")) s.sort = "total";
    return s;
  } catch { return { ...DEFAULTS }; }
}
function save() { try { localStorage.setItem("bm-settings", JSON.stringify(S)); localStorage.setItem("bm-v2", "1"); } catch {} }

function ago(ts) {
  if (!ts) return { t: "—", c: "old" };
  const m = Math.max(0, Math.round((Date.now() / 1000 - ts) / 60));
  const t = m < 1 ? "دلوقتي" : m < 60 ? `من ${m} د` : m < 1440 ? `من ${Math.floor(m / 60)} س ${m % 60 ? (m % 60) + " د" : ""}` : `من ${Math.floor(m / 1440)} يوم`;
  return { t, c: m <= 60 ? "fresh" : m <= 180 ? "stale" : "old" };
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast.h); toast.h = setTimeout(() => (t.hidden = true), 2400);
}
const taxPct = () => (S.premium ? 4 : 8);
const srcTag = src => src === "me" ? '<span class="src local">جهازك</span>' : src === "live" ? '<span class="src live">لايف</span>' : "";

/* ---------------- filters UI ---------------- */
function chipGroup(el, values, labelOf, key) {
  el.innerHTML = values.map(v => `<button data-v="${v}" class="${S[key].includes(v) ? "on" : ""}">${labelOf(v)}</button>`).join("");
  el.onclick = e => {
    const b = e.target.closest("button"); if (!b) return;
    const v = isNaN(+b.dataset.v) ? b.dataset.v : +b.dataset.v;
    S[key] = S[key].includes(v) ? S[key].filter(x => x !== v) : [...S[key], v];
    b.classList.toggle("on"); save(); applyAll();
  };
}
function seg(el, key, onChange) {
  [...el.children].forEach(b => b.classList.toggle("on", String(S[key]) === b.dataset.v));
  el.onclick = e => {
    const b = e.target.closest("button"); if (!b) return;
    S[key] = isNaN(+b.dataset.v) ? b.dataset.v : +b.dataset.v;
    [...el.children].forEach(x => x.classList.toggle("on", x === b)); save(); onChange();
  };
}
function initFilters() {
  if (!S.cities) S.cities = [...cities];
  chipGroup($("#f-cities"), cities, c => c, "cities");
  chipGroup($("#f-tiers"), [4, 5, 6, 7, 8], t => "T" + t, "tiers");
  chipGroup($("#f-ench"), [0, 1, 2, 3, 4], e => "." + e, "ench");
  chipGroup($("#f-cats"), Object.keys(CATS), c => CATS[c], "cats");
  seg($("#f-mode"), "mode", () => { hints(); reloadAll(); });
  seg($("#f-age"), "age", fetchRows);
  const prem = $("#f-premium"); prem.checked = S.premium;
  prem.onchange = () => { S.premium = prem.checked; save(); hints(); reloadAll(); };
  for (const [id, key] of [["#f-minprofit", "minprofit"], ["#f-minmargin", "minmargin"], ["#f-maxbuy", "maxbuy"], ["#f-minsold", "minsold"]]) {
    const el = $(id); el.value = S[key];
    el.oninput = () => { S[key] = el.value; save(); applyAll(); };
  }
  const best = $("#f-best"); best.checked = S.best;
  best.onchange = () => { S.best = best.checked; save(); applyAll(); };
  $("#f-search").oninput = () => applyAll();
  $("#p-city").innerHTML = cities.map(c => `<option>${c}</option>`).join("");
  for (const id of ["#p-city", "#p-budget", "#p-weight", "#p-sort"]) $(id).oninput = renderPlan;
  for (const id of ["#p-src", "#p-age"]) $(id).oninput = fetchPlan;
  for (const id of ["#s-age", "#s-min"]) $(id).oninput = fetchScan;
  $("#s-sort").oninput = renderScan;
  document.querySelectorAll("#grid th[data-sort]").forEach(th => {
    th.classList.toggle("sorted", th.dataset.sort === S.sort);
    th.onclick = () => {
      S.sort = th.dataset.sort; save();
      document.querySelectorAll("#grid th").forEach(x => x.classList.toggle("sorted", x === th)); apply();
    };
  });
  document.querySelectorAll(".tab").forEach(t => t.onclick = () => {
    tab = t.dataset.tab;
    document.querySelectorAll(".tab").forEach(x => x.classList.toggle("on", x === t));
    for (const n of ["list", "scan", "plan"]) $("#tab-" + n).hidden = n !== tab;
    if (tab === "plan") fetchPlan();
    if (tab === "scan") fetchScan();
  });
  $("#btn-more").onclick = () => { limit += 150; renderTable(); };
  hints();
}
function hints() {
  $("#tax-hint").textContent = `ضريبة البيع للبلاك ماركت: ${taxPct()}%` + (S.premium ? " (بريميوم)" : " (من غير بريميوم)");
  $("#mode-hint").textContent = S.mode === "order"
    ? "بتحط أوردر شرا بسعر أعلى أوردر + 1 سيلفر، وبتدفع رسوم 2.5%. أرخص، بس لازم تستنى لحد ما يتملى."
    : "بتشتري من أرخص سيل أوردر، من غير أي رسوم.";
}

/* ---------------- shared filtering ---------------- */
function passes(r, { profitKey = "profit", anyCity = false } = {}) {
  const q = $("#f-search").value.trim().toLowerCase();
  const minP = +S.minprofit || 0, minM = +S.minmargin || 0, maxB = +S.maxbuy || Infinity, minS = +S.minsold || 0;
  return (anyCity || S.cities.includes(r.city)) && S.tiers.includes(r.tier) && S.ench.includes(r.ench) && S.cats.includes(r.cat) &&
    r[profitKey] >= minP && r.margin * 100 >= minM && (r.cost ?? r.city_price) <= maxB &&
    (minS === 0 || (r.sold_day != null && r.sold_day >= minS)) &&
    (!q || r.name.toLowerCase().includes(q) || r.id.toLowerCase().includes(q));
}
function bestPer(list, keyOf, score) {
  const m = new Map();
  for (const r of list) { const k = keyOf(r), o = m.get(k); if (!o || score(r) > score(o)) m.set(k, r); }
  return [...m.values()];
}
function applyAll() { apply(); if (tab === "scan") renderScan(); if (tab === "plan") renderPlan(); }
function reloadAll() { fetchRows(); if (tab === "scan") fetchScan(); if (tab === "plan") fetchPlan(); }

/* ---------------- opportunities ---------------- */
async function fetchRows() {
  const r = await fetch(`/api/opportunities?premium=${S.premium ? 1 : 0}&mode=${S.mode}&max_age=${S.age}`).then(r => r.json());
  rows = r.rows || []; apply();
}
function apply() {
  let out = rows.filter(r => passes(r));
  if (S.best) out = bestPer(out, r => r.id + "|" + r.city, r => r.profit);
  const key = S.sort;
  out.sort((a, b) => key === "city" ? a.city.localeCompare(b.city) || b.total - a.total : (b[key] ?? -1) - (a[key] ?? -1));
  filtered = out; limit = 150;
  renderKpis(); renderTable();
}
function renderKpis() {
  const byTotal = filtered.slice().sort((a, b) => b.total - a.total);
  const multi = filtered.filter(r => r.qty > 1).length;
  const top10 = byTotal.slice(0, 10).reduce((s, r) => s + r.total, 0);
  $("#kpis").innerHTML = [
    ["عدد الفرص", fmt(filtered.length)],
    ["أعلى ربح كلي لايتم", byTotal[0] ? fmt(byTotal[0].total) : "—"],
    ["فرص بأكتر من قطعة", fmt(multi)],
    ["ربح أحسن 10 مع بعض", fmt(top10)],
  ].map(([k, v]) => `<div class="kpi"><div class="k">${k}</div><div class="v num">${v}</div></div>`).join("");
}
function itemCell(r) {
  return `<div class="item"><img loading="lazy" src="${icon(r.id, r.q)}" alt="">
    <div><div class="nm">${esc(r.name)}</div>
    <div class="meta"><span class="tq">T${r.tier}.${r.ench}</span><span class="qb q${r.q}">${QA[r.q]} · ${QN[r.q]}</span><span>${CATS[r.cat] || r.cat}</span></div></div></div>`;
}
function priceCell(price, at, src, amount, extra = "") {
  const a = ago(at);
  return `<span class="mono">${fmt(price)}</span>${srcTag(src)}
    <span class="age ${a.c}">${a.t}${amount ? ` · ${fmt(amount)} قطعة` : ""}</span>${extra}`;
}
function renderTable() {
  const tb = $("#grid tbody");
  const show = filtered.slice(0, limit);
  tb.innerHTML = show.map((r, i) => `<tr data-i="${i}">
    <td>${itemCell(r)}</td>
    <td>${r.city}<span class="age ${r.city === "Caerleon" ? "safe" : "risk"}">${r.city === "Caerleon" ? "جنب البلاك ماركت" : "رحلة لكارليون"}</span></td>
    <td class="num">${priceCell(r.buy_price, r.buy_at, r.buy_src, r.buy_amount)}</td>
    <td class="num">${priceCell(r.bm_price, r.bm_at, r.bm_src, r.bm_amount, r.bm_q !== r.q ? `<span class="age muted">أوردر ${QA[r.bm_q]}</span>` : "")}</td>
    <td class="num"><span class="profit">${fmt(r.profit)}</span><span class="age muted">ضريبة ${fmt(r.tax + r.setup_fee)}</span></td>
    <td class="num">${r.depth ? `<b>${r.qty}</b>` : '<span class="muted" title="مش معروف: اعمل سكان للايتم في المدينة والبلاك ماركت">1؟</span>'}</td>
    <td class="num"><span class="total">${fmt(r.total)}</span>${r.depth ? `<span class="age muted">تدفع ${fmt(r.total_cost)}</span>` : ""}</td>
    <td class="num">${(r.margin * 100).toFixed(1)}%${r.margin > 1 ? '<span class="age old">رخيص زيادة؟ اتأكد</span>' : ""}</td>
    <td class="num">${fmt(r.per_kg)}</td>
    <td class="num">${r.sold_day == null ? '<span class="muted">—</span>' : r.sold_day}</td>
    <td><button class="gone" data-gone="${i}" title="البلاك ماركت مبقاش بيشتريها (بعتها أو الأوردر خلص)">خلص</button></td>
  </tr>`).join("");
  tb.onclick = e => {
    const g = e.target.closest("[data-gone]");
    if (g) { e.stopPropagation(); return dismiss(show[+g.dataset.gone], BM); }
    const tr = e.target.closest("tr"); if (tr) openDrawer(show[+tr.dataset.i]);
  };
  const empty = $("#empty");
  empty.hidden = filtered.length > 0;
  empty.innerHTML = rows.length
    ? "مفيش فرص بالفلاتر دي. جرّب تقلل أقل ربح أو تزود عمر الداتا."
    : "مفيش أسعار لسه. دوس <b>تحديث الأسعار</b> فوق (أول مرة بتاخد حوالي دقيقة).";
  $("#more").hidden = filtered.length <= limit;
}

async function dismiss(r, market) {
  await fetch("/api/dismiss", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: r.id, city: market }) });
  toast(market === BM ? `${r.name}: اتشال. هيرجع بس لو اتسكن تاني ولقى أوردر.` : `${r.name}: اتشال من ${market}.`);
  closeDrawer(); reloadAll();
}

/* ---------------- drawer ---------------- */
function totals(r, n) {
  const fee = S.mode === "order" ? 1025 : 1000;
  const costMilli = r.buy_price * n * fee;               // exact, in 1/1000 silver
  const revCenti = r.bm_price * n * (100 - taxPct());    // exact, in 1/100 silver
  return { cost: Math.ceil(costMilli / 1000), receive: Math.floor(revCenti / 100), profit: Math.floor((revCenti * 10 - costMilli) / 1000) };
}
async function openDrawer(r) {
  $("#drawer").hidden = $("#drawer-bg").hidden = false;
  const body = $("#drawer-body");
  const buyPrice = r.buy_price ?? r.city_price;
  body.innerHTML = `<div class="d-head"><img src="${icon(r.id, r.q, 128)}" alt="">
      <div><h2>${esc(r.name)}</h2>
      <div class="muted mono">${esc(r.id)}</div>
      <div class="meta muted">${TIER[r.tier]} · T${r.tier}.${r.ench} · <span class="q${r.q}">${QA[r.q]} (${QN[r.q]})</span> · ${r.weight} كجم</div>
      <div class="actions">
        <button class="btn" id="copy">انسخ الاسم للسيرش في اللعبة</button>
        <button class="btn danger" id="gone-bm">البلاك ماركت مبقاش بيشتريها</button>
        <button class="btn danger" id="gone-city">مبقاش موجود في ${r.city}</button>
      </div></div></div>
    ${r.buy_price != null ? `<div class="calc"><h4>الحساب بالظبط (للقطعة)</h4>
      <div class="row"><span>سعر الشرا من ${r.city} (${QA[r.q]})</span><span class="num">${fmt(r.buy_price)}</span></div>
      ${r.setup_fee ? `<div class="row"><span>رسوم أوردر الشرا 2.5%</span><span class="num">+ ${fmt(r.setup_fee)}</span></div>` : ""}
      <div class="row"><span>التكلفة</span><span class="num">${fmt(r.cost)}</span></div>
      <div class="row"><span>البلاك ماركت بيشتري بـ (أوردر ${QA[r.bm_q]})</span><span class="num">${fmt(r.bm_price)}</span></div>
      <div class="row"><span>ضريبة البيع ${taxPct()}%</span><span class="num">− ${fmt(r.tax)}</span></div>
      <div class="row"><span>اللي هيدخل جيبك</span><span class="num">${fmt(r.receive)}</span></div>
      <div class="row total"><span>صافي الربح</span><span class="num profit">${fmt(r.profit)} (${(r.margin * 100).toFixed(2)}%)</span></div>
      <div class="qty"><span>لو جبت</span><input type="number" id="qty" value="1" min="1"><span>قطعة بنفس السعر:</span><b class="num" id="qty-out"></b></div>
      <div class="note" id="qty-note"></div>
    </div>` : `<div class="calc"><h4>لسه محتاج سكان</h4>
      <div class="row"><span>آخر سعر معروف في ${r.city}</span><span class="num">${fmt(buyPrice)} (${ago(r.city_at).t})</span></div>
      <div class="row"><span>البلاك ماركت طالب بـ</span><span class="num">${fmt(r.bm_price)}</span></div>
      <div class="row total"><span>الربح لو السعر لسه زي ما هو</span><span class="num profit">${fmt(r.profit)}</span></div></div>`}
    <div id="d-more" class="muted">بيحمّل كل الأسعار…</div>`;
  $("#copy").onclick = () => navigator.clipboard.writeText(r.name).then(() => toast("اتنسخ: " + r.name));
  $("#gone-bm").onclick = () => dismiss(r, BM);
  $("#gone-city").onclick = () => dismiss(r, r.city);
  if ($("#qty")) {
    const upd = () => {
      const n = Math.max(1, +$("#qty").value || 1), t = totals(r, n);
      $("#qty-out").textContent = `تدفع ${fmt(t.cost)} ← تاخد ${fmt(t.receive)} ← ربح ${fmt(t.profit)}`;
      const warn = [];
      if (r.buy_amount != null && n > r.buy_amount) warn.push(`الكمية بالسعر ده في ${r.city}: ${r.buy_amount} بس.`);
      if (r.bm_amount != null && n > r.bm_amount) warn.push(`البلاك ماركت طالب ${r.bm_amount} بس بالسعر ده.`);
      if (r.buy_amount == null || r.bm_amount == null) warn.push("السعر ده لأول قطعة بس. اعمل سكان للايتم في المدينة والبلاك ماركت عشان تعرف الكمية الحقيقية.");
      $("#qty-note").textContent = warn.join(" ");
    };
    $("#qty").oninput = upd; upd();
  }

  const d = await fetch(`/api/item?id=${encodeURIComponent(r.id)}&premium=${S.premium ? 1 : 0}&max_age=24`).then(x => x.json());
  const markets = [BM, ...cities];
  const cell = (m, q) => {
    const c = (d.markets[m] || {})[q] || {};
    const v = m === BM ? c.buy : c.sell;
    if (!v) return `<td class="muted">—</td>`;
    const a = ago(v.at);
    const best = (m === r.city && q == r.q) || (m === BM && q == r.bm_q);
    return `<td class="${best ? "best" : ""}"><span class="mono">${fmt(v.price)}</span>${srcTag(v.src)}<span class="age ${a.c}">${a.t}${v.amount ? " · " + v.amount : ""}</span></td>`;
  };
  let html = "";
  const plans = Object.entries(d.plans || {}).sort((a, b) => b[1].profit - a[1].profit);
  if (plans.length) {
    html += `<h4>خطة بالكميات الحقيقية</h4>` + plans.map(([city, p]) => `
      <div class="calc"><div class="row"><b>${city}</b><span class="num total">${fmt(p.profit)}</span></div>
      <div class="row muted"><span>${p.qty} قطعة · تدفع ${fmt(p.cost)} · تاخد ${fmt(p.receive)}</span></div>
      ${p.lines.map(l => `<div class="row muted"><span>${l.n}× اشتري ${QA[l.buy_q]} بـ ${fmt(l.buy)} ← بيع لأوردر ${QA[l.sell_q]} بـ ${fmt(l.sell)}</span></div>`).join("")}
      </div>`).join("");
  }
  html += `<h4 style="margin-top:14px">كل الأسعار (آخر 24 ساعة)</h4>
    <div class="table-wrap"><table class="board"><thead><tr><th>الماركت</th>${[1, 2, 3, 4, 5].map(q => `<th class="q${q}">${QA[q]}</th>`).join("")}</tr></thead><tbody>
    ${markets.map(m => `<tr><td>${m === BM ? "<b>البلاك ماركت</b> (بيشتري)" : m + " (بيبيع)"}</td>${[1, 2, 3, 4, 5].map(q => cell(m, q)).join("")}</tr>`).join("")}
    </tbody></table></div>
    <div class="note">البلاك ماركت بيقبل الكواليتي المطلوبة أو أعلى منها. يعني الـ Outstanding ينفع تبيعه لأوردر Normal، بس العكس لأ.</div>`;
  if (r.sold_day != null) html += `<div class="note">البلاك ماركت اشترى في المتوسط <b>${r.sold_day}</b> قطعة في اليوم من الكواليتي دي (آخر 7 أيام).</div>`;
  $("#d-more").outerHTML = html;
}
function closeDrawer() { $("#drawer").hidden = $("#drawer-bg").hidden = true; }
$("#drawer-x").onclick = closeDrawer; $("#drawer-bg").onclick = closeDrawer;
document.addEventListener("keydown", e => e.key === "Escape" && closeDrawer());

/* ---------------- what to scan ---------------- */
let scanRows = [];
async function fetchScan() {
  $("#scan-out").innerHTML = '<div class="empty">بيحسب…</div>';
  const r = await fetch(`/api/scan?premium=${S.premium ? 1 : 0}&bm_age=${$("#s-age").value}&min_profit=${+$("#s-min").value || 0}`).then(r => r.json());
  scanRows = r.rows || []; renderScan();
}
function renderScan() {
  const key = $("#s-sort").value;
  const q = $("#f-search").value.trim().toLowerCase();
  const list = scanRows.filter(r => S.cities.includes(r.city) && S.tiers.includes(r.tier) && S.ench.includes(r.ench) &&
    S.cats.includes(r.cat) && (!q || r.name.toLowerCase().includes(q)));
  if (!list.length) {
    $("#scan-out").innerHTML = `<div class="empty">مفيش اقتراحات. لازم يكون فيه داتا حديثة للبلاك ماركت: اعمل سكان في البلاك ماركت (تاب Sell)، أو استنى اللايف يجيب.</div>`;
    return;
  }
  const byCity = {};
  for (const r of list) (byCity[r.city] ||= []).push(r);
  const cityOrder = Object.entries(byCity).map(([c, l]) => [c, l.sort((a, b) => b[key] - a[key]), l.reduce((s, r) => s + r.potential, 0)])
    .sort((a, b) => b[2] - a[2]);
  $("#scan-out").innerHTML = cityOrder.map(([city, l, sum]) => `
    <div class="city-head">${city} · ${l.length} ايتم · ربح محتمل لحد ${fmt(sum)}</div>
    <div class="table-wrap"><table class="grid"><thead><tr><th>الايتم</th><th class="num">آخر سعر في ${city}</th><th class="num">البلاك ماركت دلوقتي</th>
      <th class="num">ربح القطعة لو السعر لسه كده</th><th class="num">البلاك طالب</th><th class="num">ربح كلي محتمل</th><th></th></tr></thead>
    <tbody>${l.slice(0, 40).map((r, i) => `<tr data-city="${esc(city)}" data-i="${i}">
      <td>${itemCell(r)}</td>
      <td class="num">${priceCell(r.city_price, r.city_at, r.city_src)}</td>
      <td class="num">${priceCell(r.bm_price, r.bm_at, null, r.bm_amount, r.bm_q !== r.q ? `<span class="age muted">أوردر ${QA[r.bm_q]}</span>` : "")}</td>
      <td class="num"><span class="profit">${fmt(r.profit)}</span><span class="age muted">${(r.margin * 100).toFixed(1)}%</span></td>
      <td class="num">${r.pot_qty} قطعة</td>
      <td class="num"><span class="total">${fmt(r.potential)}</span></td>
      <td><button class="gone" data-copy="${esc(r.name)}">انسخ الاسم</button></td>
    </tr>`).join("")}</tbody></table></div>`).join("");
  $("#scan-out").onclick = e => {
    const c = e.target.closest("[data-copy]");
    if (c) { e.stopPropagation(); return navigator.clipboard.writeText(c.dataset.copy).then(() => toast("اتنسخ: " + c.dataset.copy)); }
    const tr = e.target.closest("tr[data-city]");
    if (tr) openDrawer(byCity[tr.dataset.city].sort((a, b) => b[key] - a[key])[+tr.dataset.i]);
  };
}

/* ---------------- trip plan (fresh scanned data only) ---------------- */
let planRows = [];
async function fetchPlan() {
  $("#plan-out").innerHTML = '<div class="empty">بيحسب…</div>';
  const r = await fetch(`/api/opportunities?premium=${S.premium ? 1 : 0}&mode=instant&max_age=${$("#p-age").value}&sources=${$("#p-src").value}`).then(r => r.json());
  planRows = r.rows || []; renderPlan();
}
function renderPlan() {
  const city = $("#p-city").value, budget = +$("#p-budget").value || 0, cap = +$("#p-weight").value || 0, key = $("#p-sort").value;
  const cands = bestPer(planRows.filter(r => r.city === city && passes(r, { anyCity: true })), r => r.id, r => r.total)
    .sort((a, b) => (b[key] ?? 0) - (a[key] ?? 0));
  let money = budget, weight = cap, pick = [];
  for (const r of cands) {
    if (r.depth) {
      // walk the real order book line by line so partial amounts still fit the budget
      let n = 0, cost = 0, pr = 0;
      const lines = [];
      const per = r.depth.cost / r.depth.qty, perP = r.depth.profit / r.depth.qty;
      const fit = Math.min(r.depth.qty, Math.floor(money / per), Math.floor(weight / (r.weight || 0.001)));
      if (fit >= 1) {
        n = fit; cost = fit === r.depth.qty ? r.depth.cost : Math.ceil(per * fit); pr = fit === r.depth.qty ? r.depth.profit : Math.floor(perP * fit);
        pick.push({ r, n, cost, pr, w: r.weight * n, partial: fit < r.depth.qty }); money -= cost; weight -= r.weight * n;
      }
    } else if (r.cost <= money && r.weight <= weight) {
      pick.push({ r, n: 1, cost: r.cost, pr: r.profit, w: r.weight }); money -= r.cost; weight -= r.weight;
    }
  }
  const tot = pick.reduce((s, p) => ({ cost: s.cost + p.cost, pr: s.pr + p.pr, w: s.w + p.w }), { cost: 0, pr: 0, w: 0 });
  $("#plan-out").innerHTML = !pick.length ? `<div class="empty">مفيش حاجة من ${city} بالداتا الحديثة دي.<br>اعمل سكان للايتمز في ${city} وفي البلاك ماركت (أو اختار "جهازي + اللايف")، أو زوّد الوقت.</div>` : `
    <div class="kpis">
      <div class="kpi"><div class="k">هتصرف</div><div class="v num">${fmt(tot.cost)}</div></div>
      <div class="kpi"><div class="k">صافي الربح المتوقع</div><div class="v num profit">${fmt(tot.pr)}</div></div>
      <div class="kpi"><div class="k">الوزن</div><div class="v num">${tot.w.toFixed(1)} كجم</div></div>
      <div class="kpi"><div class="k">عدد القطع</div><div class="v num">${pick.reduce((s, p) => s + p.n, 0)}</div></div>
    </div>
    <div class="table-wrap"><table class="grid"><thead><tr><th>الايتم</th><th class="num">اشتري</th><th class="num">سعر الشرا</th><th class="num">البلاك ماركت</th><th class="num">تدفع</th><th class="num">ربح</th><th class="num">وزن</th></tr></thead>
    <tbody>${pick.map((p, i) => `<tr data-i="${i}"><td>${itemCell(p.r)}</td>
      <td class="num"><b>${p.n}</b>${p.partial ? '<span class="age muted">على قد فلوسك/وزنك</span>' : ""}</td>
      <td class="num">${priceCell(p.r.buy_price, p.r.buy_at, p.r.buy_src)}</td>
      <td class="num">${priceCell(p.r.bm_price, p.r.bm_at, p.r.bm_src)}</td>
      <td class="num">${fmt(p.cost)}</td><td class="num total">${fmt(p.pr)}</td><td class="num">${p.w.toFixed(1)}</td></tr>`).join("")}</tbody></table></div>
    <div class="note">${city === "Caerleon" ? "الشرا من كارليون معناه إنك مش هتتنقل. أأمن حاجة." : "انت هتعدي red zone وانت رايح كارليون. متشيلش أكتر من اللي تستحمل تخسره."} لو ايتم عليه "1" بس، يبقى الكميات مش معروفة، فاعمل سكان ليه في البلاك ماركت والمدينة الاتنين.</div>`;
  $("#plan-out tbody")?.addEventListener("click", e => { const tr = e.target.closest("tr"); if (tr) openDrawer(pick[+tr.dataset.i].r); });
}

/* ---------------- status / refresh ---------------- */
async function status() {
  const s = await fetch("/api/status").then(r => r.json());
  cities = s.cities;
  const lr = ago(s.last_refresh);
  const st = $("#st-refresh"); st.textContent = "آخر تحديث: " + (s.last_refresh ? lr.t : "ولا مرة");
  st.className = "chip " + (s.last_refresh ? (lr.c === "fresh" ? "ok" : "warn") : "warn");
  const cl = $("#st-client"), live = s.local.last_at && Date.now() / 1000 - s.local.last_at < 900;
  const c = s.client || {};
  cl.textContent = live ? `الكلاينت: شغّال (${fmt(s.local.count)} أوردر)`
    : c.running ? "الكلاينت: شغّال، افتح الماركت في اللعبة"
    : !c.installed ? "الكلاينت: مش متسطب" : "الكلاينت: واقف";
  cl.className = "chip " + (live || c.running ? "ok" : "warn");
  const lv = $("#st-live"), L = s.live || {};
  lv.textContent = L.connected ? `اللايف: متوصل · ${fmt(s.local.live_count)} أوردر` : "اللايف: مش متوصل";
  lv.className = "chip " + (L.connected ? "ok" : "warn");
  const j = s.job, p = $("#progress");
  if (j.running) {
    p.hidden = false; $("#btn-refresh").disabled = true;
    const pct = j.total ? Math.round(100 * j.done / j.total) : 0;
    $("#progress-bar").style.width = pct + "%";
    $("#progress-text").textContent = (j.stage === "history" ? "بيحمّل مبيعات البلاك ماركت" : "بيحمّل الأسعار") + ` ${fmt(j.done)} / ${fmt(j.total)} (${pct}%)`;
  } else {
    p.hidden = true; $("#btn-refresh").disabled = false;
    if (polling) { clearInterval(polling); polling = null; toast(j.stage === "error" ? "حصلت مشكلة: " + j.error : "الأسعار اتحدثت"); reloadAll(); }
  }
  return s;
}
$("#btn-refresh").onclick = async () => {
  await fetch("/api/refresh", { method: "POST" });
  if (!polling) polling = setInterval(status, 1000);
  status();
};

// Auto-update: your own scans show within ~5s, live data from others every 30s.
let lastLive = 0;
async function tick() {
  if (polling || document.hidden) return;
  const s = await status();
  const mine = String(s.local.last_at);
  const now = Date.now();
  if (!$("#drawer").hidden) return;
  if (mine !== lastSeen || now - lastLive > 30000) {
    lastSeen = mine; lastLive = now; reloadAll();
  }
}

(async function init() {
  const s = await status();
  lastSeen = String(s.local.last_at); lastLive = Date.now();
  initFilters();
  await fetchRows();
  if (s.job.running && !polling) polling = setInterval(status, 1000);
  setInterval(tick, 5000);
})();
