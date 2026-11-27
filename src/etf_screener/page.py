"""The screener page: one self-contained HTML file from the screener payload.

The payload is ``const D`` in the page; no CDN, no external request, so the page works offline and from any static
host. Filtering, sorting and comparing run in the browser with ``screenFunds``, which applies ``D.filters``
(``screen.FILTERS``) exactly as ``screen.py`` does; the tests run both on the same funds and require the same answer.

Copy rules (``gate.py`` enforces them): the page describes funds and the reader's own filters, never the reader;
the disclosure, the data source and the date are on the page; a missing figure is a dash, never a zero.
"""
from __future__ import annotations

import html
import json
from typing import Any

DISCLOSURE = (
    "This screener is general information. It is not advice tailored to you, and nothing on it is an offer, a "
    "solicitation or a recommendation to buy or sell any security. The results are the funds that meet the filters "
    "you choose. Past performance does not guarantee future returns, and returns shown are before any adviser fee "
    "and before tax. Check a fund's documents with its issuer before you rely on any figure here.")

REPO = "https://github.com/InvestMint-Labs/etf-screener"
TITLE = "ETF Screener"

CSS = r"""
:root{--bg:#ffffff;--ink:#111827;--muted:#6b7280;--line:#e5e7eb;--soft:#f9fafb;--brand:#059669;--brand-ink:#047857;
--brand-soft:#ecfdf5;--neg:#b91c1c;--card:#ffffff}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0b1220;--ink:#e5e7eb;--muted:#9ca3af;
--line:#1f2937;--soft:#111827;--brand:#34d399;--brand-ink:#6ee7b7;--brand-soft:#052e24;--neg:#f87171;--card:#0f172a}}
:root[data-theme="dark"]{--bg:#0b1220;--ink:#e5e7eb;--muted:#9ca3af;--line:#1f2937;--soft:#111827;--brand:#34d399;
--brand-ink:#6ee7b7;--brand-soft:#052e24;--neg:#f87171;--card:#0f172a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{border-bottom:1px solid var(--line);padding:18px 16px}
.wrap{max-width:1280px;margin:0 auto;padding:0 16px}
.brand{font-weight:700;color:var(--brand-ink);letter-spacing:.02em}
h1{font-size:26px;margin:6px 0 4px}
.lede{color:var(--muted);margin:0;max-width:760px}
.layout{display:grid;grid-template-columns:270px minmax(0,1fr);gap:24px;padding:20px 16px;max-width:1280px;margin:0 auto}
main{min-width:0}
@media (max-width:860px){.layout{grid-template-columns:1fr}}
aside{background:var(--soft);border:1px solid var(--line);border-radius:10px;padding:14px;align-self:start}
summary{cursor:pointer;list-style:none}summary::-webkit-details-marker{display:none}
summary h2::after{content:" ▾"}details:not([open]) summary h2::after{content:" ▸"}
aside h2{display:inline;font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0 0 10px}
label{display:block;font-size:13px;color:var(--muted);margin:10px 0 4px}
input,select{width:100%;padding:7px 8px;border:1px solid var(--line);border-radius:6px;background:var(--card);
color:var(--ink);font:inherit;font-size:14px}
select[multiple]{height:96px}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
button{font:inherit;font-size:14px;border-radius:6px;border:1px solid var(--brand);background:var(--brand);color:#fff;
padding:7px 12px;cursor:pointer}
button.ghost{background:transparent;color:var(--brand-ink)}
.bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;margin-bottom:10px}
.count{color:var(--muted);font-size:14px}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{background:var(--soft);font-weight:600;cursor:pointer;user-select:none;position:sticky;top:0}
th.l,td.l{text-align:left}
td.name{white-space:normal;min-width:220px}
tr:hover td{background:var(--brand-soft)}
.neg{color:var(--neg)}
.dash{color:var(--muted)}
.sym{font-weight:600}
.tray{position:sticky;bottom:0;background:var(--card);border-top:2px solid var(--brand);padding:10px 16px;display:none}
.tray.on{display:block}
#compare{display:none;padding:0 16px 20px}
#compare.on{display:block}
#compare td,#compare th{text-align:left}
.note{color:var(--muted);font-size:13px}
footer{border-top:1px solid var(--line);padding:18px 16px 28px;color:var(--muted);font-size:12.5px}
footer p{max-width:900px}
"""

JS = r"""
const FMT = {
  pct: v => v == null ? null : (v * 100).toFixed(2) + "%",
  mer: v => v == null ? null : v.toFixed(2) + "%",
  yrs: v => v == null ? null : v.toFixed(1),
  aum: v => v == null ? null : (v >= 1e9 ? (v / 1e9).toFixed(1) + "B" : v >= 1e6 ? (v / 1e6).toFixed(0) + "M"
        : (v / 1e3).toFixed(0) + "k"),
};
const COLS = [
  ["symbol", "Ticker", "l", null], ["name", "Fund", "l name", null], ["issuer", "Issuer", "l", null],
  ["category", "Category", "l", null], ["cost_pct", "MER", "", "mer"], ["yield", "Yield", "", "pct"],
  ["aum", "Assets", "", "aum"], ["return_1y", "1 yr", "", "pct"], ["return_3y", "3 yr /yr", "", "pct"],
  ["return_5y", "5 yr /yr", "", "pct"], ["volatility_3y", "3 yr vol", "", "pct"],
  ["max_drawdown_3y", "3 yr max fall", "", "pct"], ["duration", "Duration (yrs)", "", "yrs"],
  ["cost_url", "Cost source", "l", null], ["asset_class", "Asset class", "l", null],
];
// a page names the columns it carries (D.columns); without it, the full table less the two web-only columns
const SHOWN = () => D.columns ? D.columns.map(k => COLS.find(c => c[0] === k)).filter(Boolean)
  : COLS.filter(c => !["cost_url", "asset_class"].includes(c[0]));

function passes(f, field, op, value) {
  if (op === "text") {
    const needle = String(value).trim().toLowerCase();
    return !needle || field.split(",").some(k => String(f[k] == null ? "" : f[k]).toLowerCase().includes(needle));
  }
  const have = f[field];
  if (op === "in") {
    const wanted = Array.isArray(value) ? value : [value];
    return wanted.length === 0 || wanted.includes(have);
  }
  if (have == null) return false;
  return op === "min" ? have >= Number(value) : have <= Number(value);
}

function screenFunds(funds, filters, sort, descending, limit) {
  const active = Object.entries(filters || {}).filter(([k, v]) => v != null && v !== "" &&
    !(Array.isArray(v) && v.length === 0));
  for (const [k] of active) if (!(k in D.filters)) throw new Error("unknown filter " + k);
  const out = funds.filter(f => active.every(([k, v]) => passes(f, D.filters[k][0], D.filters[k][1], v)));
  const present = out.filter(f => f[sort] != null), missing = out.filter(f => f[sort] == null);
  const key = f => typeof f[sort] === "string" ? f[sort].toLowerCase() : f[sort];
  const cmp = (a, b) => a < b ? -1 : a > b ? 1 : 0;
  present.sort((a, b) => cmp(a.symbol, b.symbol));
  present.sort((a, b) => descending ? cmp(key(b), key(a)) : cmp(key(a), key(b)));
  missing.sort((a, b) => cmp(a.symbol, b.symbol));
  const ranked = present.concat(missing);
  return limit ? ranked.slice(0, limit) : ranked;
}
if (typeof window !== "undefined") window.screenFunds = screenFunds;

function esc(s) { return String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c])); }

function cell(f, col) {
  const [field, , cls, fmt] = col;
  const v = f[field];
  if (v == null) return `<td class="${cls}"><span class="dash" title="Not available">—</span></td>`;
  if (field === "cost_url") return /^https:\/\//.test(v) ? `<td class="${cls}"><a href="${esc(v)}" rel="noopener" ` +
    `target="_blank" title="${esc(f.sources.cost || "")}">issuer page</a></td>` : `<td class="${cls}"></td>`;
  if (!fmt) return `<td class="${cls}${field === "symbol" ? " sym" : ""}">${esc(v)}</td>`;
  let text = FMT[fmt](v);
  if (field === "cost_pct" && f.cost_kind === "management fee") text += ' <span class="dash">fee</span>';
  const neg = fmt === "pct" && field.startsWith("return") && v < 0 ? " neg" : "";
  const src = f.sources[{cost_pct: "cost", yield: "yield", aum: "aum", duration: "duration"}[field] || "performance"];
  return `<td class="${cls}${neg}" title="${esc(src || "")}">${text}</td>`;
}

const state = {sort: (typeof D !== "undefined" && D.default_sort) || "aum", desc: !(typeof D !== "undefined" && D.default_sort),
  picked: []};

function readFilters() {
  const el = id => document.getElementById(id);
  const multi = id => el(id) ? Array.from(el(id).selectedOptions).map(o => o.value) : [];
  const num = (id, scale) => { const v = el(id) ? el(id).value : ""; return v === "" ? null : Number(v) / scale; };
  return {
    text: el("f-text").value,
    asset_class: multi("f-asset_class"), category: multi("f-category"), issuer: multi("f-issuer"),
    cost_max: num("f-cost_max", 1), yield_min: num("f-yield_min", 100), aum_min: num("f-aum_min", 1 / 1e6),
    return_1y_min: num("f-return_1y_min", 100), return_3y_min: num("f-return_3y_min", 100),
    volatility_max: num("f-volatility_max", 100), drawdown_max: num("f-drawdown_max", 100),
    duration_min: num("f-duration_min", 1), duration_max: num("f-duration_max", 1),
  };
}

function render() {
  const rows = screenFunds(D.funds, readFilters(), state.sort, state.desc);
  document.getElementById("count").textContent = `${rows.length} of ${D.funds.length} funds meet your filters`;
  const head = "<tr><th class='l'></th>" + SHOWN().map(c =>
    `<th class="${c[2].split(" ")[0]}" data-k="${c[0]}">${c[1]}${state.sort === c[0] ? (state.desc ? " ▾" : " ▴") : ""}</th>`
  ).join("") + "</tr>";
  const body = rows.map(f => `<tr><td class="l"><input type="checkbox" aria-label="Compare ${esc(f.symbol)}"
    data-s="${esc(f.symbol)}" ${state.picked.includes(f.symbol) ? "checked" : ""}></td>` +
    SHOWN().map(c => cell(f, c)).join("") + "</tr>").join("");
  document.getElementById("results").innerHTML = `<thead>${head}</thead><tbody>${body}</tbody>`;
  renderTray();
}

function renderTray() {
  const tray = document.getElementById("tray");
  tray.classList.toggle("on", state.picked.length > 0);
  document.getElementById("picked").textContent = state.picked.join(", ");
}

function renderCompare() {
  const funds = state.picked.map(s => D.funds.find(f => f.symbol === s));
  const rows = SHOWN().slice(1).map(c => `<tr><th class="l">${c[1]}</th>${funds.map(f => cell(f, c)).join("")}</tr>`);
  const box = document.getElementById("compare");
  box.innerHTML = `<h2>Side by side</h2><div class="tablewrap"><table><thead><tr><th class="l"></th>${
    funds.map(f => `<th>${esc(f.symbol)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
  box.classList.add("on");
  box.scrollIntoView({behavior: "smooth"});
}

function fill(id, values) {
  document.getElementById(id).innerHTML = values.map(v => `<option>${esc(v)}</option>`).join("");
}

function boot() {
  if (window.matchMedia("(max-width:860px)").matches) document.getElementById("filters").removeAttribute("open");
  for (const k of ["asset_class", "category", "issuer"]) if (document.getElementById("f-" + k)) fill("f-" + k, D.options[k]);
  document.querySelectorAll("aside input, aside select").forEach(el => el.addEventListener("input", render));
  document.getElementById("reset").addEventListener("click", () => {
    document.querySelectorAll("aside input").forEach(el => el.value = "");
    document.querySelectorAll("aside select option").forEach(o => o.selected = false);
    render();
  });
  document.getElementById("results").addEventListener("click", e => {
    const th = e.target.closest("th[data-k]");
    if (th) { const k = th.dataset.k; state.desc = state.sort === k ? !state.desc : !["symbol", "name", "issuer",
      "category"].includes(k); state.sort = k; render(); return; }
    const box = e.target.closest("input[type=checkbox]");
    if (box) {
      const s = box.dataset.s;
      if (box.checked && state.picked.length >= D.compare_max) { box.checked = false; return; }
      state.picked = box.checked ? state.picked.concat(s) : state.picked.filter(x => x !== s);
      renderTray();
    }
  });
  document.getElementById("go-compare").addEventListener("click", renderCompare);
  document.getElementById("clear").addEventListener("click", () => { state.picked = [];
    document.getElementById("compare").classList.remove("on"); render(); });
  render();
  if (typeof bootPrices === "function") bootPrices();
}
if (typeof document !== "undefined") document.addEventListener("DOMContentLoaded", boot);
"""


def _json(data: Any) -> str:
    return json.dumps(data, separators=(",", ":")).replace("</", "<\\/")


def render(data: dict[str, Any]) -> str:
    g = data["gaps"]
    exchange = "the TSX"
    gaps = (f"{g['funds']} funds. {g['funds'] - g['no_mer']} show the issuer's MER; {g['fee_only']} show the "
            f"management fee instead, marked fee (the MER is higher). Fewer than three years of prices for "
            f"{g['under_3y']}, so their three-year figures are blank rather than estimated."
            + (f" {g['broken_prices']} have returns left blank because their price history failed a check."
               if g.get("broken_prices") else ""))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{TITLE}</title>
<meta name="description" content="Screen and compare every ETF listed on {html.escape(exchange)}: costs, yields, returns and risk computed from daily prices.">
<style>{CSS}</style></head>
<body>
<header><div class="wrap"><div class="brand">Open ETF Screener</div><h1>ETF Screener</h1>
<p class="lede">Every ETF listed on {html.escape(exchange)}, with returns and risk computed from daily prices. Choose the filters; the screener lists the funds that meet them. Data as of {html.escape(data['as_of'])}.</p>
</div></header>
<div class="layout">
<aside aria-label="Filters"><details id="filters" open><summary><h2>Filters</h2></summary>
<label for="f-text">Search ticker or name</label><input id="f-text" type="search" placeholder="e.g. XBB, bond">
<label for="f-asset_class">Asset class</label><select id="f-asset_class" multiple></select>
<label for="f-category">Category</label><select id="f-category" multiple></select>
<label for="f-issuer">Issuer</label><select id="f-issuer" multiple></select>
<div class="row2"><div><label for="f-cost_max">MER or fee at most (%)</label><input id="f-cost_max" type="number" step="0.05" min="0"></div>
<div><label for="f-yield_min">Yield at least (%)</label><input id="f-yield_min" type="number" step="0.25" min="0"></div></div>
<label for="f-aum_min">Assets at least ($M)</label><input id="f-aum_min" type="number" step="10" min="0">
<div class="row2"><div><label for="f-return_1y_min">1 yr at least (%)</label><input id="f-return_1y_min" type="number" step="1"></div>
<div><label for="f-return_3y_min">3 yr /yr at least (%)</label><input id="f-return_3y_min" type="number" step="1"></div></div>
<div class="row2"><div><label for="f-volatility_max">3 yr vol at most (%)</label><input id="f-volatility_max" type="number" step="1" min="0"></div>
<div><label for="f-drawdown_max">Max fall at most (%)</label><input id="f-drawdown_max" type="number" step="1" min="0"></div></div>
<div class="row2"><div><label for="f-duration_min">Duration from (yrs)</label><input id="f-duration_min" type="number" step="0.5" min="0"></div>
<div><label for="f-duration_max">Duration to (yrs)</label><input id="f-duration_max" type="number" step="0.5" min="0"></div></div>
<p><button id="reset" class="ghost" type="button">Clear filters</button></p>
</details></aside>
<main>
<div class="bar"><span id="count" class="count"></span><span class="note">Tick up to {data['compare_max']} funds to compare. Click a heading to sort.</span></div>
<div class="tablewrap"><table id="results"></table></div>
<p class="note">— means the figure is not available: no reliable source, or not enough price history for the window. {html.escape(gaps)}</p>
</main>
</div>
<section id="compare" class="wrap" aria-live="polite"></section>
<div id="tray" class="tray"><div class="wrap bar"><span>Comparing: <strong id="picked"></strong></span>
<span><button id="go-compare" type="button">Compare</button> <button id="clear" class="ghost" type="button">Clear</button></span></div></div>
<footer><div class="wrap">
<p><strong>About the data.</strong> {html.escape(data['data_note'])} {html.escape(data.get('risk_note') or '')}</p>
<p><strong>Important.</strong> {html.escape(DISCLOSURE)}</p>
<p>Built with the open-source <a href="{REPO}">ETF screener</a>. Fund facts CC BY 4.0. Data as of {html.escape(data['as_of'])}.</p>
</div></footer>
<script>const D={_json(data)};</script>
<script>{JS}</script>
</body></html>
"""


# -- the web screener: prices fetched in the reader's own browser with their own key ------------------------------
# Alpha Vantage confirmed in writing (2026-11-27) that a free, open-source, bring-your-own-key project needs no licence;
# a hosted service on a company's own website using its data would. So this page is built for the project's own
# GitHub Pages address, ships no price, and its only network request goes from the reader's browser to Alpha Vantage
# (the Content-Security-Policy below allows nothing else). The key and the computed figures stay in that browser.
# The figures are the same formulas as funds.window_measures; the tests hold the two to the same answers.
PRICES_JS = r"""
const AV_BASE = "https://www.alphavantage.co/query";
const AV_FUNCTIONS = {daily: ["TIME_SERIES_DAILY_ADJUSTED", "Time Series (Daily)"],
                      weekly: ["TIME_SERIES_WEEKLY_ADJUSTED", "Weekly Adjusted Time Series"]};
const PER_YEAR = {daily: 252, weekly: 52};
const PERF_SOURCE = {daily: "Computed in your browser from Alpha Vantage dividend-adjusted daily closes",
                     weekly: "Computed in your browser from Alpha Vantage dividend-adjusted weekly closes"};
const WINDOWS = [["1y", 1], ["3y", 3], ["5y", 5]];
const MAX_AGE_DAYS = 7, PLAN_RECHECK_DAYS = 30, SPACING_MS = 12500, BATCH = 20;

function avSymbol(s) { const m = String(s).toUpperCase().match(/^(.*)\.TO$/); return m ? m[1] + ".TRT" : String(s).toUpperCase(); }

function avMessage(d) { return d && typeof d === "object" ? String(d.Information || d.Note || d["Error Message"] || "") : ""; }

function avClassify(d) {
  if (d && typeof d === "object" && Object.values(AV_FUNCTIONS).some(([, k]) => d[k] && typeof d[k] === "object")) return "ok";
  const t = avMessage(d).toLowerCase();
  if (t.includes("premium")) return "plan";
  if (/rate limit|requests per day|call frequency/.test(t)) return "limit";
  if (d && d["Error Message"]) return "symbol";
  return "unknown";
}

function parseAdjusted(d) {
  const key = Object.values(AV_FUNCTIONS).map(([, k]) => k).find(k => d[k]);
  const rows = Object.entries(d[key] || {}).map(([day, v]) => [Date.parse(day + "T00:00:00Z"), Number(v["5. adjusted close"])])
    .filter(([t, v]) => isFinite(t) && v > 0).sort((a, b) => a[0] - b[0]);
  return {t: rows.map(r => r[0]), v: rows.map(r => r[1])};
}

function yearsBefore(t, years) {      // pandas DateOffset(years): the same day n years earlier, Feb 29 -> Feb 28
  const d = new Date(t), y = d.getUTCFullYear() - years, m = d.getUTCMonth();
  const out = new Date(Date.UTC(y, m, d.getUTCDate()));
  return out.getUTCMonth() === m ? out.getTime() : Date.UTC(y, m + 1, 0);
}

function windowMeasures(s, years, perYear) {
  const minCloses = Math.max(12, Math.floor(60 * perYear / 252));
  const n = s.v.length;
  if (n < minCloses) return null;
  const start = yearsBefore(s.t[n - 1], years);
  if (s.t[0] > start + 7 * 864e5) return null;
  let i0 = 0;
  for (let i = 0; i < n; i++) if (s.t[i] <= start) i0 = i;
  const w = s.v.slice(i0);
  const r = [];
  for (let i = 1; i < w.length; i++) r.push(w[i] / w[i - 1] - 1);
  if (r.length < minCloses) return null;
  const mean = r.reduce((a, b) => a + b, 0) / r.length;
  const sd = Math.sqrt(r.reduce((a, b) => a + (b - mean) * (b - mean), 0) / r.length);
  let path = 1, peak = 1, worst = 0;
  for (const x of r) { path *= 1 + x; peak = Math.max(peak, path); worst = Math.min(worst, (path - peak) / (peak + 1e-8)); }
  const total = w[w.length - 1] / w[0] - 1;
  return {ret: years > 1 ? Math.pow(1 + total, 1 / years) - 1 : total, vol: sd * Math.sqrt(perYear), dd: Math.abs(worst)};
}

function performanceOf(s, interval) {
  const out = {};
  for (const [label, years] of WINDOWS) {
    const m = windowMeasures(s, years, PER_YEAR[interval]);
    out["return_" + label] = m ? m.ret : null;
    if (label === "3y") { out.volatility_3y = m ? m.vol : null; out.max_drawdown_3y = m ? m.dd : null; }
  }
  out.last_close = s.t.length ? new Date(s.t[s.t.length - 1]).toISOString().slice(0, 10) : null;
  return out;
}
if (typeof module !== "undefined") module.exports = {avSymbol, avClassify, parseAdjusted, windowMeasures, performanceOf};

// -- storage: this browser only --------------------------------------------------------------------------------
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem(k) || sessionStorage.getItem(k) || "null"); } catch (e) { return null; } },
  set(k, v, keep = true) { try { (keep ? localStorage : sessionStorage).setItem(k, JSON.stringify(v)); } catch (e) {} },
  drop(k) { try { localStorage.removeItem(k); sessionStorage.removeItem(k); } catch (e) {} },
};
const today = () => new Date().toISOString().slice(0, 10);
const daysSince = d => (Date.parse(today()) - Date.parse(d)) / 864e5;
const cache = () => store.get("etfs.figures") || {};

function applyFigures() {
  const figs = cache();
  for (const f of D.funds) {
    const g = figs[f.symbol];
    if (!g || daysSince(g.fetched) > MAX_AGE_DAYS) continue;
    for (const k of ["return_1y", "return_3y", "return_5y", "volatility_3y", "max_drawdown_3y"]) f[k] = g[k];
    if (["return_1y", "return_3y", "return_5y"].some(k => g[k] != null)) f.sources.performance = PERF_SOURCE[g.interval];
  }
}

function plan() {
  const p = store.get("etfs.plan");
  return p && p.daily === false && daysSince(p.checked) <= PLAN_RECHECK_DAYS ? "weekly" : "daily";
}

function say(text) { document.getElementById("av-status").textContent = text; }

let running = false;
async function fetchFigures(symbols) {
  const key = store.get("etfs.key");
  if (!key) { say("Enter your Alpha Vantage key first."); return; }
  if (running) return;
  running = true;
  const figs = cache();
  const todo = symbols.filter(s => !figs[s] || daysSince(figs[s].fetched) > MAX_AGE_DAYS);
  let interval = plan(), calls = 0, done = 0;
  try {
    for (const symbol of todo) {
      if (calls) await new Promise(r => setTimeout(r, SPACING_MS));
      say(`Fetching ${symbol} (${done + 1} of ${todo.length}), ${interval} prices. The free key allows 5 calls a minute.`);
      const [fn] = AV_FUNCTIONS[interval];
      const params = new URLSearchParams({function: fn, symbol: avSymbol(symbol), apikey: key});
      if (interval === "daily") params.set("outputsize", "full");
      let data;
      try { data = await (await fetch(AV_BASE + "?" + params)).json(); }
      catch (e) { say("Alpha Vantage did not answer. Check your connection and try again."); break; }
      calls++;
      const kind = avClassify(data);
      if (kind === "plan" && interval === "daily") {
        store.set("etfs.plan", {daily: false, checked: today()});
        interval = "weekly";
        await new Promise(r => setTimeout(r, SPACING_MS));     // ask again for the same fund, weekly
        const again = new URLSearchParams({function: AV_FUNCTIONS.weekly[0], symbol: avSymbol(symbol), apikey: key});
        try { data = await (await fetch(AV_BASE + "?" + again)).json(); } catch (e) { break; }
        calls++;
      }
      const result = avClassify(data);
      if (result === "limit") { say(`Alpha Vantage says this key's allowance is used for now. ${todo.length - done} fund(s) left: try again tomorrow.`); break; }
      if (result === "ok") {
        figs[symbol] = {...performanceOf(parseAdjusted(data), interval), interval, fetched: today()};
        store.set("etfs.figures", figs);
        applyFigures(); render();
      }
      done++;
    }
    if (done === todo.length) say(todo.length ? `Done: returns and risk added for ${done} fund(s).` : "Those funds already have this week's figures.");
  } finally { running = false; }
}

function bootPrices() {
  applyFigures(); render();
  const input = document.getElementById("av-key");
  if (store.get("etfs.key")) { input.placeholder = "Key saved in this browser"; }
  document.getElementById("av-save").addEventListener("click", () => {
    const v = input.value.trim(); if (!v) return;
    store.set("etfs.key", v, document.getElementById("av-remember").checked);
    input.value = ""; input.placeholder = "Key saved in this browser"; say("Key saved in this browser only.");
  });
  document.getElementById("av-forget").addEventListener("click", () => {
    store.drop("etfs.key"); store.drop("etfs.figures"); store.drop("etfs.plan");
    input.placeholder = "Your Alpha Vantage key"; say("Key and figures removed from this browser."); location.reload();
  });
  document.getElementById("av-picked").addEventListener("click", () => fetchFigures(state.picked.slice()));
  document.getElementById("av-top").addEventListener("click", () =>
    fetchFigures(screenFunds(D.funds, readFilters(), state.sort, state.desc).slice(0, BATCH).map(f => f.symbol)));
}
"""

WEB_FILTERS = """<label for="f-text">Search ticker or name</label><input id="f-text" type="search" placeholder="e.g. XBB, bond">
<label for="f-asset_class">Asset class</label><select id="f-asset_class" multiple></select>
<label for="f-issuer">Issuer</label><select id="f-issuer" multiple></select>
<label for="f-cost_max">MER or fee at most (%)</label><input id="f-cost_max" type="number" step="0.05" min="0">
<div class="row2"><div><label for="f-return_1y_min">1 yr at least (%)</label><input id="f-return_1y_min" type="number" step="1"></div>
<div><label for="f-return_3y_min">3 yr /yr at least (%)</label><input id="f-return_3y_min" type="number" step="1"></div></div>
<div class="row2"><div><label for="f-volatility_max">3 yr vol at most (%)</label><input id="f-volatility_max" type="number" step="1" min="0"></div>
<div><label for="f-drawdown_max">Max fall at most (%)</label><input id="f-drawdown_max" type="number" step="1" min="0"></div></div>
<div class="row2"><div><label for="f-duration_min">Duration from (yrs)</label><input id="f-duration_min" type="number" step="0.5" min="0"></div>
<div><label for="f-duration_max">Duration to (yrs)</label><input id="f-duration_max" type="number" step="0.5" min="0"></div></div>
<p><button id="reset" class="ghost" type="button">Clear filters</button></p>"""

CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; "
       "connect-src https://www.alphavantage.co; base-uri 'none'; form-action 'none'")


def render_web(data: dict[str, Any]) -> str:
    """The web screener: the fund facts for every fund, and returns and risk for the funds the reader fetches."""
    g = data["gaps"]
    gaps = (f"{g['funds']} funds. {g['funds'] - g['no_mer']} show the issuer's MER; {g['fee_only']} show the "
            "management fee instead, marked fee (the MER is higher). Returns and risk appear for the funds you add "
            "prices for; a fund with too little history for a window shows a dash.")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<title>{TITLE}</title>
<meta name="description" content="Screen and compare every ETF listed on the TSX by cost, and add returns and risk with your own free Alpha Vantage key.">
<style>{CSS}
.keybox{{background:var(--brand-soft);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin-bottom:12px}}
.keybox input[type=password]{{max-width:320px;display:inline-block}} .keybox label{{display:inline;margin:0 8px 0 0}}
.keybox .row{{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:6px 0}}</style></head>
<body>
<header><div class="wrap"><div class="brand">Open ETF Screener</div><h1>ETF Screener</h1>
<p class="lede">Every ETF listed on the TSX, with the cost its issuer publishes. Add returns and risk for the funds you choose with your own free Alpha Vantage key: your browser fetches the prices directly. Fund facts as read on or before {html.escape(data['as_of'])}.</p>
</div></header>
<div class="layout">
<aside aria-label="Filters"><details id="filters" open><summary><h2>Filters</h2></summary>
{WEB_FILTERS}
</details></aside>
<main>
<section class="keybox" aria-label="Prices">
<div class="row"><strong>Returns and risk</strong> <span class="note">Prices from Alpha Vantage, fetched with your own key in this browser. Your key and the figures stay in this browser; nothing is sent to us. <a href="https://www.alphavantage.co/support/#api-key" rel="noopener" target="_blank">Get a free key</a>.</span></div>
<div class="row"><input id="av-key" type="password" autocomplete="off" placeholder="Your Alpha Vantage key" aria-label="Alpha Vantage key">
<label><input id="av-remember" type="checkbox" checked style="width:auto"> remember on this device</label>
<button id="av-save" type="button">Save key</button> <button id="av-forget" class="ghost" type="button">Forget key and figures</button></div>
<div class="row"><button id="av-top" type="button">Add returns: first 20 in the list</button> <button id="av-picked" class="ghost" type="button">Add returns: ticked funds</button>
<span id="av-status" class="note" aria-live="polite">A free key allows 25 funds a day; figures are kept for a week.</span></div>
</section>
<div class="bar"><span id="count" class="count"></span><span class="note">Tick up to {data['compare_max']} funds to compare. Click a heading to sort.</span></div>
<div class="tablewrap"><table id="results"></table></div>
<p class="note">— means the figure is not available. {html.escape(gaps)}</p>
</main>
</div>
<section id="compare" class="wrap" aria-live="polite"></section>
<div id="tray" class="tray"><div class="wrap bar"><span>Comparing: <strong id="picked"></strong></span>
<span><button id="go-compare" type="button">Compare</button> <button id="clear" class="ghost" type="button">Clear</button></span></div></div>
<footer><div class="wrap">
<p><strong>About the data.</strong> {html.escape(data['data_note'])} {html.escape(data.get('risk_note') or '')}</p>
<p><strong>Important.</strong> {html.escape(DISCLOSURE)}</p>
<p>The open-source <a href="{REPO}">ETF screener</a>. Code MIT; fund facts CC BY 4.0. Fund facts as read on or before {html.escape(data['as_of'])}.</p>
</div></footer>
<script>const D={_json(data)};</script>
<script>{JS}
{PRICES_JS}</script>
</body></html>
"""
