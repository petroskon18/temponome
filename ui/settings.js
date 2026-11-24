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
    const rm = document.createElement('button'); rm.textContent = 'Remove';
    rm.setAttribute('aria-label', `Remove ${lname(d)}`);
    rm.onclick = () => { cfg.devices.splice(i, 1); saveDevices(); renderDevs(); renderFinder(); calSummary(); };
    row.append(info, color, rm);
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
function makeWheel(cid, swid, key) {
  const c = $(cid), ctx = c.getContext('2d'), R = c.width / 2;
  const img = ctx.createImageData(c.width, c.height);
  for (let y = 0; y < c.height; y++) for (let x = 0; x < c.width; x++) {
    const dx = x - R, dy = y - R, r = Math.hypot(dx, dy), i = (y * c.width + x) * 4;
    if (r <= R) {
      let h = Math.atan2(dy, dx) * 180 / Math.PI; if (h < 0) h += 360;
      const hex = hsv2hex(h, r / R, 1);
      img.data[i] = parseInt(hex.slice(1, 3), 16); img.data[i + 1] = parseInt(hex.slice(3, 5), 16); img.data[i + 2] = parseInt(hex.slice(5, 7), 16); img.data[i + 3] = 255;
    }
  }
  function draw() {
    ctx.putImageData(img, 0, 0);
    const [h, s] = hex2hs(cfg[key]), a = h * Math.PI / 180, px = R + Math.cos(a) * s * R, py = R + Math.sin(a) * s * R;
    ctx.beginPath(); ctx.arc(px, py, 8, 0, 7); ctx.lineWidth = 3; ctx.strokeStyle = '#fff'; ctx.stroke();
    ctx.beginPath(); ctx.arc(px, py, 9.5, 0, 7); ctx.lineWidth = 1; ctx.strokeStyle = '#000'; ctx.stroke();
    $(swid).style.background = cfg[key];
  }
  function pick(e) {
    const rc = c.getBoundingClientRect();
    const x = (e.clientX - rc.left) * c.width / rc.width - R, y = (e.clientY - rc.top) * c.height / rc.height - R;
    let h = Math.atan2(y, x) * 180 / Math.PI; if (h < 0) h += 360;
    cfg[key] = hsv2hex(h, Math.min(1, Math.hypot(x, y) / R), 1); draw(); T.saveCfg({ [key]: cfg[key] });
  }
  let down = false;
  c.addEventListener('pointerdown', e => { down = true; c.setPointerCapture(e.pointerId); pick(e); });
  c.addEventListener('pointermove', e => { if (down) pick(e); });
  c.addEventListener('pointerup', () => down = false);
  draw();
}
document.querySelectorAll('input[name=mode]').forEach(r => r.onchange = () => {
  cfg.mode = r.value; T.saveCfg({ mode: r.value }); $('boxB').style.opacity = r.value === 'fixed' ? .35 : 1;
});

// ---------- sound ----------
$('device').onchange = () => T.saveCfg({ device: $('device').value });
$('lock').onclick = () => { const on = $('lock').getAttribute('aria-checked') !== 'true'; $('lock').setAttribute('aria-checked', on); T.saveCfg({ lock: on }); };
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

// ---------- start ----------
async function init() {
  const devs = await T.api('/api/devices');
  $('device').innerHTML = '<option value="">Mac default input</option>' + devs.map(d => {
    const o = document.createElement('option'); o.value = d.id;
    o.textContent = /blackhole/i.test(d.name) ? d.name + ' (recommended)' : d.name; return o.outerHTML;
  }).join('');
  st = await T.api('/api/state'); cfg = st.cfg;
  $('email').value = cfg.email || ''; if (cfg.has_password) $('password').placeholder = 'Saved';
  $('device').value = cfg.device;
  document.querySelector(`input[name=mode][value=${cfg.mode}]`).checked = true;
  $('boxB').style.opacity = cfg.mode === 'fixed' ? .35 : 1;
  $('lock').setAttribute('aria-checked', !!cfg.lock);
  $('sens').value = cfg.sensitivity; $('minB').value = cfg.minB; $('minBv').textContent = cfg.minB + '%';
  setLead(cfg.lead);
  makeWheel('wA', 'swA', 'colorA'); makeWheel('wB', 'swB', 'colorB');
  renderDevs(); calSummary();
  showTab(location.hash.slice(1));
  setInterval(async () => {
    if ($('sound').hidden) return;
    const s = await T.api('/api/state');
    $('meter').style.width = s.running ? Math.max(0, Math.min(100, (s.db + 70) / 60 * 100)) + '%' : '0';
  }, 150);
}
init();
