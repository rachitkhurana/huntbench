// Profile view: the master CV as a rendered preview (same builder as the PDF) + a markdown editor.
import { $, el, esc } from '../lib/dom.js';
import { api } from '../lib/api.js';
import { toast } from '../lib/toast.js';
import { registerView } from '../lib/nav.js';

let CVMODE="preview", CVTPL=null;

async function loadProfile(){
  const t=await api("/api/cv-templates").catch(()=>({templates:[],current:"classic"}));
  if(!CVTPL)CVTPL=t.current;
  $("#vcount").textContent="config/master-cv.md";
  const c=$("#content"); c.innerHTML="";
  const w=el("div","cvwrap",
    `<div class="cvbar">`+
      `<div class="seg"><button data-m="preview">Preview</button><button data-m="edit">Edit</button></div>`+
      `<select id="cv-tpl" class="tbtn" title="CV template">`+
        t.templates.map(x=>`<option value="${esc(x.id)}"${x.id===CVTPL?" selected":""}>${esc(x.label)}</option>`).join("")+
      `</select>`+
      `<button class="tbtn" id="cv-pdf">↓ PDF</button>`+
      `<span class="sp" style="flex:1"></span>`+
      `<span class="cvhint" id="cv-hint"></span>`+
      `<button class="ob-btn" id="cv-save" style="display:none">Save</button>`+
    `</div><div id="cv-body"></div>`);
  c.appendChild(w);
  w.querySelectorAll(".seg button").forEach(b=>{
    b.classList.toggle("on",b.dataset.m===CVMODE);
    b.onclick=()=>{CVMODE=b.dataset.m;loadProfile();};
  });
  // Picking a template persists it, so `jobsdb cv` generates what the preview shows.
  $("#cv-tpl").onchange=async e=>{
    CVTPL=e.target.value;
    await api("/api/cv-template",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({template:CVTPL})}).catch(()=>{});
    if(CVMODE==="preview"){$("#cv-body").innerHTML="";cvPreview();}
  };
  $("#cv-pdf").onclick=cvPdf;
  return CVMODE==="edit"?cvEdit():cvPreview();
}
function cvPreview(){
  $("#cv-hint").textContent="rendered exactly as the generated PDF";
  const f=el("iframe","cvpaper"); f.src="/api/cv-preview?template="+encodeURIComponent(CVTPL)+"&t="+Date.now();
  f.onload=()=>{try{f.style.height=(f.contentDocument.body.scrollHeight+64)+"px";}catch(e){}};
  $("#cv-body").appendChild(f);
}
async function cvPdf(){
  const b=$("#cv-pdf"); b.disabled=true; b.textContent="rendering…";
  try{
    const r=await fetch("/api/cv-pdf?template="+encodeURIComponent(CVTPL));
    if(!r.ok)throw new Error((await r.json().catch(()=>({}))).error||r.status);
    const url=URL.createObjectURL(await r.blob());
    const a=el("a"); a.href=url; a.download="cv.pdf"; a.click(); URL.revokeObjectURL(url);
    toast("ok","PDF downloaded");
  }catch(e){toast("err","PDF failed",e.message);}
  b.disabled=false; b.textContent="↓ PDF";
}
async function cvEdit(){
  const d=await api("/api/setup/master-cv").catch(()=>({markdown:""}));
  $("#cv-hint").innerHTML=`⌘S to save · keep the <span class="ob-code">## Section</span> headers`;
  $("#cv-body").innerHTML=`<div class="ob-field"><textarea id="cv-ta" spellcheck="false"></textarea></div>`;
  const ta=$("#cv-ta"); ta.value=d.markdown||"";
  const btn=$("#cv-save"); btn.style.display="";
  const save=async()=>{
    try{await api("/api/setup/master-cv",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({markdown:ta.value})});
      toast("ok","CV saved","config/master-cv.md"); CVMODE="preview"; loadProfile();
    }catch(e){toast("err","Couldn't save",e.message);}
  };
  btn.onclick=save;
  ta.addEventListener("keydown",e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==="s"){e.preventDefault();save();}});
}

registerView("profile", loadProfile);
