// First-run onboarding wizard: agent setup, or a manual profile/CV/targets flow.
import { $, esc } from '../lib/dom.js';
import { api } from '../lib/api.js';
import { toast } from '../lib/toast.js';
import { refreshMeta } from '../lib/sidebar.js';
import { refreshView } from '../lib/nav.js';
import { refreshSyncState } from '../lib/tasks.js';

let OB={};
function obEl(){return $("#onboard");}
function closeOnboard(){obEl().classList.remove("show");obEl().innerHTML="";
  refreshMeta&&refreshMeta();refreshView&&refreshView();refreshSyncState&&refreshSyncState();}
function obShell(inner){obEl().classList.add("show");obEl().innerHTML=`<div class="ob-wrap">${inner}</div>`;}
function steps(cur){return `<div class="ob-steps">`+[0,1,2,3].map(i=>`<div class="ob-step ${i<cur?"done":i===cur?"cur":""}"></div>`).join("")+`</div>`;}

export function renderOnboard(st){
  OB={data:{},cv:"",titles:[],companies:[]};
  obShell(
    `<div class="ob-logo">h</div>`+
    `<div class="ob-h1">Welcome to Huntbench</div>`+
    `<div class="ob-sub">Your job hunt as mission control. First, let's set up your profile and CV so tailoring + scoring work for <i>you</i>. Takes about 2 minutes.</div>`+
    `<div class="ob-card" id="ob-agent"><span class="em">✦</span><div><div class="t">Set up with your agent<span class="rec">recommended</span></div><div class="d">Open this folder in Claude Code / Codex / Cursor and say “set me up” — it interviews you and writes your profile + CV. We'll detect it automatically.</div></div></div>`+
    `<div class="ob-card" id="ob-manual"><span class="em">✎</span><div><div class="t">Set up manually</div><div class="d">Fill in a short form here — profile, master CV, and the roles/companies you're targeting. No agent needed.</div></div></div>`+
    `<span class="ob-skip" id="ob-demo">or explore the demo first →</span>`
  );
  $("#ob-agent").onclick=obAgent; $("#ob-manual").onclick=obProfile;
  $("#ob-demo").onclick=()=>{localStorage.setItem("hb_explore","1");closeOnboard();};
}

function obAgent(){
  obShell(
    `<div class="ob-h1" style="font-size:22px">Set up with your agent</div>`+
    `<div class="ob-sub">In your coding agent, opened on this folder, just say:</div>`+
    `<div class="ob-agentbox">1. Open <span class="ob-code">huntbench/</span> in Claude Code, Codex, or Cursor.<br>2. Say: <b style="color:var(--accent)">“set me up”</b><br>3. It reads <span class="ob-code">AGENTS.md</span>, interviews you, and writes your <span class="ob-code">config/profile.yml</span> + <span class="ob-code">config/master-cv.md</span>.</div>`+
    `<div class="ob-wait"><span class="spin"></span> Waiting for your profile to appear…</div>`+
    `<div class="ob-nav"><button class="ob-btn ghost" id="ob-back">← Back</button><button class="ob-btn ghost" id="ob-demo2">Explore the demo instead</button></div>`
  );
  $("#ob-back").onclick=()=>renderOnboard(OB);
  $("#ob-demo2").onclick=()=>{localStorage.setItem("hb_explore","1");closeOnboard();};
  const poll=setInterval(async()=>{
    if(!obEl().classList.contains("show")){clearInterval(poll);return;}
    let s;try{s=await api("/api/status");}catch(e){return;}
    if(s.has_profile){clearInterval(poll);obDone(s);}
  },3000);
}
function obDone(s){
  obShell(
    `<div class="ob-logo" style="background:var(--green)">✓</div>`+
    `<div class="ob-h1">You're all set${s.name?", "+esc(s.name.split(" ")[0]):""}!</div>`+
    `<div class="ob-sub">Your profile is in place. Next, pull in some jobs with <span class="ob-code">Scan</span> (or ask your agent to find roles), then triage them on the board.</div>`+
    `<div class="ob-nav"><span></span><button class="ob-btn" id="ob-open">Open dashboard →</button></div>`
  );
  $("#ob-open").onclick=closeOnboard;
}

function _field(id,label,hint,val,ph){return `<div class="ob-field"><label>${label}${hint?` <span class="hint">${hint}</span>`:""}</label><input id="${id}" value="${esc(val||"")}" placeholder="${esc(ph||"")}"></div>`;}
function obProfile(){
  const d=OB.data;
  obShell(steps(0)+
    `<div class="ob-h1" style="font-size:22px">Your profile</div>`+
    `<div class="ob-sub">Used to score jobs and tailor your CV + application answers.</div>`+
    `<div class="ob-row">${_field("f-name","Full name","",d.name,"Jane Doe")}${_field("f-email","Email","",d.email,"jane@example.com")}</div>`+
    `<div class="ob-row">${_field("f-phone","Phone","",d.phone,"+1 555 000 0000")}${_field("f-location","Location","",d.location,"Berlin, Germany")}</div>`+
    `<div class="ob-row">${_field("f-linkedin","LinkedIn","",d.linkedin,"linkedin.com/in/…")}${_field("f-portfolio","Portfolio","",d.portfolio,"https://…")}</div>`+
    _field("f-roles","Target roles","comma-separated",(OB.titles||[]).join(", "),"Senior Frontend Engineer, Product Engineer")+
    _field("f-headline","One-line headline","",d.headline,"Senior Frontend Engineer — 6 yrs, React/TypeScript")+
    `<div class="ob-row">${_field("f-country","Country","",d.country,"Germany")}${_field("f-city","City","",d.city,"Berlin")}</div>`+
    _field("f-auth","Work authorization","optional",d.work_auth,"EU work authorization; sponsorship for US/UK")+
    `<div class="ob-nav"><button class="ob-btn ghost" id="ob-back">← Back</button><button class="ob-btn" id="ob-next">Continue →</button></div>`
  );
  $("#ob-back").onclick=()=>renderOnboard(OB);
  $("#ob-next").onclick=async()=>{
    const g=id=>$("#"+id).value.trim();
    OB.titles=g("f-roles").split(",").map(s=>s.trim()).filter(Boolean);
    OB.data={name:g("f-name"),email:g("f-email"),phone:g("f-phone"),location:g("f-location"),
      linkedin:g("f-linkedin"),portfolio:g("f-portfolio"),headline:g("f-headline"),
      country:g("f-country"),city:g("f-city"),work_auth:g("f-auth"),roles:OB.titles};
    if(!OB.data.name||!OB.data.email){toast("err","Name + email are required");return;}
    try{await api("/api/setup/profile",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(OB.data)});
      obCV();}catch(e){toast("err","Couldn't save",e.message);}
  };
}
async function obCV(){
  let tpl="";try{tpl=(await api("/api/setup/cv-template")).template||"";}catch(e){}
  const val=OB.cv||tpl;
  obShell(steps(1)+
    `<div class="ob-h1" style="font-size:22px">Your master CV</div>`+
    `<div class="ob-sub">Paste your CV in this Markdown structure (keep the <span class="ob-code">## Section</span> headers). Or leave the template and let your agent fill it later. Mark private/unnamed work with a trailing <span class="ob-code">[STEALTH]</span>.</div>`+
    `<div class="ob-field"><textarea id="f-cv">${esc(val)}</textarea></div>`+
    `<div class="ob-nav"><button class="ob-btn ghost" id="ob-back">← Back</button><button class="ob-btn" id="ob-next">Continue →</button></div>`
  );
  $("#ob-back").onclick=obProfile;
  $("#ob-next").onclick=async()=>{OB.cv=$("#f-cv").value;
    try{await api("/api/setup/master-cv",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({markdown:OB.cv})});
      obTargets();}catch(e){toast("err","Couldn't save",e.message);}
  };
}
async function obTargets(){
  let cos=[];try{cos=(await api("/api/setup/starter-companies")).companies||[];}catch(e){}
  if(!OB.companies.length)OB.companies=cos.map(c=>c.name);   // default: all checked
  obShell(steps(2)+
    `<div class="ob-h1" style="font-size:22px">What to scan</div>`+
    `<div class="ob-sub">These become your title filter + the company boards Huntbench scans. Tune anytime in <span class="ob-code">config/portals.yml</span>.</div>`+
    _field("f-titles","Target job titles","comma-separated",(OB.titles||[]).join(", "),"Senior Frontend Engineer, Product Engineer")+
    `<label style="font-size:12.5px;font-weight:500;display:block;margin:10px 0 2px">Starter companies</label>`+
    `<div class="ob-cos" id="ob-cos">`+cos.map(c=>`<div class="ob-co ${OB.companies.includes(c.name)?"on":""}" data-n="${esc(c.name)}"><span>${OB.companies.includes(c.name)?"☑":"☐"}</span>${esc(c.name)}</div>`).join("")+`</div>`+
    `<div class="ob-nav"><button class="ob-btn ghost" id="ob-back">← Back</button><button class="ob-btn" id="ob-next">Continue →</button></div>`
  );
  $("#ob-back").onclick=obCV;
  $("#ob-cos").querySelectorAll(".ob-co").forEach(el=>el.onclick=()=>{const n=el.dataset.n;
    if(OB.companies.includes(n)){OB.companies=OB.companies.filter(x=>x!==n);el.classList.remove("on");el.querySelector("span").textContent="☐";}
    else{OB.companies.push(n);el.classList.add("on");el.querySelector("span").textContent="☑";}});
  $("#ob-next").onclick=async()=>{
    OB.titles=$("#f-titles").value.split(",").map(s=>s.trim()).filter(Boolean);
    const picked=cos.filter(c=>OB.companies.includes(c.name));
    try{await api("/api/setup/portals",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({titles:OB.titles,companies:picked})});
      obFinish();}catch(e){toast("err","Couldn't save",e.message);}
  };
}
function obFinish(){
  obShell(steps(3)+
    `<div class="ob-logo" style="background:var(--green)">✓</div>`+
    `<div class="ob-h1">Ready to go</div>`+
    `<div class="ob-sub">Your profile, CV, and scan targets are saved. Clear the demo jobs and start fresh?</div>`+
    `<label class="ob-co on" id="ob-clear" style="max-width:280px"><span>☑</span> Clear the demo jobs</label>`+
    `<div class="ob-nav"><button class="ob-btn ghost" id="ob-back">← Back</button><button class="ob-btn" id="ob-open">Open dashboard →</button></div>`
  );
  let clear=true;
  $("#ob-clear").onclick=()=>{clear=!clear;$("#ob-clear").classList.toggle("on",clear);$("#ob-clear").querySelector("span").textContent=clear?"☑":"☐";};
  $("#ob-back").onclick=obTargets;
  $("#ob-open").onclick=async()=>{
    try{await api("/api/setup/finish",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({clear_demo:clear})});}catch(e){}
    localStorage.removeItem("hb_explore"); closeOnboard();
    if(clear)toast("ok","Setup complete","run Scan to pull in jobs");
  };
}
