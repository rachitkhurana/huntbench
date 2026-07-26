// Shared visual helpers: status ring, fit badge, nav icons, status pill, company monogram.
import { SCOLOR, PROG, FITC, A } from './state.js';
import { esc } from './dom.js';

export function statusIcon(s,size){
  size=size||14; const col=SCOLOR[s]||"#9ca3af", frac=PROG[s]||0, r=5, c=2*Math.PI*r, dashed=(s==="new"||s==="skip");
  return `<svg width="${size}" height="${size}" viewBox="0 0 14 14" style="display:block">`+
    `<circle cx="7" cy="7" r="5" fill="none" stroke="${col}" stroke-opacity=".32" stroke-width="1.5" ${dashed?'stroke-dasharray="1.6 1.9"':""}/>`+
    (frac>0?`<circle cx="7" cy="7" r="5" fill="none" stroke="${col}" stroke-width="1.5" stroke-linecap="round" stroke-dasharray="${(frac*c).toFixed(2)} ${c.toFixed(2)}" transform="rotate(-90 7 7)"/>`:"")+
    (frac>=1?`<circle cx="7" cy="7" r="2.1" fill="${col}"/>`:"")+`</svg>`;
}
export function fitStyle(f){const c=FITC[f]||"#9ca3af";return `color:${c};background:${c}1e`;}
export function icon(name){const p={
  list:'<path d="M2 4h12M2 8h12M2 12h9" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>',
  board:'<rect x="2" y="2.5" width="4" height="11" rx="1" stroke="currentColor" stroke-width="1.3"/><rect x="10" y="2.5" width="4" height="7" rx="1" stroke="currentColor" stroke-width="1.3"/>',
  inbox:'<path d="M2 3.5h12v9H2z" stroke="currentColor" stroke-width="1.3"/><path d="M2 9h3l1 2h4l1-2h3" stroke="currentColor" stroke-width="1.3" fill="none"/>',
  profile:'<circle cx="8" cy="5.5" r="2.6" stroke="currentColor" stroke-width="1.3"/><path d="M3 13.5c0-2.5 2.2-4 5-4s5 1.5 5 4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>'
  }[name];return `<svg width="16" height="16" viewBox="0 0 16 16" fill="none">${p}</svg>`;}
export function stpill(s){const col=SCOLOR[s]||A.gray;return `<span class="stpill" style="color:${col}">${statusIcon(s,11)}${esc(s)}</span>`;}

const MONO_HUES=[214,262,338,152,28,192,340,48];
export function colorFromName(n){let h=0;for(let i=0;i<(n||"").length;i++)h=(h*31+n.charCodeAt(i))>>>0;
  const hue=MONO_HUES[h%MONO_HUES.length];return {bg:`hsl(${hue} 70% 95%)`,fg:`hsl(${hue} 55% 42%)`};}
export function monogram(name,cls){const c=colorFromName(name);const ch=esc((name||"?").trim().charAt(0));
  return `<span class="mono ${cls||""}" style="background:${c.bg};color:${c.fg}">${ch}</span>`;}
