// View registry + dispatcher. View modules call registerView() at load; refreshView()
// looks the current view up here. nav.js imports no view module, so there's no cycle:
// the dispatcher never depends on the loaders it calls.
import { $ } from './dom.js';
import { STATE } from './state.js';

const loaders = {};
export function registerView(name, fn){ loaders[name] = fn; }

export function refreshView(){
  STATE.cursor = -1;
  return (loaders[STATE.view] || loaders.list)();
}

export function setView(v){
  STATE.view=v; localStorage.setItem("v2view",v);
  document.querySelectorAll(".navitem").forEach(n=>n.classList.toggle("on",n.dataset.view===v));
  $("#vtitle").textContent={list:"All jobs",saved:"Saved",board:"Board",inbox:"Inbox",profile:"Profile"}[v];
  document.querySelectorAll('.seclabel[data-sec="status"],.chips[data-sec="status"]').forEach(e=>e.style.display=(v==="list")?"":"none");
  $("#sort").style.display=(v==="inbox"||v==="profile")?"none":"";
  $("#q").style.display=(v==="profile")?"none":"";
  $("#listmode-seg").style.display=(v==="list"||v==="saved")?"":"none";   // List|Cards toggle: All jobs + Saved
  refreshView();
}
