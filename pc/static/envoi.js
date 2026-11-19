/* File d'envoi du PC vers la tablette (envoi.py), vue depuis le Studio et la bibliothèque :
   - pastille en bas à gauche : demandes en attente (et ce qu'elles attendent), abandons récents ; clic = détail ;
   - marques de texte en attente dessinées en pointillés sur les pages du document affiché ; clic = annuler.
   EnvoiUI.start({ doc: () => id, pages: '.docpage', index: d => +d.dataset.i, notify: msg => {} })
   EnvoiUI.refresh()   // après une nouvelle demande
*/
window.EnvoiUI = (() => {
  let cfg = null, pill = null, last = { attente: [], abandons: [] }, open = false;
  const KIND = { highlight: 'surlignage', underline: 'soulignement', strike: 'barré' };
  const label = e => e.type === 'marks' ? `${KIND[e.kind] || 'marque'}, page ${e.page + 1}`
    : e.type === 'upload' ? `envoi de « ${e.nom} »` : e.type === 'links' ? 'carnets liés' : 'palette de couleurs';
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  async function cancel(id) {
    const r = await fetch('/api/envoi/annuler', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-RM-Viewer': '1' },
                                                body: JSON.stringify({ id }) }).then(r => r.json()).catch(() => ({}));
    cfg.notify(r.ok ? 'Demande annulée' : 'Déjà traitée ou introuvable');
    refresh();
  }

  function drawPill() {
    const n = last.attente.length, a = last.abandons.length;
    pill.hidden = !n && !a;
    if (pill.hidden) return;
    const first = last.attente[0];
    pill.querySelector('.head').textContent = n
      ? `${n} envoi${n > 1 ? 's' : ''} en attente${first && first.en_attente_de ? ' : ' + first.en_attente_de : ''}` + (a ? ` · ${a} échec${a > 1 ? 's' : ''}` : '')
      : `${a} envoi${a > 1 ? 's' : ''} abandonné${a > 1 ? 's' : ''}`;
    pill.classList.toggle('bad', !n && a > 0);
    const list = pill.querySelector('.list');
    list.hidden = !open;
    list.innerHTML = last.attente.map(e => `<div>${esc(label(e))} — attend ${esc(e.en_attente_de || 'son tour')}`
        + (e.erreur ? ` <span class="sub">(${esc(e.erreur)})</span>` : '') + ` <button data-c="${e.id}">annuler</button></div>`).join('')
      + last.abandons.map(e => `<div class="ab">${esc(label(e))} — abandonné : ${esc(e.erreur || '?')}</div>`).join('');
  }

  function drawMarks() {
    document.querySelectorAll('.queued').forEach(e => e.remove());
    const doc = cfg.doc();
    if (!doc) return;
    for (const q of last.attente) {
      if (q.type !== 'marks' || q.doc !== doc || !q.rects) continue;
      const d = [...document.querySelectorAll(cfg.pages)].find(p => cfg.index(p) === q.page);
      if (!d || !d._text || !d._text.bounds) continue;
      const [bx, by, bw, bh] = d._text.bounds;
      for (const [x, y, w, h] of q.rects) {
        const e = document.createElement('div');
        e.className = 'queued ' + q.kind;
        e.title = `${KIND[q.kind]} en attente : ${q.en_attente_de || 'envoi en cours'} — cliquer pour annuler`;
        // fond : couleur demandée, translucide ; contour pointillé violet (lisible même pour un jaune clair)
        const c = /^#[0-9a-f]{6}$/i.test(q.couleur || '') ? q.couleur : '#7451eb';
        e.style.cssText = `left:${(x - bx) / bw * 100}%;top:${(y - by) / bh * 100}%;width:${w / bw * 100}%;height:${h / bh * 100}%;`
                        + (q.kind === 'highlight' ? `background:${c}66` : '');
        e.onclick = ev => { ev.stopPropagation(); if (confirm(`Annuler ce ${KIND[q.kind]} en attente ?`)) cancel(q.id); };
        d.append(e);
      }
    }
  }

  async function refresh() {
    if (!cfg || document.hidden) return;
    try { last = await (await fetch('/api/envoi', { cache: 'no-store' })).json(); } catch (e) { return; }
    document.querySelectorAll('.pend').forEach(e => e.remove());   // l'aperçu provisoire laisse place à l'état réel
    drawPill(); drawMarks();
  }

  function start(c) {
    cfg = Object.assign({ notify: () => {} }, c);
    pill = document.createElement('div'); pill.id = 'envoipill'; pill.hidden = true;
    pill.innerHTML = '<div class="head"></div><div class="list" hidden></div>';
    document.body.append(pill);
    pill.addEventListener('click', e => {
      const b = e.target.closest('button[data-c]');
      if (b) return cancel(b.dataset.c);
      open = !open; drawPill();
    });
    setInterval(refresh, 5000);
    document.addEventListener('visibilitychange', refresh);
    refresh();
  }
  return { start, refresh };
})();
