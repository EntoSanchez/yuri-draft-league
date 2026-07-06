/* =====================================================================
   ui-mon.js — one combatant (attacker or defender) panel
   ===================================================================== */
(function (root) {
  'use strict';
  const D = root.CalcData, E = root.Engine, Combo = root.Combo, esc = root.escHtml;

  // ── Effective-stat modifiers (display): boost stage × item × ability × status ──
  const BOOST_MULT = { '6':4,'5':3.5,'4':3,'3':2.5,'2':2,'1':1.5,'0':1,'-1':2/3,'-2':0.5,'-3':0.4,'-4':1/3,'-5':2/7,'-6':0.25 };
  const _id = s => ('' + (s || '')).toLowerCase().replace(/[^a-z0-9]/g, '');
  function itemMult(item, stat, sid) {
    const it = _id(item);
    if (it === 'choiceband'  && stat === 'atk') return 1.5;
    if (it === 'choicespecs' && stat === 'spa') return 1.5;
    if (it === 'choicescarf' && stat === 'spe') return 1.5;
    if (it === 'assaultvest' && stat === 'spd') return 1.5;
    if (it === 'eviolite' && (stat === 'def' || stat === 'spd')) return 1.5;
    if (it === 'ironball' && stat === 'spe') return 0.5;
    if (it === 'lightball' && sid === 'pikachu' && (stat === 'atk' || stat === 'spa')) return 2;
    if (it === 'thickclub' && (sid === 'cubone' || sid === 'marowak' || sid === 'marowakalola') && stat === 'atk') return 2;
    if (it === 'souldew' && (sid === 'latios' || sid === 'latias') && (stat === 'spa' || stat === 'spd')) return 1.5;
    if (it === 'deepseatooth' && sid === 'clamperl' && stat === 'spa') return 2;
    if (it === 'deepseascale' && sid === 'clamperl' && stat === 'spd') return 2;
    if (it === 'metalpowder' && sid === 'ditto' && stat === 'def') return 1.5;
    if (it === 'quickpowder' && sid === 'ditto' && stat === 'spe') return 2;
    return 1;
  }
  function abilityMult(ability, stat, status) {
    const a = _id(ability), s = status || '';
    if ((a === 'hugepower' || a === 'purepower') && stat === 'atk') return 2;
    if ((a === 'hustle' || a === 'gorillatactics') && stat === 'atk') return 1.5;
    if (a === 'furcoat' && stat === 'def') return 2;
    if (a === 'guts' && s && stat === 'atk') return 1.5;
    if (a === 'flareboost' && s === 'brn' && stat === 'spa') return 1.5;
    if (a === 'toxicboost' && (s === 'psn' || s === 'tox') && stat === 'atk') return 1.5;
    if (a === 'marvelscale' && s && stat === 'def') return 1.5;
    if (a === 'quickfeet' && s && stat === 'spe') return 1.5;
    return 1;
  }
  function statusMult(status, stat, ability) {
    const a = _id(ability);
    if (status === 'brn' && stat === 'atk' && a !== 'guts') return 0.5;
    if (status === 'par' && stat === 'spe' && a !== 'quickfeet') return 0.5;  // gen 7+
    return 1;
  }
  // Apply all display modifiers to a raw (nature/EV/IV) stat.
  function effectiveStat(stat, raw, st, sid) {
    if (stat === 'hp') return raw;
    let v = Math.floor(raw * (BOOST_MULT[String(st.boosts[stat] || 0)] || 1));
    v = Math.floor(v * itemMult(st.item, stat, sid));
    v = Math.floor(v * abilityMult(st.ability, stat, st.status) * statusMult(st.status, stat, st.ability));
    return v;
  }

  // ── Hover tooltips for move/item combos (uses bundled dex-mini.json) ──
  const TIP_CAT = c => c === 'Physical' ? '#ff7a8f' : c === 'Special' ? '#5fe0ff' : '#b0b3c0';
  function moveTipHTML(name) {
    if (!name) return null;
    const dex = (root._DEX && root._DEX.moves) || {};
    const d = dex[_id(name)];
    const e = E.moveInfo(name);
    if (!d && !e) return null;
    const type = (d && d.t) || (e && e.type) || '?';
    const cat = (d && d.c) || (e && e.category) || 'Status';
    const bp = (e && e.bp) || (d && d.bp) || 0;
    const acc = (d && d.acc) || 0;
    const eff = (d && d.d) || '';
    const tc = D.TYPE_COLORS[type] || '#9099a1';
    return `<div class="cdt-h">${esc(name)}</div>` +
      `<div class="cdt-meta"><span style="color:${tc}">${type}</span><span style="color:${TIP_CAT(cat)}">${cat}</span>` +
      `<span>BP <b>${bp || '—'}</b></span><span>ACC <b>${acc || '—'}</b></span></div>` +
      (eff ? `<div class="cdt-d">${esc(eff)}</div>` : '');
  }
  function itemTipHTML(name) {
    if (!name) return null;
    const dex = (root._DEX && root._DEX.items) || {};
    const d = dex[_id(name)];
    if (!d) return null;
    return `<div class="cdt-h" style="color:#ff8fe6">${esc(name)}</div>` + (d.d ? `<div class="cdt-d">${esc(d.d)}</div>` : '');
  }
  function abilityTipHTML(name) {
    if (!name) return null;
    const dex = (root._DEX && root._DEX.abilities) || {};
    const d = dex[_id(name)];
    if (!d) return null;
    return `<div class="cdt-h" style="color:#7bd88f">${esc(name)}</div>` + (d.d ? `<div class="cdt-d">${esc(d.d)}</div>` : '');
  }

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
      const STAT_LBL = { atk: 'Atk', def: 'Def', spa: 'SpA', spd: 'SpD', spe: 'Spe' };
      const natureOpts = D.NATURE_NAMES.map(n => {
        const [plus, minus] = D.NATURES[n];
        const lbl = plus ? `${n}  +${STAT_LBL[plus]} / −${STAT_LBL[minus]}` : `${n}`;
        return `<option value="${n}">${lbl}</option>`;
      }).join('');
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
            <div class="mega-row" data-mega-row style="display:none;align-items:center;gap:6px;margin-top:3px">
              <label style="font-family:var(--font-mono);font-size:9px;letter-spacing:.1em;color:var(--text-dim)">FORME</label>
              <select class="field" data-mega style="flex:1;min-width:0"></select>
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
        if (!team.pokemon || !team.pokemon.length) {
          monSel.innerHTML = '<option value="">No draft picks yet</option>';
          monSel.style.display = '';
          return;
        }
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
        tip: abilityTipHTML,
        onPick: (v) => { this.st.ability = v; this.refreshStats(); this.changed(); }
      });
      this.combos.item = new Combo(this.q('[data-item]'), {
        placeholder: 'Item', allowFree: true,
        getList: () => E.lists().items,
        tip: itemTipHTML,
        onPick: (v) => { this.st.item = v; this.refreshStats(); this.changed(); }
      });
      this.q('[data-ability]').addEventListener('change', () => { this.st.ability = this.q('[data-ability]').value; this.refreshStats(); this.changed(); });
      this.q('[data-item]').addEventListener('change', () => { this.st.item = this.q('[data-item]').value; this.refreshStats(); this.changed(); });

      // moves
      [0, 1, 2, 3].forEach(i => {
        this.combos['move' + i] = new Combo(this.q(`[data-move="${i}"]`), {
          placeholder: 'Move ' + (i + 1), allowFree: true,
          getList: () => E.lists().moves,
          decorate: (v) => { const m = E.moveInfo(v); return m ? { dot: D.TYPE_COLORS[m.type], meta: m.category === 'Status' ? '—' : m.bp } : null; },
          tip: moveTipHTML,
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
      this.q('[data-status]').addEventListener('change', () => { this.st.status = this.q('[data-status]').value; this.refreshStats(); this.changed(); });
      // mega / forme toggle
      this.q('[data-mega]').addEventListener('change', () => {
        const v = this.q('[data-mega]').value;
        if (v) { this.combos.species.setValue(v); this.setSpecies(v, true); }
      });
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
        sel.addEventListener('change', () => { this.st.boosts[sel.dataset.boost] = parseInt(sel.value) || 0; this.refreshStats(); this.changed(); });
      });

      this.q('[data-act="import"]').addEventListener('click', () => root.CalcApp.openImport(this.role));

      // set selector
      this.q('[data-set]').addEventListener('change', (e) => { if (e.target.value) this.applySetByName(e.target.value); });
      this.q('[data-act="save-set"]').addEventListener('click', () => root.CalcApp.openSaveSet(this.role));

      // tera toggle
      this.q('[data-teraon]').addEventListener('change', (e) => { this.st.teraActive = e.target.checked; this.renderTypes(); this.changed(); });

      // per-move option toggles (always visible)
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
        // Auto mega stone: equip the selected Mega's stone. First clear a stone we
        // previously auto-equipped (so switching forme/base doesn't strand it), but
        // leave a manually-chosen item untouched.
        if (this.st._autoStone && this.st.item === this.st._autoStone) {
          this.st.item = ''; this.combos.item.setValue('');
        }
        this.st._autoStone = '';
        if (info.stone) {
          this.st.item = info.stone;
          this.combos.item.setValue(info.stone);
          this.st._autoStone = info.stone;
        }
      }
      this.renderTypes();
      this.renderSprite();
      this.refreshMegaControl();
      this.refreshSets();
      // On a fresh species pick, auto-apply the first available preset set so the
      // panel loads a real spread/moves (and the stat bars reflect it) instead of a
      // blank 0-EV default. applySetByName handles stats + recompute; if there are no
      // presets, fall back to just refreshing the stat display.
      if (resetDefaults) {
        const firstSet = this._firstSetName();
        if (firstSet) { this.applySetByName(firstSet); return; }
      }
      this.refreshStats();
      this.changed();
    }

    // The first preset-set name currently in the dropdown (skips the placeholder).
    _firstSetName() {
      const sel = this.q('[data-set]');
      if (!sel) return '';
      for (const opt of sel.options) { if (opt.value) return opt.value; }
      return '';
    }

    // Show a Base/Mega forme switcher when the current mon has league Mega forme(s).
    refreshMegaControl() {
      const row = this.q('[data-mega-row]'); const sel = this.q('[data-mega]');
      if (!row || !sel) return;
      const base = E.baseOf(this.st.species);
      const megas = E.megasForBase(base);
      if (!megas.length) { row.style.display = 'none'; return; }
      const cur = E.toID(this.st.species);
      let opts = `<option value="${esc(base)}"${cur === E.toID(base) ? ' selected' : ''}>${esc(base)} (base)</option>`;
      opts += megas.map(m => `<option value="${esc(m)}"${cur === E.toID(m) ? ' selected' : ''}>${esc(m)}</option>`).join('');
      sel.innerHTML = opts;
      row.style.display = 'flex';
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
      let chain = D.spriteChain(info.name, animated);
      // League Megas: the default chain collapses "Mega Garchomp" → "megagarchomp"
      // (no such Showdown sprite). Use the backend-provided URLs (Showdown ani for
      // canonical megas, self-hosted PNG for Z-A megas) ahead of the default chain.
      if (info.sprite) chain = [info.sprite, info.spriteStatic].filter(Boolean).concat(chain);
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
      // Load the set's tera type as a suggestion but do NOT terastallize automatically —
      // the user opts in via the Tera toggle. (Auto-teraing on every set/species change
      // silently changed defensive typing and damage numbers.)
      st.nature = norm.nature; st.teraType = norm.teraType; st.teraActive = false;
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
      const sid = E.toID(this.st.species);
      D.STATS.forEach(s => {
        const row = this.el.querySelector(`.stat-row.${s.key}`);
        const base = info.baseStats[s.key];
        row.querySelector('[data-base]').textContent = base;
        const raw = final[s.key];
        const eff = effectiveStat(s.key, raw, this.st, sid);   // boost × item × ability × status
        const totEl = row.querySelector('[data-total]');
        const modCol = eff > raw ? '#7bd88f' : eff < raw ? '#ff6b81' : '';
        const title = (eff !== raw) ? ` title="base ${raw} → ${eff} (item/ability/boost/status)"` : '';
        totEl.innerHTML = `<span${title} style="${modCol ? 'color:' + modCol + ';font-weight:700' : ''}">${eff}</span>`;
        const fill = row.querySelector('[data-fill]');
        const pct = s.key === 'hp' ? Math.min(100, (base / 255) * 100) : Math.min(100, (eff / 600) * 100);
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
      if (st.species) { this.combos.species.setValue(st.species); this.renderTypes(); this.renderSprite(); this.refreshMegaControl(); }
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
