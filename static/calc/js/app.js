/* =====================================================================
   app.js — orchestration: state, modes, format, sets, pool, randoms
   ===================================================================== */
(function (root) {
  'use strict';
  const D = root.CalcData, E = root.Engine, S = root.CalcSets;
  const LS_KEY = 'ycs9-damage-calc-v2';

  function blankMon(species) {
    return {
      species: species || '', level: 100, ability: '', item: '', nature: 'Hardy',
      teraType: '', teraActive: false, status: '', curHPpercent: 100, setName: '',
      evs: {}, ivs: {}, boosts: {}, moves: ['', '', '', ''], moveOpts: [{}, {}, {}, {}]
    };
  }
  function defaultField() {
    return { gameType: 'Singles', weather: '', terrain: '', isGravity: false,
      attackerSide: { spikes: 0 }, defenderSide: { spikes: 0 } };
  }

  const App = {
    state: null, format: 'All', mode: '1v1',
    panelA: null, panelB: null, field: null, results: null, pool: null,
    setsLoaded: {},

    init() {
      E.setGen(9);
      this.state = this.load() || this.seed();
      this.format = this.state.format || 'All';
      this.mode = this.state.mode || '1v1';
      this.animated = !!this.state.animated;

      this.panelA = new root.MonPanel('atk', this.state.a, () => this.recompute());
      this.panelB = new root.MonPanel('def', this.state.b, () => this.recompute());
      this.field = new root.FieldPanel(this.state.field, () => this.recompute());
      this.results = new root.ResultsPanel(() => this.swap());
      this.pool = new root.PoolPanel((sp, mode) => this.pickFromPool(sp, mode));

      document.getElementById('panel-a').appendChild(this.panelA.el);
      document.getElementById('panel-b').appendChild(this.panelB.el);
      document.getElementById('pool-mount').appendChild(this.pool.el);
      document.getElementById('field-mount').appendChild(this.field.el);
      document.getElementById('results-mount').appendChild(this.results.el);
      this.syncFieldControls();

      // generation select
      const genSel = document.getElementById('gen-select');
      D.GENS.forEach(g => { const o = document.createElement('option'); o.value = g.num; o.textContent = g.label; genSel.appendChild(o); });
      genSel.value = this.state.gen || 9;
      genSel.addEventListener('change', () => this.setGen(parseInt(genSel.value)));

      // mode tabs
      document.querySelectorAll('.mode-tab').forEach(tab => tab.addEventListener('click', () => this.setMode(tab.dataset.mode)));
      // format select
      document.getElementById('format-select').addEventListener('change', (e) => { this.format = e.target.value; this.panelA.refreshSets(); this.panelB.refreshSets(); this.recompute(); });
      // buttons
      document.getElementById('btn-reset').addEventListener('click', () => this.reset());
      document.getElementById('btn-export').addEventListener('click', () => this.openExport());
      document.getElementById('btn-roll').addEventListener('click', () => this.rollRandom());
      const animBtn = document.getElementById('btn-animated');
      animBtn.classList.toggle('primary', this.animated);
      animBtn.addEventListener('click', () => {
        this.animated = !this.animated;
        animBtn.classList.toggle('primary', this.animated);
        this.panelA.renderSprite(); this.panelB.renderSprite();
        this.save(); this.recompute();
        this.toast(this.animated ? 'Animated sprites on' : 'Static sprites');
      });

      this.wireModal();

      // lazy-load this gen's preset sets, then populate format list + set dropdowns
      this.ensureSets(this.state.gen || 9).then(() => {
        this.buildFormatList();
        this.panelA.refreshSets(); this.panelB.refreshSets();
      });

      this.applyMode();
      this.recompute();
    },

    seed() {
      const a = blankMon('Great Tusk');
      a.nature = 'Adamant'; a.ability = 'Protosynthesis'; a.item = 'Booster Energy';
      a.evs = { atk: 252, hp: 4, spe: 252 };
      a.moves = ['Headlong Rush', 'Close Combat', 'Ice Spinner', 'Rapid Spin'];
      const b = blankMon('Gholdengo');
      b.nature = 'Bold'; b.ability = 'Good as Gold'; b.item = 'Leftovers';
      b.evs = { hp: 252, def: 252, spd: 4 };
      b.moves = ['Make It Rain', 'Shadow Ball', 'Nasty Plot', 'Recover'];
      return { gen: 9, a, b, field: defaultField(), format: 'All', mode: '1v1' };
    },

    // ---- lazy set data ----
    ensureSets(genNum) {
      if (this.setsLoaded[genNum]) return Promise.resolve();
      const v = S.GEN_VAR[genNum];
      if (root[v]) { this.setsLoaded[genNum] = true; return Promise.resolve(); }
      return new Promise((resolve) => {
        const sc = document.createElement('script');
        sc.src = '/damage-calc/data/sets/gen' + genNum + '.js';
        sc.onload = () => { this.setsLoaded[genNum] = true; resolve(); };
        sc.onerror = () => { resolve(); };
        document.head.appendChild(sc);
      });
    },

    buildFormatList() {
      const sel = document.getElementById('format-select');
      const fmts = S.formats(this.state.gen || 9);
      sel.innerHTML = '<option value="All">All Formats</option>' + fmts.map(f => `<option value="${f}">${f}</option>`).join('');
      sel.value = fmts.includes(this.format) || this.format === 'All' ? this.format : 'All';
      this.format = sel.value;
    },

    // ---- modes ----
    setMode(mode) {
      this.mode = mode;
      document.getElementById('btn-roll').style.display = mode === 'random' ? '' : 'none';
      this.applyMode();
      if (mode === 'random' && !this._rolledOnce) { this._rolledOnce = true; this.rollRandom(); return; }
      this.recompute();
    },

    applyMode() {
      const mode = this.mode;
      document.querySelectorAll('.mode-tab').forEach(t => t.classList.toggle('active', t.dataset.mode === mode));
      const pa = document.getElementById('panel-a'), pb = document.getElementById('panel-b'), pm = document.getElementById('pool-mount');
      const rr = document.getElementById('results-row'), fr = document.getElementById('field-row');
      const poolMode = (mode === '1vAll' || mode === 'Allv1');
      pa.style.display = (mode === 'Allv1') ? 'none' : '';
      pb.style.display = (mode === '1vAll') ? 'none' : '';
      pm.style.display = poolMode ? '' : 'none';
      rr.style.display = poolMode ? 'none' : '';
      fr.style.display = '';
      this.results.setRandom(mode === 'random');
      document.getElementById('btn-roll').style.display = mode === 'random' ? '' : 'none';
    },

    pickFromPool(species, mode) {
      // load clicked pool mon into the editable opposite panel and switch to 1v1
      const target = (mode === '1vAll') ? 'b' : 'a';
      const panel = target === 'b' ? this.panelB : this.panelA;
      const set = S.defaultSetFor(this.state.gen, species, this.format, E.toID);
      const st = E.stateFromSet(species, set ? set.data : null);
      st.setName = set ? set.name : '';
      Object.assign(this.state[target], blankMon(species), st);
      panel.st = this.state[target];
      this.setMode('1v1');
      panel.syncFromState();
      this.recompute();
    },

    setGen(num) {
      E.setGen(num); this.state.gen = num;
      this.ensureSets(num).then(() => {
        this.buildFormatList();
        this.panelA.setSpecies(this.state.a.species, false);
        this.panelB.setSpecies(this.state.b.species, false);
        this.panelA.refreshSets(); this.panelB.refreshSets();
        this.recompute();
      });
    },

    swap() {
      const t = this.state.a; this.state.a = this.state.b; this.state.b = t;
      this.panelA.st = this.state.a; this.panelB.st = this.state.b;
      const fa = this.state.field.attackerSide; this.state.field.attackerSide = this.state.field.defenderSide; this.state.field.defenderSide = fa;
      this.panelA.syncFromState(); this.panelB.syncFromState();
      this.syncFieldControls(); this.recompute();
    },

    reset() {
      localStorage.removeItem(LS_KEY);
      this.state = this.seed(); this.format = 'All'; this.mode = '1v1';
      this.panelA.st = this.state.a; this.panelB.st = this.state.b;
      this.field.st = this.state.field;
      document.getElementById('gen-select').value = 9; E.setGen(9);
      this.buildFormatList();
      this.panelA.syncFromState(); this.panelB.syncFromState();
      this.syncFieldControls(); this.applyMode(); this.recompute();
      this.toast('Reset to default matchup');
    },

    rollRandom() {
      this.toast('Rolling random battle…');
      root.RandomData.rollMatchup(this.state.gen).then(({ a, b }) => {
        this.state.a = Object.assign(blankMon(a.species), a);
        this.state.b = Object.assign(blankMon(b.species), b);
        this.panelA.st = this.state.a; this.panelB.st = this.state.b;
        this.panelA.syncFromState(); this.panelB.syncFromState();
        this.recompute();
        this.toast('Rolled: ' + a.species + ' vs ' + b.species);
      }).catch((e) => this.toast('Random sets unavailable for this gen'));
    },

    syncFieldControls() {
      const f = this.field.el, st = this.state.field;
      const q = (s) => f.querySelector(s);
      q('[data-gametype]').value = st.gameType || 'Singles';
      q('[data-weather]').value = st.weather || '';
      q('[data-terrain]').value = st.terrain || '';
      f.querySelectorAll('[data-global]').forEach(cb => cb.checked = !!st[cb.dataset.key]);
      f.querySelectorAll('input[data-side]').forEach(cb => {
        const side = st[cb.dataset.side] || {};
        cb.checked = cb.dataset.val ? side[cb.dataset.key] === cb.dataset.val : !!side[cb.dataset.key];
      });
      f.querySelectorAll('select[data-side]').forEach(sel => { sel.value = (st[sel.dataset.side] || {}).spikes || 0; });
      root.reflectForm(f);
    },

    recompute() {
      const a = this.state.a, b = this.state.b, field = this.state.field;
      this.state.format = this.format; this.state.mode = this.mode; this.state.animated = this.animated;
      if (this.mode === '1vAll') {
        this.pool.setData('1vAll', a, field, this.format, this.state.gen);
      } else if (this.mode === 'Allv1') {
        this.pool.setData('Allv1', b, field, this.format, this.state.gen);
      } else {
        const resA = [0, 1, 2, 3].map(i => a.moves[i] ? E.run(a, b, a.moves[i], field, a.moveOpts && a.moveOpts[i]) : { empty: true });
        const resB = [0, 1, 2, 3].map(i => b.moves[i] ? E.run(b, a, b.moves[i], field, b.moveOpts && b.moveOpts[i]) : { empty: true });
        this.results.render(a, b, resA, resB);
      }
      this.save();
      if (root.reflectForm) root.reflectForm(document.body);
    },

    // ---- modal (import / export / save) ----
    wireModal() {
      document.getElementById('modal-close').addEventListener('click', () => this.closeModal());
      document.getElementById('modal-back').addEventListener('click', (e) => { if (e.target.id === 'modal-back') this.closeModal(); });
      document.getElementById('modal-confirm').addEventListener('click', () => this.confirmModal());
    },
    openImport(role) {
      this.modalMode = 'import'; this.modalRole = role;
      this.showModal('Import ' + (role === 'atk' ? 'Attacker' : 'Defender'), 'Import Set', true, false);
      const ta = document.getElementById('modal-text');
      ta.value = '';
      ta.placeholder = 'Paste a Showdown set, e.g.\n\nGreat Tusk @ Booster Energy\nAbility: Protosynthesis\nTera Type: Ground\nEVs: 252 Atk / 4 HP / 252 Spe\nJolly Nature\n- Headlong Rush\n- Close Combat\n- Ice Spinner\n- Rapid Spin';
      document.getElementById('modal-hint').textContent = 'Paste from Pokémon Showdown teambuilder or any standard set export.';
      setTimeout(() => ta.focus(), 50);
    },
    openExport() {
      this.modalMode = 'export';
      this.showModal('Export Both Sets', 'Copy', true, false);
      const a = this.toExport(this.state.a), b = this.toExport(this.state.b);
      const ta = document.getElementById('modal-text');
      ta.value = D.exportSet(a) + '\n\n' + D.exportSet(b);
      document.getElementById('modal-hint').textContent = 'Standard Showdown format — paste into the teambuilder or share.';
      setTimeout(() => ta.select(), 50);
    },
    openSaveSet(role) {
      this.modalMode = 'save'; this.modalRole = role;
      const st = role === 'atk' ? this.state.a : this.state.b;
      this.showModal('Save Custom Set', 'Save Set', false, true);
      const inp = document.getElementById('modal-name');
      inp.value = (st.setName && st.setName.charAt(0) !== '★') ? st.setName : (E.speciesInfo(st.species)?.name || '') + ' Custom';
      document.getElementById('modal-hint').textContent = 'Saved to this browser. Appears as “★ …” in the set list for ' + (E.speciesInfo(st.species)?.name || 'this Pokémon') + '.';
      setTimeout(() => { inp.focus(); inp.select(); }, 50);
    },
    showModal(title, confirmLabel, showText, showName) {
      document.getElementById('modal-title').textContent = title;
      document.getElementById('modal-confirm').textContent = confirmLabel;
      document.getElementById('modal-text').style.display = showText ? '' : 'none';
      document.getElementById('modal-name-row').style.display = showName ? '' : 'none';
      document.getElementById('modal-back').classList.add('open');
    },
    toExport(st) {
      return { species: st.species, item: st.item, ability: st.ability, level: st.level,
        nature: st.nature, teraType: st.teraActive ? st.teraType : '', evs: st.evs, ivs: st.ivs, moves: st.moves };
    },
    confirmModal() {
      if (this.modalMode === 'export') {
        const ta = document.getElementById('modal-text'); ta.select();
        try { navigator.clipboard.writeText(ta.value); } catch (e) { document.execCommand('copy'); }
        this.toast('Copied to clipboard'); return;
      }
      if (this.modalMode === 'save') {
        const name = (document.getElementById('modal-name').value || '').trim();
        if (!name) { this.toast('Enter a set name'); return; }
        const role = this.modalRole, st = role === 'atk' ? this.state.a : this.state.b;
        S.saveCustom(this.state.gen, st.species, name, st);
        st.setName = '★ ' + name;
        (role === 'atk' ? this.panelA : this.panelB).refreshSets();
        this.closeModal(); this.toast('Saved “' + name + '”'); return;
      }
      // import
      const text = document.getElementById('modal-text').value;
      const set = D.parseSet(text);
      if (!set || !set.species) { this.toast('Could not parse set'); return; }
      const target = this.modalRole === 'atk' ? this.state.a : this.state.b;
      const panel = this.modalRole === 'atk' ? this.panelA : this.panelB;
      const info = E.speciesInfo(set.species);
      target.species = info ? info.name : set.species;
      target.level = set.level || 100; target.nature = set.nature || 'Hardy';
      target.item = set.item || ''; target.ability = set.ability || (info ? (info.abilities[0] || '') : '');
      target.teraType = set.teraType || ''; target.teraActive = !!set.teraType;
      target.evs = {}; target.ivs = {}; target.boosts = {}; target.setName = '';
      Object.assign(target.evs, set.evs); Object.assign(target.ivs, set.ivs);
      target.moves = (set.moves || []).slice(0, 4); while (target.moves.length < 4) target.moves.push('');
      target.moveOpts = [{}, {}, {}, {}];
      panel.st = target; panel.syncFromState();
      this.closeModal(); this.recompute(); this.toast('Imported ' + target.species);
    },
    closeModal() { document.getElementById('modal-back').classList.remove('open'); },

    toast(msg) {
      const t = document.getElementById('toast');
      t.textContent = msg; t.classList.add('show');
      clearTimeout(this._tt); this._tt = setTimeout(() => t.classList.remove('show'), 1800);
    },

    save() { try { localStorage.setItem(LS_KEY, JSON.stringify(this.state)); } catch (e) {} },
    load() { try { const s = localStorage.getItem(LS_KEY); return s ? JSON.parse(s) : null; } catch (e) { return null; } }
  };

  root.CalcApp = App;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => App.init());
  else App.init();
})(window);
