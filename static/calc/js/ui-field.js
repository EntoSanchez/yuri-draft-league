/* =====================================================================
   ui-field.js — battlefield conditions panel
   ===================================================================== */
(function (root) {
  'use strict';
  const D = root.CalcData;

  const SIDE_TOGGLES = [
    { k: 'isReflect', label: 'Reflect' },
    { k: 'isLightScreen', label: 'Light Screen' },
    { k: 'isAuroraVeil', label: 'Aurora Veil' },
    { k: 'isTailwind', label: 'Tailwind' },
    { k: 'isHelpingHand', label: 'Helping Hand' },
    { k: 'isFriendGuard', label: 'Friend Guard' },
    { k: 'isSR', label: 'Stealth Rock' },
    { k: 'isProtected', label: 'Protect' },
    { k: 'isSeeded', label: 'Leech Seed' },
    { k: 'isSwitching', label: 'Switching Out', val: 'out' }
  ];
  const GLOBAL_TOGGLES = [
    { k: 'isGravity', label: 'Gravity' },
    { k: 'isMagicRoom', label: 'Magic Room' },
    { k: 'isWonderRoom', label: 'Wonder Room' },
    { k: 'isBeadsOfRuin', label: 'Beads of Ruin' },
    { k: 'isSwordOfRuin', label: 'Sword of Ruin' },
    { k: 'isTabletsOfRuin', label: 'Tablets of Ruin' },
    { k: 'isVesselOfRuin', label: 'Vessel of Ruin' }
  ];

  class FieldPanel {
    constructor(state, onChange) {
      this.st = state; this.onChange = onChange;
      this.el = document.createElement('div');
      this.el.className = 'field-panel';
      this.el.innerHTML = this.template();
      this.wire();
    }
    template() {
      const weatherOpts = D.WEATHERS.map(w => `<option value="${w}">${w || 'No Weather'}</option>`).join('');
      const terrainOpts = D.TERRAINS.map(t => `<option value="${t}">${t ? t + ' Terrain' : 'No Terrain'}</option>`).join('');
      const sideBlock = (side, label, cls) => `
        <div class="field-side ${cls}">
          <h4>${label}</h4>
          <div class="toggle-grid">
            ${SIDE_TOGGLES.map(t => `<label class="tog"><input type="checkbox" data-side="${side}" data-key="${t.k}" ${t.val ? `data-val="${t.val}"` : ''}><span class="box"></span><span class="lbl">${t.label}</span></label>`).join('')}
          </div>
          <div style="display:flex;align-items:center;gap:8px;margin-top:9px">
            <label style="font-family:var(--font-mono);font-size:9px;letter-spacing:.12em;color:var(--text-dim)">SPIKES</label>
            <select class="field" data-side="${side}" data-spikes style="width:70px"><option value="0">0</option><option value="1">1</option><option value="2">2</option><option value="3">3</option></select>
          </div>
        </div>`;
      return `
      <div class="field-head" data-toggle>
        <span class="eyebrow">// field</span>
        <span class="ttl">Battlefield Conditions</span>
        <span class="chev">▾</span>
      </div>
      <div class="field-body">
        <div class="field-global">
          <div class="sel-cell"><label>Format</label><select class="field" data-gametype><option value="Singles">Singles</option><option value="Doubles">Doubles</option></select></div>
          <div class="sel-cell"><label>Weather</label><select class="field" data-weather>${weatherOpts}</select></div>
          <div class="sel-cell"><label>Terrain</label><select class="field" data-terrain>${terrainOpts}</select></div>
          <div class="sel-cell"><label>Global</label>
            <div class="toggle-grid" style="grid-template-columns:1fr 1fr">
              ${GLOBAL_TOGGLES.map(t => `<label class="tog"><input type="checkbox" data-global data-key="${t.k}"><span class="box"></span><span class="lbl">${t.label}</span></label>`).join('')}
            </div>
          </div>
        </div>
        ${sideBlock('attackerSide', 'ATTACKER SIDE', 'atk')}
        ${sideBlock('defenderSide', 'DEFENDER SIDE', 'def')}
      </div>`;
    }
    wire() {
      const q = (s) => this.el.querySelector(s);
      const qa = (s) => Array.from(this.el.querySelectorAll(s));
      q('[data-toggle]').addEventListener('click', () => this.el.classList.toggle('collapsed'));
      q('[data-gametype]').addEventListener('change', (e) => { this.st.gameType = e.target.value; this.changed(); });
      q('[data-weather]').addEventListener('change', (e) => { this.st.weather = e.target.value; this.changed(); });
      q('[data-terrain]').addEventListener('change', (e) => { this.st.terrain = e.target.value; this.changed(); });
      qa('[data-global]').forEach(cb => cb.addEventListener('change', () => { this.st[cb.dataset.key] = cb.checked; this.changed(); }));
      qa('[data-side]').forEach(cb => {
        if (cb.matches('select')) {
          cb.addEventListener('change', () => { this.st[cb.dataset.side].spikes = parseInt(cb.value) || 0; this.changed(); });
        } else {
          cb.addEventListener('change', () => {
            const side = this.st[cb.dataset.side];
            if (cb.dataset.val) side[cb.dataset.key] = cb.checked ? cb.dataset.val : undefined;
            else side[cb.dataset.key] = cb.checked;
            this.changed();
          });
        }
      });
    }
    changed() { if (this.onChange) this.onChange(); }
  }
  root.FieldPanel = FieldPanel;
})(window);
