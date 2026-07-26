// The ★ save/bookmark toggle, shared by list rows, cards, and the detail panel.
// `saved` is orthogonal to pipeline status — toggling it never changes the stage.
import { el } from './dom.js';
import { STATE, store } from './state.js';
import { api } from './api.js';
import { toast } from './toast.js';
import { refreshMeta } from './sidebar.js';
import { refreshView } from './nav.js';

export function starIcon(filled){
  return `<svg width="15" height="15" viewBox="0 0 24 24" fill="${filled ? "currentColor" : "none"}" `
    + `stroke="currentColor" stroke-width="1.7" stroke-linejoin="round">`
    + `<path d="M12 2.6l2.9 5.9 6.5.95-4.7 4.6 1.1 6.5L12 17.9 6.2 20.5l1.1-6.5-4.7-4.6 6.5-.95z"/></svg>`;
}

export function star(rec){
  const b = el("button", "star" + (rec.saved ? " on" : ""));
  b.innerHTML = starIcon(!!rec.saved);
  b.title = rec.saved ? "Saved — click to remove" : "Save this job";
  b.onclick = e => { e.stopPropagation(); toggleSaved(rec, b); };   // don't open the detail panel
  return b;
}

function paint(id, on){   // keep every visible ★ for this job (rows/cards/panel) + ROWS in sync
  (store.ROWS || []).forEach(r => { if (r.id === id) r.saved = on; });
  document.querySelectorAll('.star').forEach(s => {
    const host = s.closest('[data-id]');
    if (host && host.dataset.id === id) { s.classList.toggle("on", on); s.innerHTML = starIcon(on); }
  });
}

async function toggleSaved(rec, b){
  const next = !rec.saved;
  rec.saved = next;                                  // optimistic
  b.classList.toggle("on", next); b.innerHTML = starIcon(next);
  b.title = next ? "Saved — click to remove" : "Save this job";
  try {
    await api("/api/job/" + encodeURIComponent(rec.id) + "/update",
      { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ saved: next }) });
    paint(rec.id, next);
    await refreshMeta();                              // updates the Saved nav badge
    if (STATE.view === "saved" && !next) refreshView();   // drop it out of the Saved view
  } catch (e) {
    rec.saved = !next;                               // revert on failure
    b.classList.toggle("on", !next); b.innerHTML = starIcon(!next);
    toast("err", "Couldn't save", e.message);
  }
}
