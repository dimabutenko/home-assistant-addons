// Formula effects: write the colour of every LED as a few lines of maths, see it on the real layout at once.
'use strict';

const FM = { items: [], examples: [], reference: null, cur: null, orig: null, vals: {}, previewTimer: null, checkTimer: null,
  tok: 0, anim: null, info: '', status: null, seam: null, previewData: null, loaded: false };

async function loadFormulas() {
  const r = await api('api/formulas');
  FM.items = r.items; FM.examples = r.examples; FM.reference = r.reference; FM.loaded = true;
}

function fmNew(from) {
  const src = from || { name: '', code: 'palette("fire", y)', params: [] };
  FM.cur = { name: src.name ? fmUniqueName(src.name) : fmUniqueName('my formula'), code: src.code, params: clone(src.params) };
  FM.orig = null; FM.vals = {}; FM.previewData = null; FM.status = null; FM.seam = null;
  renderFormulas(); fmSchedule(0);
}

function fmUniqueName(base) {
  const taken = new Set([...FM.items.map(i => i.name), ...S.insts.map(i => i.key)]);
  let n = base.slice(0, 32), k = 2;
  while (FM.items.some(i => i.name === n)) { const suf = ` ${k++}`; n = base.slice(0, 32 - suf.length) + suf; }
  return n;
}

function fmPick(name) {
  const it = FM.items.find(i => i.name === name); if (!it) return;
  FM.cur = clone(it); FM.orig = name; FM.vals = {}; FM.previewData = null; FM.status = null; FM.seam = null;
  renderFormulas(); fmSchedule(0);
}

function fmDefs() {  // the parameters as the server wants them (ignoring half-filled rows)
  return FM.cur.params.filter(p => p.name && Number.isFinite(Number(p.min)) && Number.isFinite(Number(p.max)) && Number(p.max) > Number(p.min))
    .map(p => ({ name: p.name.trim(), label: p.label || p.name, min: Number(p.min), max: Number(p.max), default: Number(p.default) }));
}

function fmSchedule(delay = 700) {
  clearTimeout(FM.previewTimer); FM.previewTimer = setTimeout(fmPreview, delay);
}

async function fmPreview() {
  if (!FM.cur) return;
  const dev = (S.status[0] && S.status[0].name) || S.previewDevice; if (!dev) { FM.status = { ok: false, msg: 'No device configured: the preview needs the LED layout of a garland.' }; fmShowStatus(); return; }
  const tok = ++FM.tok, params = { _formula: { code: FM.cur.code, params: fmDefs() } };
  for (const d of fmDefs()) params[d.name] = FM.vals[d.name] !== undefined ? FM.vals[d.name] : d.default;
  try {
    const r = await send('api/preview', { device: dev, instance: { key: 'preview', duration: 10, fps: 10, layers: [{ effect: 'formula', params }] } });
    if (tok !== FM.tok) return;
    FM.previewData = { layout: r.layout, frames: decode(r.frames), fps: r.fps };
    FM.status = { ok: true }; FM.seam = r.seam; FM.info = `${r.layout.length} LEDs · rendered in ${r.render_ms} ms`;
    const canvas = document.getElementById('fm-canvas');
    if (canvas) { stopAnim(FM.anim); FM.anim = makeAnim(canvas, FM.previewData.layout, FM.previewData.frames, FM.previewData.fps, 2.6); }
  } catch (e) { if (tok !== FM.tok) return; FM.status = { ok: false, msg: e.message }; }
  fmShowStatus();
}

function fmShowStatus() {
  const el = document.getElementById('fm-status'); if (!el) return;
  el.replaceChildren();
  if (!FM.status) { el.textContent = 'Rendering...'; return; }
  if (!FM.status.ok) { el.append(h('span', { class: 'bad' }, FM.status.msg)); return; }
  const seamOk = FM.seam === null || FM.seam <= 2.5;
  el.append(h('span', { class: 'ok' }, 'The formula works. '), FM.info + '. ',
    seamOk ? h('span', { class: 'ok' }, 'The loop is seamless.')
      : h('span', { class: 'warn' }, `The loop has a visible jump (${FM.seam}x a normal step). Use whole numbers of cycles of t, e.g. sin(tau*2*t), or tnoise / rise.`));
}

async function fmSave() {
  const c = FM.cur;
  if (!/^[A-Za-z0-9 _-]{1,32}$/.test(c.name.trim())) { toast('Name: 1-32 letters, digits, space, _ or -', true); return false; }
  const item = { name: c.name.trim(), code: c.code, params: fmDefs() };
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
  const set = (k, num) => e => { p[k] = num ? e.target.value : e.target.value; fmSchedule(); };
  return h('div', { class: 'fm-param' },
    h('input', { type: 'text', placeholder: 'name', value: p.name, size: 8, oninput: e => { p.name = e.target.value; fmSchedule(); } }),
    h('input', { type: 'text', placeholder: 'label', value: p.label || '', size: 14, oninput: e => { p.label = e.target.value; } }),
    h('input', { type: 'number', step: 'any', value: p.min, title: 'min', onchange: e => { p.min = e.target.value; fmSchedule(); } }),
    h('input', { type: 'number', step: 'any', value: p.max, title: 'max', onchange: e => { p.max = e.target.value; fmSchedule(); } }),
    h('input', { type: 'number', step: 'any', value: p.default, title: 'default', onchange: e => { p.default = e.target.value; FM.vals[p.name] = undefined; fmSchedule(); renderFormulas(); } }),
    h('button', { class: 'small danger', onclick: () => { FM.cur.params.splice(i, 1); renderFormulas(); fmSchedule(); } }, 'Remove'));
}

function renderFormulas() {
  const root = document.getElementById('view-formulas'); root.replaceChildren();
  if (!FM.loaded) { root.textContent = 'Loading...'; loadFormulas().then(renderFormulas).catch(e => root.textContent = 'Failed to load: ' + e.message); return; }
  const c = FM.cur;
  const top = h('div', { class: 'card', style: 'margin-bottom:12px' },
    h('h2', {}, 'Formula effects'),
    h('div', { class: 'muted', style: 'margin-bottom:8px' }, 'Describe the colour of every LED with a few lines of maths: it is a function of the position (x, y), the loop time t and your own sliders. The preview shows it on the real layout. Saved formulas appear as generators in the effect editor, so they can be mixed in layers like the built-in ones.'),
    h('div', { class: 'row' },
      FM.items.map(i => h('button', { class: i.name === FM.orig ? 'primary' : '', onclick: () => fmPick(i.name) }, i.name)),
      h('button', { onclick: () => fmNew() }, '+ New'),
      h('select', { onchange: e => { const ex = FM.examples[Number(e.target.value)]; if (ex) fmNew(ex); e.target.value = ''; } },
        h('option', { value: '' }, 'Start from an example...'), FM.examples.map((ex, n) => h('option', { value: n }, ex.name)))));
  root.append(top);
  if (!c) { root.append(h('div', { class: 'card muted' }, 'Pick a saved formula, press "+ New", or start from an example.')); return; }

  const canvas = h('canvas', { id: 'fm-canvas', width: 460, height: 300 });
  if (FM.anim) { stopAnim(FM.anim); FM.anim = null; }
  if (FM.previewData) FM.anim = makeAnim(canvas, FM.previewData.layout, FM.previewData.frames, FM.previewData.fps, 2.6);
  const defs = fmDefs();
  const code = h('textarea', { id: 'fm-code', spellcheck: 'false', rows: 14, class: 'fm-code', value: c.code,
    oninput: e => { c.code = e.target.value; fmSchedule(); } });
  const ref = FM.reference;
  root.append(h('div', { class: 'editor' },
    h('div', { class: 'preview sticky' },
      h('div', { class: 'card' }, h('h2', {}, 'Preview'), canvas, h('div', { id: 'fm-status', class: 'muted' }, 'Rendering...'),
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
      h('div', { class: 'row', style: 'margin-bottom:10px' },
        h('button', { class: 'primary', onclick: fmSave }, 'Save'),
        h('button', { onclick: fmMakeEffect, title: 'Save and create an effect in the library that uses this formula' }, 'Save & make an effect'),
        FM.orig ? h('button', { class: 'danger', onclick: fmDelete }, 'Delete') : null),
      h('details', { class: 'card' }, h('summary', {}, 'Reference: variables and functions'),
        h('ul', {}, ref.rules.map(t => h('li', {}, t))),
        h('h3', {}, 'Variables'), h('ul', {}, ref.variables.map(t => h('li', {}, t))),
        h('h3', {}, 'Functions'), h('ul', { class: 'fm-funcs' }, ref.functions.map(t => h('li', {}, t)))))));
  fmShowStatus();
}
