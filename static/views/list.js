// "All jobs" view. Fetches once, groups by status into collapsible sections. The body of
// each group is built by a pluggable `buildBody` so the same grouping serves the row list
// today and the card grid (Part B) tomorrow.
import { $, el, esc, cap } from '../lib/dom.js';
import { STATE, store, COLLAPSE, CHEV, WML, EXPL, TAG_SKIP, cleanLoc } from '../lib/state.js';
import { statusIcon, fitStyle } from '../lib/ui.js';
import { api } from '../lib/api.js';
import { registerView } from '../lib/nav.js';
import { openDetail } from './panel.js';
import { cardGridBody } from './cards.js';

async function loadAllJobs(){
  const p=new URLSearchParams({region:STATE.region,status:STATE.status,q:STATE.q,sort:STATE.sort});
  const d=await api("/api/jobs?"+p); store.ROWS=d.jobs;
  $("#vcount").textContent=`${d.count}`;
  const c=$("#content"); c.innerHTML="";
  if(!store.ROWS.length){c.appendChild(el("div","empty","No jobs match these filters."));return;}
  renderGrouped(c, STATE.listmode==="cards" ? cardGridBody : listBody);
}

// Shared status-grouping: `buildBody(rows)` returns the DOM node placed under each header.
export function renderGrouped(c, buildBody){
  const by={}; store.ROWS.forEach(r=>{(by[r.status]=by[r.status]||[]).push(r);});
  store.META.statuses.forEach(s=>{
    const rows=by[s]; if(!rows||!rows.length)return;
    const head=el("div","grouphead"+(COLLAPSE.has(s)?" collapsed":""));
    head.innerHTML=`<span class="chev">${CHEV}</span>${statusIcon(s)}<span>${cap(s)}</span><span class="cnt">${rows.length}</span>`;
    const body=buildBody(rows); if(COLLAPSE.has(s))body.style.display="none";
    head.onclick=()=>{COLLAPSE.has(s)?COLLAPSE.delete(s):COLLAPSE.add(s);head.classList.toggle("collapsed");body.style.display=COLLAPSE.has(s)?"none":"";};
    c.appendChild(head); c.appendChild(body);
  });
}
function listBody(rows){const b=el("div"); rows.forEach(r=>b.appendChild(rowEl(r))); return b;}

function rowEl(r){
  const row=el("div","row"+(r.id===STATE.id?" sel":"")); row.dataset.id=r.id;
  const sub=[];
  const loc=cleanLoc(r.location); if(loc)sub.push(`<span class="loc">${esc(loc)}</span>`);
  const exp=EXPL[r.experience_tag]; if(exp)sub.push(`<span class="exp">${esc(exp)}</span>`);
  const tags=(r.tags||[]).filter(t=>!TAG_SKIP.has((t||"").toLowerCase())).slice(0,2);
  const tagHtml=tags.map(t=>`<span class="tg">${esc(t)}</span>`).join("");
  const subLine=sub.join('<span class="sep">·</span>')+(tags.length?` ${tagHtml}`:"");
  const wm=(r.work_mode&&r.work_mode!=="unknown")?`<span class="wm wm-${r.work_mode}">${WML[r.work_mode]||r.work_mode}</span>`:"";
  row.innerHTML=`<span class="sicon">${statusIcon(r.status)}</span>`+
    `<div class="rmain">`+
      `<div class="rtop"><span class="co">${esc(r.company)}</span><span class="ti">${esc(r.title)}</span></div>`+
      (subLine.trim()?`<div class="rsub">${subLine}</div>`:"")+
    `</div>`+
    `<div class="rright">${wm}<span class="rtag">${esc(store.META.region_abbr[r.region_bucket]||"?")}</span>`+
      `<span class="fitb" style="${fitStyle(r.fit_score)}">${r.fit_score||"·"}</span></div>`;
  row.onclick=()=>openDetail(r.id);
  return row;
}

registerView("list", loadAllJobs);
