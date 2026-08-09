// Right-side detail drawer + the job mutations (status/fit/notes/promote) it drives.
import { $, el, esc } from '../lib/dom.js';
import { STATE, store, SCOLOR, FITC, ACTC, A, SRCL, CHEV } from '../lib/state.js';
import { statusIcon, monogram } from '../lib/ui.js';
import { api } from '../lib/api.js';
import { toast } from '../lib/toast.js';
import { refreshView } from '../lib/nav.js';
import { refreshMeta } from '../lib/sidebar.js';
import { runTask } from '../lib/tasks.js';
import { star } from '../lib/saved.js';

export async function openDetail(id){
  store.drawerId=id; STATE.id=id;
  document.querySelectorAll(".row,.jcard").forEach(r=>r.classList.toggle("sel",r.dataset.id===id));
  const {record}=await api("/api/job/"+encodeURIComponent(id));
  renderPanel(record);
  $("#panel").classList.add("open"); $("#backdrop").classList.add("open");
}
export function closePanel(){closeMenu();store.drawerId=null;$("#panel").classList.remove("open");$("#backdrop").classList.remove("open");}
function prow(k,v){return v?`<div class="k">${esc(k)}</div><div class="v">${esc(v)}</div>`:"";}

function renderPanel(r){
  closeMenu();
  const enr=r.enrichment||{}; const rl=store.META.region_label[r.region_bucket]||r.region_bucket;
  $("#pbCrumb").textContent=(r.company||"")+" · "+(r.id||"");
  const d=$("#panelBody"); d.innerHTML="";

  // 1 · Identity
  const head=el("div","p-head"); head.dataset.id=r.id;
  head.innerHTML=monogram(r.company)+
    `<div class="p-titles"><div class="p-co">${esc(r.company)}</div><div class="p-ti">${esc(r.title)}</div></div>`;
  head.appendChild(star(r));
  d.appendChild(head);

  // 2 · Info (read-only facts; status + fit now live in the controls row below)
  const props=el("div","props");
  props.innerHTML=
    prow("Region",rl)+prow("Work mode",r.work_mode)+prow("Location",r.location)+prow("Salary",r.salary)+
    prow("Experience",r.experience_tag)+prow("Source",SRCL[r.source]||r.source)+prow("Why (fit)",r.fit_reason)+
    prow("Skills",(enr.skills||[]).join(", "))+prow("Tags",(r.tags||[]).join(", "))+prow("Promoted",r.promoted_to);
  d.appendChild(props);

  // 3 · Controls — status picker + fit picker + promote
  const controls=el("div","p-controls");
  controls.appendChild(statusChip(r));
  controls.appendChild(fitChip(r));
  const pm=el("button","tbtn",'Promote →'); pm.onclick=()=>promote(r); controls.appendChild(pm);
  d.appendChild(controls);

  // 4 · Open posting — the prominent filled CTA
  if(r.url){
    const cta=el("a","btn-primary block"); cta.href=r.url; cta.target="_blank"; cta.rel="noopener";
    cta.innerHTML=`Open posting <span style="font-size:15px;line-height:1">↗</span>`;
    d.appendChild(cta);
  }

  // 5 · Evaluation
  d.appendChild(evalSection(r));

  // 6 · Prepare & apply tools
  d.appendChild(el("div","sec","CV & apply"));
  const ab=el("div","p-tools");
  ab.appendChild(taskBtn("AI-tailor",{cmd:"tailor",id:r.id},"AI-tailoring CV to JD"));
  ab.appendChild(taskBtn("CV",{cmd:"cv",id:r.id},"Rendering CV + cover letter"));
  ab.appendChild(taskBtn("Prep apply",{cmd:"apply",id:r.id},"Building apply packet"));
  ab.appendChild(taskBtn("Liveness",{cmd:"liveness",id:r.id},"Checking URL liveness"));
  d.appendChild(ab);
  d.appendChild(el("div",null,`<div style="font-size:11px;color:var(--text3);margin-top:7px">After "Prep apply", tell Claude in chat: <b style="color:var(--accent);font-family:var(--mono)">apply to ${esc(r.id)}</b></div>`));

  // 7 · Artifacts — file tiles
  d.appendChild(el("div","sec","Artifacts"));
  const art=el("div","filetiles",`<span class="ft-empty">—</span>`); d.appendChild(art); loadArtifacts(r.id,art);

  // 8 · Notes
  d.appendChild(el("div","sec","Notes"));
  const ta=el("textarea"); ta.value=r.notes||""; ta.placeholder="Notes…"; d.appendChild(ta);
  const sn=el("button","tbtn","Save note"); sn.style.marginTop="7px"; sn.onclick=()=>update(r.id,{notes:ta.value}); d.appendChild(sn);

  // 9 · Activity
  d.appendChild(el("div","sec","Activity"));
  const aw=el("div");
  const lb=el("button","tbtn","+ Log interview"); lb.style.marginBottom="9px"; lb.onclick=()=>toggleLog(aw,r.id); aw.appendChild(lb);
  const acts=(r.activity||[]).slice().sort((a,b)=>(b.date||"").localeCompare(a.date||""));
  if(!acts.length)aw.appendChild(el("div",null,`<div style="color:var(--text3);font-size:12px">No activity yet — log an interview, or say "sync inbox" in chat.</div>`));
  acts.forEach(a=>aw.appendChild(actCard(a))); d.appendChild(aw);

  // 10 · Job description
  if(enr.description){d.appendChild(el("div","sec","Job description"));d.appendChild(el("div","jd",esc(enr.description)));}
}

// ---------- status / fit chip pickers ----------
function statusChip(r){
  const col=SCOLOR[r.status]||A.gray;
  const wrap=el("div","chip-select");
  const trig=el("button","cs-trig");
  trig.innerHTML=`<span class="cs-lab">Status</span>${statusIcon(r.status,12)}`+
    `<span style="color:${col};text-transform:capitalize">${esc(r.status)}</span><span class="cs-chev">${CHEV}</span>`;
  trig.onclick=e=>{e.stopPropagation();
    openMenu(wrap, store.META.statuses.map(s=>({
      value:s, on:s===r.status,
      html:`${statusIcon(s,12)}<span style="color:${SCOLOR[s]||A.gray};text-transform:capitalize">${esc(s)}</span>`
    })), s=>{ if(s!==r.status) update(r.id,{status:s}); });
  };
  wrap.appendChild(trig); return wrap;
}
const FITW={5:"Excellent",4:"Strong",3:"Fair",2:"Weak",1:"Poor"};
function fitChip(r){
  const f=r.fit_score; const col=f?(FITC[f]||A.gray):A.gray;
  const wrap=el("div","chip-select");
  const trig=el("button","cs-trig");
  trig.innerHTML=`<span class="cs-lab">Fit</span><span style="color:${col};font-weight:600">${f||"?"}</span><span class="cs-chev">${CHEV}</span>`;
  trig.onclick=e=>{e.stopPropagation();
    openMenu(wrap, [5,4,3,2,1].map(n=>({
      value:n, on:n===f,
      html:`<span style="color:${FITC[n]||A.gray};font-weight:600;font-family:var(--mono);width:14px;display:inline-block">${n}</span>`+
           `<span style="color:var(--text2)">${FITW[n]}</span>`
    })), n=>{ if(n!==f) update(r.id,{fit:n}); });
  };
  wrap.appendChild(trig); return wrap;
}

// ---------- one lightweight popover (single-open, outside-click / re-click to close) ----------
let _menu=null;
function _onDoc(e){ if(_menu && !_menu.parentNode.contains(e.target)) closeMenu(); }
function closeMenu(){ if(_menu){_menu.remove();_menu=null;document.removeEventListener("mousedown",_onDoc,true);} }
function openMenu(anchorWrap, items, onPick){
  const wasHere=_menu && _menu.parentNode===anchorWrap; closeMenu(); if(wasHere)return;
  const m=el("div","menu");
  items.forEach(it=>{const mi=el("div","menuitem"+(it.on?" on":""),it.html);
    mi.onclick=e=>{e.stopPropagation();closeMenu();onPick(it.value);}; m.appendChild(mi);});
  anchorWrap.appendChild(m); _menu=m;
  setTimeout(()=>document.addEventListener("mousedown",_onDoc,true),0);
}

// ---------- artifacts as file tiles ----------
const FT_COLOR={pdf:"#dc2626",html:"#4f7d4a",txt:"#8a8f80",json:"#d98e26",md:"#8b5cf6"};
function friendlyArtifact(name){
  const ext=(name.split(".").pop()||"").toLowerCase();
  const base=name.toLowerCase();
  const label = base.startsWith("cv") ? "CV"
              : base.startsWith("cover-letter") ? "Cover letter"
              : base.startsWith("apply-packet") ? "Apply packet"
              : name;
  return {ext:ext.toUpperCase(), label, color:FT_COLOR[ext]||"#9ca3af"};
}
function fileTile(name,path){
  const {ext,label,color}=friendlyArtifact(name);
  const a=el("a","filetile"); a.href="/api/file?path="+encodeURIComponent(path); a.target="_blank"; a.rel="noopener";
  a.innerHTML=`<span class="ft-badge" style="background:${color}">${esc(ext)}</span>`+
    `<span class="ft-meta"><span class="ft-name">${esc(name)}</span><span class="ft-label">${esc(label)}</span></span>`;
  return a;
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
    const files=Object.entries(a.files).filter(([,v])=>v);
    if(!files.length){box.innerHTML=`<span class="ft-empty">none yet — run CV or Prep apply</span>`;return;}
    box.innerHTML=""; files.forEach(([k,v])=>box.appendChild(fileTile(k,v)));
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

// ---------- deep evaluation section (rubric + risk flags) ----------
function verdictTag(o){return o>=4?["worth pursuing","#16a34a"]:(o===3?["marginal","#d98e26"]:["skip","#dc2626"]);}
const EVAX=[["role","Role"],["seniority","Seniority"],["comp","Comp"],["location","Location"],["stack","Stack"]];
function evalSection(r){
  const wrap=el("div"); wrap.style.marginTop="4px";
  const head=el("div","sec"); head.style.cssText="display:flex;align-items:center;gap:8px";
  head.appendChild(el("span",null,"Evaluation"));
  const btn=taskBtn(r.evaluation?"Re-evaluate":"Evaluate",{cmd:"evaluate",id:r.id},"Evaluating role fit + risk");
  btn.style.cssText="margin-left:auto;padding:2px 9px;font-size:11px"; head.appendChild(btn);
  wrap.appendChild(head);
  const ev=r.evaluation;
  if(!ev){wrap.appendChild(el("div",null,`<div style="color:var(--text3);font-size:12px">Not evaluated yet — click Evaluate for a deep read (role fit, comp, location, scam/ghost check).</div>`));return wrap;}
  const [vt,vc]=verdictTag(ev.overall||3);
  const top=el("div"); top.style.cssText="display:flex;align-items:center;gap:10px;margin:2px 0 10px";
  top.innerHTML=`<span style="font:600 20px var(--mono,monospace);color:${vc}">${ev.overall||"–"}/5</span>`+
    `<span style="font-size:11px;color:${vc};border:1px solid ${vc};border-radius:10px;padding:1px 8px">${esc(vt)}</span>`+
    (ev.method==="ai"?`<span style="font-size:10px;color:var(--text3);border:1px solid var(--border,#ddd);border-radius:8px;padding:1px 6px">AI</span>`:"");
  wrap.appendChild(top);
  const axes=ev.axes||{};
  EVAX.forEach(([k,label])=>{
    const v=axes[k]; const c=v>=4?"#16a34a":(v>=3?"#d98e26":(v?"#dc2626":"var(--border,#ddd)")); const pct=v?(v/5*100):0;
    const row=el("div"); row.style.cssText="display:flex;align-items:center;gap:8px;margin:3px 0";
    row.innerHTML=`<span style="font-size:11px;color:var(--text2);width:66px">${label}</span>`+
      `<span style="flex:1;height:5px;background:var(--surface2,#eee);border-radius:3px;overflow:hidden"><i style="display:block;height:100%;width:${pct}%;background:${c}"></i></span>`+
      `<span style="font-size:11px;color:var(--text3);width:16px;text-align:right">${v||"–"}</span>`;
    wrap.appendChild(row);
  });
  if((ev.flags||[]).length){
    const fl=el("div"); fl.style.cssText="margin-top:9px;display:flex;flex-wrap:wrap;gap:5px";
    fl.innerHTML=ev.flags.map(f=>`<span style="font-size:11px;color:#dc2626;background:rgba(220,38,38,.09);border-radius:6px;padding:2px 7px">⚠ ${esc(f)}</span>`).join("");
    wrap.appendChild(fl);
  }
  if(ev.verdict){const v=el("div"); v.style.cssText="margin-top:9px;font-size:12.5px;color:var(--text2);line-height:1.5"; v.textContent=ev.verdict; wrap.appendChild(v);}
  return wrap;
}
