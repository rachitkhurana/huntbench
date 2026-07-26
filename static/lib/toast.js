// Transient bottom-right notifications.
import { $, el, esc } from './dom.js';

export function toast(kind,msg,sub,keep){
  const t=el("div","toast "+kind);
  t.innerHTML=(kind==="run"?'<span class="spin"></span>':"")+`<span>${esc(msg)}</span>`+(sub?`<div class="sub">${esc(sub)}</div>`:"");
  $("#toasts").appendChild(t); if(!keep)setTimeout(()=>t.remove(),4000); return t;
}
