// Sidebar: region/status filter chips, the overview mini-bars, section collapse,
// nav badges, and the meta refresh that repaints them.
import { $, el, esc } from './dom.js';
import { STATE, store, SCOLOR, FITC, SECOFF } from './state.js';
import { api } from './api.js';
import { refreshView } from './nav.js';

export function toggleSec(sec){
  if(SECOFF.has(sec))SECOFF.delete(sec); else SECOFF.add(sec);
  document.querySelectorAll('.seclabel[data-sec="'+sec+'"]').forEach(l=>l.classList.toggle("collapsed",SECOFF.has(sec)));
  document.querySelectorAll('.chips[data-sec="'+sec+'"],.mini[data-sec="'+sec+'"]').forEach(c=>c.style.display=SECOFF.has(sec)?"none":"");
}
function chip(cont,label,count,active,on){
  const c=el("span","chip"+(active?" on":""));
  c.innerHTML=esc(label)+(count!=null?` <span class="n">${count}</span>`:"");
  c.onclick=on; cont.appendChild(c);
}
export function buildChips(){
  const META=store.META;
  const rc=$("#regionChips"); rc.innerHTML="";
  chip(rc,"all",META.total,STATE.region==="",()=>{STATE.region="";refreshView();buildChips();});
  META.regions.forEach(r=>chip(rc,r,META.region_counts[r],STATE.region===r,()=>{STATE.region=STATE.region===r?"":r;refreshView();buildChips();}));
  const sc=$("#statusChips"); sc.innerHTML="";
  chip(sc,"all",null,STATE.status==="",()=>{STATE.status="";refreshView();buildChips();});
  META.statuses.forEach(s=>chip(sc,s,META.funnel[s],STATE.status===s,()=>{STATE.status=STATE.status===s?"":s;refreshView();buildChips();}));
}
export function buildStats(){
  const META=store.META;
  const box=$("#stats"); box.innerHTML="";
  const fmax=Math.max(1,...Object.values(META.funnel));
  META.statuses.filter(s=>META.funnel[s]).forEach(s=>box.appendChild(mbar(s,META.funnel[s],fmax,SCOLOR[s])));
  const xmax=Math.max(1,...Object.values(META.fit_counts));
  [5,4,3,2,1].forEach(k=>box.appendChild(mbar("fit "+k,META.fit_counts[k],xmax,FITC[k])));
}
function mbar(l,v,max,color){
  const b=el("div","mbar");
  b.innerHTML=`<span class="l">${esc(l)}</span><span class="t"><span class="f" style="width:0;background:${color}"></span></span><span class="v">${v}</span>`;
  requestAnimationFrame(()=>{b.querySelector(".f").style.width=(100*v/max)+"%";});
  return b;
}
export async function refreshMeta(){store.META=await api("/api/meta");buildChips();buildStats();syncBadges();}
export function syncBadges(){$("#nb-list").textContent=store.META.total; $("#nb-inbox").textContent=store.META.upcoming_interviews||"";
  $("#nb-saved").textContent=store.META.saved_count||"";}
