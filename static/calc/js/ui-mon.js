/* =====================================================================
   ui-mon.js — one combatant (attacker or defender) panel
   ===================================================================== */
(function (root) {
  'use strict';
  const D = root.CalcData, E = root.Engine, Combo = root.Combo, esc = root.escHtml;

  class MonPanel {
    constructor(role, state, onChange) {
      this.role = role;            // 'atk' | 'def'
      this.st = state;
      this.onChange = onChange;
      this.combos = {};
      this.el = document.createElement('div');
      this.el.className = 'mon ' + role;
      this.el.innerHTML = this.template();
      this.q = (s) => this.el.querySelector(s);
      this.qa = (s) => Array.from(this.el.querySelectorAll(s));
      this.wire();
    }

    template() {
      const roleLabel = this.role === 'atk' ? 'ATTACKER' : 'DEFENDER';
      const idx = this.role === 'atk' ? '01' : '02';
      const natureOpts = D.NATURE_NAMES.map(n => `<option value="${n}">${n}</option>`).join('');
      const statusOpts = D.STATUSES.map(s => `<option value="${s.v}">${s.label}</option>`).join('');
      const typeOpts = ['<option value="">— Tera —</option>'].concat(D.TYPES.map(t => `<option value="${t}">${t}</option>`)).join('');
      const statRows = D.STATS.map(s => `
        <div class="stat-row ${s.key}" data-stat="${s.key}">
          <span class="sname">${s.label}</span>
          <span class="sbase" data-base>—</span>
          <span class="sbar"><i data-fill style="width:0%"></i></span>
          <input class="field iv" type="number" min="0" max="31" value="31" data-iv title="IVs">
          <input class="field ev" type="number" min="0" max="252" step="4" value="0" data-ev title="EVs">
          <span class="nat" data-nat title="Nature effect"></span>
          <span class="stot" data-total>—</span>
        </div>`).join('');
      const boostStages = ['atk', 'def', 'spa', 'spd', 'spe'].map(k => {
        const opts = [];
        for (let i = 6; i >= -6; i--) opts.push(`<option value="${i}"${i === 0 ? ' selected' : ''}>${i > 0 ? '+' + i : i}</option>`);
        return `<div class="boost-stage"><label>${k.toUpperCase()}</label><select class="field" data-boost="${k}">${opts.join('')}</select></div>`;
      }).join('');

      return `
      <div class="mon-head">
        <span class="mon-role"><span class="idx">${idx}</span> ${roleLabel}</span>
        <span class="spacer"></span>
        <button class="btn sm" data-act="import">Import</button>
      </div>
      <div class="mon-body">
        <div class="species-row">
          <div class="sprite" data-sprite><span class="brk tl"></span><span class="brk br"></span><span class="ph">NO MON</span></div>
          <div class="species-meta">
            <div class="species-line">
              <div class="combo"><input data-species></div>
              <div class="lvl-wrap"><span>Lv</span><input class="field lvl" type="number" min="1" max="100" value="100" data-level></div>
            </div>
            <div class="set-line">
              <select class="field" data-set><option value="">— choose preset set —</option></select>
              <button class="save-set" data-act="save-set" title="Save current build as a custom set">★</button>
            </div>
            <div class="league-team-line" style="display:flex;gap:6px;align-items:center">
              <select class="field" data-league-team style="flex:1;min-width:0">
                <option value="">— League Team —</option>
              </select>
              <select class="field" data-league-mon style="flex:1;min-width:0;display:none">
                <option value="">— Pokémon —</option>
              </select>
            </div>
            <div class="type-tera">
              <div class="types" data-types></div>
              <select class="field" data-tera style="width:88px">${typeOpts}</select>
              <label class="tera-tog"><input type="checkbox" data-teraon><span class="box"></span><span class="lbl">Tera</span></label>
            </div>
          </div>
        </div>

        <div class="sel-grid">
          <div class="sel-cell"><label>Ability</label><div class="combo"><input data-ability></div></div>
          <div class="sel-cell"><label>Item</label><div class="combo"><input data-item></div></div>
          <div class="sel-cell"><label>Nature</label><select class="field" data-nature>${natureOpts}</select></div>
          <div class="sel-cell"><label>Status</label><select class="field" data-status>${statusOpts}</select></div>
        </div>

        <div class="stats">
          <div class="stats-head">
            <span>STAT</span><span class="r">BASE</span><span class="r"></span><span class="r">IV</span><span class="r">EV</span><span class="r"></span><span class="r" style="text-align:right">TOTAL</span>
          </div>
          ${statRows}
          <div class="stat-tools">
            <span class="ev-left">EVs LEFT <b data-evleft>508</b> / 508</span>
          </div>
          <div class="boost-row" style="margin-top:8px">
            <label style="font-family:var(--font-mono);font-size:9px;color:var(--text-dim);letter-spacing:.12em">BOOST</label>
            <div class="boost-stages">${boostStages}</div>
          </div>
        </div>

        <div class="moves">
          <div class="moves-label"><span class="eyebrow ${this.role === 'atk' ? 'mag' : ''}" style="${this.role === 'def' ? 'color:var(--cyan)' : ''}">// moveset</span><span class="rule"></span></div>
          ${[0, 1, 2, 3].map(i => `
          <div class="move-row" data-moverow="${i}">
            <div class="move-slot">
              <span class="mtype-dot" data-mtypedot="${i}" style="display:none"></span>
              <div class="combo"><input data-move="${i}"></div>
              <button class="move-opt-btn" data-moveoptbtn="${i}" title="Crit · Z-Move · Max · multi-hit">⚙</button>
            </div>
            <div class="move-opts" data-moveopts="${i}">
              <label class="mini-tog"><input type="checkbox" data-mopt="isCrit" data-mi="${i}">CRIT</label>
              <label class="mini-tog"><input type="checkbox" data-mopt="useZ" data-mi="${i}">Z-MOVE</label>
              <label class="mini-tog"><input type="checkbox" data-mopt="useMax" data-mi="${i}">MAX</label>
              <span class="mini-hits">HITS <input class="field" type="number" min="1" max="10" data-mopt="hits" data-mi="${i}" placeholder="—"></span>
            </div>
          </div>`).join('')}
        </div>
      </div>`;
    }

    wire() {
      // ── League team picker ──
      const teamSel = this.q('[data-league-team]');
      const monSel  = this.q('[data-league-mon]');
      if (!root._calcTeamsCache) root._calcTeamsCache = null;
      const loadTeams = () => {
        if (root._calcTeamsCache) { populateTeams(root._calcTeamsCache); return; }
        fetch('/api/calc/teams').then(r => r.json()).then(data => {
          root._calcTeamsCache = data;
          populateTeams(data);
        }).catch(() => {});
      };
      const populateTeams = (data) => {
        teamSel.innerHTML = '<option value="">— League Team —</option>' +
          data.map(t => `<option value="${t.id}">${t.team} (${t.coach})</option>`).join('');
      };
      loadTeams();
      teamSel.addEventListener('change', () => {
        const id = parseInt(teamSel.value);
        const team = (root._calcTeamsCache || []).find(t => t.id === id);
        if (!team) { monSel.style.display = 'none'; monSel.innerHTML = '<option value="">— Pokémon —</option>'; return; }
        monSel.innerHTML = '<option value="">— Pokémon —</option>' +
          team.pokemon.map(p => `<option value="${p}">${p}</option>`).join('');
        monSel.style.display = '';
      });
      monSel.addEventListener('change', () => {
        const name = monSel.value;
        if (name) {
          this.combos.species.setValue(name);
          this.setSpecies(name, true);
        }
      });

      // species combo
      this.combos.species = new Combo(this.q('[data-species]'), {
        placeholder: 'Search Pokémon…',
        getList: () => E.lists().species,
        decorate: (v) => { const s = E.speciesInfo(v); return s ? { meta: s.types.join('/') } : null; },
        onPick: (v) => this.setSpecies(v, true)
      });
      // ability / item combos
      this.combos.ability = new Combo(this.q('[data-ability]'), {
        placeholder: 'Ability', allowFree: true,
        getList: () => E.lists().abilities,
        onPick: (v) => { this.st.ability = v; this.changed(); }
      });
      this.combos.item = new Combo(this.q('[data-item]'), {
        placeholder: 'Item', allowFree: true,
        getList: () => E.lists().items,
        onPick: (v) => { this.st.item = v; this.changed(); }
      });
      this.q('[data-ability]').addEventListener('change', () => { this.st.ability = this.q('[data-ability]').value; this.changed(); });
      this.q('[data-item]').addEventListener('change', () => { this.st.item = this.q('[data-item]').value; this.changed(); });

      // moves
      [0, 1, 2, 3].forEach(i => {
        this.combos['move' + i] = new Combo(this.q(`[data-move="${i}"]`), {
          placeholder: 'Move ' + (i + 1), allowFree: true,
          getList: () => E.lists().moves,
          decorate: (v) => { const m = E.moveInfo(v); return m ? { dot: D.TYPE_COLORS[m.type], meta: m.category === 'Status' ? '—' : m.bp } : null; },
          onPick: (v) => { this.st.moves[i] = v; this.refreshMoveDot(i); this.changed(); }
        });
        this.q(`[data-move="${i}"]`).addEventListener('change', () => { this.st.moves[i] = this.q(`[data-move="${i}"]`).value; this.refreshMoveDot(i); this.changed(); });
      });

      // level
      this.q('[data-level]').addEventListener('input', () => {
        let v = parseInt(this.q('[data-level]').value) || 1; v = Math.max(1, Math.min(100, v));
        this.st.level = v; this.refreshStats(); this.changed();
      });
      // nature
      this.q('[data-nature]').addEventListener('change', () => { this.st.nature = this.q('[data-nature]').value; this.refreshStats(); this.changed(); });
      // status
      this.q('[data-status]').addEventListener('change', () => { this.st.status = this.q('[data-status]').value; this.changed(); });
      // tera
      this.q('[data-tera]').addEventListener('change', () => {
        this.st.teraType = this.q('[data-tera]').value;
        this.st.teraActive = !!this.st.teraType;
        this.q('[data-teraon]').checked = this.st.teraActive;
        this.renderTypes(); this.changed();
      });

      // IV / EV
      this.qa('[data-iv]').forEach((inp, i) => {
        const stat = D.STATS[i].key;
        inp.addEventListener('input', () => {
          let v = parseInt(inp.value); if (isNaN(v)) v = 31; v = Math.max(0, Math.min(31, v));
          this.st.ivs[stat] = v; this.refreshStats(); this.changed();
        });
      });
      this.qa('[data-ev]').forEach((inp, i) => {
        const stat = D.STATS[i].key;
        inp.addEventListener('input', () => {
          let v = parseInt(inp.value); if (isNaN(v)) v = 0; v = Math.max(0, Math.min(252, v));
          this.st.evs[stat] = v; inp.value = v; this.refreshStats(); this.changed();
        });
      });
      // boosts
      this.qa('[data-boost]').forEach(sel => {
        sel.addEventListener('change', () => { this.st.boosts[sel.dataset.boost] = parseInt(sel.value) || 0; this.changed(); });
      });

      this.q('[data-act="import"]').addEventListener('click', () => root.CalcApp.openImport(this.role));

      // set selector
      this.q('[data-set]').addEventListener('change', (e) => { if (e.target.value) this.applySetByName(e.target.value); });
      this.q('[data-act="save-set"]').addEventListener('click', () => root.CalcApp.openSaveSet(this.role));

      // tera toggle
      this.q('[data-teraon]').addEventListener('change', (e) => { this.st.teraActive = e.target.checked; this.renderTypes(); this.changed(); });

      // per-move option buttons + toggles
      this.qa('[data-moveoptbtn]').forEach(btn => {
        btn.addEventListener('click', () => {
          const i = btn.dataset.moveoptbtn;
          const opts = this.el.querySelector(`[data-moveopts="${i}"]`);
          const open = opts.classList.toggle('open');
          btn.classList.toggle('on', open);
        });
      });
      this.qa('[data-mopt]').forEach(inp => {
        const i = parseInt(inp.dataset.mi), key = inp.dataset.mopt;
        inp.addEventListener('change', () => {
          if (!this.st.moveOpts[i]) this.st.moveOpts[i] = {};
          if (key === 'hits') {
            const v = parseInt(inp.value); this.st.moveOpts[i].hits = (v && v > 0) ? v : undefined;
          } else {
            this.st.moveOpts[i][key] = inp.checked;
            inp.closest('.mini-tog').classList.toggle('checked', inp.checked);
          }
          this.markMoveOptBtn(i);
          this.changed();
        });
      });

      // initialize from state
      this.syncFromState(true);
    }

    setSpecies(name, resetDefaults) {
      const info = E.speciesInfo(name);
      if (!info) { this.st.species = name; return; }
      this.st.species = info.name;
      this.combos.species.setValue(info.name);
      if (resetDefaults) {
        this.st.ability = info.abilities[0] || '';
        this.combos.ability.setValue(this.st.ability);
        this.st.setName = '';
      }
      this.renderTypes();
      this.renderSprite();
      this.refreshSets();
      this.refreshStats();
      this.changed();
    }

    renderTypes() {
      const info = E.speciesInfo(this.st.species);
      const wrap = this.q('[data-types]');
      if (!info) { wrap.innerHTML = ''; return; }
      let types = info.types.slice();
      let html = types.map(t => {
        const c = D.TYPE_COLORS[t] || '#888';
        return `<span class="tchip" style="--tc:${c};background:${c}">${t}</span>`;
      }).join('');
      if (this.st.teraActive && this.st.teraType) {
        const c = D.TYPE_COLORS[this.st.teraType] || '#888';
        html += `<span class="tchip sm" style="--tc:${c};background:${c};border-style:dashed" title="Terastallized">★ ${this.st.teraType}</span>`;
      }
      wrap.innerHTML = html;
    }

    renderSprite() {
      const sp = this.q('[data-sprite]');
      const info = E.speciesInfo(this.st.species);
      sp.querySelectorAll('img,.ph').forEach(n => n.remove());
      if (!info) { const ph = document.createElement('span'); ph.className = 'ph'; ph.textContent = 'NO MON'; sp.appendChild(ph); return; }
      const animated = !!(root.CalcApp && root.CalcApp.animated);
      const chain = D.spriteChain(info.name, animated);
      const img = document.createElement('img');
      img.alt = info.name;
      let idx = 0;
      img.src = chain[idx];
      img.onerror = () => {
        idx++;
        if (idx < chain.length) { img.src = chain[idx]; return; }
        img.onerror = null; img.remove();
        const ph = document.createElement('span'); ph.className = 'ph'; ph.textContent = info.name.slice(0, 8).toUpperCase(); sp.appendChild(ph);
      };
      sp.appendChild(img);
    }

    refreshMoveDot(i) {
      const dot = this.el.querySelector(`[data-mtypedot="${i}"]`);
      const m = E.moveInfo(this.st.moves[i]);
      if (m) { dot.style.display = 'block'; dot.style.background = D.TYPE_COLORS[m.type] || '#888'; }
      else dot.style.display = 'none';
    }

    markMoveOptBtn(i) {
      const o = this.st.moveOpts[i] || {};
      const active = !!(o.isCrit || o.useZ || o.useMax || o.hits);
      const btn = this.el.querySelector(`[data-moveoptbtn="${i}"]`);
      if (btn) btn.classList.toggle('on', active || this.el.querySelector(`[data-moveopts="${i}"]`).classList.contains('open'));
    }

    // populate the preset-set dropdown for current species + global format
    refreshSets() {
      const sel = this.q('[data-set]');
      if (!root.CalcSets || !root.CalcApp) return;
      const gen = root.CalcApp.state.gen, fmt = root.CalcApp.format;
      const sets = root.CalcSets.forSpecies(gen, this.st.species, E.toID);
      this._sets = sets;
      let names = Object.keys(sets);
      if (fmt && fmt !== 'All') {
        const inFmt = names.filter(n => n.charAt(0) === '★' || root.CalcSets.getFormat(n) === fmt);
        if (inFmt.length) names = inFmt;
      }
      const cur = this.st.setName || '';
      sel.innerHTML = '<option value="">' + (names.length ? '— choose preset set —' : '— no presets —') + '</option>' +
        names.map(n => `<option value="${esc(n)}"${n === cur ? ' selected' : ''}>${esc(n)}</option>`).join('');
    }

    applySetByName(name) {
      const data = this._sets && this._sets[name];
      if (!data) return;
      const norm = root.CalcSets.normalize(data);
      const st = this.st;
      st.setName = name;
      st.level = norm.level; st.ability = norm.ability; st.item = norm.item;
      st.nature = norm.nature; st.teraType = norm.teraType; st.teraActive = !!norm.teraType;
      st.status = ''; st.evs = {}; st.ivs = {}; st.boosts = {};
      Object.assign(st.evs, norm.evs); Object.assign(st.ivs, norm.ivs);
      st.moves = norm.moves.slice(); st.moveOpts = [{}, {}, {}, {}];
      this.syncFromState();
      this.changed();
    }

    refreshStats() {
      const info = E.speciesInfo(this.st.species);
      const evleft = this.q('[data-evleft]');
      const totalEv = D.STATS.reduce((a, s) => a + (this.st.evs[s.key] || 0), 0);
      evleft.textContent = Math.max(0, 508 - totalEv);
      evleft.style.color = totalEv > 508 ? 'var(--red)' : 'var(--lime)';
      if (!info) return;
      const final = E.finalStats(this.st) || {};
      let maxStat = 1;
      D.STATS.forEach(s => { if (s.key !== 'hp') maxStat = Math.max(maxStat, final[s.key] || 0); });
      D.STATS.forEach(s => {
        const row = this.el.querySelector(`.stat-row.${s.key}`);
        const base = info.baseStats[s.key];
        row.querySelector('[data-base]').textContent = base;
        const total = final[s.key];
        const totEl = row.querySelector('[data-total]');
        const boosted = (this.st.boosts[s.key] || 0) !== 0;
        totEl.innerHTML = `<span class="${boosted ? 'boosted' : ''}">${total}</span>`;
        const fill = row.querySelector('[data-fill]');
        const pct = s.key === 'hp' ? Math.min(100, (base / 255) * 100) : Math.min(100, (total / 600) * 100);
        fill.style.width = pct + '%';
        // nature glyph
        const nat = row.querySelector('[data-nat]');
        if (s.key !== 'hp') {
          const m = D.natureMod(this.st.nature, s.key);
          nat.className = 'nat' + (m > 1 ? ' up' : m < 1 ? ' down' : '');
          nat.textContent = m > 1 ? '▲' : m < 1 ? '▼' : '';
        }
      });
    }

    // push state → inputs (after import or init)
    syncFromState(skipSpecies) {
      const st = this.st;
      if (st.species) { this.combos.species.setValue(st.species); this.renderTypes(); this.renderSprite(); }
      this.q('[data-level]').value = st.level || 100;
      this.combos.ability.setValue(st.ability || '');
      this.combos.item.setValue(st.item || '');
      this.q('[data-nature]').value = st.nature || 'Hardy';
      this.q('[data-status]').value = st.status || '';
      this.q('[data-tera]').value = st.teraType || '';
      this.q('[data-teraon]').checked = !!st.teraActive;
      if (!st.moveOpts) st.moveOpts = [{}, {}, {}, {}];
      D.STATS.forEach((s, i) => {
        this.qa('[data-iv]')[i].value = st.ivs[s.key] != null ? st.ivs[s.key] : 31;
        this.qa('[data-ev]')[i].value = st.evs[s.key] != null ? st.evs[s.key] : 0;
      });
      this.qa('[data-boost]').forEach(sel => { sel.value = st.boosts[sel.dataset.boost] || 0; });
      [0, 1, 2, 3].forEach(i => {
        this.combos['move' + i].setValue(st.moves[i] || ''); this.refreshMoveDot(i);
        const o = st.moveOpts[i] || {};
        ['isCrit', 'useZ', 'useMax'].forEach(k => {
          const inp = this.el.querySelector(`[data-mopt="${k}"][data-mi="${i}"]`);
          if (inp) { inp.checked = !!o[k]; inp.closest('.mini-tog').classList.toggle('checked', !!o[k]); }
        });
        const hinp = this.el.querySelector(`[data-mopt="hits"][data-mi="${i}"]`);
        if (hinp) hinp.value = o.hits || '';
        this.markMoveOptBtn(i);
      });
      this.refreshSets();
      this.refreshStats();
      root.reflectForm(this.el);
    }

    changed() { if (this.onChange) this.onChange(); }
  }

  root.MonPanel = MonPanel;
})(window);
