/* =====================================================================
   ui-modes.js — PoolPanel: one-vs-all / all-vs-one damage table
   ===================================================================== */
(function (root) {
  'use strict';
  const D = root.CalcData, E = root.Engine, S = root.CalcSets, esc = root.escHtml;

  class PoolPanel {
    constructor(onPick) {
      this.onPick = onPick;
      this.sortKey = 'pct'; this.sortDir = -1;
      this.filter = '';
      this.rows = [];
      this.el = document.createElement('div');
      this.el.className = 'pool-wrap';
      this.el.innerHTML = `
        <div class="pool-bar">
          <span class="eyebrow mag" data-eyebrow>// matrix</span>
          <span class="ttl" data-title>Pool</span>
          <input class="field" data-filter placeholder="Filter Pokémon…">
          <span class="meta" data-meta></span>
        </div>
        <div class="pool-scroll">
          <table class="ptbl">
            <thead><tr>
              <th data-sort="name">Pokémon</th>
              <th data-sort="move">Best Move</th>
              <th data-sort="pct" style="text-align:right">Max %<span class="sort">▼</span></th>
            </tr></thead>
            <tbody data-body></tbody>
          </table>
        </div>`;
      this.el.querySelector('[data-filter]').addEventListener('input', (e) => { this.filter = e.target.value.toLowerCase(); this.renderRows(); });
      this.el.querySelectorAll('th[data-sort]').forEach(th => th.addEventListener('click', () => {
        const k = th.dataset.sort;
        if (this.sortKey === k) this.sortDir *= -1; else { this.sortKey = k; this.sortDir = k === 'pct' ? -1 : 1; }
        this.renderHeaders(); this.renderRows();
      }));
    }

    setData(mode, fixedState, field, format, genNum) {
      this.mode = mode; this.fixed = fixedState; this.field = field; this.format = format; this.genNum = genNum;
      const body = this.el.querySelector('[data-body]');
      const isAtkFixed = mode === '1vAll';
      this.el.querySelector('[data-title]').textContent = isAtkFixed
        ? `${E.speciesInfo(fixedState.species)?.name || '—'} vs the field`
        : `The field vs ${E.speciesInfo(fixedState.species)?.name || '—'}`;
      body.innerHTML = `<tr><td colspan="3"><div class="pool-loading">▚ computing ${format === 'All' ? 'full dex' : format} matchups…</div></td></tr>`;
      // compute next frame so the loading state paints
      clearTimeout(this._t);
      this._t = setTimeout(() => this.compute(), 30);
    }

    compute() {
      const { mode, fixed, field, format, genNum } = this;
      const species = S.pool(genNum, format || 'All');
      const rows = [];
      const isAtkFixed = mode === '1vAll';
      for (const sp of species) {
        const set = S.defaultSetFor(genNum, sp, format, E.toID);
        if (!set) continue;
        const variable = E.stateFromSet(sp, set.data);
        let best;
        if (isAtkFixed) best = E.runBest(fixed, variable, field, fixed.moveOpts);
        else best = E.runBest(variable, fixed, field, null);
        if (!best) continue;
        rows.push({
          species: sp, setName: set.name, moveName: best.moveName, type: best.type,
          pct: best.pctMax, pctMin: best.pctMin, ko: best.ko, koClass: best.koClass
        });
      }
      this.rows = rows;
      this.el.querySelector('[data-meta]').textContent = rows.length + ' targets · ' + (format === 'All' ? 'full dex' : format);
      this.renderHeaders();
      this.renderRows();
    }

    renderHeaders() {
      this.el.querySelectorAll('th[data-sort]').forEach(th => {
        const span = th.querySelector('.sort');
        if (span) span.remove();
        if (th.dataset.sort === this.sortKey) {
          const s = document.createElement('span'); s.className = 'sort'; s.textContent = this.sortDir < 0 ? '▼' : '▲'; th.appendChild(s);
        }
      });
    }

    renderRows() {
      const body = this.el.querySelector('[data-body]');
      let rows = this.rows.slice();
      if (this.filter) rows = rows.filter(r => r.species.toLowerCase().includes(this.filter));
      rows.sort((a, b) => {
        let av, bv;
        if (this.sortKey === 'name') { av = a.species; bv = b.species; return av.localeCompare(bv) * this.sortDir; }
        if (this.sortKey === 'move') { av = a.moveName; bv = b.moveName; return av.localeCompare(bv) * this.sortDir; }
        av = a.pct; bv = b.pct; return (av - bv) * this.sortDir;
      });
      if (!rows.length) { body.innerHTML = `<tr><td colspan="3"><div class="pool-empty">No matchups. Pick a format with a set pool, or check the fixed Pokémon's moves.</div></td></tr>`; return; }
      const frag = document.createDocumentFragment();
      const animated = !!(root.CalcApp && root.CalcApp.animated);
      rows.forEach(r => {
        const tr = document.createElement('tr');
        const tcolor = D.TYPE_COLORS[r.type] || '#888';
        const w = Math.min(100, r.pct);
        const chain = D.spriteChain(r.species, animated);
        const fb = chain[1] || '';
        tr.innerHTML =
          `<td><div class="pt-mon"><img class="pt-spr" alt="" src="${chain[0]}" data-fb="${fb}" onerror="if(this.dataset.fb){this.src=this.dataset.fb;this.dataset.fb='';}else{this.style.visibility='hidden';}">
             <div><div class="pt-name">${esc(r.species)}</div><div class="pt-set">${esc(r.setName)}</div></div></div></td>` +
          `<td><div class="pt-move"><span class="dot" style="background:${tcolor}"></span>${esc(r.moveName)}</div>
             <div class="pt-bar" style="margin-top:5px"><i style="width:${w}%"></i></div></td>` +
          `<td style="text-align:right"><div class="pt-pct">${r.pct.toFixed(1)}%</div><div class="pt-ko ko ${r.koClass}">${esc(shortKO(r.ko))}</div></td>`;
        tr.addEventListener('click', () => this.onPick && this.onPick(r.species, this.mode));
        frag.appendChild(tr);
      });
      body.innerHTML = '';
      body.appendChild(frag);
    }
  }
  function shortKO(ko) { return ko ? ko.replace(/\s*\(after.*?\)/, '').replace(/after.*$/, '').trim() : ''; }

  root.PoolPanel = PoolPanel;
})(window);
