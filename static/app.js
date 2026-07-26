// Dashboard entry point: boot, DB live-reload watcher, command palette, keyboard nav.
// Importing the view modules for their side effect (registerView) wires the dispatcher.
import { $, el, esc, debounce } from './lib/dom.js';
import { STATE, store, SCOLOR, A } from './lib/state.js';
import { api } from './lib/api.js';
import { icon, statusIcon } from './lib/ui.js';
import { setView, refreshView } from './lib/nav.js';
import { buildChips, buildStats, syncBadges, refreshMeta, toggleSec } from './lib/sidebar.js';
import { runTask, requestSync, refreshSyncState } from './lib/tasks.js';
import { openDetail, closePanel } from './views/panel.js';
import { renderOnboard } from './views/onboard.js';
import { openAddDialog } from './lib/addjob.js';
import './views/list.js';     // registerView("list", …)  (pulls in cards.js)
import './views/saved.js';    // registerView("saved", …)
import './views/board.js';    // registerView("board", …)
import './views/inbox.js';    // registerView("inbox", …)
import './views/profile.js';  // registerView("profile", …)

// ---------- init ----------
async function init(){
  const st=await api("/api/status").catch(()=>({configured:true}));
  if(!st.configured && !localStorage.getItem("hb_explore")) renderOnboard(st);
  await bootDashboard();
}
async function bootDashboard(){
  $("#ic-list").innerHTML=icon("list"); $("#ic-saved").innerHTML=icon("saved"); $("#ic-board").innerHTML=icon("board");
  $("#ic-inbox").innerHTML=icon("inbox"); $("#ic-profile").innerHTML=icon("profile");
  store.META=await api("/api/meta");
  $("#sort").innerHTML=store.META.sorts.map(s=>`<option value="${s}">sort: ${s}</option>`).join("");
  buildChips(); buildStats(); syncBadges();
  $("#q").addEventListener("input",debounce(()=>{STATE.q=$("#q").value;refreshView();},220));
  $("#sort").addEventListener("change",()=>{STATE.sort=$("#sort").value;refreshView();});
  $("#scanBtn").onclick=()=>runTask({cmd:"scan"},"Scanning ATS portals",()=>{refreshMeta();refreshView();});
  $("#addBtn").onclick=openAddDialog;
  $("#syncBtn").onclick=requestSync; refreshSyncState();
  document.querySelectorAll(".navitem").forEach(n=>n.onclick=()=>setView(n.dataset.view));
  document.querySelectorAll(".seclabel").forEach(l=>l.onclick=()=>toggleSec(l.dataset.sec));
  document.querySelectorAll('#listmode-seg button').forEach(b=>b.onclick=()=>setListmode(b.dataset.lm));
  paintListmode();
  $("#panelClose").onclick=closePanel; $("#backdrop").onclick=closePanel;
  $("#cmdtrigger").onclick=openCmdk;
  wireCmdk(); wireKeys(); watchDb();
  setView(STATE.view);
}

// ---------- List | Cards sub-toggle (All jobs) ----------
function setListmode(v){
  STATE.listmode=v; localStorage.setItem("v2listmode",v);
  paintListmode();
  if(STATE.view!=="list")setView("list"); else refreshView();
}
function paintListmode(){
  document.querySelectorAll('#listmode-seg button').forEach(b=>b.classList.toggle("on",b.dataset.lm===STATE.listmode));
}

// ---------- live reload on DB change ----------
// Poll a cheap mtime+size token; when a tool (scan/apply/inbox sync) rewrites jobs.ndjson,
// pull the new data in place. Skipped while typing or mid-drag so we never clobber input.
function watchDb(){
  setInterval(async()=>{
    if(document.hidden||store.DRAG||/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName||""))return;
    const rev=(await api("/api/rev").catch(()=>null))?.rev; if(!rev)return;
    if(store.REV===null){store.REV=rev;return;}
    if(rev===store.REV)return;
    store.REV=rev;
    await refreshMeta(); await refreshView();
    if(store.drawerId)openDetail(store.drawerId);
  },3000);
}

// ---------- command palette ----------
let cmdItems=[], cmdSel=0;
function openCmdk(){$("#cmdkBack").classList.add("open");const i=$("#cmdkInput");i.value="";i.focus();buildCmd("");}
function closeCmdk(){$("#cmdkBack").classList.remove("open");}
function wireCmdk(){
  $("#cmdkInput").addEventListener("input",e=>buildCmd(e.target.value));
  $("#cmdkBack").addEventListener("click",e=>{if(e.target.id==="cmdkBack")closeCmdk();});
  $("#cmdkInput").addEventListener("keydown",e=>{
    if(e.key==="ArrowDown"){e.preventDefault();cmdSel=Math.min(cmdItems.length-1,cmdSel+1);paintCmd();}
    else if(e.key==="ArrowUp"){e.preventDefault();cmdSel=Math.max(0,cmdSel-1);paintCmd();}
    else if(e.key==="Enter"){e.preventDefault();cmdItems[cmdSel]&&cmdItems[cmdSel].run();}
    else if(e.key==="Escape"){closeCmdk();}
  });
}
function buildCmd(q){
  q=(q||"").toLowerCase().trim();
  const actions=[
    {t:"Go to All jobs",s:"view",hint:"",run:()=>{setView("list");closeCmdk();}},
    {t:"Go to Saved",s:"view",run:()=>{setView("saved");closeCmdk();}},
    {t:"Go to Board",s:"view",run:()=>{setView("board");closeCmdk();}},
    {t:"Go to Inbox",s:"view",run:()=>{setView("inbox");closeCmdk();}},
    {t:"Toggle card view",s:"view",run:()=>{setListmode(STATE.listmode==="cards"?"list":"cards");closeCmdk();}},
    {t:"Add job posting / board",s:"action",run:()=>{closeCmdk();openAddDialog();}},
    {t:"Scan ATS portals",s:"action",run:()=>{runTask({cmd:"scan"},"Scanning ATS portals",()=>{refreshMeta();refreshView();});closeCmdk();}},
    {t:"Sync inbox",s:"action",run:()=>{requestSync();closeCmdk();}},
    {t:"Re-render markdown views",s:"action",run:()=>{runTask({cmd:"render"},"Regenerating views");closeCmdk();}},
  ].filter(a=>!q||a.t.toLowerCase().includes(q));
  let jobs=[];
  if(q){ try{ jobs=(store.ROWS||[]).filter(r=>((r.company||"")+" "+(r.title||"")).toLowerCase().includes(q)).slice(0,7)
    .map(r=>({t:r.company+" · "+r.title,s:"job",job:r,run:()=>{closeCmdk();openDetail(r.id);}})); }catch(e){} }
  cmdItems=[...actions,...jobs]; cmdSel=0; paintCmd();
}
function paintCmd(){
  const list=$("#cmdkList"); list.innerHTML="";
  let last=null;
  cmdItems.forEach((it,i)=>{
    if(it.s!==last){list.appendChild(el("div","cmdk-sec",it.s==="view"?"Navigate":it.s==="action"?"Actions":"Jobs"));last=it.s;}
    const row=el("div","cmdk-item"+(i===cmdSel?" on":""));
    row.innerHTML=`<span class="ci-t">${esc(it.t)}</span>`+(it.s==="job"&&it.job?`<span class="stpill" style="color:${SCOLOR[it.job.status]||A.gray};border:0">${statusIcon(it.job.status,11)}</span>`:"");
    row.onmouseenter=()=>{cmdSel=i;paintCmd();}; row.onclick=()=>it.run(); list.appendChild(row);
  });
}

// ---------- keyboard ----------
function wireKeys(){
  document.addEventListener("keydown",e=>{
    if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==="k"){e.preventDefault();openCmdk();return;}
    const typing=/INPUT|TEXTAREA|SELECT/.test((e.target.tagName||""));
    if(e.key==="Escape"){if($("#cmdkBack").classList.contains("open"))closeCmdk();else closePanel();return;}
    if(typing)return;
    if(STATE.view==="list"&&(e.key==="j"||e.key==="k"||e.key==="ArrowDown"||e.key==="ArrowUp")){
      e.preventDefault(); const rows=[...document.querySelectorAll(".row,.jcard")]; if(!rows.length)return;
      rows.forEach(r=>r.classList.remove("cursor"));
      STATE.cursor+= (e.key==="j"||e.key==="ArrowDown")?1:-1;
      STATE.cursor=Math.max(0,Math.min(rows.length-1,STATE.cursor));
      const cur=rows[STATE.cursor]; cur.classList.add("cursor"); cur.scrollIntoView({block:"nearest"});
    } else if(e.key==="Enter"&&STATE.cursor>=0&&STATE.view==="list"){
      const rows=[...document.querySelectorAll(".row,.jcard")]; rows[STATE.cursor]&&openDetail(rows[STATE.cursor].dataset.id);
    }
  });
}

init().catch(e=>{document.body.innerHTML='<p style="padding:24px;color:#dc2626">Failed to load: '+esc(e.message)+'</p>';});
