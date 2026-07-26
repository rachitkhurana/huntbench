// Long-running tool runner (scan/cv/tailor/apply/liveness/render) + inbox-sync request.
import { $, el, esc } from './dom.js';
import { api } from './api.js';
import { toast } from './toast.js';

export async function runTask(body,msg,onDone){
  const t=toast("run",msg,body.cmd,true); const t0=Date.now();
  const tick=setInterval(()=>{const s=t.querySelector(".sub");if(s)s.textContent=`${body.cmd} · ${Math.round((Date.now()-t0)/1000)}s…`;},1000);
  try{const {tid}=await api("/api/tasks",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    const poll=setInterval(async()=>{let s;try{s=await api("/api/tasks/"+tid);}catch(e){return;} if(s.status==="running")return;
      clearInterval(poll);clearInterval(tick); t.className="toast "+(s.status==="done"?"ok":"err");
      t.innerHTML=`<div>${esc(msg)} — ${s.status} (${Math.round((Date.now()-t0)/1000)}s)</div><div class="sub">${esc((s.log||"").split("\n").slice(-1)[0].slice(0,150))}</div>`;
      setTimeout(()=>t.remove(),6000); if(s.status==="done"&&onDone)onDone();
    },1200);
  }catch(e){clearInterval(tick);t.className="toast err";t.innerHTML=`<div>${esc(msg)} — failed</div><div class="sub">${esc(e.message)}</div>`;}
}
export async function requestSync(){
  try{await api("/api/sync-request",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({})});
    $("#syncBtn").classList.add("pending"); toast("ok","Inbox sync requested",'Claude reads your Gmail in chat → lands in Inbox. Say "sync inbox".');
  }catch(e){toast("err","Request failed",e.message);}
}
export async function refreshSyncState(){try{const d=await api("/api/sync-request");$("#syncBtn").classList.toggle("pending",!!d.pending);}catch(e){}}
