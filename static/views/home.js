// Home view — the "garden" you land on. One full-bleed canvas layer (#garden-canvas)
// spans the whole page; the floating UI (greeting, heatmap, metrics) sits on top in the
// clear top-left. Reads /api/momentum (Phase 1) + /api/status (name) + store.META (funnel).
// Pure derivation, no writes. The 3D bonsai later renders into #garden-canvas, composed so
// the tree sits right + the ground runs along the bottom (leaving the top-left clear); until
// then this is a calm, data-aware placeholder that still reflects the real hunt.
import { $, el, esc, cap } from '../lib/dom.js';
import { store } from '../lib/state.js';
import { api } from '../lib/api.js';
import { ring } from '../lib/ui.js';
import { registerView } from '../lib/nav.js';

const LAST_VISIT_KEY = "hb_last_visit";
const HEATMAP_WEEKS = 18;                 // trailing window shown in the heatmap
// Heatmap intensity ramp: empty is a faint neutral, activity is graduated --green
// (garden/growth on-theme; GitHub convention). Levels 0..4.
const HEAT = ["rgba(0,0,0,.06)", "rgba(22,163,74,.32)", "rgba(22,163,74,.54)",
              "rgba(22,163,74,.78)", "#16a34a"];

async function loadHome(){
  const since = localStorage.getItem(LAST_VISIT_KEY) || "";
  const [m, st] = await Promise.all([
    api("/api/momentum" + (since ? "?since=" + encodeURIComponent(since) : "")).catch(() => null),
    api("/api/status").catch(() => ({})),
  ]);
  $("#vcount").textContent = "";
  const c = $("#content"); c.innerHTML = "";
  if(!m){ c.appendChild(el("div", "empty", "Couldn't load your momentum data.")); return; }

  const g = m.growth || {};
  const funnel = (store.META && store.META.funnel) || {};
  const home = el("div", "home");
  home.appendChild(gardenCanvas(g));                       // z-0: full-bleed placeholder
  const ui = el("div", "home-ui");                         // z-1: floating, cardless UI
  ui.appendChild(greetingEl(firstName(st.name)));
  ui.appendChild(heatmapEl(m));
  ui.appendChild(metricsEl(m, funnel));
  home.appendChild(ui);
  c.appendChild(home);

  // Stamp this visit AFTER new_since was computed for this load (drives it next time).
  try{ localStorage.setItem(LAST_VISIT_KEY, m.today); }catch(e){}
}

// ---- greeting ----
function firstName(n){ return (String(n || "").trim().split(/\s+/)[0]) || "there"; }
function timeGreeting(){
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}
function greetingEl(name){
  return el("div", "home-greet",
    `<div class="hg-hello">${timeGreeting()}</div>` +
    `<div class="hg-name">${esc(name)}</div>`);
}

// ---- heatmap (borderless) ----
function isoDay(d){ return d.toISOString().slice(0, 10); }
function heatLevel(n){ return n <= 0 ? 0 : n <= 1 ? 1 : n <= 3 ? 2 : n <= 5 ? 3 : 4; }

// GitHub-style grid: 7 weekday rows x HEATMAP_WEEKS columns, ending today, aligned so
// each column is one Sun..Sat week. UTC to dodge timezone drift; days absent from
// daily_counts are simply level 0.
function heatCells(counts, today){
  const end = new Date(today + "T00:00:00Z");
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - (HEATMAP_WEEKS * 7 - 1));
  start.setUTCDate(start.getUTCDate() - start.getUTCDay());   // back up to Sunday
  const cells = [];
  for(let d = new Date(start); d <= end; d.setUTCDate(d.getUTCDate() + 1)){
    const iso = isoDay(d);
    cells.push({ iso, n: counts[iso] || 0 });
  }
  return cells;
}
function heatmapEl(m){
  const cells = heatCells(m.daily_counts || {}, m.today);
  const total = cells.reduce((a, c) => a + c.n, 0);
  const wrap = el("div", "hm");
  wrap.appendChild(el("div", "hm-head",
    `<span class="hm-title">Activity</span>` +
    `<span class="hm-sub">${total} action${total === 1 ? "" : "s"} in the last ${HEATMAP_WEEKS} weeks</span>`));
  const scroll = el("div", "hm-scroll");
  const grid = el("div", "hm-grid");
  grid.innerHTML = cells.map(c =>
    `<i class="hm-c" style="background:${HEAT[heatLevel(c.n)]}" title="${c.iso} · ${c.n} action${c.n === 1 ? "" : "s"}"></i>`
  ).join("");
  scroll.appendChild(grid);
  wrap.appendChild(scroll);
  wrap.appendChild(el("div", "hm-legend",
    `<span>Less</span>` + HEAT.map(col => `<i class="hm-c" style="background:${col}"></i>`).join("") + `<span>More</span>`));
  return wrap;
}

// ---- metrics (borderless row, thin dividers) ----
function metricsEl(m, funnel){
  const wrap = el("div", "metrics");
  // "Applications" = the advanced funnel (an application was actually sent).
  const applied = (funnel.applied || 0) + (funnel.screening || 0) +
                  (funnel.interviewing || 0) + (funnel.offer || 0);
  wrap.appendChild(metric("Applications", applied, "var(--accent)"));
  wrap.appendChild(metric("Interviewing", funnel.interviewing || 0, "var(--violet)"));
  wrap.appendChild(metric("Offers", funnel.offer || 0, "var(--green)"));
  wrap.appendChild(streakMetric(m.streak || 0, m.goal || {}));
  wrap.appendChild(metric("New since last visit", m.new_since || 0, "var(--blue)"));
  return wrap;
}
function metric(label, value, color){
  return el("div", "metric",
    `<div class="metric-v" style="color:${color}">${value}</div><div class="metric-l">${esc(label)}</div>`);
}
function streakMetric(streak, goal){
  const done = goal.done || 0, target = goal.target || 3;
  const frac = target ? done / target : 0;
  const col = goal.met ? "#16a34a" : "#4f7d4a";
  return el("div", "metric metric-streak",
    `<div class="ms-num"><div class="metric-v" style="color:${col}">${streak}</div>` +
    `<div class="metric-l">day streak</div></div>` +
    `<div class="goalring" title="Today: ${done} of ${target} actions">` +
      ring(frac, col, 40) + `<span class="gr-txt">${done}/${target}</span></div>`);
}

// ---- garden placeholder (full-bleed; the 3D bonsai replaces this layer's children) ----
function sproutSVG(){
  return `<svg class="gc-art" width="132" height="164" viewBox="0 0 132 164" fill="none" aria-hidden="true">` +
    `<path d="M66 164V78" stroke="#7a9033" stroke-width="3.2" stroke-linecap="round"/>` +
    `<path d="M66 106C66 106 48 101 39 86C55 81 66 92 66 106Z" fill="#8ca35b" fill-opacity=".9"/>` +
    `<path d="M66 92C66 92 84 86 95 68C78 63 66 76 66 92Z" fill="#9db566" fill-opacity=".9"/>` +
    `<path d="M66 80C66 80 55 68 57 52C69 57 69 71 66 80Z" fill="#8ca35b" fill-opacity=".95"/>` +
    `<ellipse cx="66" cy="160" rx="38" ry="5.5" fill="#000" fill-opacity=".05"/></svg>`;
}
function gardenCanvas(g){
  const stage = g.stage || "seed", pct = Math.round((g.growth || 0) * 100);
  const b = g.blossoms || 0, f = g.fruit || 0, mood = g.mood || "resting", planted = g.planted_at || "";
  const chip = (dot, txt) => `<span class="gc-chip"><i class="gc-dot" style="background:${dot}"></i>${txt}</span>`;
  const layer = el("div", "garden-canvas");
  layer.id = "garden-canvas";
  layer.innerHTML =
    `<span class="gc-soon">bonsai coming soon</span>` +
    `<div class="gc-tree">${sproutSVG()}` +
      `<div class="gc-cap"><span class="gc-stage">${esc(cap(stage))}</span>` +
      `<span class="gc-pct">${pct}% grown</span></div></div>` +
    `<div class="gc-ground">` +
      chip("#e39aa6", `${b} blossom${b === 1 ? "" : "s"} · interviews`) +
      chip("#e0863f", `${f} fruit · offers`) +
      chip("#8ca35b", `garden is ${esc(mood)}`) +
      (planted ? `<span class="gc-chip gc-planted">planted ${esc(planted)}</span>` : "") +
    `</div>`;
  return layer;
}

registerView("home", loadHome);
