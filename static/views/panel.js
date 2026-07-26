// Right-side detail drawer + the job mutations (status/fit/notes/promote) it drives.
import { $, el, esc } from '../lib/dom.js';
import { STATE, store, SCOLOR, ACTC, A } from '../lib/state.js';
import { statusIcon, fitStyle, stpill } from '../lib/ui.js';
import { api } from '../lib/api.js';
import { toast } from '../lib/toast.js';
import { refreshView } from '../lib/nav.js';
import { refreshMeta } from '../lib/sidebar.js';
import { runTask } from '../lib/tasks.js';

export async function openDetail(id){
  store.drawerId=id; STATE.id=id;
  document.querySelectorAll(".row,.jcard").forEach(r=>r.classList.toggle("sel",r.dataset.id===id));
  const {record}=await api("/api/job/"+encodeURIComponent(id));
  renderPanel(record);
  $("#panel").classList.add("open"); $("#backdrop").classList.add("open");
}
export function closePanel(){store.drawerId=null;$("#panel").classList.remove("open");$("#backdrop").classList.remove("open");}
function prow(k,v){return v?`<div class="k">${esc(k)}</div><div class="v">${esc(v)}</div>`:"";}
function renderPanel(r){
  const enr=r.enrichment||{}; const rl=store.META.region_label[r.region_bucket]||r.region_bucket;
  $("#pbCrumb").textContent=(r.company||"")+" · "+(r.id||"");
  const d=$("#panelBody"); d.innerHTML="";
  d.appendChild(el("div",null,`<div class="p-co">${esc(r.company)}</div><div class="p-ti">${esc(r.title)}</div>`));
  const props=el("div","props");
  props.innerHTML=`<div class="k">Status</div><div class="v">${stpill(r.status)}</div>`+
    `<div class="k">Fit</div><div class="v"><span class="fitb" style="${fitStyle(r.fit_score)}">${r.fit_score||"?"}</span></div>`+
    prow("Region",rl)+prow("Work mode",r.work_mode)+prow("Location",r.location)+prow("Salary",r.salary)+
    prow("Experience",r.experience_tag)+prow("Why (fit)",r.fit_reason)+
    prow("Skills",(enr.skills||[]).join(", "))+prow("Tags",(r.tags||[]).join(", "))+prow("Promoted",r.promoted_to);
  d.appendChild(props);
  if(r.url){const u=el("div");u.style.margin="8px 0";u.innerHTML=`<a href="${esc(r.url)}" target="_blank" rel="noopener">↗ open posting</a>`;d.appendChild(u);}

  d.appendChild(el("div","sec","Set status"));
  const sm=el("div","stmenu");
  store.META.statuses.forEach(s=>{const col=SCOLOR[s]||A.gray;const b=el("button","stopt"+(s===r.status?" on":""),`${statusIcon(s,11)}${s}`);
    b.style.color=(s===r.status)?col:"var(--text2)"; b.onclick=()=>update(r.id,{status:s}); sm.appendChild(b);});
  d.appendChild(sm);
  const fitrow=el("div"); fitrow.style.margin="12px 0"; fitrow.innerHTML=`<span style="color:var(--text3);font-size:12px;margin-right:8px">Fit</span>`;
  const fs=el("span","fitset"); [1,2,3,4,5].forEach(f=>{const b=el("button",f===r.fit_score?"on":"",String(f));b.onclick=()=>update(r.id,{fit:f});fs.appendChild(b);}); fitrow.appendChild(fs);
  const pm=el("button","tbtn",'Promote →'); pm.style.marginLeft="10px"; pm.onclick=()=>promote(r); fitrow.appendChild(pm);
  d.appendChild(fitrow);

  const ta=el("textarea"); ta.value=r.notes||""; ta.placeholder="Notes…"; d.appendChild(ta);
  const sn=el("button","tbtn","Save note"); sn.style.marginTop="7px"; sn.onclick=()=>update(r.id,{notes:ta.value}); d.appendChild(sn);

  d.appendChild(el("div","sec","CV & apply"));
  const ab=el("div","actionbtns");
  ab.appendChild(taskBtn("CV",{cmd:"cv",id:r.id},"Rendering CV + cover letter"));
  ab.appendChild(taskBtn("AI-tailor",{cmd:"tailor",id:r.id},"AI-tailoring CV to JD"));
  ab.appendChild(taskBtn("Prep apply",{cmd:"apply",id:r.id},"Building apply packet"));
  ab.appendChild(taskBtn("Liveness",{cmd:"liveness",id:r.id},"Checking URL liveness"));
  d.appendChild(ab);
  d.appendChild(el("div",null,`<div style="font-size:11px;color:var(--text3);margin-top:7px">After "Prep apply", tell Claude in chat: <b style="color:var(--accent);font-family:var(--mono)">apply to ${esc(r.id)}</b></div>`));

  d.appendChild(el("div","sec","Artifacts"));
  const art=el("div","artifacts",`<span style="color:var(--text3)">—</span>`); d.appendChild(art); loadArtifacts(r.id,art);

  d.appendChild(el("div","sec","Activity"));
  const aw=el("div");
  const lb=el("button","tbtn","+ Log interview"); lb.style.marginBottom="9px"; lb.onclick=()=>toggleLog(aw,r.id); aw.appendChild(lb);
  const acts=(r.activity||[]).slice().sort((a,b)=>(b.date||"").localeCompare(a.date||""));
  if(!acts.length)aw.appendChild(el("div",null,`<div style="color:var(--text3);font-size:12px">No activity yet — log an interview, or say "sync inbox" in chat.</div>`));
  acts.forEach(a=>aw.appendChild(actCard(a))); d.appendChild(aw);

  if(enr.description){d.appendChild(el("div","sec","Job description"));d.appendChild(el("div","jd",esc(enr.description)));}
}
function actCard(a){
  const col=ACTC[a.kind]||A.gray; const c=el("div","actcard"); c.style.borderLeftColor=col;
  c.innerHTML=`<div class="ci-top"><span class="actkind" style="color:${col}">${esc(a.kind)}</span><span class="ci-date" style="margin-left:auto">${esc(a.date||"")}</span></div>`+
    (a.title?`<div class="ci-sub">${esc(a.title)}</div>`:"")+(a.contact?`<div class="ci-from">${esc(a.contact)}</div>`:"")+
    (a.detail?`<div class="ci-detail">${esc(a.detail)}</div>`:"")+
    (a.link?`<a style="font:11px var(--mono)" href="${esc(a.link)}" target="_blank" rel="noopener">↗ open ${a.kind==="email"?"email":"link"}</a>`:"");
  return c;
}
function toggleLog(wrap,id){
  const ex=wrap.querySelector(".logform"); if(ex){ex.remove();return;}
  const f=el("div","logform");
  f.innerHTML=`<input type="date" class="lf-date"><select class="lf-stage"><option>Screen call</option><option>Technical</option><option>Hiring manager</option><option>Onsite</option><option>Final</option></select><input class="lf-contact" placeholder="contact"><input class="lf-note" placeholder="note">`;
  const s=el("button","tbtn","Save");
  s.onclick=async()=>{const date=f.querySelector(".lf-date").value; if(!date){toast("err","Pick a date");return;}
    try{await api("/api/job/"+encodeURIComponent(id)+"/activity",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({kind:"interview",date,title:f.querySelector(".lf-stage").value,contact:f.querySelector(".lf-contact").value,detail:f.querySelector(".lf-note").value,status:"interviewing",source:"manual"})});
      toast("ok","Interview logged"); await refreshMeta(); if(store.drawerId===id)openDetail(id); refreshView();
    }catch(e){toast("err","Log failed",e.message);}};
  f.appendChild(s); wrap.prepend(f);
}
async function loadArtifacts(id,box){
  try{const a=await api("/api/job/"+encodeURIComponent(id)+"/artifacts");
    const links=Object.entries(a.files).filter(([,v])=>v).map(([k,v])=>`<a href="/api/file?path=${encodeURIComponent(v)}" target="_blank" rel="noopener">${esc(k)}</a>`);
    box.innerHTML=links.length?links.join(""):`<span style="color:var(--text3)">none yet — run CV or Prep apply</span>`;
  }catch(e){}
}

// ---------- mutations ----------
export async function update(id,changes,opts){opts=opts||{};
  try{const {record}=await api("/api/job/"+encodeURIComponent(id)+"/update",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(changes)});
    toast("ok","Saved",Object.keys(changes).join(", ")); await refreshMeta();
    if(!opts.skipView)refreshView();
    if(store.drawerId===id)renderPanel(record);
  }catch(e){toast("err","Save failed",e.message); if(opts.skipView)refreshView();}
}
async function promote(r){
  const slug=prompt("Opportunity slug:",(r.company+" "+r.title).toLowerCase().replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"").slice(0,60));
  if(!slug)return;
  try{const d=await api("/api/job/"+encodeURIComponent(r.id)+"/promote",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({slug})});
    toast("ok",d.created?"Promoted + scaffold":"Promoted",d.path); await refreshMeta(); refreshView(); if(store.drawerId===r.id)openDetail(r.id);
  }catch(e){toast("err","Promote failed",e.message);}
}

// ---------- task buttons (panel-local; wraps runTask with a re-open callback) ----------
function taskBtn(label,body,msg){const b=el("button","tbtn",label);b.onclick=()=>runTask(body,msg,()=>{if(body.id&&store.drawerId===body.id)openDetail(body.id);});return b;}
