/* Couche de texte du PDF, commune au Studio et à la bibliothèque : mots invisibles sélectionnables posés sur
   chaque page (positions données par le serveur, en unités de page), barre d'actions sur la sélection
   (surligner, souligner, barrer, copier), aperçu provisoire du marquage.

   TextLayer.init({
     pages: '.docpage',                  // sélecteur des blocs de page (position: relative, taille de l'image)
     index: d => +d.dataset.i,           // numéro de page d'un bloc
     doc: () => id,                      // document affiché
     enabled: () => true,                // sélection active (ex. outil « vue » du Studio)
     scroller: element,                  // zone qui défile (la barre se cache au défilement)
     annotate: (info, kind, color) => {},// info = {d, page, text, rects}
     notify: msg => {},                  // message court (copie)
   })
   TextLayer.load(bloc, doc, n, force)   // pose la couche de texte d'une page
*/
window.TextLayer = (() => {
  const measure = document.createElement('canvas').getContext('2d');
  measure.font = '100px Arial, Helvetica, sans-serif';
  let cfg = null, bar = null, info = null;

  async function load(d, doc, n, force) {
    if (!doc || (d.dataset.txt && !force)) return;
    d.dataset.txt = '1';
    let t;
    try { t = await (await fetch(`/api/text/${doc}/${n}`)).json(); } catch (e) { delete d.dataset.txt; return; }
    if (!t.bounds || (cfg && cfg.doc() !== doc)) return;
    d._text = t;
    let layer = d.querySelector('.txt');
    if (!layer) { layer = document.createElement('div'); layer.className = 'txt'; d.append(layer); }
    layer.textContent = '';
    if (!t.lines.length) return;
    const [bx, by, bw, bh] = t.bounds, frag = document.createDocumentFragment();
    t.lines.forEach((line, l) => line.forEach((wd, k) => {
      const [x, y, w, h, txt] = wd, sp = document.createElement('span');
      sp.textContent = txt + (k === line.length - 1 ? '\n' : ' ');
      sp.dataset.l = l; sp.dataset.w = k;
      const fs = h / bw * 100 * 0.88;                                  // taille de police en % de la largeur de page
      const tw = measure.measureText(txt).width / 100;                 // largeur du mot pour une police de 1 px
      sp.style.cssText = `left:${(x - bx) / bw * 100}%;top:${(y - by) / bh * 100}%;font-size:${fs}cqw;`
                       + `transform:scaleX(${tw > 0 ? (w / (tw * h * 0.88)).toFixed(4) : 1})`;
      frag.append(sp);
    }));
    layer.append(frag);
  }

  // sélection -> rectangles par ligne (unités de page)
  function read() {
    const sel = getSelection();
    if (sel.isCollapsed || !sel.rangeCount) return null;
    const n = sel.anchorNode && (sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentNode);
    const d = n && n.closest && n.closest(cfg.pages);
    if (!d || !d._text) return null;
    const byLine = new Map();
    d.querySelectorAll('.txt span').forEach(sp => {
      if (!sel.containsNode(sp, true)) return;
      const l = +sp.dataset.l, [x, y, w, h] = d._text.lines[l][+sp.dataset.w];
      const r = byLine.get(l);
      if (!r) byLine.set(l, [x, y, x + w, y + h]);
      else { r[0] = Math.min(r[0], x); r[1] = Math.min(r[1], y); r[2] = Math.max(r[2], x + w); r[3] = Math.max(r[3], y + h); }
    });
    if (!byLine.size) return null;
    return { d, page: cfg.index(d), text: sel.toString(), rects: [...byLine.values()].map(r => [r[0], r[1], r[2] - r[0], r[3] - r[1]]) };
  }

  function hide(clear) { if (bar) bar.hidden = true; info = null; if (clear) getSelection().removeAllRanges(); }

  // aperçu du marquage en attendant l'image de la tablette (retiré au rechargement de la page, ou après 20 s)
  function pending(i, kind, color) {
    const [bx, by, bw, bh] = i.d._text.bounds;
    for (const [x, y, w, h] of i.rects) {
      const e = document.createElement('div'); e.className = 'pend ' + kind;
      const top = kind === 'highlight' ? y : y + h * (kind === 'underline' ? 0.86 : 0.56) - 1.5, ht = kind === 'highlight' ? h : 3;
      e.style.cssText = `left:${(x - bx) / bw * 100}%;top:${(top - by) / bh * 100}%;width:${w / bw * 100}%;height:${ht / bh * 100}%;background:${color}`;
      i.d.append(e);
    }
    setTimeout(() => i.d.querySelectorAll('.pend').forEach(e => e.remove()), 20000);
  }

  const ICONS = {
    underline: 'M12 17c3.31 0 6-2.69 6-6V4c0-.55-.45-1-1-1s-1 .45-1 1v7c0 2.21-1.79 4-4 4s-4-1.79-4-4V4c0-.55-.45-1-1-1s-1 .45-1 1v7c0 3.31 2.69 6 6 6zM5 20c0 .55.45 1 1 1h12c.55 0 1-.45 1-1s-.45-1-1-1H6c-.55 0-1 .45-1 1z',
    strike: 'M10 19h4v-3h-4v3zM5 4v3h5v3h4V7h5V4H5zM3 14h18v-2H3v2z',
    copy: 'M15 20H5V7c0-.55-.45-1-1-1s-1 .45-1 1v13c0 1.1.9 2 2 2h10c.55 0 1-.45 1-1s-.45-1-1-1zm5-4V4c0-1.1-.9-2-2-2H9c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h9c1.1 0 2-.9 2-2zm-2 0H9V4h9v12z',
  };
  const COLORS = [['#FFE94D', 'jaune'], ['#9BE36B', 'vert'], ['#FF9AC8', 'rose'], ['#8FD3FF', 'bleu']];

  function makeBar() {
    bar = document.createElement('div'); bar.id = 'selbar'; bar.hidden = true;
    const ico = (k, title) => `<button data-mk="${k}" title="${title}"><svg class="ico" viewBox="0 0 24 24"><path d="${ICONS[k]}"/></svg></button>`;
    bar.innerHTML = COLORS.map(([c, n]) => `<button data-hl="${c}" title="Surligner en ${n}"><span class="sw" style="background:${c}"></span></button>`).join('')
      + '<span class="sep"></span>' + ico('underline', 'Souligner') + ico('strike', 'Barrer')
      + '<span class="sep"></span>' + ico('copy', 'Copier le texte');
    document.body.append(bar);
    bar.addEventListener('mousedown', e => e.preventDefault());        // garder la sélection
    bar.addEventListener('click', e => {
      const b = e.target.closest('button');
      if (!b || !info) return;
      const i = info;
      if (b.dataset.mk === 'copy') {
        const t = i.text.replace(/[ \t]+\n/g, '\n').trim();
        navigator.clipboard.writeText(t).then(() => cfg.notify('Texte copié'), () => cfg.notify('Copie impossible'));
        return hide(true);
      }
      hide(true);
      cfg.annotate(i, b.dataset.hl ? 'highlight' : b.dataset.mk, b.dataset.hl || null);
    });
  }

  function init(c) {
    cfg = Object.assign({ enabled: () => true, notify: () => {} }, c);
    makeBar();
    document.addEventListener('mouseup', e => {
      if (e.target.closest && e.target.closest('#selbar')) return;
      setTimeout(() => {
        if (!cfg.enabled()) return;
        info = read();
        if (!info) { bar.hidden = true; return; }
        bar.hidden = false;
        const bw = bar.offsetWidth, bh = bar.offsetHeight;
        bar.style.left = Math.max(8, Math.min(e.clientX - bw / 2, innerWidth - bw - 8)) + 'px';
        bar.style.top = (e.clientY + 14 + bh > innerHeight ? e.clientY - bh - 14 : e.clientY + 14) + 'px';
      }, 0);
    });
    if (cfg.scroller) cfg.scroller.addEventListener('scroll', () => { if (!bar.hidden) hide(false); }, { passive: true });
  }

  return { init, load, pending, hide, get info() { return info; } };
})();
