// Shared helpers for the Temponome pages (main deck and Settings).
(function () {
  async function api(path, body) {
    const opt = body === undefined ? {} :
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
    const r = await fetch(path, opt);
    return r.json();
  }

  // Save some settings; the server merges them into the saved settings. Calls within
  // 150 ms are combined into one request, and every caller's promise settles with its
  // result (or null if it failed, in which case 'temponome-save-failed' is announced).
  let pending = {}, timer = null, waiters = [];
  function saveCfg(partial) {
    Object.assign(pending, partial);
    clearTimeout(timer);
    const p = new Promise(resolve => waiters.push(resolve));
    timer = setTimeout(async () => {
      const body = pending, done = waiters; pending = {}; waiters = [];
      let result = null;
      try { result = await api('/api/config', body); }
      catch (e) { window.dispatchEvent(new CustomEvent('temponome-save-failed')); }
      done.forEach(r => r(result));
    }, 150);
    return p;
  }

  // Open the Settings window (native window inside the app, a page in a browser).
  function openSettings(tab) {
    tab = tab || 'lights';
    if (window.pywebview && window.pywebview.api && window.pywebview.api.open_settings) {
      window.pywebview.api.open_settings(tab);
    } else {
      window.open('/settings#' + tab, 'temponome-settings');
    }
  }

  window.T = { api, saveCfg, openSettings };
})();
