// Temponome Settings window: Lights, Colors, Sound, Timing.
const $ = id => document.getElementById(id);
let cfg = null, st = null, found = [];
const MODELS = ['l530', 'l535', 'l630', 'l900', 'l920', 'l930', 'govee'];
const MODEL_NAME = k => k === 'govee' ? 'Govee lamp' : 'Tapo ' + k.toUpperCase();
const blankDev = () => ({ ip: '', model: 'l530', color: 'blend', offset: 0, calib: null, name: '' });
const lights = () => cfg.devices.filter(d => d.ip);
const lname = d => d.name || d.ip;
const saveDevices = () => T.saveCfg({ devices: cfg.devices.length ? cfg.devices : [blankDev()] });

// ---------- tabs ----------
const TABS = ['lights', 'colors', 'sound', 'timing'];
function showTab(name) {
  if (!TABS.includes(name)) name = 'lights';
  for (const t of TABS) {
    $(t).hidden = t !== name;
    $('tab-' + t).setAttribute('aria-selected', t === name);
    $('tab-' + t).tabIndex = t === name ? 0 : -1;
  }
  // the #tab in the address also matches the section's id, which makes the page jump past
  // the section's first lines: always show a tab from its top
  requestAnimationFrame(() => window.scrollTo(0, 0));
}
TABS.forEach((t, i) => {
  $('tab-' + t).onclick = () => { history.replaceState(null, '', '#' + t); showTab(t); };
  $('tab-' + t).onkeydown = e => {
    const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
    if (d) { const n = TABS[(i + d + TABS.length) % TABS.length]; $('tab-' + n).click(); $('tab-' + n).focus(); }
  };
});
window.addEventListener('hashchange', () => showTab(location.hash.slice(1)));
window.showTab = showTab;   // the app shell calls this when Settings is opened on a given tab

// ---------- lights ----------
// what a light reacts to: buttons in groups instead of one long menu
const REACT = [
  { label: null, opts: [['beat', 'On the beat']] },
  { label: 'Drum', opts: [['kick', 'Kick'], ['snare', 'Snare'], ['hats', 'Hi-hats']] },
  { label: 'Bar', opts: [['low', 'Bass'], ['mid', 'Middle'], ['high', 'Treble']] },
  { label: null, opts: [['pitch', 'Pitch to color']] },
];
const REACT_FULL = { beat: 'on the beat', kick: 'the kick drum', snare: 'the snare', hats: 'the hi-hats',
  low: 'a bass bar', mid: 'a middle bar', high: 'a treble bar', pitch: 'pitch to color' };
function reactPicker(d, changed) {
  const box = document.createElement('div'); box.className = 'react';
  box.setAttribute('role', 'radiogroup'); box.setAttribute('aria-label', `What ${lname(d)} reacts to`);
  const buttons = [];
  const show = () => buttons.forEach(b => {
    const on = b.dataset.v === (d.sound || 'beat');
    b.setAttribute('aria-checked', on); b.tabIndex = on ? 0 : -1;
  });
  const pick = v => { d.sound = v; show(); changed(); saveDevices(); };
  for (const g of REACT) {
    const grp = document.createElement('div'); grp.className = g.label ? 'chips' : 'chips solo';
    if (g.label) { const l = document.createElement('span'); l.className = 'chiplbl'; l.textContent = g.label; l.setAttribute('aria-hidden', 'true'); grp.appendChild(l); }
    for (const [v, text] of g.opts) {
      const b = document.createElement('button'); b.textContent = text; b.dataset.v = v;
      b.setAttribute('role', 'radio'); b.setAttribute('aria-label', REACT_FULL[v]);
      b.onclick = () => pick(v);
      buttons.push(b); grp.appendChild(b);
    }
    box.appendChild(grp);
  }
  box.onkeydown = e => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (!step) return;
    e.preventDefault();
    const i = buttons.findIndex(b => b.dataset.v === (d.sound || 'beat'));
    const n = buttons[(i + step + buttons.length) % buttons.length];
    pick(n.dataset.v); n.focus();
  };
  show();
  return box;
}
function renderDevs() {
  const box = $('devList'); box.innerHTML = '';
  if (!lights().length) {
    box.innerHTML = '<div class="row"><span class="grow mut">No lights yet. Press Find my lights.</span></div>';
    return;
  }
  cfg.devices.forEach((d, i) => {
    if (!d.ip) return;
    const row = document.createElement('div'); row.className = 'row';
    const info = document.createElement('div'); info.className = 'grow';
    const title = document.createElement('div'); title.className = 'title'; title.textContent = lname(d);
    const sub = document.createElement('div'); sub.className = 'hint'; sub.style.margin = 0;
    sub.textContent = `${MODEL_NAME(d.model)} · ${d.ip}` + (d.calib == null ? ' · timing not measured' : ' · timing measured');
    info.append(title, sub);
    const color = document.createElement('select');
    color.setAttribute('aria-label', `Color for ${lname(d)}`);
    color.innerHTML = '<option value="blend">Tempo blend</option><option value="A">Always color A</option><option value="B">Always color B</option>';
    color.value = d.color; color.onchange = () => { d.color = color.value; saveDevices(); };
    // with a color pulse every light goes calm -> energetic; pitch to color picks its own color
    color.hidden = cfg.pulse === 'color' || d.sound === 'pitch';
    const react = reactPicker(d, () => { color.hidden = cfg.pulse === 'color' || d.sound === 'pitch'; });
    const shade = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    shade.setAttribute('viewBox', '0 0 46 46'); shade.setAttribute('aria-hidden', 'true'); shade.classList.add('shade');
    shade.innerHTML = '<polygon points="4,38 42,38 33,6 13,6"/><ellipse cx="23" cy="42" rx="18" ry="3"/>';
    const rm = document.createElement('button'); rm.textContent = 'Remove';
    rm.setAttribute('aria-label', `Remove ${lname(d)}`);
    rm.onclick = () => { cfg.devices.splice(i, 1); saveDevices(); renderDevs(); renderFinder(); calSummary(); };
    row.append(shade, info, color, rm, react);
    box.appendChild(row);
  });
  renderOffsets();
}

// per-light timing offsets live on the Timing tab
function renderOffsets() {
  const box = $('offList'); box.innerHTML = '';
  $('offBox').hidden = lights().length < 2;
  for (const d of lights()) {
    const row = document.createElement('div'); row.className = 'row';
    const name = document.createElement('span'); name.className = 'grow'; name.textContent = lname(d);
    const off = document.createElement('input'); off.type = 'number'; off.step = 10; off.min = -200; off.max = 300;
    off.value = d.offset || 0;
    off.setAttribute('aria-label', `${lname(d)}: milliseconds earlier`);
    off.oninput = () => { d.offset = +off.value || 0; saveDevices(); };
    const unit = document.createElement('span'); unit.className = 'marking'; unit.textContent = 'ms earlier';
    row.append(name, off, unit); box.appendChild(row);
  }
}

function addDevice(dev) {
  if (cfg.devices.some(d => d.ip === dev.ip)) return;
  const empty = cfg.devices.find(d => !d.ip);
  if (empty) Object.assign(empty, dev); else cfg.devices.push(dev);
}

function renderFinder() {
  const box = $('finder'); box.innerHTML = ''; box.hidden = !found.length;
  for (const l of found) {
    const row = document.createElement('label'); row.className = 'found';
    const cb = document.createElement('input'); cb.type = 'checkbox';
    cb.checked = cfg.devices.some(d => d.ip === l.ip);
    const txt = document.createElement('span'); txt.textContent = l.name || (l.brand + ' light');
    const sub = document.createElement('small');
    sub.textContent = ' ' + (l.model === 'govee' ? 'Govee' : `${l.brand} ${l.model.toUpperCase()}`) + ` · ${l.ip}`;
    txt.appendChild(sub);
    cb.onchange = () => {
      if (cb.checked) addDevice({ ...blankDev(), ip: l.ip, model: l.model, name: l.name });
      else cfg.devices = cfg.devices.filter(d => d.ip !== l.ip);
      saveDevices(); renderDevs(); calSummary();
    };
    row.append(cb, txt); box.appendChild(row);
  }
}

$('scan').onclick = async () => {
  const msg = $('scanMsg'); msg.className = 'msg'; msg.textContent = 'Searching your Wi-Fi for lights… (about 3 seconds)';
  $('scan').disabled = true;
  try {
    await T.api('/api/config', { email: $('email').value.trim(), password: $('password').value });
    const r = await T.api('/api/scan');
    found = r.lights;
    for (const l of found) { const d = cfg.devices.find(d => d.ip === l.ip); if (d) { if (!d.name) d.name = l.name; d.model = l.model; } }
    saveDevices(); renderDevs(); renderFinder();
    const notes = r.notes.join('\n');
    if (!found.length) {
      msg.className = 'msg err';
      msg.textContent = (notes ? notes + '\n' : '') + "No lights answered. Check they're switched on and on the same Wi-Fi as this Mac. For Govee, switch on LAN Control. If macOS asked, allow Temponome under System Settings > Privacy & Security > Local Network.";
      return;
    }
    msg.textContent = `Found ${found.length} light${found.length > 1 ? 's' : ''}. Tick the ones to use.` + (notes ? '\n' + notes : '');
  } catch (e) { msg.className = 'msg err'; msg.textContent = "The search didn't work. Try again in a moment."; }
  finally { $('scan').disabled = false; }
};

$('addModel').innerHTML = MODELS.map(k => `<option value="${k}">${MODEL_NAME(k)}</option>`).join('');
$('addToggle').onclick = () => { $('addForm').hidden = !$('addForm').hidden; if (!$('addForm').hidden) $('addIp').focus(); };
$('addBtn').onclick = () => {
  const ip = $('addIp').value.trim();
  if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(ip)) { $('scanMsg').className = 'msg err'; $('scanMsg').textContent = 'Enter an IP address like 192.168.1.50.'; return; }
  addDevice({ ...blankDev(), ip, model: $('addModel').value });
  saveDevices(); renderDevs(); renderFinder();
  $('addIp').value = ''; $('addForm').hidden = true; $('scanMsg').className = 'msg'; $('scanMsg').textContent = `Added ${ip}.`;
};
$('flash').onclick = async () => {
  const r = await T.api('/api/state');
  if (!r.running) { $('scanMsg').className = 'msg'; $('scanMsg').textContent = 'Press Play in the main window first, then flash the lights.'; return; }
  T.api('/api/flash', {});
};
$('email').oninput = () => T.saveCfg({ email: $('email').value.trim() });
$('password').oninput = () => { if ($('password').value) T.saveCfg({ password: $('password').value }); };

// ---------- colors ----------
function hsv2hex(h, s, v) {
  const f = n => { const k = (n + h / 60) % 6; return v - v * s * Math.max(0, Math.min(k, 4 - k, 1)); };
  return '#' + [f(5), f(3), f(1)].map(x => Math.round(x * 255).toString(16).padStart(2, '0')).join('');
}
function hex2hs(hex) {
  const r = parseInt(hex.slice(1, 3), 16) / 255, g = parseInt(hex.slice(3, 5), 16) / 255, b = parseInt(hex.slice(5, 7), 16) / 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn; let h = 0;
  if (d) { h = mx == r ? ((g - b) / d) % 6 : mx == g ? (b - r) / d + 2 : (r - g) / d + 4; h *= 60; if (h < 0) h += 360; }
  return [h, mx ? d / mx : 0];
}
// The wheel: 24 hues x 6 rings, vivid at the edge and softer toward the middle; the
// center is white. Every piece is a color both Tapo (hue + saturation) and Govee (RGB)
// lamps can show; brightness is set by the beat, not by the color.
const HUES = 24, RINGS = 6, R_OUT = 124, R_IN = 22, CX = 130, CY = 130;
function hsl2hex(h, s, l) {
  s /= 100; l /= 100;
  const k = n => (n + h / 30) % 12, a = s * Math.min(l, 1 - l);
  const f = n => l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1));
  return '#' + [f(0), f(8), f(4)].map(x => Math.round(x * 255).toString(16).padStart(2, '0')).join('');
}
const pieceHex = (i, r) => hsl2hex(i * 360 / HUES, 90 - r * 5, 50 + r * 36 / (RINGS - 1));
// where a saved color sits on the wheel: the nearest piece, or the white center
function locate(hex) {
  const [h, s] = hex2hs(hex);
  if (s < 0.1) return null;
  const sats = [...Array(RINGS)].map((_, r) => hex2hs(pieceHex(0, r))[1]);
  let ring = 0; sats.forEach((v, r) => { if (Math.abs(v - s) < Math.abs(sats[ring] - s)) ring = r; });
  return { i: Math.round(h / (360 / HUES)) % HUES, r: ring };
}
function sector(r0, r1, a0, a1) {
  const p = (r, a) => [CX + r * Math.sin(a), CY - r * Math.cos(a)].map(v => v.toFixed(2));
  const [x1, y1] = p(r1, a0), [x2, y2] = p(r1, a1), [x3, y3] = p(r0, a1), [x4, y4] = p(r0, a0);
  return `M${x1} ${y1}A${r1} ${r1} 0 0 1 ${x2} ${y2}L${x3} ${y3}A${r0} ${r0} 0 0 0 ${x4} ${y4}Z`;
}
const SVGNS = 'http://www.w3.org/2000/svg';
function svgEl(tag, attrs, parent) {
  const e = document.createElementNS(SVGNS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(e);
  return e;
}
let pickKey = 'colorA', liveBpm = 0;
// White can be warm or cool: the lights use their white LEDs at that color temperature
// (same numbers as temponome.kelvin_hex, so the screen matches the lamps on the stage)
const isWhiteHex = hex => hex2hs(hex)[1] < 0.005;
const kKey = key => 'kelvin' + key.slice(-1);
function kelvinHex(k) {
  const t = (Math.min(6500, Math.max(2500, k)) - 2500) / 4000, warm = [255, 180, 107], cool = [236, 241, 255];
  return '#' + warm.map((w, i) => Math.round(w + (cool[i] - w) * t).toString(16).padStart(2, '0')).join('');
}
const shown = key => isWhiteHex(cfg[key]) ? kelvinHex(cfg[kKey(key)] || 4000) : cfg[key];
function ctWord(k) { return (k <= 3300 ? 'Warm white' : k >= 5000 ? 'Cool white' : 'Neutral white') + ` · ${k} K`; }
function showCt() {
  const white = isWhiteHex(cfg[pickKey]), k = cfg[kKey(pickKey)] || 4000;
  $('ctBox').hidden = !white;
  if (!white) return;
  $('ct').value = k; $('ctV').textContent = ctWord(k); $('ct').setAttribute('aria-valuetext', ctWord(k));
}
$('ct').oninput = () => {
  const k = +$('ct').value; cfg[kKey(pickKey)] = k;
  T.saveCfg({ [kKey(pickKey)]: k }); showCt(); drawMarks(); drawStrip();
};

function buildWheel() {
  const w = $('wheel'), band = (R_OUT - R_IN) / RINGS;
  w.innerHTML = '';
  for (let i = 0; i < HUES; i++) for (let r = 0; r < RINGS; r++) {
    const hex = pieceHex(i, r), a0 = i * 2 * Math.PI / HUES - Math.PI / HUES, a1 = a0 + 2 * Math.PI / HUES;
    const piece = svgEl('path', { d: sector(R_OUT - (r + 1) * band, R_OUT - r * band, a0, a1), fill: hex, stroke: hex, 'stroke-width': .6 }, w);
    piece.onclick = () => setColor(hex);
  }
  svgEl('circle', { cx: CX, cy: CY, r: R_OUT, fill: 'none', stroke: 'var(--well)', 'stroke-width': 2 }, w);
  const white = svgEl('circle', { id: 'whiteDot', cx: CX, cy: CY, r: R_IN, fill: '#ffffff', stroke: 'var(--well)', 'stroke-width': 2 }, w);
  white.style.cursor = 'pointer';
  white.onclick = () => setColor('#ffffff');
  svgEl('g', { id: 'marks' }, w);
}
function markerAt(hex) {
  const at = locate(hex), band = (R_OUT - R_IN) / RINGS;
  if (!at) return [CX, CY];
  const a = at.i * 2 * Math.PI / HUES, rr = R_OUT - (at.r + .5) * band;
  return [CX + rr * Math.sin(a), CY - rr * Math.cos(a)];
}
function drawMarks() {
  const g = $('marks'); g.innerHTML = '';
  const keys = cfg.mode === 'fixed' ? ['colorA'] : (pickKey === 'colorA' ? ['colorB', 'colorA'] : ['colorA', 'colorB']);
  for (const k of keys) {             // the color being set is drawn last, on top, and larger
    const [x, y] = markerAt(cfg[k]), on = k === pickKey;
    svgEl('circle', { cx: x, cy: y, r: on ? 10 : 8, fill: shown(k), stroke: '#1d1d1f', 'stroke-width': on ? 5 : 4 }, g);
    svgEl('circle', { cx: x, cy: y, r: on ? 10 : 8, fill: 'none', stroke: '#ffffff', 'stroke-width': on ? 3 : 2 }, g);
  }
  $('swA').style.background = shown('colorA'); $('swB').style.background = shown('colorB');
  // the white center shows the warmth of the white being set
  $('whiteDot').setAttribute('fill', isWhiteHex(cfg[pickKey]) ? shown(pickKey) : '#ffffff');
  $('wheel').setAttribute('aria-label', `Color wheel, setting the ${pickKey === 'colorA' ? 'calm' : 'energetic'} color`);
}

// same blend as the lights (temponome.pick_color): around the wheel, the short way
function blendAt(bpm) {
  let [ha, sa] = hex2hs(cfg.colorA), [hb, sb] = hex2hs(cfg.colorB);
  if (cfg.mode === 'fixed') return shown('colorA');
  const t0 = Math.min(Math.max((bpm - 60) / 120, 0), 1);
  if (sa < 0.005 && sb < 0.005) return kelvinHex(Math.round(((cfg.kelvinA || 4000) + ((cfg.kelvinB || 4000) - (cfg.kelvinA || 4000)) * t0) / 100) * 100);
  if (sa < 0.005) ha = hb;
  if (sb < 0.005) hb = ha;
  const t = Math.min(Math.max((bpm - 60) / 120, 0), 1), d = ((hb - ha + 540) % 360) - 180;
  return hsv2hex(((ha + d * t) % 360 + 360) % 360, sa + (sb - sa) * t, 1);
}
function drawStrip() {
  const s = $('strip'); s.innerHTML = '';
  const steps = 12, x0 = 4, w = 552, cw = w / steps;
  for (let k = 0; k < steps; k++)
    svgEl('rect', { x: x0 + k * cw, y: 18, width: cw + .5, height: 30, fill: blendAt(60 + 120 * (k + .5) / steps) }, s);
  svgEl('rect', { x: x0, y: 18, width: w, height: 30, rx: 3, fill: 'none', stroke: 'var(--well)', 'stroke-width': 2 }, s);
  const lab = (x, anchor, text) => { const t = svgEl('text', { x, y: 66, 'text-anchor': anchor, 'font-size': 11, fill: 'var(--mut)' }, s); t.textContent = text; };
  if (cfg.mode === 'fixed') { lab(x0, 'start', 'every tempo'); return; }
  lab(x0, 'start', '60 bpm · calm'); lab(x0 + w, 'end', 'energetic · 180 bpm');
  if (liveBpm) {                    // where the music is now
    const x = x0 + w * Math.min(Math.max((liveBpm - 60) / 120, 0), 1);
    svgEl('line', { x1: x, y1: 14, x2: x, y2: 52, stroke: 'var(--ink)', 'stroke-width': 2 }, s);
    const right = x > x0 + w - 70;
    const t = svgEl('text', { x: right ? x - 6 : x + 6, y: 11, 'text-anchor': right ? 'end' : 'start', 'font-size': 11, fill: 'var(--ink)' }, s);
    t.textContent = 'now ' + Math.round(liveBpm);
  }
}
function setColor(hex) {
  cfg[pickKey] = hex; T.saveCfg({ [pickKey]: hex });
  drawMarks(); drawStrip(); showCt();
}
function setPick(key) {
  pickKey = cfg.mode === 'fixed' ? 'colorA' : key;
  $('pickA').setAttribute('aria-checked', pickKey === 'colorA');
  $('pickB').setAttribute('aria-checked', pickKey === 'colorB');
  drawMarks(); showCt();
}
function showMode() {
  const pulse = cfg.pulse === 'color';
  $('tempoColors').hidden = pulse;           // the tempo blend doesn't apply to a color pulse
  $('pickB').hidden = cfg.mode === 'fixed' && !pulse;
  setPick(pickKey); drawStrip();
}
$('pickA').onclick = () => setPick('colorA');
$('pickB').onclick = () => setPick('colorB');
$('wheel').onkeydown = e => {          // arrow keys walk the wheel: left/right = hue, up/down = more vivid / softer
  const at = locate(cfg[pickKey]) || { i: 0, r: RINGS };
  let { i, r } = at;
  if (e.key === 'ArrowLeft') i = (i + HUES - 1) % HUES;
  else if (e.key === 'ArrowRight') i = (i + 1) % HUES;
  else if (e.key === 'ArrowUp') r = Math.max(0, r - 1);
  else if (e.key === 'ArrowDown') r = r + 1;
  else return;
  e.preventDefault();
  setColor(r >= RINGS ? '#ffffff' : pieceHex(i, r));
};
$('preview').onclick = async () => {
  const r = await T.api('/api/preview', { color: cfg[pickKey], kelvin: cfg[kKey(pickKey)] });
  $('pvMsg').className = r.ok ? 'msg' : 'msg err';
  $('pvMsg').textContent = r.ok ? 'Showing it on your lights for a moment.' : r.error;
  clearTimeout($('pvMsg').t); $('pvMsg').t = setTimeout(() => { $('pvMsg').textContent = ''; }, 4000);
};
for (const id of ['accent', 'drops']) {
  $(id).onclick = () => { const on = $(id).getAttribute('aria-checked') !== 'true'; $(id).setAttribute('aria-checked', on); cfg[id] = on; T.saveCfg({ [id]: on }); };
}
$('barShift').onchange = () => { cfg.bar_shift = +$('barShift').value; T.saveCfg({ bar_shift: cfg.bar_shift }); };
function showPulse() {
  for (const id of ['pulseB', 'pulseC']) {
    const on = $(id).dataset.v === (cfg.pulse || 'brightness');
    $(id).setAttribute('aria-checked', on); $(id).tabIndex = on ? 0 : -1;
  }
}
for (const id of ['pulseB', 'pulseC']) {
  $(id).onclick = () => { cfg.pulse = $(id).dataset.v; T.saveCfg({ pulse: cfg.pulse }); showPulse(); showMode(); renderDevs(); };
  $(id).onkeydown = e => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
    e.preventDefault(); const other = id === 'pulseB' ? 'pulseC' : 'pulseB'; $(other).click(); $(other).focus();
  };
}
document.querySelectorAll('input[name=mode]').forEach(r => r.onchange = () => {
  cfg.mode = r.value; T.saveCfg({ mode: r.value }); showMode();
});

// ---------- sound ----------
$('device').onchange = () => { cfg.device = $('device').value; T.saveCfg({ device: cfg.device }); showPass(); };
$('lock').onclick = () => { const on = $('lock').getAttribute('aria-checked') !== 'true'; $('lock').setAttribute('aria-checked', on); T.saveCfg({ lock: on }); };
// ---------- play through Temponome ----------
let outs = { outputs: [], blackhole: false, current: '' }, inputs = [];
const spkUid = () => $('outDev').value || outs.current;
function micChosen() {
  const d = inputs.find(x => x.id === String(cfg.device));
  return !!(cfg.device !== '' && d && !/blackhole/i.test(d.name));
}
// the diagram shows the real delay while music is playing through Temponome (kept fresh by the poll)
function flowDelay(s) {
  $('flowMid').textContent = s && s.running && s.pass_delay ? `hears it ${s.pass_delay.toFixed(1)} s early` : 'hears it early';
}
function showPass() {
  const why = !outs.blackhole ? 'Install BlackHole 2ch to use this.'
    : micChosen() ? 'Choose BlackHole 2ch above to use this.' : '';
  const on = !!cfg.passthru && !why;
  $('passthru').disabled = !!why;
  $('passthru').setAttribute('aria-checked', on);
  $('flow').classList.toggle('on', on);
  flowDelay(st);
  $('ptWhy').hidden = !why; $('ptWhy').textContent = why;
  $('outDev').disabled = $('spk').disabled = !on;
  $('device').disabled = on;
  const o = outs.outputs.find(x => x.uid === spkUid());
  const ms = (cfg.spk_delay || {})[spkUid()] ?? Math.round(o ? o.latency_ms : 0);
  $('spk').value = ms; $('spkV').textContent = ms + ' ms';
}
$('passthru').onclick = () => {
  if ($('passthru').disabled) return;
  cfg.passthru = $('passthru').getAttribute('aria-checked') !== 'true';
  T.saveCfg({ passthru: cfg.passthru }); showPass();
};
$('outDev').onchange = () => { cfg.out_device = $('outDev').value; T.saveCfg({ out_device: cfg.out_device }); showPass(); };
$('spk').oninput = () => {
  cfg.spk_delay = Object.assign({}, cfg.spk_delay, { [spkUid()]: +$('spk').value });
  $('spkV').textContent = $('spk').value + ' ms'; T.saveCfg({ spk_delay: cfg.spk_delay });
};
$('steady').onclick = () => { const on = $('steady').getAttribute('aria-checked') !== 'true'; $('steady').setAttribute('aria-checked', on); T.saveCfg({ steady: on }); };
$('sens').oninput = () => T.saveCfg({ sensitivity: +$('sens').value });
$('minB').oninput = () => { $('minBv').textContent = $('minB').value + '%'; T.saveCfg({ minB: +$('minB').value }); };

// ---------- timing: fine-tune ----------
// the slider runs Earlier (left) to Later (right); the saved "lead" is how much earlier
const leadVal = () => -$('lead').value;
const setLead = v => { $('lead').value = -v; leadLabel(); };
function leadLabel() {
  const v = leadVal(), t = v > 0 ? v + ' ms earlier' : v < 0 ? (-v) + ' ms later' : 'no change';
  $('leadV').textContent = t; $('lead').setAttribute('aria-valuetext', t);
}
$('lead').oninput = () => { leadLabel(); T.saveCfg({ lead: leadVal() }); };

// ---------- timing: webcam calibration ----------
// The camera can't hear the beat, so it only measures each light's real delay:
// command sent -> bulb visibly brighter. The camera's own delay is measured first by
// flashing the screen (which lights up what the camera sees) and subtracted.
const CAL = { stream: null, frames: [], rec: false, cancel: false, off: 0, tsMode: null };
const calCv = document.createElement('canvas'); calCv.width = 64; calCv.height = 48;
const calCtx = calCv.getContext('2d', { willReadFrequently: true });
const sleep = ms => new Promise(r => setTimeout(r, ms));
const median = a => { const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
const calSay = (t, err) => { $('calMsg').textContent = t; $('calMsg').className = err ? 'msg err' : 'msg'; };
const nextFrame = () => new Promise(r => requestAnimationFrame(r));
const calApi = body => T.api('/api/calib', body);

function calSummary() {
  const parts = lights().filter(d => d.calib != null).map(d => `${lname(d)}: measured (${d.calib >= 0 ? '+' : ''}${d.calib} ms)`);
  $('calSum').textContent = parts.length ? parts.join(' · ') : 'Not measured yet.';
  $('calClear').hidden = !parts.length;
}

function calGrab(t) {
  calCtx.drawImage($('calVid'), 0, 0, 64, 48);
  const d = calCtx.getImageData(0, 0, 64, 48).data, y = new Uint8Array(64 * 48);
  for (let i = 0, j = 0; j < y.length; i += 4, j++) y[j] = (d[i] * 77 + d[i + 1] * 150 + d[i + 2] * 29) >> 8;
  CAL.frames.push({ t: t + CAL.off, y });
}
function calLoop() {
  const v = $('calVid');
  if (v.requestVideoFrameCallback) {
    const cb = (now, m) => {
      if (!CAL.stream) return;
      if (CAL.rec) { if (CAL.tsMode === null) CAL.tsMode = (m && m.captureTime) ? 'capture' : 'cb'; calGrab(CAL.tsMode === 'capture' ? m.captureTime : now); }
      v.requestVideoFrameCallback(cb);
    };
    v.requestVideoFrameCallback(cb);
  } else {
    let last = -1;
    const cb = now => { if (!CAL.stream) return; if (CAL.rec && v.currentTime !== last) { last = v.currentTime; calGrab(now); } requestAnimationFrame(cb); };
    requestAnimationFrame(cb);
  }
}

// frames: [{t (epoch ms), y: Uint8Array luma}], events: [epoch ms when the change was commanded/shown]
// returns, per event, ms until the watched area got halfway brighter (null = change not seen)
function calAnalyze(frames, events, pre = 300, post = 1100) {
  if (!frames.length) return events.map(() => null);
  const N = frames[0].y.length, diff = new Float32Array(N);
  const win = (a, b) => frames.filter(f => f.t >= a && f.t < b);
  for (const e of events) {
    const B = win(e - pre, e), A = win(e + 450, e + post); if (!B.length || !A.length) continue;
    for (let p = 0; p < N; p++) { let sb = 0, sa = 0; for (const f of B) sb += f.y[p]; for (const f of A) sa += f.y[p]; diff[p] += sa / A.length - sb / B.length; }
  }
  const idx = [...diff.keys()].sort((a, b) => diff[b] - diff[a]).slice(0, Math.max(24, Math.round(N * 0.03)));
  const sig = frames.map(f => { let s = 0; for (const p of idx) s += f.y[p]; return { t: f.t, v: s / idx.length }; });
  return events.map(e => {
    const B = sig.filter(s => s.t >= e - pre && s.t < e), A = sig.filter(s => s.t >= e && s.t < e + post);
    if (B.length < 3 || A.length < 5) return null;
    const bv = B.map(s => s.v), base = median(bv), noise = median(bv.map(v => Math.abs(v - base))) + 0.5;
    const top = Math.max(...A.map(s => s.v));
    if (top - base < Math.max(5, 8 * noise)) return null;
    const thr = (base + top) / 2; let prev = B[B.length - 1];
    for (const s of A) { if (s.v >= thr) return prev.t + (thr - prev.v) / (s.v - prev.v || 1) * (s.t - prev.t) - e; prev = s; }
    return null;
  });
}

function calStopCam() {
  if (CAL.stream) CAL.stream.getTracks().forEach(t => t.stop());
  CAL.stream = null; CAL.rec = false; $('calBox').hidden = true; $('calFlash').style.display = 'none';
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
}

async function ensurePlaying() {   // calibration needs the app connected to the lights
  let s = await T.api('/api/state');
  if (s.running && s.lights) return true;
  calSay('Connecting to your lights…');
  await T.api('/api/start', {});
  for (let i = 0; i < 40; i++) { await sleep(200); s = await T.api('/api/state'); if (s.running && s.lights) return true; if (!s.running && s.error) break; }
  calSay(s.status || "Couldn't connect to your lights.", true);
  return false;
}

$('calOpen').onclick = async () => {
  if (!lights().length) { calSay('Add your lights first (Lights tab).', true); return; }
  try { CAL.stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, frameRate: { ideal: 60 } }, audio: false }); }
  catch (e) {
    calSay(`Couldn't open the camera (${e.name}). Allow camera access for Temponome in System Settings > Privacy & Security > Camera, then try again.`, true);
    CAL.stream = null;
    if (window.pywebview && window.pywebview.api && window.pywebview.api.open_in_browser) {
      calSay('The camera isn’t available inside the app window, so calibration is opening in your web browser.');
      window.pywebview.api.open_in_browser('/settings#timing');
    }
    return;
  }
  $('calVid').srcObject = CAL.stream; $('calBox').hidden = false; calSay(''); calLoop();
};
$('calCancel').onclick = async () => { CAL.cancel = true; calStopCam(); await calApi({ action: 'end' }); calSay('Calibration cancelled.'); };
$('calClear').onclick = async () => {
  const s = await calApi({ action: 'save', results: cfg.devices.map((d, i) => ({ idx: i, calib: null })) });
  cfg.devices = s.cfg.devices; calSummary(); renderDevs(); calSay('Measurements cleared. The lights use the fine-tune setting only.');
};

$('calRun').onclick = async () => {
  CAL.cancel = false; CAL.frames = []; CAL.tsMode = null; $('calRun').disabled = true;
  try {
    if (!await ensurePlaying()) return;
    const b = await calApi({ action: 'begin' });
    if (!b.ok) { calSay(b.error, true); return; }
    CAL.off = Date.now() - performance.now(); CAL.rec = true;
    for (const L of b.lights) await calApi({ action: 'flash', pos: L.pos, b: 1 });   // all lights dim
    // 1) camera delay: flash the screen black -> white (full screen if allowed, so it lights the room)
    const fl = $('calFlash'); fl.style.display = 'block'; fl.style.background = '#000';
    try { await fl.requestFullscreen(); } catch (e) { /* the window flash still works, a bit dimmer */ }
    const scr = []; await sleep(800);
    for (let i = 0; i < 6 && !CAL.cancel; i++) {
      fl.style.background = '#000'; fl.style.color = '#777'; await sleep(800);
      fl.style.background = '#fff'; fl.style.color = '#bbb'; await nextFrame();
      scr.push(performance.now() + CAL.off); await sleep(900);
    }
    fl.style.display = 'none';
    if (document.fullscreenElement) await document.exitFullscreen().catch(() => {});
    const fps = CAL.frames.length / Math.max(1, (CAL.frames.length > 1 ? CAL.frames[CAL.frames.length - 1].t - CAL.frames[0].t : 1) / 1000);
    if (CAL.frames.length < 20 || fps < 12) { calSay(`The camera only delivered ${Math.round(fps)} pictures per second (needs at least 12). Keep this window in front during calibration, close other apps using the camera, and try again.`, true); return; }
    const sd = calAnalyze(CAL.frames, scr, 300, 850).filter(v => v != null);
    let camDelay = 80, camOk = false;
    if (sd.length >= 3) { camDelay = median(sd); camOk = true; }
    // 2) each light: dim -> bright, 8 times
    const results = [], lines = [`Camera delay: ${Math.round(camDelay)} ms${camOk ? '' : ' (estimated: the screen flash wasn’t visible to the camera)'}`];
    for (const L of b.lights) {
      if (CAL.cancel) break;
      const d = cfg.devices[L.idx] || { ip: L.ip };
      calSay(lines.join('\n') + `\nMeasuring ${lname(d)}…`);
      const t0 = performance.now() + CAL.off, ev = [];
      for (let i = 0; i < 8 && !CAL.cancel; i++) {
        await calApi({ action: 'flash', pos: L.pos, b: 1 }); await sleep(1000);
        const r = await calApi({ action: 'flash', pos: L.pos, b: 100 });
        if (r.ok) ev.push(r); await sleep(1200);
      }
      await calApi({ action: 'flash', pos: L.pos, b: 1 });
      const seen = calAnalyze(CAL.frames.filter(f => f.t >= t0), ev.map(r => r.t));
      const vals = ev.map((r, i) => seen[i] == null ? null : seen[i] - camDelay - r.lat).filter(v => v != null);
      if (vals.length < 4) { lines.push(`${lname(d)}: couldn't see it light up clearly (${vals.length}/8). Aim the camera at it, dim the room and try again.`); continue; }
      const s = [...vals].sort((x, y) => x - y), spread = s[Math.floor(s.length * 0.75)] - s[Math.floor(s.length * 0.25)];
      const calib = Math.round(median(vals)), total = Math.round(median(ev.map(r => r.lat)) + calib);
      results.push({ idx: L.idx, calib });
      lines.push(`${lname(d)}: lights up about ${total} ms after a beat is sent (${vals.length}/8 readings, spread ±${Math.round(spread / 2)} ms)${spread > 120 ? ' · readings were uneven, consider running it again' : ''}`);
    }
    CAL.rec = false;
    if (CAL.cancel) return;
    if (results.length) {
      const s2 = await calApi({ action: 'save', results, reset_nudge: true });
      cfg.devices = s2.cfg.devices; cfg.lead = s2.cfg.lead; setLead(s2.cfg.lead); calSummary(); renderDevs();
      lines.push('Saved. Each light now fires early by its own measured delay. Fine-tune was reset to no change.');
    }
    calSay(lines.join('\n'));
  } catch (e) { calSay("Calibration stopped because something went wrong. Try again.", true); }
  finally { $('calRun').disabled = false; await calApi({ action: 'end' }); calStopCam(); }
};

// a failed save is shown at the top of the window for a few seconds
window.addEventListener('temponome-save-failed', () => {
  let b = $('saveFail');
  if (!b) {
    b = document.createElement('div'); b.id = 'saveFail'; b.setAttribute('role', 'alert');
    b.style.cssText = 'position:sticky;top:0;padding:8px 24px;background:var(--warn);color:#fff;font-weight:500';
    document.body.prepend(b);
  }
  b.textContent = "Couldn't save your last change. Try again.";
  b.hidden = false; clearTimeout(b._t); b._t = setTimeout(() => { b.hidden = true; }, 4000);
});

// ---------- presets (Colors) ----------
let curPreset = '';
function presetMsg(text, err) {
  $('presetMsg').className = err ? 'msg err' : 'msg'; $('presetMsg').textContent = text;
  clearTimeout($('presetMsg').t); $('presetMsg').t = setTimeout(() => { $('presetMsg').textContent = ''; }, 4000);
}
async function presetDo(body) {
  const r = await T.api('/api/preset', body);
  if (!r.ok) { presetMsg(r.error, true); return false; }
  st = r.state; curPreset = st.preset; cfg.presets = st.cfg.presets;
  return true;
}
function renderPresets() {
  const box = $('presetList'); box.innerHTML = '';
  const list = cfg.presets || [];
  if (!list.length) { box.innerHTML = '<div class="row"><span class="hint" style="margin:0">No presets yet. Save the look you have now below.</span></div>'; return; }
  for (const p of list) {
    const row = document.createElement('div'); row.className = 'row';
    const name = document.createElement('span'); name.className = 'pname'; name.textContent = p.name;
    if (p.name === curPreset) { const t = document.createElement('span'); t.className = 'inuse'; t.textContent = 'In use'; name.appendChild(t); }
    const btn = (text, fn) => { const b = document.createElement('button'); b.textContent = text; b.onclick = fn; b.setAttribute('aria-label', `${text} ${p.name}`); return b; };
    const apply = btn('Use', async () => { if (await presetDo({ action: 'apply', name: p.name })) location.reload(); });
    const ren = btn('Rename', () => {
      const inp = document.createElement('input'); inp.type = 'text'; inp.value = p.name; inp.maxLength = 40; inp.setAttribute('aria-label', 'New name');
      const ok = btn('OK', async () => { if (await presetDo({ action: 'rename', name: p.name, new: inp.value })) renderPresets(); });
      const cancel = btn('Cancel', renderPresets);
      inp.onkeydown = e => { if (e.key === 'Enter') ok.click(); if (e.key === 'Escape') cancel.click(); };
      row.replaceChildren(inp, ok, cancel); inp.focus(); inp.select();
    });
    const del = btn('Delete', async () => { if (await presetDo({ action: 'delete', name: p.name })) { renderPresets(); presetMsg(`Deleted ${p.name}.`); } });
    row.append(name, apply, ren, del);
    box.appendChild(row);
  }
}
$('presetSave').onclick = async () => {
  const name = $('presetName').value.trim();
  if (!name) { presetMsg('Give the preset a name first.', true); $('presetName').focus(); return; }
  // wait for any change still being saved, so the preset holds exactly what you see
  await T.saveCfg({});
  const had = (cfg.presets || []).some(p => p.name.toLowerCase() === name.toLowerCase());
  if (await presetDo({ action: 'save', name })) {
    $('presetName').value = ''; renderPresets();
    presetMsg(had ? `Updated ${name}.` : `Saved ${name}.`);
  }
};
$('presetName').onkeydown = e => { if (e.key === 'Enter') $('presetSave').click(); };

// ---------- start by itself (Sound) ----------
function renderApps() {
  $('autostart').setAttribute('aria-checked', !!cfg.autostart);
  const box = $('appList'); box.innerHTML = '';
  for (const a of cfg.music_apps || []) {
    const row = document.createElement('div'); row.className = 'row';
    const n = document.createElement('span'); n.className = 'grow'; n.textContent = a.name;
    const b = document.createElement('button'); b.textContent = 'Remove'; b.setAttribute('aria-label', `Remove ${a.name}`);
    b.onclick = () => { cfg.music_apps = cfg.music_apps.filter(x => x.id !== a.id); T.saveCfg({ music_apps: cfg.music_apps }); renderApps(); };
    row.append(n, b); box.appendChild(row);
  }
  if (!(cfg.music_apps || []).length) box.innerHTML = '<div class="row"><span class="hint" style="margin:0">No music apps yet. Add one below.</span></div>';
}
$('autostart').onclick = () => { cfg.autostart = !cfg.autostart; T.saveCfg({ autostart: cfg.autostart }); renderApps(); };
$('appAdd').onclick = async () => {
  const box = $('appFound'); $('appMsg').textContent = '';
  const known = new Set((cfg.music_apps || []).map(a => a.id));
  const now = (await T.api('/api/playing')).filter(a => !known.has(a.id));
  box.innerHTML = '';
  if (!now.length) {
    box.hidden = true;
    $('appMsg').textContent = 'No other app is playing sound right now. Start a song in the app you want to add, then try again.';
    return;
  }
  for (const a of now) {
    const row = document.createElement('div'); row.className = 'row';
    const n = document.createElement('span'); n.className = 'grow'; n.textContent = a.name;
    const b = document.createElement('button'); b.textContent = 'Add'; b.setAttribute('aria-label', `Add ${a.name}`);
    b.onclick = () => { cfg.music_apps = [...(cfg.music_apps || []), a]; T.saveCfg({ music_apps: cfg.music_apps }); renderApps(); row.remove(); if (!box.children.length) box.hidden = true; };
    row.append(n, b); box.appendChild(row);
  }
  box.hidden = false;
};

// ---------- menu bar lamp (Lights → App) ----------
$('menubar').onclick = () => {
  cfg.menubar = $('menubar').getAttribute('aria-checked') !== 'true';
  $('menubar').setAttribute('aria-checked', cfg.menubar); T.saveCfg({ menubar: cfg.menubar });
};

// ---------- welcome guide (Lights) ----------
$('guideAgain').onclick = () => {
  if (window.pywebview && window.pywebview.api && window.pywebview.api.show_guide) window.pywebview.api.show_guide();
  else window.open('/#guide', 'temponome-main');
};

// ---------- start ----------
async function init() {
  const devs = await T.api('/api/devices');
  inputs = devs;
  $('device').innerHTML = '<option value="">Mac default input</option>' + devs.map(d => {
    const o = document.createElement('option'); o.value = d.id;
    o.textContent = /blackhole/i.test(d.name) ? d.name + ' (recommended)' : d.name; return o.outerHTML;
  }).join('');
  st = await T.api('/api/state'); cfg = st.cfg;
  $('email').value = cfg.email || ''; if (cfg.has_password) $('password').placeholder = 'Saved';
  $('device').value = cfg.device;
  document.querySelector(`input[name=mode][value=${cfg.mode}]`).checked = true;
  showPulse();
  $('accent').setAttribute('aria-checked', !!cfg.accent); $('drops').setAttribute('aria-checked', !!cfg.drops);
  $('barShift').value = String(cfg.bar_shift || 0);
  $('lock').setAttribute('aria-checked', !!cfg.lock);
  $('steady').setAttribute('aria-checked', cfg.steady !== false);
  outs = await T.api('/api/outputs');
  const same = outs.outputs.find(o => o.uid === outs.current);
  $('outDev').innerHTML = '<option value="">Same as before' + (same ? ' (' + same.name + ')' : '') + '</option>'
    + outs.outputs.map(o => { const e = document.createElement('option'); e.value = o.uid; e.textContent = o.name; return e.outerHTML; }).join('');
  $('outDev').value = outs.outputs.some(o => o.uid === cfg.out_device) ? cfg.out_device : '';
  showPass();
  $('sens').value = cfg.sensitivity; $('minB').value = cfg.minB; $('minBv').textContent = cfg.minB + '%';
  setLead(cfg.lead);
  buildWheel(); showMode();
  renderDevs(); calSummary();
  curPreset = st.preset; renderPresets(); renderApps();
  $('menubar').setAttribute('aria-checked', cfg.menubar !== false);
  showTab(location.hash.slice(1));
  let rev = st.cfg_rev;
  setInterval(async () => {
    // a preset was put on from the main window or the menu bar: show (and keep) its values
    const s0 = await T.api('/api/state');
    if (s0.cfg_rev !== rev) { location.reload(); return; }
    if (s0.preset !== curPreset && !$('colors').hidden) { curPreset = s0.preset; renderPresets(); }
    if (!$('colors').hidden) {         // keep the strip's "now" marker on the current tempo
      const s = s0, b = s.running ? s.bpm : 0;
      if (Math.round(b) !== Math.round(liveBpm)) { liveBpm = b; drawStrip(); }
      return;
    }
    if ($('sound').hidden) return;
    const s = s0;
    $('meter').style.width = s.running ? Math.max(0, Math.min(100, (s.db + 70) / 60 * 100)) + '%' : '0';
    flowDelay(s);
  }, 150);
}
init();
