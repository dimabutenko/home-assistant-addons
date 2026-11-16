// Twinkly Garland UI. All URLs are relative: required for HA ingress (page lives under a path prefix).
'use strict';

// ---- helpers ----------------------------------------------------------------
const $ = (s, r = document) => r.querySelector(s);

function h(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e[k] = v;
    else if (k === 'value' || k === 'checked' || k === 'disabled' || k === 'hidden') e[k] = v;
    else e.setAttribute(k, v);
  }
  for (const c of kids.flat(Infinity)) if (c !== undefined && c !== null && c !== false) e.append(c.nodeType ? c : document.createTextNode(String(c)));
  return e;
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  const t = await r.text();
  let j; try { j = JSON.parse(t); } catch { j = t; }
  if (!r.ok) {
    const d = typeof j === 'object' && j ? j.detail : j;
    throw new Error(typeof d === 'string' ? d : JSON.stringify(d));
  }
  return j;
}
const send = (path, body, method = 'POST') => api(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
const clone = o => JSON.parse(JSON.stringify(o));

let toastTimer = null;
function toast(msg, err = false, ms = 4000) {
  const t = $('#toast'); t.textContent = msg; t.className = err ? 'err' : ''; t.hidden = false;
  clearTimeout(toastTimer); if (ms) toastTimer = setTimeout(() => t.hidden = true, ms);
}

const S = {
  gens: {}, pals: [], insts: [], status: [], gallery: null,
  tab: 'library', filter: '',
  draft: null, draftKey: null, previewDevice: null, previewTok: 0, previewTimer: null, previewAnim: null, previewInfo: '',
  palSel: null, palDraft: null,
};
const palByName = n => S.pals.find(p => p.name === n);
const gradient = stops => `linear-gradient(90deg, ${stops.map(s => `${s[1]} ${(s[0] * 100).toFixed(0)}%`).join(', ')})`;
const frameCount = i => i.duration * i.fps;

// ---- animated dots on canvas ------------------------------------------------
const anims = new Set();
function decode(frames) { return frames.map(b => Uint8Array.from(atob(b), c => c.charCodeAt(0))); }

function makeAnim(canvas, layout, frames, fps, radius) {
  const xs = layout.map(p => p[0]), ys = layout.map(p => p[1]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const pad = radius * 2 + 2, W = canvas.width;
  const sc = (W - 2 * pad) / ((x1 - x0) || 1);
  canvas.height = Math.round((y1 - y0) * sc + 2 * pad);
  const pos = layout.map(p => [pad + (p[0] - x0) * sc, canvas.height - pad - (p[1] - y0) * sc]);
  const a = { canvas, pos, frames, fps, radius, t0: performance.now(), last: -1 };
  anims.add(a); return a;
}
function stopAnim(a) { if (a) anims.delete(a); }
function tick(now) {
  for (const a of anims) {
    if (!a.canvas.isConnected) { anims.delete(a); continue; }
    const idx = Math.floor((now - a.t0) / 1000 * a.fps) % a.frames.length;
    if (idx === a.last) continue;
    a.last = idx;
    const g = a.canvas.getContext('2d'), fr = a.frames[idx];
    g.clearRect(0, 0, a.canvas.width, a.canvas.height);
    for (let i = 0; i < a.pos.length; i++) {
      g.fillStyle = `rgb(${fr[3 * i]},${fr[3 * i + 1]},${fr[3 * i + 2]})`;
      g.beginPath(); g.arc(a.pos[i][0], a.pos[i][1], a.radius, 0, 6.2832); g.fill();
    }
  }
  requestAnimationFrame(tick);
}
requestAnimationFrame(tick);

// ---- tabs -----------------------------------------------------------------------
function showTab(t) {
  S.tab = t;
  for (const b of document.querySelectorAll('.tab')) b.classList.toggle('active', b.dataset.tab === t);
  for (const v of ['library', 'editor', 'palettes']) $('#view-' + v).hidden = v !== t;
  if (t === 'library') { renderLibrary(); loadStatus(); }
  if (t === 'editor') renderEditor();
  if (t === 'palettes') renderPalettes();
}
for (const b of document.querySelectorAll('.tab')) b.onclick = () => showTab(b.dataset.tab);

// ---- data loading -----------------------------------------------------------------
async function loadStatus() {
  try { S.status = await api('api/status'); } catch (e) { toast('Status failed: ' + e.message, true); return; }
  if (!S.previewDevice && S.status.length) S.previewDevice = S.status[0].name;
  if (S.tab === 'library') renderLibrary();
}
async function loadGallery() {
  try {
    const g = await api('api/gallery');
    S.gallery = { layout: g.layout, items: Object.fromEntries(g.items.map(i => [i.key, { fps: i.fps, frames: decode(i.frames), total: i.frames_total }])) };
  } catch (e) { toast('Gallery failed: ' + e.message, true); }
  if (S.tab === 'library') renderLibrary();
}
async function saveInsts(list) {
  await send('api/instances', list, 'PUT');
  S.insts = await api('api/instances');
}

// ---- library -------------------------------------------------------------------------
function deviceCard(d) {
  if (!d.online) return h('div', { class: 'card' }, h('h2', {}, h('span', { class: 'dot' }), `${d.name} (${d.host})`), h('div', { class: 'bad' }, `Offline (${d.error || 'no answer'})`));
  const cap = d.capacity || 2245, want = d.desired_frames || 0, over = want > cap;
  const plan = d.plan, synced = plan && plan.action === 'ok';
  const playing = d.mode !== 'movie' ? `LEDs: ${d.mode}` : (d.playing_key ? `Playing: ${d.playing_key}` : 'Playing: unknown movie');
  return h('div', { class: 'card' },
    h('h2', {}, h('span', { class: 'dot on' }), `${d.name} (${d.host})`),
    h('div', {}, h('b', {}, playing), h('span', { class: 'muted' }, `  ·  fw ${d.firmware}`)),
    h('div', { class: 'bar' + (over ? ' over' : '') }, h('div', { style: `width:${Math.min(100, want / cap * 100)}%` })),
    h('div', { class: 'muted' }, `Frames wanted ${want} of ${cap}` + (over ? ' - too many, turn some effects off' : '') + ` · stored on the device: ${cap - d.available_frames}`),
    d.status_error ? h('div', { class: 'bad' }, d.status_error) : synced
      ? h('div', { class: 'ok' }, 'In sync: the device holds exactly the enabled effects')
      : h('div', { class: 'warn' }, plan ? `Out of sync. To upload: ${plan.missing.join(', ') || 'nothing'}; to remove: ${plan.extra.join(', ') || 'nothing'}` : 'Checking...'),
    h('div', { class: 'row', style: 'margin-top:8px' },
      h('button', { class: synced ? '' : 'primary', disabled: synced || over, onclick: () => syncDevice(d.name) }, 'Sync now'),
      h('button', { onclick: loadStatus }, 'Refresh')));
}

async function syncDevice(name) {
  if (!confirm(`Re-upload the enabled effects to ${name}? The garland goes dark for a short time while its stored effects are rebuilt.`)) return;
  toast('Uploading to the garland... this can take up to a minute.', false, 0);
  try { await send(`api/devices/${encodeURIComponent(name)}/ensure`, {}); toast('Synced.'); } catch (e) { toast('Sync failed: ' + e.message, true, 8000); }
  loadStatus();
}

function playingKeys() { return new Set(S.status.map(d => d.playing_key).filter(Boolean)); }
function pendingKeys() { const s = new Set(); for (const d of S.status) if (d.plan) d.plan.missing.forEach(k => s.add(k)); return s; }

function fxCard(inst, playing, pending) {
  const canvas = h('canvas', { width: 190 });
  const th = S.gallery && S.gallery.items[inst.key];
  if (th) makeAnim(canvas, S.gallery.layout, th.frames, th.fps, 1.4); else canvas.height = 120;
  const upd = async fn => { fn(); try { await saveInsts(S.insts); } catch (e) { toast(e.message, true); } renderLibrary(); loadStatus(); };
  return h('div', { class: 'card fx' + (inst.on_device ? '' : ' off') },
    canvas,
    h('div', { class: 'name' }, inst.key),
    h('div', { class: 'muted' }, `${inst.layers.length} layer${inst.layers.length > 1 ? 's' : ''} · ${frameCount(inst)} frames`),
    h('div', { class: 'row' },
      playing.has(inst.key) ? h('span', { class: 'badge play' }, 'playing') : null,
      inst.on_device && pending.has(inst.key) ? h('span', { class: 'badge pend' }, 'not uploaded yet') : null),
    h('label', {}, h('input', { type: 'checkbox', checked: inst.on_device, onchange: e => upd(() => inst.on_device = e.target.checked) }), 'On the garland'),
    h('label', {}, h('input', { type: 'checkbox', checked: inst.rotation, onchange: e => upd(() => inst.rotation = e.target.checked) }), 'In rotation',
      inst.rotation ? h('select', { class: 'small', title: 'Weight: how often it is picked', onchange: e => upd(() => inst.weight = Number(e.target.value)) },
        [1, 2, 3, 4, 5].map(n => h('option', { value: n, selected: n === inst.weight }, `x${n}`))) : null),
    h('div', { class: 'row' },
      h('button', { class: 'small', onclick: () => openEditor(inst.key) }, 'Edit'),
      h('button', { class: 'small', onclick: () => playNow(inst) }, 'Play now')));
}

async function playNow(inst) {
  if (!inst.on_device) {
    if (!confirm(`"${inst.key}" is not on the garland yet. Add it and play? The garland will be re-uploaded (dark for a moment).`)) return;
    inst.on_device = true;
    try { await saveInsts(S.insts); } catch (e) { toast(e.message, true); return; }
  }
  toast(`Starting "${inst.key}"... (uploads first if needed)`, false, 0);
  try { await send('api/play', { effect: inst.key, devices: inst.devices }); toast(`Playing "${inst.key}".`); } catch (e) { toast('Play failed: ' + e.message, true, 8000); }
  loadStatus();
}

function renderLibrary() {
  const root = $('#view-library'); root.replaceChildren();
  root.append(h('div', { class: 'devices' }, S.status.length ? S.status.map(deviceCard) : h('div', { class: 'card muted' }, 'Loading devices... (add devices in the add-on options)')));
  const playing = playingKeys(), pending = pendingKeys();
  const list = S.insts.filter(i => i.key.toLowerCase().includes(S.filter.toLowerCase()));
  root.append(h('div', { class: 'toolbar' },
    h('button', { class: 'primary', onclick: () => openEditor(null) }, '+ New effect'),
    h('input', { type: 'text', placeholder: 'Filter...', value: S.filter, oninput: e => { S.filter = e.target.value; renderLibrary(); const i = $('#view-library input[type=text]'); i.focus(); i.setSelectionRange(S.filter.length, S.filter.length); } }),
    h('span', { class: 'muted' }, `${S.insts.length} effects. "On the garland" = stored on the device (uses frames). "In rotation" = picked by the automation.`)));
  root.append(h('div', { class: 'grid' }, list.map(i => fxCard(i, playing, pending))));
}

// ---- editor ---------------------------------------------------------------------------
function newDraft(effect) {
  const g = Object.keys(S.gens)[0];
  return { key: '', layers: [{ effect: effect || g, params: {}, blend: 'normal', opacity: 1, mask: { type: 'none', from: 0, to: 1, invert: false } }],
    duration: 10, fps: 10, on_device: true, rotation: true, weight: 1, devices: [] };
}
function openEditor(key) {
  if (key === null) { S.draft = newDraft(); S.draft.key = uniqueKey('new effect'); S.draftKey = null; }
  else { S.draft = clone(S.insts.find(i => i.key === key)); S.draftKey = key; }
  showTab('editor'); schedulePreview(0);
}
function uniqueKey(base) {
  let k = base.slice(0, 32), n = 2;
  while (S.insts.some(i => i.key === k)) { const suf = ` ${n++}`; k = base.slice(0, 32 - suf.length) + suf; }
  return k;
}
function paramValue(layer, p) { return layer.params[p.name] !== undefined ? layer.params[p.name] : p.default; }

function randomize(layer) {
  for (const p of S.gens[layer.effect].params) {
    if (p.type === 'palette') { layer.params.palette = S.pals[Math.floor(Math.random() * S.pals.length)].name; continue; }
    if (p.name === 'intensity') continue;
    const steps = Math.round((p.max - p.min) / p.step);
    layer.params[p.name] = +(p.min + Math.floor(Math.random() * (steps + 1)) * p.step).toFixed(4);
  }
}

function paramRow(layer, p, rerender) {
  if (p.type === 'palette') {
    const cur = paramValue(layer, p), pal = palByName(cur) || S.pals[0];
    const sw = h('div', { class: 'swatch', style: `background:${gradient(pal.stops)}` });
    const sel = h('select', { onchange: e => { layer.params.palette = e.target.value; sw.style.background = gradient(palByName(e.target.value).stops); schedulePreview(); } },
      S.pals.map(x => h('option', { value: x.name, selected: x.name === cur }, x.name)));
    return [h('label', {}, p.label), sel, sw];
  }
  const val = paramValue(layer, p);
  const num = h('input', { type: 'number', min: p.min, max: p.max, step: p.step, value: val });
  const rng = h('input', { type: 'range', min: p.min, max: p.max, step: p.step, value: val });
  const set = v => { layer.params[p.name] = Number(v); num.value = v; rng.value = v; schedulePreview(); };
  rng.oninput = () => set(rng.value);
  num.onchange = () => set(Math.min(p.max, Math.max(p.min, Number(num.value))));
  return [h('label', {}, p.label), rng, num];
}

function layerCard(d, i, rerender) {
  const layer = d.layers[i], g = S.gens[layer.effect];
  const move = dir => { const j = i + dir; if (j < 0 || j >= d.layers.length) return; [d.layers[i], d.layers[j]] = [d.layers[j], d.layers[i]]; rerender(); schedulePreview(); };
  const mask = layer.mask;
  return h('div', { class: 'card layer' },
    h('div', { class: 'layer-head' },
      h('b', {}, `Layer ${i + 1}`),
      h('select', { onchange: e => { layer.effect = e.target.value; layer.params = {}; rerender(); schedulePreview(); } },
        Object.entries(S.gens).map(([k, v]) => h('option', { value: k, selected: k === layer.effect }, v.title))),
      h('button', { class: 'small', title: 'Random parameters', onclick: () => { randomize(layer); rerender(); schedulePreview(); } }, 'Randomize'),
      h('button', { class: 'small', title: 'Reset parameters', onclick: () => { layer.params = {}; rerender(); schedulePreview(); } }, 'Reset'),
      h('button', { class: 'small', disabled: i === 0, onclick: () => move(-1) }, 'Up'),
      h('button', { class: 'small', disabled: i === d.layers.length - 1, onclick: () => move(1) }, 'Down'),
      h('button', { class: 'small danger', disabled: d.layers.length === 1, onclick: () => { d.layers.splice(i, 1); rerender(); schedulePreview(); } }, 'Remove')),
    h('div', { class: 'params' }, g.params.map(p => paramRow(layer, p, rerender))),
    i === 0 ? h('div', { class: 'muted', style: 'margin-top:8px' }, 'First layer is the base. Add more layers to mix effects.') :
      h('div', { class: 'field', style: 'margin-top:8px' },
        h('label', {}, 'Mix', h('select', { onchange: e => { layer.blend = e.target.value; schedulePreview(); } },
          ['normal', 'add', 'screen', 'multiply', 'max'].map(m => h('option', { value: m, selected: m === layer.blend }, m)))),
        h('label', {}, 'Opacity', h('input', { type: 'range', min: 0, max: 1, step: 0.05, value: layer.opacity, oninput: e => { layer.opacity = Number(e.target.value); schedulePreview(); } })),
        h('label', {}, 'Show only', h('select', { onchange: e => { mask.type = e.target.value; rerender(); schedulePreview(); } },
          [['none', 'everywhere'], ['x', 'left to right'], ['y', 'bottom to top'], ['radial', 'centre to edge']].map(([v, t]) => h('option', { value: v, selected: v === mask.type }, t)))),
        mask.type !== 'none' ? [
          h('label', {}, 'from', h('input', { type: 'range', min: 0, max: 1, step: 0.05, value: mask.from, oninput: e => { mask.from = Number(e.target.value); schedulePreview(); } })),
          h('label', {}, 'to', h('input', { type: 'range', min: 0, max: 1, step: 0.05, value: mask.to, oninput: e => { mask.to = Number(e.target.value); schedulePreview(); } })),
          h('label', {}, h('input', { type: 'checkbox', checked: mask.invert, onchange: e => { mask.invert = e.target.checked; schedulePreview(); } }), 'invert')] : null));
}

function renderEditor() {
  const root = $('#view-editor'); root.replaceChildren();
  const d = S.draft;
  if (!d) { root.append(h('div', { class: 'card' }, 'Pick an effect in the Library (Edit) or ', h('button', { class: 'primary', onclick: () => openEditor(null) }, 'create a new one'))); return; }
  const rerender = () => renderEditor();
  const canvas = h('canvas', { width: 460, height: 300 });
  const info = h('div', { class: 'muted', id: 'pinfo' }, S.previewInfo);
  if (S.previewAnim) { stopAnim(S.previewAnim); S.previewAnim = null; }
  if (S.previewData) S.previewAnim = makeAnim(canvas, S.previewData.layout, S.previewData.frames, S.previewData.fps, 2.6);
  const frames = d.duration * d.fps;
  root.append(
    h('ol', { class: 'steps' },
      h('li', {}, 'Tune the layers and parameters'), h('li', {}, 'Watch the preview (it updates by itself)'),
      h('li', {}, 'Save to the library'), h('li', {}, 'Apply to the garland (Save & play)')),
    h('div', { class: 'editor' },
      h('div', { class: 'preview sticky' },
        h('div', { class: 'card' },
          h('h2', {}, 'Preview'), canvas, info,
          h('div', { class: 'row', style: 'margin-top:8px' },
            h('label', {}, 'On layout of ', h('select', { onchange: e => { S.previewDevice = e.target.value; schedulePreview(0); } },
              S.status.map(x => h('option', { value: x.name, selected: x.name === S.previewDevice }, x.name)))),
            h('button', { onclick: () => schedulePreview(0) }, 'Re-render')),
          h('div', { class: 'muted' }, 'The preview only runs in the browser. Nothing is sent to the garland until you press Save & play.'))),
      h('div', {},
        h('div', { class: 'card', style: 'margin-bottom:10px' },
          h('div', { class: 'field' },
            h('label', {}, 'Name', h('input', { type: 'text', maxlength: 32, size: 22, value: d.key, oninput: e => d.key = e.target.value })),
            h('label', {}, 'Loop, s', h('input', { type: 'number', min: 4, max: 30, value: d.duration, style: 'width:70px', onchange: e => { d.duration = Math.min(30, Math.max(4, Number(e.target.value))); rerender(); schedulePreview(); } })),
            h('label', {}, 'FPS', h('input', { type: 'number', min: 5, max: 15, value: d.fps, style: 'width:70px', onchange: e => { d.fps = Math.min(15, Math.max(5, Number(e.target.value))); rerender(); schedulePreview(); } }))),
          h('div', { class: 'muted' }, `Uses ${frames} frames on the garland (the device holds about 2245 in total).`)),
        d.layers.map((_, i) => layerCard(d, i, rerender)),
        h('div', { class: 'row', style: 'margin-bottom:10px' },
          h('button', { disabled: d.layers.length >= 4, onclick: () => { d.layers.push({ effect: Object.keys(S.gens)[0], params: {}, blend: 'add', opacity: 1, mask: { type: 'none', from: 0, to: 1, invert: false } }); rerender(); schedulePreview(); } }, '+ Add layer'),
          h('button', { onclick: () => { d.layers.forEach(randomize); rerender(); schedulePreview(); } }, 'Randomize everything')),
        h('div', { class: 'card', style: 'margin-bottom:10px' },
          h('div', { class: 'field' },
            h('label', {}, h('input', { type: 'checkbox', checked: d.on_device, onchange: e => d.on_device = e.target.checked }), 'On the garland'),
            h('label', {}, h('input', { type: 'checkbox', checked: d.rotation, onchange: e => d.rotation = e.target.checked }), 'In rotation'),
            h('label', {}, 'Weight', h('select', { onchange: e => d.weight = Number(e.target.value) }, [1, 2, 3, 4, 5].map(n => h('option', { value: n, selected: n === d.weight }, `x${n}`))))),
          h('div', { class: 'field' }, h('span', { class: 'muted' }, 'Only on devices (none ticked = all):'),
            S.status.map(x => h('label', {}, h('input', { type: 'checkbox', checked: d.devices.includes(x.name), onchange: e => { d.devices = e.target.checked ? [...d.devices, x.name] : d.devices.filter(n => n !== x.name); } }), x.name)))),
        h('div', { class: 'row' },
          h('button', { onclick: () => saveDraft(false) }, 'Save'),
          h('button', { class: 'primary', onclick: () => saveDraft(true) }, 'Save & play on garland'),
          h('button', { onclick: duplicateDraft }, 'Duplicate'),
          S.draftKey ? h('button', { class: 'danger', onclick: deleteDraft }, 'Delete') : null,
          h('button', { onclick: () => showTab('library') }, 'Back to library')))));
}

function schedulePreview(delay = 500) {
  clearTimeout(S.previewTimer);
  S.previewTimer = setTimeout(runPreview, delay);
}
async function runPreview() {
  if (!S.draft || !S.previewDevice) return;
  const tok = ++S.previewTok;
  const info = $('#pinfo'); if (info) info.textContent = 'Rendering...';
  try {
    const r = await send('api/preview', { instance: { ...S.draft, key: 'preview' }, device: S.previewDevice });
    if (tok !== S.previewTok) return;
    S.previewData = { layout: r.layout, frames: decode(r.frames), fps: r.fps };
    S.previewInfo = `${r.layout.length} LEDs · ${r.frames.length} frames at ${r.fps} fps · rendered in ${r.render_ms} ms`;
    const canvas = $('#view-editor canvas');
    if (canvas) { stopAnim(S.previewAnim); S.previewAnim = makeAnim(canvas, S.previewData.layout, S.previewData.frames, S.previewData.fps, 2.6); const i = $('#pinfo'); if (i) i.textContent = S.previewInfo; }
  } catch (e) { if (tok === S.previewTok) { const i = $('#pinfo'); if (i) i.textContent = 'Preview failed: ' + e.message; } }
}

async function saveDraft(play) {
  const d = S.draft, key = d.key.trim();
  if (!/^[A-Za-z0-9 _-]{1,32}$/.test(key)) { toast('Name: 1-32 letters, digits, space, _ or -', true); return false; }
  if (S.insts.some(i => i.key === key && i.key !== S.draftKey)) { toast('Another effect already has this name', true); return false; }
  d.key = key; if (play) d.on_device = true;
  const list = clone(S.insts), idx = list.findIndex(i => i.key === S.draftKey);
  if (idx >= 0) list[idx] = clone(d); else list.push(clone(d));
  try { await saveInsts(list); } catch (e) { toast('Not saved: ' + e.message, true, 8000); return false; }
  S.draftKey = key; toast('Saved.');
  loadGallery();
  if (play) {
    toast(`Starting "${key}"... (uploads first if needed, can take up to a minute)`, false, 0);
    try { await send('api/play', { effect: key, devices: d.devices }); toast(`Playing "${key}".`); } catch (e) { toast('Play failed: ' + e.message, true, 8000); }
  }
  loadStatus(); renderEditor();
  return true;
}
function duplicateDraft() {
  S.draft = clone(S.draft); S.draft.key = uniqueKey(S.draft.key + ' copy'); S.draftKey = null; renderEditor(); toast('Duplicated. Save to keep it.');
}
async function deleteDraft() {
  if (!confirm(`Delete "${S.draftKey}"? The garland keeps it until the next sync.`)) return;
  try { await saveInsts(S.insts.filter(i => i.key !== S.draftKey)); } catch (e) { toast(e.message, true); return; }
  S.draft = null; S.draftKey = null; loadGallery(); showTab('library');
}

// ---- palettes ----------------------------------------------------------------------------
function renderPalettes() {
  const root = $('#view-palettes'); root.replaceChildren();
  const sel = S.palDraft;
  const list = h('div', {}, h('button', { class: 'primary', style: 'margin-bottom:10px', onclick: newPalette }, '+ New palette'),
    S.pals.map(p => h('div', { class: 'card pal-item' + (sel && sel.orig === p.name ? ' sel' : ''), onclick: () => { S.palDraft = { orig: p.name, builtin: p.builtin, name: p.name, stops: clone(p.stops) }; renderPalettes(); } },
      h('b', {}, p.name, p.builtin ? h('span', { class: 'muted' }, '  built-in') : null),
      h('div', { class: 'swatch', style: `background:${gradient(p.stops)}` }))));
  let edit;
  if (!sel) edit = h('div', { class: 'card muted' }, 'Select a palette to see or edit it. Built-in ones are read-only: duplicate them to make your own.');
  else {
    const bar = h('div', { class: 'swatch', style: `height:32px;background:${gradient(sel.stops)}` });
    const refresh = () => { sel.stops.sort((a, b) => a[0] - b[0]); bar.style.background = gradient(sel.stops); };
    edit = h('div', { class: 'card' },
      h('h2', {}, sel.builtin ? `${sel.name} (built-in, read-only)` : 'Edit palette'),
      bar,
      h('div', { class: 'field', style: 'margin-top:10px' }, h('label', {}, 'Name', h('input', { type: 'text', maxlength: 32, value: sel.name, disabled: sel.builtin, oninput: e => sel.name = e.target.value }))),
      sel.stops.map((s, i) => h('div', { class: 'stop' },
        h('input', { type: 'range', min: 0, max: 1, step: 0.01, value: s[0], disabled: sel.builtin, oninput: e => { s[0] = Number(e.target.value); refresh(); } }),
        h('span', { class: 'muted' }, `${Math.round(s[0] * 100)}%`),
        h('input', { type: 'color', value: s[1], disabled: sel.builtin, oninput: e => { s[1] = e.target.value; refresh(); } }),
        sel.builtin ? null : h('button', { class: 'small danger', disabled: sel.stops.length <= 2, onclick: () => { sel.stops.splice(i, 1); renderPalettes(); } }, 'Remove'))),
      h('div', { class: 'row', style: 'margin-top:8px' },
        sel.builtin ? null : h('button', { onclick: () => { sel.stops.push([0.5, '#ffffff']); refresh(); renderPalettes(); } }, '+ Add colour'),
        sel.builtin ? null : h('button', { class: 'primary', onclick: savePalette }, 'Save'),
        h('button', { onclick: () => { S.palDraft = { orig: null, builtin: false, name: uniquePal(sel.name + ' copy'), stops: clone(sel.stops) }; renderPalettes(); } }, 'Duplicate'),
        !sel.builtin && sel.orig ? h('button', { class: 'danger', onclick: deletePalette }, 'Delete') : null),
      h('div', { class: 'muted' }, 'Effects sample the palette from its first colour (dark / low) to its last (bright / high).'));
  }
  root.append(h('div', { class: 'pals' }, list, edit));
}
function uniquePal(base) {
  let n = base.slice(0, 32), k = 2;
  while (palByName(n)) { const suf = ` ${k++}`; n = base.slice(0, 32 - suf.length) + suf; }
  return n;
}
function newPalette() { S.palDraft = { orig: null, builtin: false, name: uniquePal('my palette'), stops: [[0, '#000000'], [1, '#ff8800']] }; renderPalettes(); }
async function savePalette() {
  const d = S.palDraft, name = d.name.trim();
  const custom = S.pals.filter(p => !p.builtin && p.name !== d.orig).map(p => ({ name: p.name, stops: p.stops }));
  custom.push({ name, stops: d.stops });
  try {
    await send('api/palettes', custom, 'PUT');
    if (d.orig && d.orig !== name) {  // keep effects that used the old name working
      const list = clone(S.insts); let changed = false;
      for (const i of list) for (const l of i.layers) if (l.params.palette === d.orig) { l.params.palette = name; changed = true; }
      if (changed) await saveInsts(list);
    }
    S.pals = await api('api/palettes'); S.palDraft = { orig: name, builtin: false, name, stops: clone(d.stops) };
    toast('Palette saved. Effects using it are re-rendered on the next sync.'); loadGallery(); renderPalettes();
  } catch (e) { toast('Not saved: ' + e.message, true, 8000); }
}
async function deletePalette() {
  const d = S.palDraft;
  if (!confirm(`Delete palette "${d.orig}"? Effects that use it fall back to rainbow.`)) return;
  try { await send('api/palettes', S.pals.filter(p => !p.builtin && p.name !== d.orig).map(p => ({ name: p.name, stops: p.stops })), 'PUT'); S.pals = await api('api/palettes'); S.palDraft = null; renderPalettes(); } catch (e) { toast(e.message, true); }
}

// ---- start -------------------------------------------------------------------------------
(async function init() {
  try {
    [S.gens, S.pals, S.insts] = await Promise.all([api('api/effects'), api('api/palettes'), api('api/instances')]);
  } catch (e) { $('#view-library').textContent = 'Failed to load: ' + e.message; return; }
  renderLibrary();
  loadStatus(); loadGallery();
  setInterval(() => { if (S.tab === 'library' && !document.hidden) loadStatus(); }, 20000);
})();
