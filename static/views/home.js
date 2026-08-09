// Home view — the page you land on. A calm, cardless summary of the hunt: a greeting, the
// activity heatmap, and a borderless metrics row (applications, interviewing, offers, streak +
// today's goal ring, new-since-last-visit). Reads /api/momentum (Phase 1) + /api/status (name)
// + store.META (funnel). Pure derivation, no writes. (The 3D bonsai garden lands later, on
// feat/momentum-bonsai.)
import { $, el, esc } from '../lib/dom.js';
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

  const funnel = (store.META && store.META.funnel) || {};
  const home = el("div", "home");
  home.appendChild(greetingEl(firstName(st.name)));
  home.appendChild(heatmapEl(m));
  home.appendChild(metricsEl(m, funnel));
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

registerView("home", loadHome);
