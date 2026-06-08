/* =====================================================================
   combo.js — lightweight autocomplete combobox
   ===================================================================== */
(function (root) {
  'use strict';

  class Combo {
    constructor(input, opts) {
      this.input = input;
      this.getList = opts.getList;          // () => string[]
      this.onPick = opts.onPick;            // (value) => void
      this.decorate = opts.decorate;        // (value) => {dot?, meta?} | null
      this.allowFree = opts.allowFree || false;
      this.placeholder = opts.placeholder || '';
      this.input.setAttribute('autocomplete', 'off');
      this.input.classList.add('field');
      if (this.placeholder) this.input.placeholder = this.placeholder;

      this.menu = document.createElement('div');
      this.menu.className = 'combo-menu';
      this.input.parentNode.appendChild(this.menu);

      this.active = -1;
      this.filtered = [];

      input.addEventListener('focus', () => this.open(input.value));
      input.addEventListener('input', () => this.open(input.value));
      input.addEventListener('keydown', (e) => this.key(e));
      input.addEventListener('blur', () => setTimeout(() => this.close(), 140));
    }

    setValue(v) { this.input.value = v || ''; this.input.setAttribute('value', v || ''); }

    open(q) {
      const list = this.getList() || [];
      q = (q || '').trim().toLowerCase();
      let res;
      if (!q) {
        res = list.slice(0, 60);
      } else {
        const starts = [], incl = [];
        for (const item of list) {
          const lc = item.toLowerCase();
          const i = lc.indexOf(q);
          if (i === 0) starts.push(item);
          else if (i > 0) incl.push(item);
          if (starts.length + incl.length > 120) break;
        }
        res = starts.concat(incl).slice(0, 60);
      }
      this.filtered = res;
      this.active = -1;
      this.render();
    }

    render() {
      const m = this.menu;
      if (!this.filtered.length) {
        m.innerHTML = '<div class="combo-empty">no matches</div>';
        m.classList.add('open');
        return;
      }
      m.innerHTML = '';
      this.filtered.forEach((val, idx) => {
        const el = document.createElement('div');
        el.className = 'combo-opt' + (idx === this.active ? ' active' : '');
        const dec = this.decorate ? this.decorate(val) : null;
        let html = '';
        if (dec && dec.dot) html += `<span style="width:11px;height:11px;border-radius:2px;flex:0 0 auto;border:1px solid rgba(255,255,255,.25);background:${dec.dot}"></span>`;
        html += `<span class="lbl">${esc(val)}</span>`;
        if (dec && dec.meta) html += `<span class="meta">${esc(dec.meta)}</span>`;
        el.innerHTML = html;
        el.addEventListener('mousedown', (e) => { e.preventDefault(); this.pick(val); });
        m.appendChild(el);
      });
      m.classList.add('open');
    }

    key(e) {
      if (!this.menu.classList.contains('open')) {
        if (e.key === 'ArrowDown') this.open(this.input.value);
        return;
      }
      if (e.key === 'ArrowDown') { e.preventDefault(); this.active = Math.min(this.active + 1, this.filtered.length - 1); this.render(); this.scrollTo(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); this.active = Math.max(this.active - 1, 0); this.render(); this.scrollTo(); }
      else if (e.key === 'Enter') {
        if (this.active >= 0 && this.filtered[this.active]) { e.preventDefault(); this.pick(this.filtered[this.active]); }
        else if (this.filtered.length === 1) { e.preventDefault(); this.pick(this.filtered[0]); }
        else if (this.allowFree) { this.pick(this.input.value); }
      }
      else if (e.key === 'Escape') { this.close(); }
      else if (e.key === 'Tab') {
        if (this.active >= 0) this.pick(this.filtered[this.active]);
        else if (this.filtered.length >= 1 && this.input.value) this.pick(this.filtered[0]);
      }
    }

    scrollTo() {
      const el = this.menu.children[this.active];
      if (el) el.scrollIntoView ? el.scrollIntoView({ block: 'nearest' }) : null;
    }

    pick(val) {
      this.input.value = val;
      this.close();
      if (this.onPick) this.onPick(val);
    }

    close() { this.menu.classList.remove('open'); this.active = -1; }
  }

  function esc(s) { return ('' + s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

  // Reflect live form state (value properties) into attributes so DOM-clone
  // screenshots & static inspectors render the current selections.
  function reflectForm(rootEl) {
    rootEl.querySelectorAll('input').forEach(inp => {
      if (inp.type === 'checkbox' || inp.type === 'radio') {
        if (inp.checked) inp.setAttribute('checked', ''); else inp.removeAttribute('checked');
      } else {
        inp.setAttribute('value', inp.value);
      }
    });
    rootEl.querySelectorAll('select').forEach(sel => {
      Array.from(sel.options).forEach(o => {
        if (o.value === sel.value) o.setAttribute('selected', ''); else o.removeAttribute('selected');
      });
    });
  }

  root.Combo = Combo;
  root.escHtml = esc;
  root.reflectForm = reflectForm;
})(window);
