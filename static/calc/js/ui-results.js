/* =====================================================================
   ui-results.js — bidirectional damage report (two columns) + readout
   ===================================================================== */
(function (root) {
  'use strict';
  const D = root.CalcData, E = root.Engine, esc = root.escHtml;

  class ResultsPanel {
    constructor(onSwap, onSelect) {
      this.onSwap = onSwap; this.onSelect = onSelect;
      this.selected = { col: 'a', i: 0 };
      this.el = document.createElement('div');
      this.el.className = 'results';
      this.el.innerHTML = `
        <div class="results-head">
          <span class="eyebrow mag">// damage_report</span>
          <span class="rb-badge" data-rbbadge style="display:none">Random Battle</span>
          <span style="flex:1"></span>
          <button class="swap-btn" data-swap title="Swap attacker / defender">⇄</button>
        </div>
        <div class="results-body">
          <div class="report-cols">
            <div class="report-col a"><div class="col-head" data-head-a></div><div data-rows-a></div></div>
            <div class="report-col d"><div class="col-head" data-head-d></div><div data-rows-d></div></div>
          </div>
        </div>
        <div class="readout" data-readout style="display:none">
          <span class="brk tl"></span><span class="brk tr"></span><span class="brk bl"></span><span class="brk br"></span>
          <span class="tag">// calculation</span>
          <span data-readout-text></span>
          <div class="rolls" data-rolls></div>
        </div>`;
      this.el.querySelector('[data-swap]').addEventListener('click', () => this.onSwap && this.onSwap());
    }

    setRandom(on) { this.el.querySelector('[data-rbbadge]').style.display = on ? '' : 'none'; }

    render(aState, bState, resA, resB) {
      this._a = aState; this._b = bState; this._resA = resA; this._resB = resB;
      const a = E.speciesInfo(aState.species), b = E.speciesInfo(bState.species);
      this.el.querySelector('[data-head-a]').innerHTML =
        `<span>${a ? esc(a.name) : '—'}</span><span class="arrow">▸ vs ▸</span><span style="color:var(--def)">${b ? esc(b.name) : '—'}</span>`;
      this.el.querySelector('[data-head-d]').innerHTML =
        `<span>${b ? esc(b.name) : '—'}</span><span class="arrow">▸ vs ▸</span><span style="color:var(--atk)">${a ? esc(a.name) : '—'}</span>`;
      this.renderCol('a', aState, resA, this.el.querySelector('[data-rows-a]'));
      this.renderCol('d', bState, resB, this.el.querySelector('[data-rows-d]'));
      this.renderReadout();
    }

    renderCol(col, atkState, results, wrap) {
      const accent = col === 'a' ? 'var(--atk)' : 'var(--def)';
      wrap.innerHTML = '';
      results.forEach((r, i) => {
        const filled = !!atkState.moves[i];
        const row = document.createElement('div');
        const isSel = this.selected.col === col && this.selected.i === i && r && (r.ok || r.status || r.immune);
        row.className = 'res-row' + (filled ? '' : ' empty') + (isSel ? ' sel' : '');
        row.style.setProperty('--accent', accent);
        row.style.gridTemplateColumns = '116px 1fr 112px';
        if (!filled) {
          row.innerHTML = `<div class="res-move"><span class="mname" style="color:var(--text-dim)">Move ${i + 1}</span></div><div></div><div></div>`;
          wrap.appendChild(row); return;
        }
        const mInfo = E.moveInfo(atkState.moves[i]);
        const tcolor = mInfo ? D.TYPE_COLORS[mInfo.type] : '#888';
        let mid = '', pct = '';
        if (r && r.ok) {
          const w = Math.min(100, r.pctMax);
          mid = `<div class="res-bar-wrap"><div class="res-bar"><i style="width:${w}%;background:linear-gradient(90deg,${accent}88,${accent})"></i></div>
              <div class="res-sub">${r.minD}–${r.maxD} dmg</div></div>`;
          pct = `<div class="res-pct"><span class="range" style="color:${accent}">${r.pctMin.toFixed(1)}–${r.pctMax.toFixed(1)}%</span><span class="ko ${r.koClass}">${esc(shortKO(r.ko))}</span></div>`;
        } else if (r && r.status) {
          mid = `<div class="res-sub" style="align-self:center">Status / non-damaging</div>`;
          pct = `<div class="res-pct"><span class="big" style="font-size:13px;color:var(--text-dim)">—</span></div>`;
        } else if (r && r.immune) {
          mid = `<div class="res-sub" style="align-self:center;color:var(--amber)">No effect — immune</div>`;
          pct = `<div class="res-pct"><span class="big" style="font-size:13px;color:var(--amber)">0%</span></div>`;
        } else if (r && r.error) {
          mid = `<div class="res-sub" style="align-self:center;color:var(--red)">err</div>`;
        }
        row.innerHTML = `<div class="res-move"><span class="mtype" style="background:${tcolor}"></span><span class="mname">${esc(atkState.moves[i])}</span></div>` + mid + pct;
        row.addEventListener('click', () => { this.selected = { col, i }; this.render(this._a, this._b, this._resA, this._resB); });
        wrap.appendChild(row);
      });
    }

    renderReadout() {
      const results = this.selected.col === 'a' ? this._resA : this._resB;
      const sel = results[this.selected.i];
      const ro = this.el.querySelector('[data-readout]');
      const txt = this.el.querySelector('[data-readout-text]');
      const rolls = this.el.querySelector('[data-rolls]');
      if (sel && sel.ok) {
        ro.style.display = 'block';
        txt.innerHTML = `<span class="verdict">${esc(sel.verdict)}</span> <span class="amount">— ${esc(sel.ko || '')}</span>`;
        rolls.textContent = '[ ' + sel.rolls.join('  ') + ' ]';
      } else if (sel && sel.status) {
        ro.style.display = 'block';
        txt.innerHTML = `<span class="verdict">${esc(sel.moveName)} is a non-damaging move.</span>`;
        rolls.textContent = '';
      } else if (sel && sel.immune) {
        ro.style.display = 'block';
        txt.innerHTML = `<span class="verdict">The target is <span class="amount">immune</span> to ${esc(sel.moveName)} (${esc(sel.type)}). No damage dealt.</span>`;
        rolls.textContent = '';
      } else { ro.style.display = 'none'; }
    }
  }

  function shortKO(ko) {
    if (!ko) return '';
    return ko.replace(/\s*\(after.*?\)/, '').replace(/after.*$/, '').trim();
  }

  root.ResultsPanel = ResultsPanel;
})(window);
