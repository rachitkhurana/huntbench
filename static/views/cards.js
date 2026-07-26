// Card renderer for the "All jobs" view. Same data as a list row (the /api/jobs projection),
// laid out as a richer card. `cardGridBody` is dropped into the shared status grouping by
// list.js when STATE.listmode === "cards".
import { el, esc } from '../lib/dom.js';
import { STATE, store, WML, EXPL, TAG_SKIP, cleanLoc } from '../lib/state.js';
import { monogram, stpill, fitStyle } from '../lib/ui.js';
import { openDetail } from './panel.js';
import { star } from '../lib/saved.js';

export function cardEl(r){
  const card=el("div","jcard"+(r.id===STATE.id?" sel":"")); card.dataset.id=r.id;
  const meta=[];
  const loc=cleanLoc(r.location); if(loc)meta.push(`<span class="loc">${esc(loc)}</span>`);
  const exp=EXPL[r.experience_tag]; if(exp)meta.push(`<span class="exp">${esc(exp)}</span>`);
  if(r.salary)meta.push(`<span class="sal">${esc(r.salary)}</span>`);
  const tags=(r.tags||[]).filter(t=>!TAG_SKIP.has((t||"").toLowerCase())).slice(0,2)
    .map(t=>`<span class="tg">${esc(t)}</span>`).join("");
  const wm=(r.work_mode&&r.work_mode!=="unknown")?`<span class="wm wm-${r.work_mode}">${WML[r.work_mode]||r.work_mode}</span>`:"";
  card.innerHTML=
    `<div class="jc-top">${monogram(r.company,"sm")}<span class="jc-co">${esc(r.company)}</span>`+
      `<span class="fitb" style="${fitStyle(r.fit_score)}">${r.fit_score||"·"}</span></div>`+
    `<div class="jc-ti">${esc(r.title)}</div>`+
    `<div class="jc-meta">${stpill(r.status)}${meta.map(m=>'<span class="sep">·</span>'+m).join("")}</div>`+
    `<div class="jc-foot">${wm}${tags}<span class="sp"></span><span class="rtag">${esc(store.META.region_abbr[r.region_bucket]||"?")}</span></div>`;
  card.querySelector(".jc-top").appendChild(star(r));
  card.onclick=()=>openDetail(r.id);
  return card;
}

export function cardGridBody(rows){const g=el("div","cardgrid"); rows.forEach(r=>g.appendChild(cardEl(r))); return g;}
