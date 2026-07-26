// "＋ Add job" modal: paste a posting or board URL. Posting -> full ingest + open in the list;
// Board -> validate, add to the scan list, offer a re-scan. All backend work is POST /api/add.
import { $, esc } from './dom.js';
import { api } from './api.js';
import { toast } from './toast.js';
import { runTask } from './tasks.js';
import { setView, refreshView } from './nav.js';
import { refreshMeta } from './sidebar.js';
import { openDetail } from '../views/panel.js';

let kind = "posting";
let wired = false;

const HINTS = {
  posting: "A single job link (Greenhouse, Ashby, Lever, Workable, Recruitee, SmartRecruiters) — we fetch, score, and drop it in New. Anything else is saved as a lead to enrich later.",
  board: "A company's careers/board URL — we validate it, add it to your scan list, then offer to re-scan.",
};

function setKind(k){
  kind = k;
  document.querySelectorAll('#addSeg button').forEach(b=>b.classList.toggle('on', b.dataset.k===k));
  $("#addUrl").placeholder = k==="board" ? "Paste a job board URL…" : "Paste a job posting URL…";
  $("#addHint").textContent = HINTS[k];
  $("#addResult").innerHTML = "";
}
function closeAdd(){ $("#addBack").classList.remove("open"); }

function wire(){
  if(wired) return; wired = true;
  document.querySelectorAll('#addSeg button').forEach(b=>b.onclick=()=>setKind(b.dataset.k));
  $("#addCancel").onclick = closeAdd;
  $("#addGo").onclick = submit;
  $("#addBack").addEventListener("click", e=>{ if(e.target.id==="addBack") closeAdd(); });
  $("#addUrl").addEventListener("keydown", e=>{
    if(e.key==="Enter"){ e.preventDefault(); submit(); }
    else if(e.key==="Escape"){ closeAdd(); }
  });
}

export function openAddDialog(){
  wire();
  setKind("posting");
  $("#addUrl").value = "";
  $("#addBack").classList.add("open");
  setTimeout(()=>$("#addUrl").focus(), 30);
}

async function submit(){
  const url = $("#addUrl").value.trim();
  if(!url){ $("#addUrl").focus(); return; }
  const go = $("#addGo"); go.disabled = true; go.textContent = "Adding…";
  $("#addResult").innerHTML = "";
  try{
    const res = await api("/api/add", {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ kind, url })});
    if(kind==="posting") await onPosting(res); else onBoard(res);
  }catch(e){
    $("#addResult").innerHTML = `<span class="am-err">${esc(e.message||"Couldn't add that URL.")}</span>`;
  }finally{
    go.disabled = false; go.textContent = "Add";
  }
}

async function onPosting(res){
  const r = res.record || {};
  closeAdd();
  const lead = res.source === "lead";
  const verb = res.existed ? "Already in your list" : (lead ? "Added as a lead" : "Added");
  toast("ok", `${verb}: ${r.company||""} — ${r.title||""}`,
    lead ? "needs a JD — enrich it later" : `fit ${r.fit_score||"·"} · status new`);
  setView("list");
  await refreshMeta(); await refreshView();
  if(r.id) openDetail(r.id);
}

function onBoard(res){
  if(res.existed){
    $("#addResult").innerHTML = `<span class="am-ok">✓ <b>${esc(res.name)}</b> is already in your scan list.</span>`;
    return;
  }
  const n = res.count;
  $("#addResult").innerHTML =
    `<div class="am-ok">✓ Added <b>${esc(res.name)}</b> <span class="am-prov">${esc(res.provider)}</span> · ${n} open role${n===1?"":"s"}.</div>`+
    `<div class="am-rescan"><button class="ob-btn" id="addRescan">Re-scan now</button>`+
    `<button class="tbtn" id="addLater">Later</button></div>`;
  $("#addRescan").onclick = ()=>{ closeAdd(); runTask({cmd:"scan"}, "Re-scanning ATS portals", ()=>{refreshMeta();refreshView();}); };
  $("#addLater").onclick = closeAdd;
}
