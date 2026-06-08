/* =====================================================================
   randoms.js — official Random Battle sets (pkmn randbats data)
   ===================================================================== */
(function (root) {
  'use strict';
  const cache = {};
  const URL = (g) => `https://pkmn.github.io/randbats/data/gen${g}randombattle.json`;

  async function load(genNum) {
    if (cache[genNum]) return cache[genNum];
    const res = await fetch(URL(genNum));
    if (!res.ok) throw new Error('randbats ' + res.status);
    const json = await res.json();
    cache[genNum] = json;
    return json;
  }

  function pick(arr) { return arr && arr.length ? arr[Math.floor(Math.random() * arr.length)] : undefined; }
  function sample(arr, n) {
    const a = (arr || []).slice();
    for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1));[a[i], a[j]] = [a[j], a[i]]; }
    return a.slice(0, n);
  }

  // Build an app-state set for a species from random-battle data (handles roles + flat shapes)
  function sampleSet(data, species) {
    const d = data[species];
    if (!d) return null;
    let abilities = d.abilities, items = d.items, moves = d.moves, tera = d.teraTypes, level = d.level;
    if (d.roles) {
      const roleNames = Object.keys(d.roles);
      const role = d.roles[pick(roleNames)];
      abilities = role.abilities || abilities;
      items = role.items || items;
      moves = role.moves || moves;
      tera = role.teraTypes || tera;
    }
    const mv = sample(moves, 4);
    while (mv.length < 4) mv.push('');
    const teraType = tera ? pick(tera) : '';
    return {
      species, level: level || 80, ability: pick(abilities) || '', item: pick(items) || '',
      nature: 'Hardy', teraType: teraType || '', teraActive: false, status: '', curHPpercent: 100,
      evs: { hp: 85, atk: 85, def: 85, spa: 85, spd: 85, spe: 85 }, ivs: {}, boosts: {},
      moves: mv, moveOpts: [{}, {}, {}, {}], setName: 'Random Battle'
    };
  }

  async function rollMatchup(genNum) {
    const data = await load(genNum);
    const keys = Object.keys(data);
    const a = sampleSet(data, pick(keys));
    let bKey = pick(keys); let guard = 0;
    while (bKey === a.species && guard++ < 5) bKey = pick(keys);
    const b = sampleSet(data, bKey);
    return { a, b };
  }

  async function rollOne(genNum) {
    const data = await load(genNum);
    return sampleSet(data, pick(Object.keys(data)));
  }

  root.RandomData = { load, sampleSet, rollMatchup, rollOne };
})(window);
