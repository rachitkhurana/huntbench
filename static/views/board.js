// Kanban board: one column per status, cards drag between columns to change status.
import { $, el, esc, cap, cssEsc } from '../lib/dom.js';
import { STATE, store } from '../lib/state.js';
import { statusIcon, fitStyle } from '../lib/ui.js';
import { api } from '../lib/api.js';
import { registerView } from '../lib/nav.js';
import { openDetail, update } from './panel.js';

async function loadBoard(){
  const p=new URLSearchParams({region:STATE.region,experience:STATE.experience,q:STATE.q,sort:"fit"});
  const d=await api("/api/jobs?"+p); $("#vcount").textContent=`${d.count}`;
  const by={}; store.META.statuses.forEach(s=>by[s]=[]); d.jobs.forEach(j=>{(by[j.status]||(by[j.status]=[])).push(j);});
  const c=$("#content"); c.innerHTML=""; const board=el("div","board");
  store.META.statuses.forEach(s=>board.appendChild(bcol(s,by[s]||[]))); c.appendChild(board);
}
function bcol(status,jobs){
  const col=el("div","bcol");
  const head=el("div","bcolhead"); head.innerHTML=`${statusIcon(status,13)}<span>${cap(status)}</span><span class="cnt">${jobs.length}</span>`;
  const body=el("div","bcolbody"); body.dataset.status=status;
  body.addEventListener("dragover",e=>{e.preventDefault();body.classList.add("over");});
  body.addEventListener("dragleave",()=>body.classList.remove("over"));
  body.addEventListener("drop",e=>{e.preventDefault();body.classList.remove("over");onDrop(status,body);});
  jobs.forEach(j=>body.appendChild(bcard(j)));
  col.appendChild(head); col.appendChild(body); return col;
}
function bcard(j){
  const card=el("div","bcard"); card.draggable=true; card.dataset.id=j.id; card.dataset.status=j.status;
  card.innerHTML=`<div class="bc-top">${statusIcon(j.status,13)}<span class="bc-co">${esc(j.company)}</span>`+
    `<span class="fitb" style="${fitStyle(j.fit_score)}">${j.fit_score||"·"}</span></div><div class="bc-ti">${esc(j.title)}</div>`;
  card.addEventListener("dragstart",e=>{store.DRAG={id:card.dataset.id,from:card.dataset.status};card.classList.add("dragging");e.dataTransfer.effectAllowed="move";});
  card.addEventListener("dragend",()=>{card.classList.remove("dragging");store.DRAG=null;});
  card.addEventListener("click",()=>openDetail(j.id));
  return card;
}
function onDrop(to,body){
  if(!store.DRAG||store.DRAG.from===to)return; const id=store.DRAG.id;
  const card=document.querySelector('.bcard[data-id="'+cssEsc(id)+'"]');
  if(card){card.dataset.status=to;body.appendChild(card);bump(store.DRAG.from,-1);bump(to,1);}
  update(id,{status:to},{skipView:true});
}
function bump(s,d){const col=[...document.querySelectorAll(".bcol")].find(c=>c.querySelector(".bcolbody")?.dataset.status===s);
  if(col){const n=col.querySelector(".cnt");n.textContent=Math.max(0,(parseInt(n.textContent)||0)+d);}}

registerView("board", loadBoard);
