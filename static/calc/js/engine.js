/* =====================================================================
   engine.js — thin wrapper over @smogon/calc
   Exposes enumerations + a single calc() entry point used by the UI.
   ===================================================================== */
(function (root) {
  'use strict';
  const C = root.calc; // global from production.min.js
  const { Generations, Pokemon, Move, Field, calculate } = C;

  let GEN = null;
  let GEN_NUM = 9;

  // cached enumeration lists per gen
  const cache = {};

  // Custom league species (Megas) — gen 9 has none, so they're injected via a
  // base species + stat/type/ability overrides. Keyed by toID(name).
  let CUSTOM = {};
  function setCustomSpecies(list) {
    CUSTOM = {};
    (list || []).forEach(c => { if (c && c.name) CUSTOM[toID(c.name)] = c; });
    for (const k in cache) delete cache[k];   // rebuild lists so autocomplete includes them
    if (GEN) cache[GEN_NUM] = buildLists(GEN);
  }
  // Megas (league custom species) available for a base species name.
  function megasForBase(baseName) {
    const bid = toID(baseName);
    return Object.values(CUSTOM).filter(c => toID(c.base) === bid).map(c => c.name);
  }
  // The base species of a name (if it's a league mega → its base; else itself).
  function baseOf(name) {
    const c = CUSTOM[toID(name)];
    return c ? c.base : name;
  }

  // → { realName: species to construct, overrides: partial species data | undefined }
  function resolveSpecies(name) {
    const c = CUSTOM[toID(name)];
    if (!c) return { realName: name, overrides: undefined };
    const ov = { name: c.name, types: c.types, baseStats: c.baseStats };
    if (c.ability) ov.abilities = { 0: c.ability };
    return { realName: c.base || c.name, overrides: ov };
  }

  function setGen(num) {
    GEN_NUM = num;
    GEN = Generations.get(num);
    if (!cache[num]) cache[num] = buildLists(GEN);
    return GEN;
  }
  function gen() { return GEN; }
  function genNum() { return GEN_NUM; }

  function buildLists(g) {
    const species = [];
    for (const s of g.species) if (s.nfe !== undefined || true) species.push(s.name);
    Object.values(CUSTOM).forEach(c => species.push(c.name));   // league Megas
    const moves = [];
    for (const m of g.moves) moves.push(m.name);
    const items = [];
    for (const i of g.items) items.push(i.name);
    const abilities = [];
    for (const a of g.abilities) abilities.push(a.name);
    species.sort(byName); moves.sort(byName); items.sort(byName); abilities.sort(byName);
    return { species, moves, items, abilities };
  }
  function byName(a, b) { return a.localeCompare(b); }

  function lists() { return cache[GEN_NUM]; }

  function speciesInfo(name) {
    if (!name) return null;
    const c = CUSTOM[toID(name)];
    if (c) {
      const base = GEN.species.get(toID(c.base || ''));
      return {
        name: c.name, types: c.types, baseStats: c.baseStats,
        weightkg: base ? base.weightkg : 100,
        abilities: c.ability ? [c.ability] : (base && base.abilities ? Object.values(base.abilities) : []),
        sprite: c.sprite || null, spriteStatic: c.spriteStatic || null, stone: c.stone || ''
      };
    }
    const s = GEN.species.get(toID(name));
    if (!s) return null;
    return {
      name: s.name,
      types: s.types,
      baseStats: s.baseStats,
      weightkg: s.weightkg,
      abilities: s.abilities ? Object.values(s.abilities) : []
    };
  }

  function moveInfo(name) {
    if (!name) return null;
    const m = GEN.moves.get(toID(name));
    if (!m) return null;
    return { name: m.name, type: m.type, category: m.category, bp: m.basePower };
  }

  function abilityExists(name) { return !!GEN.abilities.get(toID(name)); }
  function itemExists(name) { return !!GEN.items.get(toID(name)); }

  function toID(s) { return ('' + s).toLowerCase().replace(/[^a-z0-9]+/g, ''); }

  // Build a Pokemon from UI state object
  function buildPokemon(st) {
    const r = resolveSpecies(st.species);
    const opts = {
      level: st.level || 100,
      ability: st.ability || undefined,
      abilityOn: !!st.abilityOn,
      item: st.item || undefined,
      nature: st.nature || 'Hardy',
      ivs: st.ivs || {},
      evs: st.evs || {},
      boosts: st.boosts || {},
      status: st.status || '',
      teraType: (st.teraActive && st.teraType) ? st.teraType : undefined,
      moves: (st.moves || []).filter(Boolean),
      overrides: r.overrides,
    };
    if (st.curHPpercent != null) {
      // set originalCurHP based on percent after we know maxHP — do a two-pass
    }
    const p = new Pokemon(GEN, r.realName, opts);
    if (st.curHPpercent != null && st.curHPpercent < 100) {
      const hp = p.maxHP();
      p.originalCurHP = Math.max(1, Math.floor(hp * st.curHPpercent / 100));
    }
    return p;
  }

  function buildField(f) {
    return new Field({
      gameType: f.gameType || 'Singles',
      weather: f.weather || undefined,
      terrain: f.terrain || undefined,
      isGravity: !!f.isGravity,
      isMagicRoom: !!f.isMagicRoom,
      isWonderRoom: !!f.isWonderRoom,
      isBeadsOfRuin: !!f.isBeadsOfRuin,
      isSwordOfRuin: !!f.isSwordOfRuin,
      isTabletsOfRuin: !!f.isTabletsOfRuin,
      isVesselOfRuin: !!f.isVesselOfRuin,
      attackerSide: f.attackerSide || {},
      defenderSide: f.defenderSide || {},
    });
  }

  // Champions Meta move overrides (Pokemon Champions game mechanics)
  const CHAMPS_OVERRIDES = {
    'Apple Acid':       { bp: 90 },
    'Beak Blast':       { bp: 120 },
    'Bone Rush':        { bp: 30 },
    'Fire Lash':        { bp: 90 },
    'First Impression': { bp: 100 },
    'Grav Apple':       { bp: 90 },
    'Infernal Parade':  { bp: 65 },
    'Mountain Gale':    { bp: 120 },
    'Night Daze':       { bp: 90 },
    'Psyshield Bash':   { bp: 90 },
    'Spirit Shackle':   { bp: 90 },
    'Trop Kick':        { bp: 85 },
    'Snap Trap':        { type: 'Steel' },
    'Crush Claw':       { slicing: true },
    'Shadow Claw':      { slicing: true },
    'Dragon Claw':      { slicing: true },
  };

  function applyChampsMeta(move) {
    const o = CHAMPS_OVERRIDES[move.name];
    if (!o) return;
    if (o.bp    !== undefined) move.bp   = o.bp;
    if (o.type  !== undefined) move.type = o.type;
    if (o.slicing) { try { move.flags.slicing = true; } catch (e) {} }
  }

  // Main: returns a normalized result for one move, or {error} / {empty}
  function run(atkState, defState, moveName, fieldState, moveOpt, meta) {
    if (!moveName) return { empty: true };
    try {
      const attacker = buildPokemon(atkState);
      const defender = buildPokemon(defState);
      const mo = moveOpt || {};
      const move = new Move(GEN, moveName, {
        ability: attacker.ability, item: attacker.item, species: attacker.species.name,
        isCrit: !!mo.isCrit, useZ: !!mo.useZ, useMax: !!mo.useMax,
        hits: mo.hits || undefined
      });
      if (meta === 'champions') applyChampsMeta(move);
      const field = buildField(fieldState);
      const result = calculate(GEN, attacker, defender, move, field);

      // status move or 0 bp → no damage
      let dmg = result.damage;
      const isArr = Array.isArray(dmg);
      const flat = isArr ? dmg.flat() : [dmg];
      const maxRoll = Math.max.apply(null, flat);
      if (move.category === 'Status') {
        return { status: true, moveName: move.name, type: move.type, category: move.category, bp: move.bp };
      }
      if (maxRoll === 0) {
        return { immune: true, moveName: move.name, type: move.type, category: move.category, bp: move.bp };
      }

      const hp = defender.maxHP();
      let range;
      try { range = result.range(); } catch (e) { range = [Math.min.apply(null, flat), maxRoll]; }
      const [minD, maxD] = range;
      const pctMin = (minD / hp) * 100;
      const pctMax = (maxD / hp) * 100;

      let desc = '';
      try { desc = result.desc(); } catch (e) { desc = ''; }
      // split off KO clause
      let amount = `${minD}-${maxD}`;
      let verdict = '', ko = '';
      const dashIdx = desc.indexOf(' -- ');
      if (dashIdx >= 0) { ko = desc.slice(dashIdx + 4); verdict = desc.slice(0, dashIdx); }
      else verdict = desc;

      // rolls
      let rolls = flat.slice();

      return {
        ok: true,
        moveName: move.name, type: move.type, category: move.category, bp: move.bp,
        minD, maxD, hp, pctMin, pctMax,
        desc, verdict, ko, koClass: koClass(ko),
        amount, rolls
      };
    } catch (e) {
      return { error: e.message };
    }
  }

  function koClass(ko) {
    if (!ko) return 'none';
    const t = ko.toLowerCase();
    if (t.includes('guaranteed')) return 'guaranteed';
    const m = t.match(/([\d.]+)%\s*chance/);
    if (m) { const p = parseFloat(m[1]); return p >= 50 ? 'likely' : 'unlikely'; }
    if (t.includes('possible')) return 'likely';
    return 'none';
  }

  // Compute display stats (final) for the stat table preview
  function finalStats(st) {
    try {
      const p = buildPokemon(st);
      return p.rawStats;
    } catch (e) { return null; }
  }

  // Best damaging move (max %) of an attacker vs a defender across given moves.
  function runBest(atkState, defState, field, moveOpts) {
    const moves = (atkState.moves || []).filter(Boolean);
    let best = null;
    moves.forEach((mv, i) => {
      const r = run(atkState, defState, mv, field, (moveOpts && moveOpts[i]) || null);
      if (r && r.ok && (!best || r.pctMax > best.pctMax)) best = r;
    });
    return best;
  }

  // Build a combatant state from a species + normalized set (for pool tables)
  function stateFromSet(species, setData) {
    return Object.assign({ species, status: '', curHPpercent: 100, boosts: {}, teraActive: !!(setData && setData.teraType) }, setData || {});
  }

  root.Engine = {
    setGen, gen, genNum, lists, speciesInfo, moveInfo,
    abilityExists, itemExists, buildPokemon, run, runBest, stateFromSet, finalStats, toID,
    setCustomSpecies, resolveSpecies, megasForBase, baseOf
  };
})(window);
