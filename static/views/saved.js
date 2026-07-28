// Saved view — only the jobs the user has ★-saved. Reuses the list's grouped rendering
// (and the List/Cards toggle) via renderGrouped + currentBody from list.js.
import { $, el } from '../lib/dom.js';
import { STATE, store } from '../lib/state.js';
import { api } from '../lib/api.js';
import { registerView } from '../lib/nav.js';
import { renderGrouped, currentBody } from './list.js';

async function loadSaved(){
  const p=new URLSearchParams({saved:"1",region:STATE.region,experience:STATE.experience,q:STATE.q,sort:STATE.sort});
  const d=await api("/api/jobs?"+p); store.ROWS=d.jobs;
  $("#vcount").textContent=`${d.count} saved`;
  const c=$("#content"); c.innerHTML="";
  if(!store.ROWS.length){
    c.appendChild(el("div","empty","No saved jobs yet — tap the ★ on any job to keep it here."));
    return;
  }
  renderGrouped(c, currentBody());
}

registerView("saved", loadSaved);
