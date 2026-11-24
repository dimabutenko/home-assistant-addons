// Formula effects: write the colour of every LED as a few lines of maths, see it on the real layout at once.
// Inputs bind variables of the formula to Home Assistant entities; "Live preview" shows the formula with the real values.
'use strict';

const FM = { items: [], examples: [], reference: null, cur: null, orig: null, vals: {}, previewTimer: null,
  tok: 0, anim: null, info: '', status: null, seam: null, previewData: null, loaded: false,
  ha: null, live: null, readTimer: null, entTimer: null, streams: [], hist: {}, histTimer: null, raw: {}, manual: {}, replaySec: 90 };

async function loadFormulas() {
  const r = await api('api/formulas');
  FM.items = r.items; FM.examples = r.examples; FM.reference = r.reference; FM.loaded = true;
  try { FM.ha = await api('api/ha/status'); } catch { FM.ha = { available: false, error: 'status failed' }; }
}

function fmCopy(src) { return { name: src.name, code: src.code, params: clone(src.params || []), inputs: clone(src.inputs || []) }; }

function fmNew(from) {
  const src = from || { name: '', code: 'palette("fire", y)', params: [], inputs: [] };
  fmLiveStop();
  FM.cur = fmCopy(src); FM.cur.name = fmUniqueName(src.name || 'my formula');
  FM.orig = null; FM.vals = {}; FM.previewData = null; FM.status = null; FM.seam = null;
  renderFormulas(); fmSchedule(0);
}

function fmUniqueName(base) {
  let n = base.slice(0, 32), k = 2;
  while (FM.items.some(i => i.name === n)) { const suf = ` ${k++}`; n = base.slice(0, 32 - suf.length) + suf; }
  return n;
}

function fmPick(name) {
  const it = FM.items.find(i => i.name === name); if (!it) return;
  fmLiveStop();
  FM.cur = fmCopy(it); FM.orig = name; FM.vals = {}; FM.previewData = null; FM.status = null; FM.seam = null;
  renderFormulas(); fmSchedule(0);
}

function fmDefs() {  // parameters as the server wants them (half-filled rows are ignored)
  return FM.cur.params.filter(p => p.name && Number.isFinite(Number(p.min)) && Number.isFinite(Number(p.max)) && Number(p.max) > Number(p.min))
    .map(p => ({ name: p.name.trim(), label: p.label || p.name, min: Number(p.min), max: Number(p.max), default: Number(p.default) }));
}

function fmInputs() {
  return FM.cur.inputs.filter(i => i.name && i.entity && Number.isFinite(Number(i.min)) && Number.isFinite(Number(i.max)) && Number(i.min) !== Number(i.max))
    .map(i => ({ name: i.name.trim(), entity: i.entity.trim(), attribute: (i.attribute || '').trim(), min: Number(i.min), max: Number(i.max),
      smooth: Number(i.smooth === '' || i.smooth === undefined ? 2 : i.smooth), default: Number(i.default === '' || i.default === undefined ? 0.5 : i.default),
      auto: !!i.auto, kick: Number(i.kick === '' || i.kick === undefined ? 0.12 : i.kick) }));
}

function fmSpec() { return { code: FM.cur.code, params: fmDefs(), inputs: fmInputs() }; }

function fmSchedule(delay = 700) {
  fmDrawCharts();  // the charts of the inputs react at once, without waiting for the preview
  clearTimeout(FM.previewTimer);
  FM.previewTimer = setTimeout(() => { if (FM.live) fmLiveStart(!!FM.live.replay); else fmPreview(); }, delay);
}

function fmDevice() { return S.previewDevice || (S.status[0] && S.status[0].name); }

async function fmPreview() {
  if (!FM.cur) return;
  const dev = fmDevice(); if (!dev) { FM.status = { ok: false, msg: 'No device configured: the preview needs the LED layout of a garland.' }; fmShowStatus(); return; }
  const tok = ++FM.tok, params = { _formula: fmSpec() };
  for (const d of fmDefs()) params[d.name] = FM.vals[d.name] !== undefined ? FM.vals[d.name] : d.default;
  try {
    const r = await send('api/preview', { device: dev, instance: { key: 'preview', duration: 10, fps: 10, layers: [{ effect: 'formula', params }] } });
    if (tok !== FM.tok || FM.live) return;
    FM.previewData = { layout: r.layout, frames: decode(r.frames), fps: r.fps };
    FM.status = { ok: true }; FM.seam = r.seam; FM.info = `${r.layout.length} LEDs · rendered in ${r.render_ms} ms`;
    const canvas = document.getElementById('fm-canvas');
    if (canvas) { stopAnim(FM.anim); FM.anim = makeAnim(canvas, FM.previewData.layout, FM.previewData.frames, FM.previewData.fps, 2.6); }
  } catch (e) { if (tok !== FM.tok) return; FM.status = { ok: false, msg: e.message }; }
  fmShowStatus();
}

// ---- live preview: the server computes frames from the current Home Assistant values -------------------------
async function fmLiveStart(replay) {
  fmLiveStop(true);
  const dev = fmDevice(); if (!dev) { toast('No device configured.', true); return; }
  const params = {}; for (const d of fmDefs()) params[d.name] = FM.vals[d.name] !== undefined ? FM.vals[d.name] : d.default;
  try {
    const r = await send('api/live/preview/start', { device: dev, formula: { name: 'live', ...fmSpec() }, params,
      replay: replay ? { hours: 24, seconds: FM.replaySec } : undefined });
    const canvas = document.getElementById('fm-canvas'); stopAnim(FM.anim);
    const a = makeAnim(canvas, r.layout, [new Uint8Array(3 * r.layout.length)], 10, 2.6);
    FM.live = { id: r.id, a, layout: r.layout, timer: null, values: {}, error: null, replay: !!replay, at: null }; FM.status = { ok: true, live: true };
    if (r.replay_missing && r.replay_missing.length) toast(`No history for: ${r.replay_missing.join(', ')} (attributes and unknown entities); they keep their default value.`, true, 7000);
    for (const [name, m] of Object.entries(FM.manual)) if (m.on) fmManualSend(name);
    fmLiveTick(); fmButtons();
  } catch (e) { FM.live = null; FM.status = { ok: false, msg: e.message }; fmShowStatus(); fmButtons(); }
}

async function fmLiveTick() {
  const L = FM.live; if (!L) return;
  try {
    const r = await api(`api/live/preview/${L.id}/frame`);
    if (FM.live !== L) return;
    L.a.frames[0] = Uint8Array.from(atob(r.frame), c => c.charCodeAt(0)); L.a.last = -1; L.values = r.values; L.error = null; L.at = r.replay ? r.replay.at : null;
  } catch (e) {
    if (FM.live !== L) return;
    L.error = e.message; if (/expired/.test(e.message)) { fmLiveStart(); return; }
  }
  fmShowStatus(); fmShowValues(); fmShowReplay();
  L.timer = setTimeout(fmLiveTick, 125);
}

function fmLiveStop(keepButtons) {
  const L = FM.live; if (!L) return;
  clearTimeout(L.timer); stopAnim(L.a); FM.live = null;
  fetch(`api/live/preview/${L.id}/stop`, { method: 'POST' }).catch(() => {});
  if (!keepButtons) fmButtons();
}

function fmToggleLive() {
  if (FM.live && !FM.live.replay) { fmLiveStop(); fmSchedule(0); } else fmLiveStart(false);
}

function fmToggleReplay() {
  if (FM.live && FM.live.replay) { fmLiveStop(); fmSchedule(0); } else fmLiveStart(true);
}

function fmShowReplay() {
  const el = document.getElementById('fm-replay-clock'); if (!el) return;
  const L = FM.live;
  el.textContent = L && L.replay && L.at ? `Replaying: ${new Date(L.at * 1000).toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit' })} (24 h in ${FM.replaySec} s)` : '';
}

function fmButtons() {
  const b = document.getElementById('fm-live-btn'); if (!b) return;
  const isLive = !!FM.live && !FM.live.replay, isReplay = !!FM.live && FM.live.replay;
  b.textContent = isLive ? 'Stop live preview' : 'Live preview (real Home Assistant values)';
  b.classList.toggle('primary', isLive);
  const rb = document.getElementById('fm-replay-btn');
  if (rb) { rb.textContent = isReplay ? 'Stop replay' : 'Replay the last 24 h'; rb.classList.toggle('primary', isReplay); }
  const g = document.getElementById('fm-garland-btn'); if (!g) return;
  const on = fmOnGarland();
  g.textContent = on ? `Stop live on the garland (${on.fps} fps)` : 'Play live on the garland';
  g.classList.toggle('primary', !!on);
}

function fmOnGarland() { return FM.orig && FM.streams.find(s => s.scene === FM.orig && s.device === fmDevice() && !s.ended); }

async function fmLoadStreams() {
  try { FM.streams = await api('api/live/status'); } catch { FM.streams = []; }
  fmButtons();
}

async function fmToggleGarland() {
  const dev = fmDevice(); if (!dev) { toast('No device configured.', true); return; }
  if (fmOnGarland()) {
    try { await send('api/live/stop', { devices: [dev] }); toast('Live scene stopped, the garland is back to how it was.'); } catch (e) { toast(e.message, true, 8000); }
    await fmLoadStreams(); loadStatus(); return;
  }
  if (!(await fmSave())) return;  // the server plays the saved formula
  toast(`Starting "${FM.orig}" on ${dev}...`, false, 0);
  try { await send('api/live/play', { scene: FM.orig, devices: [dev], restart: true }); toast('Live on the garland. Any other effect (not "random") or the Stop button ends it.'); }
  catch (e) { toast('Live failed: ' + e.message, true, 9000); }
  await fmLoadStreams(); loadStatus();
}

function fmSetBar(i, v) {
  const b = document.getElementById(`fm-bar-${i}`); if (b) b.style.width = `${Math.round(Math.max(0, Math.min(1, v)) * 100)}%`;
}

function fmShowValues() {
  const el = document.getElementById('fm-values'); if (!el || !FM.live) return;
  FM.cur.inputs.forEach((p, i) => {
    const v = FM.live.values[(p.name || '').trim()]; if (!v) return;
    fmSetBar(i, v.value); FM.raw[(p.name || '').trim()] = v.raw;
    const t = document.getElementById(`fm-vnow-${i}`); if (t) t.textContent = v.value.toFixed(2);
  });
  fmDrawCharts();
  el.replaceChildren(...Object.entries(FM.live.values).map(([k, v]) => h('span', { class: 'badge', style: 'margin-right:6px' },
    `${v.kick > 0.25 ? '⚡ ' : ''}${k} ${v.value}` + (v.raw !== null && v.raw !== undefined ? ` (${v.raw})` : ' (n/a)') + (v.count ? ` #${v.count}` : ''))));
}

function fmShowStatus() {
  const el = document.getElementById('fm-status'); if (!el) return;
  el.replaceChildren();
  if (!FM.status) { el.textContent = 'Rendering...'; return; }
  if (!FM.status.ok) { el.append(h('span', { class: 'bad' }, FM.status.msg)); return; }
  if (FM.status.live) {
    el.append(h('span', { class: FM.live && FM.live.error ? 'bad' : 'ok' }, FM.live && FM.live.error ? FM.live.error
      : FM.live && FM.live.replay ? 'Replay: the history of the inputs is played back fast, so you can see how the scene looks through a whole day.'
        : 'Live: computed on the server from the current values, about 8 frames per second.'));
    return;
  }
  const seamOk = FM.seam === null || FM.seam <= 2.5;
  const liveStyle = FM.cur && (FM.cur.inputs.length > 0 || /\bnow\b/.test(FM.cur.code));
  el.append(h('span', { class: 'ok' }, 'The formula works. '), FM.info + '. ',
    !seamOk && liveStyle ? h('span', { class: 'muted' }, 'This is a live scene (it uses now or Home Assistant inputs): it runs without a loop, so the jump at the end of this 10 s preview does not matter. Do not store it on the garland as a movie.')
    : seamOk ? h('span', { class: 'ok' }, 'The loop is seamless.')
      : h('span', { class: 'warn' }, `The loop has a visible jump (${FM.seam}x a normal step). Use whole numbers of cycles of t, e.g. sin(tau*2*t), or tnoise / rise. (Ignore this for live scenes.)`));
}

async function fmSave() {
  const c = FM.cur;
  if (!/^[A-Za-z0-9 _-]{1,32}$/.test(c.name.trim())) { toast('Name: 1-32 letters, digits, space, _ or -', true); return false; }
  const item = { name: c.name.trim(), code: c.code, params: fmDefs(), inputs: fmInputs() };
  const list = clone(FM.items), idx = list.findIndex(i => i.name === FM.orig);
  if (idx >= 0) list[idx] = item; else if (list.some(i => i.name === item.name)) { toast('Another formula already has this name', true); return false; } else list.push(item);
  try { await send('api/formulas', list, 'PUT'); } catch (e) { toast('Not saved: ' + e.message, true, 9000); return false; }
  await loadFormulas(); S.gens = await api('api/effects');
  FM.orig = item.name; FM.cur.name = item.name; toast('Saved. It is now a generator in the effect editor.'); renderFormulas();
  return true;
}

async function fmDelete() {
  if (!FM.orig || !confirm(`Delete the formula "${FM.orig}"?`)) return;
  try { await send('api/formulas', FM.items.filter(i => i.name !== FM.orig), 'PUT'); } catch (e) { toast(e.message, true, 9000); return; }
  fmLiveStop();
  await loadFormulas(); S.gens = await api('api/effects'); FM.cur = null; FM.orig = null; renderFormulas();
}

async function fmMakeEffect() {
  if (!(await fmSave())) return;
  const name = FM.orig, key = uniqueKey(name);
  const inst = { key, layers: [{ effect: `custom:${name}`, params: {}, blend: 'normal', opacity: 1, mask: { type: 'none', from: 0, to: 1, invert: false } }],
    duration: 10, fps: 10, on_device: false, rotation: true, weight: 1, devices: [] };
  try { await saveInsts([...S.insts, inst]); } catch (e) { toast(e.message, true); return; }
  loadGallery(); openEditor(key);
}

function fmParamRow(p, i) {
  return h('div', { class: 'fm-param' },
    h('input', { type: 'text', placeholder: 'name', value: p.name, size: 8, oninput: e => { p.name = e.target.value; fmSchedule(); } }),
    h('input', { type: 'text', placeholder: 'label', value: p.label || '', size: 14, oninput: e => { p.label = e.target.value; } }),
    h('input', { type: 'number', step: 'any', value: p.min, title: 'min', onchange: e => { p.min = e.target.value; fmSchedule(); } }),
    h('input', { type: 'number', step: 'any', value: p.max, title: 'max', onchange: e => { p.max = e.target.value; fmSchedule(); } }),
    h('input', { type: 'number', step: 'any', value: p.default, title: 'default', onchange: e => { p.default = e.target.value; FM.vals[p.name] = undefined; fmSchedule(); renderFormulas(); } }),
    h('button', { class: 'small danger', onclick: () => { FM.cur.params.splice(i, 1); renderFormulas(); fmSchedule(); } }, 'Remove'));
}

// entity suggestions for the datalist
function fmSuggest(q) {
  clearTimeout(FM.entTimer);
  FM.entTimer = setTimeout(async () => {
    if (!FM.ha || !FM.ha.available || q.length < 2) return;
    try {
      const list = await api('api/ha/entities?q=' + encodeURIComponent(q));
      const dl = document.getElementById('fm-ents'); if (!dl) return;
      dl.replaceChildren(...list.map(e => h('option', { value: e.entity_id }, `${e.name || ''} · ${e.state} ${e.unit}${e.attributes.length ? ' · attrs: ' + e.attributes.join(', ') : ''}`)));
    } catch { /* ignore */ }
  }, 300);
}

// ---- charts and manual values of the inputs ---------------------------------------------------------------------------------------
async function fmLoadHist(force) {
  if (!FM.cur || !FM.ha || !FM.ha.available) return;
  const need = fmInputs().filter(i => { const k = `${i.entity}|${i.attribute}`, h0 = FM.hist[k]; return force || !h0 || Date.now() - h0.at > 120000; });
  if (!need.length) { fmDrawCharts(); return; }
  try {
    const res = await send('api/ha/history', { inputs: need, minutes: 30 });
    for (const r of res) { const i = need.find(x => x.name === r.name); if (i) FM.hist[`${i.entity}|${i.attribute}`] = { ...r, at: Date.now() }; }
  } catch { /* the charts stay as they were */ }
  fmDrawCharts();
}

function fmChartSim(vals, lo, hi, thr, dt) {  // the same event rule as the live scene: a jump of the target away from its slow baseline
  const ev = []; let base = null, last = -1e9;
  vals.forEach((v, k) => {
    const tg = Math.min(1, Math.max(0, (v - lo) / (hi - lo))); if (base === null) base = tg;
    const t = k * dt, jump = tg - base;
    if (t > 4 && Math.abs(jump) > thr && t - last > 0.8) { ev.push(k); base = tg; last = t; } else base += (tg - base) * (1 - Math.exp(-dt / 5));
  });
  return ev;
}

const BLUE = '#3b82f6';
function fmDrawChart(cv, p, hist) {
  const ctx = cv.getContext('2d'), W = cv.width, H = cv.height, css = getComputedStyle(document.documentElement);
  const col = n => css.getPropertyValue(n).trim();
  ctx.clearRect(0, 0, W, H); ctx.fillStyle = col('--bg'); ctx.fillRect(0, 0, W, H);
  ctx.font = '11px system-ui, sans-serif'; ctx.textBaseline = 'middle';
  const msg = t => { ctx.fillStyle = col('--muted'); ctx.fillText(t, 8, H / 2); };
  if (!FM.ha || !FM.ha.available) return msg('Home Assistant data is not available here.');
  if (!p.entity) return msg('Pick an entity to see its last 30 minutes.');
  if (!hist) return msg('Loading the history...');
  if (hist.error || !hist.values || !hist.values.length) return msg(hist.error || 'No history.');
  const vals = hist.values, n = vals.length, mn = Number(p.min), mx = Number(p.max), thr = Number(p.kick === '' || p.kick === undefined ? 0.12 : p.kick);
  let lo = mn, hi = mx;
  if (p.auto) {
    lo = Math.min(...vals); hi = Math.max(...vals);
    const span = Math.max(Math.abs(mx - mn) * 0.05, 1e-9);
    if (hi - lo < span) { const mid = (hi + lo) / 2; lo = mid - span / 2; hi = mid + span / 2; }
  }
  if (!(hi > lo)) return msg('"→ 1" must be larger than "→ 0".');
  const raw = FM.raw[(p.name || '').trim()];
  const all = [lo, hi, ...vals].concat(raw !== undefined && raw !== null ? [raw] : []);
  let vmin = Math.min(...all), vmax = Math.max(...all); const pad = (vmax - vmin) * 0.08 || 1; vmin -= pad; vmax += pad;
  const L = 6, R = W - 6, T = 8, B = H - 16, y = v => B - (v - vmin) / (vmax - vmin) * (B - T), x = k => L + (R - L) * k / (n - 1);
  ctx.fillStyle = BLUE; ctx.globalAlpha = 0.1; ctx.fillRect(L, y(hi), R - L, y(lo) - y(hi)); ctx.globalAlpha = 1;  // the range that maps to 0..1
  ctx.setLineDash([4, 3]); ctx.strokeStyle = col('--muted'); ctx.lineWidth = 1;
  for (const v of [lo, hi]) { ctx.beginPath(); ctx.moveTo(L, y(v)); ctx.lineTo(R, y(v)); ctx.stroke(); }
  ctx.setLineDash([]); ctx.fillStyle = col('--muted');
  const fmt = v => Math.abs(v) >= 100 ? String(Math.round(v)) : String(Math.round(v * 100) / 100);
  ctx.fillText(`1 = ${fmt(hi)}${p.auto ? ' (auto)' : ''}`, L + 2, y(hi) - 6); ctx.fillText(`0 = ${fmt(lo)}${p.auto ? ' (auto)' : ''}`, L + 2, y(lo) - 6);
  const dt = (hist.t1 - hist.t0) / n, ev = fmChartSim(vals, lo, hi, thr, dt);
  ctx.strokeStyle = col('--warn'); ctx.globalAlpha = 0.55; ctx.lineWidth = 1.5;
  for (const k of ev) { ctx.beginPath(); ctx.moveTo(x(k), T); ctx.lineTo(x(k), B); ctx.stroke(); }
  ctx.globalAlpha = 1; ctx.lineWidth = 1.6;
  for (let k = 1; k < n; k++) {
    const out = vals[k] < lo || vals[k] > hi; ctx.strokeStyle = out ? col('--bad') : BLUE;
    ctx.beginPath(); ctx.moveTo(x(k - 1), y(vals[k - 1])); ctx.lineTo(x(k), y(vals[k])); ctx.stroke();
  }
  if (raw !== undefined && raw !== null) { ctx.fillStyle = col('--fg'); ctx.beginPath(); ctx.arc(R - 2, y(raw), 3.5, 0, 7); ctx.fill(); }
  ctx.fillStyle = col('--muted'); ctx.textBaseline = 'alphabetic';
  const mins = Math.round((hist.t1 - hist.t0) / 60); ctx.fillText(`-${mins} min`, L, H - 3);
  ctx.textAlign = 'right'; ctx.fillText(`${ev.length} event${ev.length === 1 ? '' : 's'} in ${mins} min · red = beyond the range (clipped) · orange = event`, R, H - 3); ctx.textAlign = 'left';
}

function fmDrawCharts() {
  if (!FM.cur) return;
  FM.cur.inputs.forEach((p, i) => {
    const cv = document.getElementById(`fm-ch-${i}`); if (!cv) return;
    fmDrawChart(cv, p, FM.hist[`${(p.entity || '').trim()}|${(p.attribute || '').trim()}`]);
  });
}

async function fmManualSend(name, kick) {
  if (!FM.live) return;
  const m = FM.manual[name] || {};
  try { await send(`api/live/preview/${FM.live.id}/manual`, { name, value: m.on ? m.v : null, kick: !!kick }); } catch { /* the input was removed or the preview expired */ }
}

async function fmEnsureLive() { if (!FM.live) await fmLiveStart(false); return !!FM.live; }

function fmTryRow(p, i) {
  const name = (p.name || '').trim(), m = FM.manual[name] || (FM.manual[name] = { on: false, v: 0.5 });
  let busy = false;
  const val = h('span', { id: `fm-vnow-${i}`, class: 'muted' }, ''), cb = h('input', { type: 'checkbox', checked: m.on });
  const rng = h('input', { type: 'range', min: 0, max: 1, step: 0.01, value: m.v });
  rng.oninput = () => {
    m.v = Number(rng.value); m.on = true; cb.checked = true;
    if (!busy) { busy = true; setTimeout(async () => { busy = false; if (await fmEnsureLive()) fmManualSend(name); }, 80); }
  };
  cb.onchange = async () => { m.on = cb.checked; if (await fmEnsureLive()) fmManualSend(name); };
  return h('div', { class: 'fm-try' },
    h('strong', {}, name || `input ${i + 1}`), h('label', { class: 'muted' }, cb, ' by hand'), rng,
    h('button', { class: 'small', title: 'fire an event of this input (name_kick, name_count...)', onclick: async () => { if (await fmEnsureLive()) fmManualSend(name, true); } }, '⚡ event'),
    h('div', { class: 'bar', title: 'the value the formula gets now (0..1, smoothed)' }, h('div', { id: `fm-bar-${i}`, style: 'width:0%' })), val);
}

function fmMonitor(c) {
  if (!c.inputs.length) return null;
  return h('div', { class: 'card', style: 'margin-bottom:10px' },
    h('h3', {}, 'Watch and try the inputs'),
    h('div', { class: 'muted', style: 'margin-bottom:8px' }, 'Each chart shows the last 30 minutes of the sensor in its own units. The shaded band is the range that becomes 0..1 (the "→ 0" and "→ 1" values, or the auto range): change them above and the chart follows at once. The dot at the right edge is the value now. Below each chart you can take the input into your own hands: move the slider (or press the event button) and the preview shows what the formula does, whatever the sensor says. The preview starts by itself. "Replay the last 24 h" under the preview plays the whole past day back fast.'),
    c.inputs.map((p, i) => h('div', { style: 'margin-bottom:12px' },
      h('canvas', { id: `fm-ch-${i}`, class: 'fm-chart', width: 640, height: 96 }), fmTryRow(p, i))));
}

function fmInputRow(p, i) {
  return h('div', { class: 'fm-input' },
    h('input', { type: 'text', placeholder: 'name', value: p.name, size: 6, oninput: e => { p.name = e.target.value; fmSchedule(); } }),
    h('input', { type: 'text', placeholder: 'sensor.entity_id', list: 'fm-ents', value: p.entity, oninput: e => { p.entity = e.target.value; fmSuggest(e.target.value); }, onchange: () => { fmSchedule(); fmLoadHist(); } }),
    h('input', { type: 'text', placeholder: 'attribute (optional)', value: p.attribute || '', onchange: e => { p.attribute = e.target.value; fmSchedule(); fmLoadHist(); } }),
    h('input', { type: 'number', step: 'any', value: p.min, title: 'value mapped to 0', onchange: e => { p.min = e.target.value; fmSchedule(); } }),
    h('input', { type: 'number', step: 'any', value: p.max, title: 'value mapped to 1', onchange: e => { p.max = e.target.value; fmSchedule(); } }),
    h('input', { type: 'number', step: 'any', value: p.smooth === undefined ? 2 : p.smooth, title: 'smoothing, seconds', onchange: e => { p.smooth = e.target.value; fmSchedule(); } }),
    h('input', { type: 'number', step: 'any', min: 0, max: 1, value: p.default === undefined ? 0.5 : p.default, title: 'value 0..1 used when the effect is stored on the garland', onchange: e => { p.default = e.target.value; fmSchedule(); } }),
    h('input', { type: 'checkbox', checked: !!p.auto, title: 'auto range: the last 30 minutes of this sensor are mapped to 0..1 (the "to 0" / "to 1" values are only the starting guess)', onchange: e => { p.auto = e.target.checked; fmSchedule(); } }),
    h('input', { type: 'number', step: 'any', min: 0.02, max: 0.5, value: p.kick === undefined ? 0.12 : p.kick, title: 'event threshold: a jump of this share of the 0..1 range fires <name>_kick / _count', onchange: e => { p.kick = e.target.value; fmSchedule(); } }),
    h('span', { class: 'muted', id: `fm-now-${i}` }, ''),
    h('button', { class: 'small danger', onclick: () => { FM.cur.inputs.splice(i, 1); renderFormulas(); fmSchedule(); } }, 'Remove'));
}

async function fmReadInputs() {
  if (!FM.cur || !FM.ha || !FM.ha.available || document.getElementById('view-formulas').hidden) return;
  const ins = fmInputs(); if (!ins.length) return;
  try {
    const res = await send('api/ha/read', { inputs: ins });
    FM.cur.inputs.forEach((p, i) => {
      const el = document.getElementById(`fm-now-${i}`), r = res.find(x => x.name === (p.name || '').trim()); if (!el) return;
      el.textContent = !r ? '' : r.error ? r.error : r.value === null ? 'n/a' : `${r.raw} → ${r.value}`;
      el.className = r && r.error ? 'bad' : 'muted';
      if (r && r.raw !== null && r.raw !== undefined && !FM.live) { FM.raw[r.name] = r.raw; fmSetBar(i, r.value); }
    });
    fmDrawCharts();
  } catch { /* ignore */ }
}

function renderFormulas() {
  const root = document.getElementById('view-formulas'); root.replaceChildren();
  if (!FM.loaded) { root.textContent = 'Loading...'; loadFormulas().then(renderFormulas).catch(e => root.textContent = 'Failed to load: ' + e.message); return; }
  const c = FM.cur;
  if (!FM.readTimer) FM.readTimer = setInterval(fmReadInputs, 3000);
  if (!FM.histTimer) FM.histTimer = setInterval(() => { if (!document.getElementById('view-formulas').hidden) fmLoadHist(); }, 60000);
  const top = h('div', { class: 'card', style: 'margin-bottom:12px' },
    h('h2', {}, 'Formula effects'),
    h('div', { class: 'muted', style: 'margin-bottom:8px' }, 'Describe the colour of every LED with a few lines of maths: it is a function of the position (x, y), the loop time t, your own sliders and, if you like, live data from Home Assistant. The preview shows it on the real layout. Saved formulas appear as generators in the effect editor, so they can be mixed in layers like the built-in ones.'),
    FM.ha && !FM.ha.available ? h('div', { class: 'warn', style: 'margin-bottom:8px' }, 'Home Assistant data is not available here (' + (FM.ha.error || '') + '): inputs will show their default values.') : null,
    h('div', { class: 'row' },
      FM.items.map(i => h('button', { class: i.name === FM.orig ? 'primary' : '', onclick: () => fmPick(i.name) }, i.name)),
      h('button', { onclick: () => fmNew() }, '+ New'),
      h('select', { onchange: e => { const ex = FM.examples[Number(e.target.value)]; if (ex) fmNew(ex); e.target.value = ''; } },
        h('option', { value: '' }, 'Start from an example...'), FM.examples.map((ex, n) => h('option', { value: n }, ex.name)))));
  root.append(top);
  if (!c) { root.append(h('div', { class: 'card muted' }, 'Pick a saved formula, press "+ New", or start from an example.')); return; }

  const canvas = h('canvas', { id: 'fm-canvas', width: 460, height: 300 });
  if (FM.anim) { stopAnim(FM.anim); FM.anim = null; }
  if (FM.live) { stopAnim(FM.live.a); FM.live.a = makeAnim(canvas, FM.live.layout, FM.live.a.frames, 10, 2.6); }
  else if (FM.previewData) FM.anim = makeAnim(canvas, FM.previewData.layout, FM.previewData.frames, FM.previewData.fps, 2.6);
  const defs = fmDefs();
  const code = h('textarea', { id: 'fm-code', spellcheck: 'false', rows: 14, class: 'fm-code', value: c.code,
    oninput: e => { c.code = e.target.value; fmSchedule(); } });
  const ref = FM.reference;
  root.append(h('div', { class: 'editor' },
    h('div', { class: 'preview sticky' },
      h('div', { class: 'card' }, h('h2', {}, 'Preview'), canvas, h('div', { id: 'fm-status', class: 'muted' }, 'Rendering...'),
        h('div', { id: 'fm-values', style: 'margin-top:6px' }),
        h('div', { class: 'row', style: 'margin-top:8px' }, h('button', { id: 'fm-garland-btn', class: '', onclick: fmToggleGarland, title: 'Streams the formula to the garland in real time, with live Home Assistant values' }, 'Play live on the garland'), h('button', { id: 'fm-live-btn', disabled: !(FM.ha && FM.ha.available) && !fmInputs().length, onclick: fmToggleLive, title: 'Computes frames on the server from the current values of the inputs' }, 'Live preview (real Home Assistant values)')),
        h('div', { class: 'row', style: 'margin-top:8px' },
          h('button', { id: 'fm-replay-btn', disabled: !fmInputs().length || !(FM.ha && FM.ha.available), onclick: fmToggleReplay, title: 'Plays the last 24 hours of the inputs back fast, so you see the scene through a whole day' }, 'Replay the last 24 h'),
          h('select', { title: 'how long the 24 hours take', onchange: e => { FM.replaySec = Number(e.target.value); if (FM.live && FM.live.replay) fmLiveStart(true); } },
            [45, 90, 180, 360].map(sec => h('option', { value: sec, selected: sec === FM.replaySec }, sec < 100 ? `24 h in ${sec} s` : `24 h in ${sec / 60} min`))),
          h('span', { id: 'fm-replay-clock', class: 'muted' }, '')),
        defs.length ? h('div', { style: 'margin-top:8px' }, h('h3', {}, 'Try the parameters'),
          h('div', { class: 'params' }, defs.map(d => {
            const v = FM.vals[d.name] !== undefined ? FM.vals[d.name] : d.default, step = (d.max - d.min) / 100;
            const num = h('span', {}, String(v)), rng = h('input', { type: 'range', min: d.min, max: d.max, step, value: v });
            rng.oninput = () => { FM.vals[d.name] = Number(rng.value); num.textContent = rng.value; fmSchedule(300); };
            return [h('label', {}, d.label), rng, num];
          }))) : null)),
    h('div', {},
      h('div', { class: 'card', style: 'margin-bottom:10px' },
        h('div', { class: 'field' }, h('label', {}, 'Name', h('input', { type: 'text', maxlength: 32, size: 22, value: c.name, oninput: e => { c.name = e.target.value; } }))),
        h('div', { class: 'muted' }, 'Formula. One "name = expression" per line, the last line is the colour.'), code),
      h('div', { class: 'card', style: 'margin-bottom:10px' },
        h('h3', {}, 'Parameters (they become sliders)'),
        h('div', { class: 'fm-param muted' }, h('span', {}, 'name'), h('span', {}, 'label'), h('span', {}, 'min'), h('span', {}, 'max'), h('span', {}, 'default'), h('span', {})),
        c.params.map(fmParamRow),
        h('button', { class: 'small', disabled: c.params.length >= 8, onclick: () => { c.params.push({ name: 'p' + (c.params.length + 1), label: '', min: 0, max: 1, default: 0.5 }); renderFormulas(); } }, '+ parameter')),
      h('div', { class: 'card', style: 'margin-bottom:10px' },
        h('h3', {}, 'Inputs from Home Assistant'),
        h('div', { class: 'muted', style: 'margin-bottom:6px' }, 'Each input is a variable 0..1 in the formula. "min" is the value that maps to 0, "max" to 1 (attribute: e.g. elevation of sun.sun). Smoothing in seconds makes the value glide (use 0.3 to 0.5 for fast signals). "auto" maps the last 30 minutes of the sensor to 0..1, so every sensor uses its whole range. "event" is the size of a jump (share of the range) that fires name_kick, name_age and name_count. "default" is used when the effect is stored on the garland.'),
        h('div', { class: 'fm-input muted' }, h('span', {}, 'name'), h('span', {}, 'entity'), h('span', {}, 'attribute'), h('span', {}, '→ 0'), h('span', {}, '→ 1'), h('span', {}, 'smooth s'), h('span', {}, 'default'), h('span', {}, 'auto'), h('span', {}, 'event'), h('span', {}, 'now'), h('span', {})),
        c.inputs.map(fmInputRow),
        h('datalist', { id: 'fm-ents' }),
        h('button', { class: 'small', disabled: c.inputs.length >= 8, onclick: () => { c.inputs.push({ name: 'in' + (c.inputs.length + 1), entity: '', attribute: '', min: 0, max: 100, smooth: 0.4, default: 0.5, auto: true, kick: 0.12 }); renderFormulas(); } }, '+ input')),
      fmMonitor(c),
      h('div', { class: 'row', style: 'margin-bottom:10px' },
        h('button', { class: 'primary', onclick: fmSave }, 'Save'),
        h('button', { onclick: fmMakeEffect, title: 'Save and create an effect in the library that uses this formula' }, 'Save & make an effect'),
        FM.orig ? h('button', { class: 'danger', onclick: fmDelete }, 'Delete') : null),
      h('details', { class: 'card' }, h('summary', {}, 'Reference: variables and functions'),
        h('ul', {}, ref.rules.map(t => h('li', {}, t))),
        h('h3', {}, 'Variables'), h('ul', {}, ref.variables.map(t => h('li', {}, t))),
        h('h3', {}, 'Functions'), h('ul', { class: 'fm-funcs' }, ref.functions.map(t => h('li', {}, t)))))));
  fmShowStatus(); fmButtons(); fmShowValues(); fmShowReplay(); setTimeout(fmReadInputs, 200); fmLoadStreams(); fmLoadHist(); setTimeout(fmDrawCharts, 50);
}
