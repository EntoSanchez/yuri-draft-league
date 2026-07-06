/* =====================================================================
   data.js — static tables + helpers (no engine dependency)
   ===================================================================== */
(function (root) {
  'use strict';

  // Canonical Pokémon type colors (used for chips, move dots, bars)
  const TYPE_COLORS = {
    Normal: '#9099a1', Fire: '#ff7c43', Water: '#4d90d5', Electric: '#f3d23b',
    Grass: '#63bb5b', Ice: '#74cec0', Fighting: '#ce4069', Poison: '#ab6ac8',
    Ground: '#d97746', Flying: '#8fa8dd', Psychic: '#f97176', Bug: '#90c12c',
    Rock: '#c7b78b', Ghost: '#5269ac', Dragon: '#0a6dc4', Dark: '#5a5366',
    Steel: '#5a8ea1', Fairy: '#ec8fe6', Stellar: '#3de5ff', '???': '#68a090'
  };
  const TYPES = Object.keys(TYPE_COLORS).filter(t => t !== '???' && t !== 'Stellar');

  const STATS = [
    { key: 'hp',  label: 'HP'  },
    { key: 'atk', label: 'ATK' },
    { key: 'def', label: 'DEF' },
    { key: 'spa', label: 'SPA' },
    { key: 'spd', label: 'SPD' },
    { key: 'spe', label: 'SPE' }
  ];
  // engine stat ids
  const STAT_TO_ENGINE = { hp: 'hp', atk: 'atk', def: 'def', spa: 'spa', spd: 'spd', spe: 'spe' };

  // Nature → [plus stat, minus stat] (null = neutral)
  const NATURES = {
    Hardy: [null, null], Lonely: ['atk', 'def'], Brave: ['atk', 'spe'], Adamant: ['atk', 'spa'], Naughty: ['atk', 'spd'],
    Bold: ['def', 'atk'], Docile: [null, null], Relaxed: ['def', 'spe'], Impish: ['def', 'spa'], Lax: ['def', 'spd'],
    Timid: ['spe', 'atk'], Hasty: ['spe', 'def'], Serious: [null, null], Jolly: ['spe', 'spa'], Naive: ['spe', 'spd'],
    Modest: ['spa', 'atk'], Mild: ['spa', 'def'], Quiet: ['spa', 'spe'], Bashful: [null, null], Rash: ['spa', 'spd'],
    Calm: ['spd', 'atk'], Gentle: ['spd', 'def'], Sassy: ['spd', 'spe'], Careful: ['spd', 'spa'], Quirky: [null, null]
  };
  const NATURE_NAMES = Object.keys(NATURES);

  const STATUSES = [
    { v: '', label: 'Healthy' },
    { v: 'brn', label: 'Burned' },
    { v: 'psn', label: 'Poisoned' },
    { v: 'tox', label: 'Badly Poisoned' },
    { v: 'par', label: 'Paralyzed' },
    { v: 'slp', label: 'Asleep' },
    { v: 'frz', label: 'Frozen' }
  ];

  const WEATHERS = ['', 'Sun', 'Rain', 'Sand', 'Snow', 'Harsh Sunshine', 'Heavy Rain', 'Strong Winds'];
  const TERRAINS = ['', 'Electric', 'Grassy', 'Misty', 'Psychic'];

  const GENS = [
    { num: 9, label: 'Gen 9 · SV' },
    { num: 8, label: 'Gen 8 · SS' },
    { num: 7, label: 'Gen 7 · SM' },
    { num: 6, label: 'Gen 6 · XY' },
    { num: 5, label: 'Gen 5 · BW' },
    { num: 4, label: 'Gen 4 · DP' },
    { num: 3, label: 'Gen 3 · RS' },
    { num: 2, label: 'Gen 2 · GS' },
    { num: 1, label: 'Gen 1 · RB' }
  ];

  function natureFor(plus, minus) {
    for (const [name, [p, m]] of Object.entries(NATURES)) {
      if (p === plus && m === minus) return name;
      if (!plus && !minus && p === null && m === null) return 'Hardy';
    }
    return 'Hardy';
  }
  function natureMod(nature, stat) {
    const n = NATURES[nature];
    if (!n) return 1;
    if (n[0] === stat) return 1.1;
    if (n[1] === stat) return 0.9;
    return 1;
  }

  // Stat math (gen 3+ formula)
  function calcStat(stat, base, iv, ev, level, nature) {
    iv = iv == null ? 31 : iv; ev = ev == null ? 0 : ev;
    if (stat === 'hp') {
      if (base === 1) return 1; // shedinja
      return Math.floor(((2 * base + iv + Math.floor(ev / 4)) * level) / 100) + level + 10;
    }
    const val = Math.floor(((2 * base + iv + Math.floor(ev / 4)) * level) / 100) + 5;
    return Math.floor(val * natureMod(nature, stat));
  }

  // Showdown sprite id: lowercase, drop punctuation & spaces, KEEP forme hyphens.
  // Showdown hosts regional/alt formes hyphenated (e.g. zoroark-hisui.png,
  // landorus-therian.png); the collapsed form (zoroarkhisui) 404s.
  function spriteId(speciesName) {
    return (speciesName || '').toLowerCase()
      .replace(/[’'.]/g, '').replace(/é/g, 'e').replace(/♀/g, 'f').replace(/♂/g, 'm')
      .replace(/[:%]/g, '').replace(/\s+/g, '-')   // spaces → hyphen so "Zoroark Hisui" also works
      .replace(/-+/g, '-').replace(/^-|-$/g, '');
  }
  // Ordered list of candidate sprite URLs (animated first if requested), most-preferred
  // first. Tries the hyphenated id AND a fully-collapsed id (some base-forme sprites are
  // hosted without the hyphen), so hyphenated formes like Zoroark-Hisui resolve regardless
  // of how @smogon/calc happens to name them.
  function spriteChain(speciesName, animated) {
    const id = spriteId(speciesName);
    const flat = id.replace(/-/g, '');
    const ids = flat === id ? [id] : [id, flat];
    const gen5 = ids.map(x => `https://play.pokemonshowdown.com/sprites/gen5/${x}.png`);
    const ani = ids.map(x => `https://play.pokemonshowdown.com/sprites/ani/${x}.gif`);
    return animated ? ani.concat(gen5) : gen5.concat(ani);
  }
  function spriteUrl(speciesName) {
    if (!speciesName) return null;
    return `https://play.pokemonshowdown.com/sprites/gen5/${spriteId(speciesName)}.png`;
  }

  // ---- Showdown set import/export -------------------------------------
  function parseSet(text) {
    // Parse a single Showdown set block → plain object
    const lines = text.trim().split('\n').map(l => l.trim()).filter(Boolean);
    if (!lines.length) return null;
    const set = { moves: [], evs: {}, ivs: {}, level: 100, nature: 'Hardy' };
    // first line: "Nickname (Species) (M) @ Item"  OR  "Species @ Item"
    let first = lines.shift();
    let item = null;
    const atIdx = first.lastIndexOf('@');
    if (atIdx >= 0) { item = first.slice(atIdx + 1).trim(); first = first.slice(0, atIdx).trim(); }
    first = first.replace(/\((M|F)\)\s*$/i, '').trim();
    let species;
    const paren = first.match(/^(.*?)\s*\(([^)]+)\)\s*$/);
    if (paren) species = paren[2].trim(); else species = first.trim();
    set.species = species; set.item = item;
    for (const line of lines) {
      if (/^Ability:/i.test(line)) set.ability = line.split(':')[1].trim();
      else if (/^Level:/i.test(line)) set.level = parseInt(line.split(':')[1]) || 100;
      else if (/^Shiny:/i.test(line)) {}
      else if (/^Tera Type:/i.test(line)) set.teraType = line.split(':')[1].trim();
      else if (/Nature$/i.test(line)) set.nature = line.replace(/Nature/i, '').trim();
      else if (/^EVs:/i.test(line)) parseStatLine(line.split(':')[1], set.evs);
      else if (/^IVs:/i.test(line)) parseStatLine(line.split(':')[1], set.ivs);
      else if (/^-\s*/.test(line)) set.moves.push(line.replace(/^-\s*/, '').trim());
    }
    return set;
  }
  function parseStatLine(str, target) {
    const map = { HP: 'hp', Atk: 'atk', Def: 'def', SpA: 'spa', SpD: 'spd', Spe: 'spe' };
    str.split('/').forEach(part => {
      const m = part.trim().match(/(\d+)\s+(HP|Atk|Def|SpA|SpD|Spe)/i);
      if (m) { const k = Object.keys(map).find(x => x.toLowerCase() === m[2].toLowerCase()); if (k) target[map[k]] = parseInt(m[1]); }
    });
  }
  function exportSet(mon) {
    // mon: { species, item, ability, level, nature, evs, ivs, moves, teraType }
    const lines = [];
    let head = mon.species;
    if (mon.item) head += ' @ ' + mon.item;
    lines.push(head);
    if (mon.ability) lines.push('Ability: ' + mon.ability);
    if (mon.level && mon.level !== 100) lines.push('Level: ' + mon.level);
    if (mon.teraType) lines.push('Tera Type: ' + mon.teraType);
    const evStr = statStr(mon.evs, 0);
    if (evStr) lines.push('EVs: ' + evStr);
    if (mon.nature && mon.nature !== 'Hardy') lines.push(mon.nature + ' Nature');
    const ivStr = statStr(mon.ivs, 31);
    if (ivStr) lines.push('IVs: ' + ivStr);
    (mon.moves || []).filter(Boolean).forEach(m => lines.push('- ' + m));
    return lines.join('\n');
  }
  function statStr(obj, def) {
    const order = [['hp','HP'],['atk','Atk'],['def','Def'],['spa','SpA'],['spd','SpD'],['spe','Spe']];
    return order.filter(([k]) => obj && obj[k] != null && obj[k] !== def)
      .map(([k, lbl]) => obj[k] + ' ' + lbl).join(' / ');
  }

  root.CalcData = {
    TYPE_COLORS, TYPES, STATS, STAT_TO_ENGINE, NATURES, NATURE_NAMES, STATUSES,
    WEATHERS, TERRAINS, GENS, natureFor, natureMod, calcStat, spriteId, spriteChain, spriteUrl,
    parseSet, exportSet
  };
})(window);
