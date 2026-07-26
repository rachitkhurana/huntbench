// Inbox: upcoming/past interviews + communications grouped by opportunity (from synced mail).
import { $, el, esc } from '../lib/dom.js';
import { store, ACTC, A } from '../lib/state.js';
import { monogram, stpill } from '../lib/ui.js';
import { api } from '../lib/api.js';
import { registerView } from '../lib/nav.js';
import { openDetail } from './panel.js';

async function loadInbox(){
  const [d,act,sync]=await Promise.all([api("/api/interviews"),api("/api/activity"),api("/api/sync-request")]);
  $("#vcount").textContent=`${d.upcoming.length} upcoming · ${act.count} comms`;
  const c=$("#content"); c.innerHTML=""; const v=el("div","inbox"); c.appendChild(v);
  if(sync.pending)v.appendChild(el("div","banner",`⏳ Inbox sync requested${sync.at?" at "+esc(sync.at.replace("T"," ")):""} — Gmail is read by <b>Claude in chat</b>. Ask me to <b style="color:var(--accent)">sync inbox</b>.`));
  const applied=(store.META.funnel.applied||0), ivN=d.upcoming.length+d.past.length;
  v.appendChild(el("div","isummary",`<b>${applied}</b> applied · <b>${ivN}</b> interview${ivN===1?"":"s"} · <b>${act.count}</b> email${act.count===1?"":"s"} tracked`));
  v.appendChild(el("div","ihead","Upcoming interviews"));
  if(!d.upcoming.length)v.appendChild(el("div","iempty",'No upcoming interviews. Say <b style="color:var(--accent)">sync inbox</b> in chat, or log one from a job.'));
  else{const g=el("div","ivgrid");d.upcoming.forEach(x=>g.appendChild(ivcard(x,true)));v.appendChild(g);}
  if(d.past.length){v.appendChild(el("div","ihead","Past interviews"));const g=el("div","ivgrid");d.past.forEach(x=>g.appendChild(ivcard(x,false)));v.appendChild(g);}
  v.appendChild(el("div","ihead","Communications by opportunity"));
  if(!act.items.length)v.appendChild(el("div","iempty",'No communications yet. Say <b style="color:var(--accent)">sync inbox</b> — every email lands here linked to its Gmail thread.'));
  else{
    const groups={}; act.items.forEach(a=>{(groups[a.id]=groups[a.id]||{job:a,items:[]}).items.push(a);});
    const wrap=el("div","commwrap");
    Object.values(groups).sort((A,B)=>(B.items[0].date||"").localeCompare(A.items[0].date||"")).forEach(g=>wrap.appendChild(commGroup(g)));
    v.appendChild(wrap);
  }
}
function ivcard(x,up){
  const c=el("div","ivcard "+(up?"up":"past"));
  c.innerHTML=monogram(x.company)+`<div class="ivmain">`+
    `<div class="ivco">${esc(x.company)} ${stpill(x.status)}</div><div class="ivti">${esc(x.title)}</div>`+
    `<div class="ivmeta"><span class="d">${esc(x.date||"—")}</span>${x.stage?" · "+esc(x.stage):""}${x.contact?" · "+esc(x.contact):""}</div></div>`+
    (x.link?`<a class="ivlink" href="${esc(x.link)}" target="_blank" rel="noopener" title="open thread">↗</a>`:"");
  c.onclick=e=>{if(e.target.closest("a"))return;openDetail(x.id);}; return c;
}
function commGroup(g){
  const wrap=el("div","commgroup");
  const head=el("div","commhead");
  head.innerHTML=monogram(g.job.company,"sm")+`<div class="ch-main"><div class="ch-co">${esc(g.job.company)}</div><div class="ch-ti">${esc(g.job.title||"")}</div></div>`+
    `<div class="ch-right">${stpill(g.job.status)}<span class="ch-n">${g.items.length} msg${g.items.length>1?"s":""}</span></div>`;
  head.onclick=()=>openDetail(g.job.id);
  const body=el("div","commbody"); const tl=el("div","tl"); body.appendChild(tl);
  const items=g.items, LIM=3;
  items.slice(0,LIM).forEach(a=>tl.appendChild(commItem(a)));
  if(items.length>LIM){
    const hidden=el("div"); hidden.style.display="none";
    items.slice(LIM).forEach(a=>hidden.appendChild(commItem(a))); tl.appendChild(hidden);
    const more=el("div","ci-more",`+ ${items.length-LIM} more`);
    more.onclick=e=>{e.stopPropagation();const open=hidden.style.display!=="none";hidden.style.display=open?"none":"";more.textContent=open?`+ ${items.length-LIM} more`:"− show less";};
    body.appendChild(more);
  }
  wrap.appendChild(head); wrap.appendChild(body); return wrap;
}
function commItem(a){
  const col=ACTC[a.kind]||A.gray; const c=el("div","commitem"); c.style.setProperty("--dot",col);
  c.innerHTML=`<div class="ci-top"><span class="ci-date">${esc(a.date||"")}</span><span class="ci-kind" style="color:${col}">${esc(a.kind)}</span>`+
    (a.link?`<a class="ci-open" href="${esc(a.link)}" target="_blank" rel="noopener">↗ open</a>`:"")+`</div>`+
    (a.subject?`<div class="ci-sub">${esc(a.subject)}</div>`:"")+(a.contact?`<div class="ci-from">${esc(a.contact)}</div>`:"")+
    (a.detail?`<div class="ci-detail">${esc(a.detail)}</div>`:"");
  return c;
}

registerView("inbox", loadInbox);
