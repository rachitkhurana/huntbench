// Thin JSON fetch wrapper. On our own POSTs we re-baseline the change-token (store.REV)
// so the DB-watcher doesn't treat our write as an external change and self-refresh.
import { store } from './state.js';

export async function api(u,o){
  const r = await fetch(u,o);
  if(!r.ok) throw new Error((await r.json().catch(()=>({}))).error || r.status);
  if(o && o.method==="POST") store.REV = null;
  return r.json();
}
