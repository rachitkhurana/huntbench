// Tiny DOM + string helpers, dependency-free.

export const $ = s => document.querySelector(s);
export const el = (t,c,h) => {const e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e;};
export const esc = s => (s==null?"":String(s)).replace(/[&<>"]/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[m]));
export const cap = s => (s||"").charAt(0).toUpperCase()+(s||"").slice(1);
export function debounce(fn,ms){let h;return(...a)=>{clearTimeout(h);h=setTimeout(()=>fn(...a),ms);};}
export function cssEsc(s){return (window.CSS&&CSS.escape)?CSS.escape(s):String(s).replace(/["\\]/g,"\\$&");}
