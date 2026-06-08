/* =====================================================================
   sets.js — Smogon preset sets + metagame formats + custom (saved) sets
   Depends on the SETDEX_* globals loaded from data/sets/genN.js
   ===================================================================== */
(function (root) {
  'use strict';

  const GEN_VAR = {
    1: 'SETDEX_RBY', 2: 'SETDEX_GSC', 3: 'SETDEX_ADV', 4: 'SETDEX_DPP',
    5: 'SETDEX_BW', 6: 'SETDEX_XY', 7: 'SETDEX_SM', 8: 'SETDEX_SS', 9: 'SETDEX_SV'
  };
  const SK = { hp: 'hp', at: 'atk', df: 'def', sa: 'spa', sd: 'spd', sp: 'spe' };

  // Ordered longest/most-specific first so startsWith matching picks the right tag.
  const FORMAT_PREFIXES = [
    'National Dex Doubles', 'National Dex Monotype', 'National Dex UU', 'National Dex RU',
    'National Dex Ubers', 'National Dex AG', 'National Dex BH', 'National Dex',
    'Doubles OU', 'Doubles UU', 'Doubles',
    'Balanced Hackmons', 'Almost Any Ability', 'Mix and Mega', 'STABmons',
    'Godly Gift', 'Partners in Crime', 'Camomons', 'Inheritance', 'The Loser\'s Game',
    'BSS Reg', 'BSS', 'VGC',
    '1v1', 'Ubers UU', 'Ubers', 'Monotype', 'CAP',
    'OU', 'UU', 'RU', 'NU', 'PU', 'ZU', 'LC', 'NFE', 'AG'
  ];

  const CUSTOM_KEY = 'ycs9-calc-customsets-v1';
  let customCache = null;

  function dex(genNum) {
    const v = GEN_VAR[genNum];
    return (v && root[v]) ? root[v] : null;
  }

  function getFormat(setName) {
    for (const p of FORMAT_PREFIXES) {
      if (setName === p || setName.startsWith(p + ' ')) return p;
    }
    return 'Other';
  }

  // All formats present in a gen, as a sorted unique list.
  const fmtCache = {};
  function formats(genNum) {
    if (fmtCache[genNum]) return fmtCache[genNum];
    const d = dex(genNum);
    const set = new Set();
    if (d) {
      for (const sp of Object.keys(d)) {
        for (const sn of Object.keys(d[sp])) set.add(getFormat(sn));
      }
    }
    // present them in our preferred order, then any leftovers
    const ordered = FORMAT_PREFIXES.filter(p => set.has(p));
    if (set.has('Other')) ordered.push('Other');
    fmtCache[genNum] = ordered;
    return ordered;
  }

  function loadCustom() {
    if (customCache) return customCache;
    try { customCache = JSON.parse(localStorage.getItem(CUSTOM_KEY) || '{}'); }
    catch (e) { customCache = {}; }
    return customCache;
  }
  function saveCustomStore() { try { localStorage.setItem(CUSTOM_KEY, JSON.stringify(customCache || {})); } catch (e) {} }

  // species → { setName: setData } including custom sets (custom prefixed ★)
  function forSpecies(genNum, species, toID) {
    const d = dex(genNum);
    const result = {};
    if (d && species) {
      let entry = d[species];
      if (!entry && toID) {
        // try matching by id (handles minor punctuation differences)
        const id = toID(species);
        for (const k of Object.keys(d)) { if (toID(k) === id) { entry = d[k]; break; } }
      }
      if (entry) Object.assign(result, entry);
    }
    // custom sets
    const cust = loadCustom();
    const cs = cust[genNum + '|' + species];
    if (cs) for (const [name, data] of Object.entries(cs)) result['★ ' + name] = data;
    return result;
  }

  function saveCustom(genNum, species, name, normalizedState) {
    const cust = loadCustom();
    const key = genNum + '|' + species;
    if (!cust[key]) cust[key] = {};
    // store in compact SETDEX format
    cust[key][name] = denormalize(normalizedState);
    saveCustomStore();
  }
  function deleteCustom(genNum, species, name) {
    const cust = loadCustom();
    const key = genNum + '|' + species;
    if (cust[key]) { delete cust[key][name.replace(/^★ /, '')]; saveCustomStore(); }
  }
  function listCustom() {
    const cust = loadCustom();
    const out = [];
    for (const [k, sets] of Object.entries(cust)) {
      const [g, sp] = k.split('|');
      for (const n of Object.keys(sets)) out.push({ gen: +g, species: sp, name: n });
    }
    return out;
  }

  // SETDEX compact → app state shape (full stat keys)
  function normalize(s) {
    const out = {
      level: s.level || 100, ability: s.ability || '', item: s.item || '',
      nature: s.nature || 'Hardy', teraType: s.teraType || '',
      evs: {}, ivs: {}, moves: []
    };
    for (const [ab, full] of Object.entries(SK)) {
      if (s.evs && s.evs[ab] != null) out.evs[full] = s.evs[ab];
      if (s.ivs && s.ivs[ab] != null) out.ivs[full] = s.ivs[ab];
    }
    (s.moves || []).slice(0, 4).forEach(m => out.moves.push(Array.isArray(m) ? m[0] : m));
    while (out.moves.length < 4) out.moves.push('');
    return out;
  }
  // app state → SETDEX compact
  function denormalize(st) {
    const inv = { hp: 'hp', atk: 'at', def: 'df', spa: 'sa', spd: 'sd', spe: 'sp' };
    const o = { ability: st.ability || undefined, item: st.item || undefined, nature: st.nature || 'Hardy', moves: (st.moves || []).filter(Boolean) };
    if (st.level && st.level !== 100) o.level = st.level;
    if (st.teraType) o.teraType = st.teraType;
    const evs = {}, ivs = {};
    for (const [full, ab] of Object.entries(inv)) {
      if (st.evs && st.evs[full]) evs[ab] = st.evs[full];
      if (st.ivs && st.ivs[full] != null && st.ivs[full] !== 31) ivs[ab] = st.ivs[full];
    }
    if (Object.keys(evs).length) o.evs = evs;
    if (Object.keys(ivs).length) o.ivs = ivs;
    return o;
  }

  // pool of species names that have at least one set in `format` (or all if 'All')
  const poolCache = {};
  function pool(genNum, format) {
    const ck = genNum + '|' + format;
    if (poolCache[ck]) return poolCache[ck];
    const d = dex(genNum);
    const out = [];
    if (d) {
      for (const sp of Object.keys(d)) {
        if (format === 'All') { out.push(sp); continue; }
        const names = Object.keys(d[sp]);
        if (names.some(n => getFormat(n) === format)) out.push(sp);
      }
    }
    poolCache[ck] = out;
    return out;
  }

  // first/most-relevant set for a species within a format (for pool calcs)
  function defaultSetFor(genNum, species, format, toID) {
    const sets = forSpecies(genNum, species, toID);
    const names = Object.keys(sets);
    if (!names.length) return null;
    if (format && format !== 'All') {
      const match = names.find(n => getFormat(n) === format);
      if (match) return { name: match, data: normalize(sets[match]) };
    }
    return { name: names[0], data: normalize(sets[names[0]]) };
  }

  root.CalcSets = {
    dex, getFormat, formats, forSpecies, normalize, denormalize,
    saveCustom, deleteCustom, listCustom, pool, defaultSetFor, GEN_VAR
  };
})(window);
