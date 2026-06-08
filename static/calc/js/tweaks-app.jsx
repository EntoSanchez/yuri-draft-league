/* =====================================================================
   tweaks-app.jsx — React island that drives design-direction tweaks.
   Only mutates <html> attributes + CSS vars; the vanilla calc reacts via CSS.
   ===================================================================== */
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accent": "Duo",
  "typeColor": "Vivid",
  "density": "Comfortable",
  "ambience": true,
  "glow": true
}/*EDITMODE-END*/;

const ACCENTS = {
  magenta: { c: '#ff3d97', dim: 'rgba(255,61,151,.55)', soft: 'rgba(255,61,151,.14)' },
  cyan:    { c: '#3de5ff', dim: 'rgba(61,229,255,.55)', soft: 'rgba(61,229,255,.12)' }
};
function setSide(root, side, a) {
  root.style.setProperty('--' + side, a.c);
  root.style.setProperty('--' + side + '-dim', a.dim);
  root.style.setProperty('--' + side + '-soft', a.soft);
}

function TweaksApp() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const root = document.documentElement;

  React.useEffect(() => {
    if (t.accent === 'Magenta') { setSide(root, 'atk', ACCENTS.magenta); setSide(root, 'def', ACCENTS.magenta); }
    else if (t.accent === 'Cyan') { setSide(root, 'atk', ACCENTS.cyan); setSide(root, 'def', ACCENTS.cyan); }
    else { setSide(root, 'atk', ACCENTS.magenta); setSide(root, 'def', ACCENTS.cyan); }
  }, [t.accent]);

  React.useEffect(() => {
    root.setAttribute('data-typecolor', t.typeColor.toLowerCase());
  }, [t.typeColor]);

  React.useEffect(() => {
    root.setAttribute('data-density', t.density.toLowerCase());
  }, [t.density]);

  React.useEffect(() => { root.setAttribute('data-ambience', t.ambience ? 'on' : 'off'); }, [t.ambience]);
  React.useEffect(() => { root.setAttribute('data-glow', t.glow ? 'on' : 'off'); }, [t.glow]);

  return (
    <TweaksPanel title="Tweaks">
      <TweakSection label="Accent direction" />
      <TweakRadio label="Side colors" value={t.accent}
        options={['Duo', 'Magenta', 'Cyan']}
        onChange={(v) => setTweak('accent', v)} />
      <TweakSection label="Type colors" />
      <TweakRadio label="Intensity" value={t.typeColor}
        options={['Vivid', 'Subtle', 'Mono']}
        onChange={(v) => setTweak('typeColor', v)} />
      <TweakSection label="Layout & finish" />
      <TweakRadio label="Density" value={t.density}
        options={['Comfortable', 'Compact']}
        onChange={(v) => setTweak('density', v)} />
      <TweakToggle label="Scanline ambience" value={t.ambience}
        onChange={(v) => setTweak('ambience', v)} />
      <TweakToggle label="Neon glow" value={t.glow}
        onChange={(v) => setTweak('glow', v)} />
    </TweaksPanel>
  );
}

(function mount() {
  const el = document.getElementById('tweaks-root');
  if (el && window.ReactDOM) ReactDOM.createRoot(el).render(<TweaksApp />);
})();
