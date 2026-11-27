// Channels: the Home Assistant signals that scenes read (entity, attribute, range, smoothing, event threshold, default value),
// set up once and shared by every scene that uses them. A formula input is only a name and a reference to a channel.
'use strict';

const CH = { items: [], palettes: [], paceRange: [0.6, 1.6], ha: false, loaded: false, draft: {}, focus: null, creating: false,
  merge: null, filter: '', entTimer: null, read: {} };

async function chLoad() {
  const r = await api('api/channels');
  CH.items = r.items; CH.palettes = r.palettes; CH.paceRange = r.pace_range; CH.ha = r.ha; CH.loaded = true;
  CH.draft = {};
  if (typeof FM !== 'undefined') FM.loaded = false;  // the editor of formulas reads the channels again when it is opened
}

function chOpen(id, create) {  // from the editor of a formula: show a channel (or the form of a new one)
  CH.focus = id || null; CH.creating = !!create; CH.filter = '';
  showTab('channels');
}

function chSuggest(q) {
  clearTimeout(CH.entTimer);
  CH.entTimer = setTimeout(async () => {
    if (!CH.ha || q.length < 2) return;
    try {
      const list = await api('api/ha/entities?q=' + encodeURIComponent(q));
      const dl = document.getElementById('ch-ents'); if (!dl) return;
      dl.replaceChildren(...list.map(e => h('option', { value: e.entity_id }, `${e.name || ''} · ${e.state} ${e.unit}${e.attributes.length ? ' · attrs: ' + e.attributes.join(', ') : ''}`)));
    } catch { /* ignore */ }
  }, 300);
}

function chValue(c, k) {
  const d = CH.draft[c.id];
  if (d && k in d) return d[k];
  return k === 'on_states' ? (c.on_states || []).join(', ') : c[k];
}

function chBody(c) {  // what changed, as the server wants it
  const d = CH.draft[c.id] || {}, out = {};
  for (const k of Object.keys(d)) {
    const v = d[k];
    if (['min', 'max', 'smooth', 'default', 'span', 'kick'].includes(k)) { if (v === '' || !Number.isFinite(Number(v))) continue; out[k] = Number(v); }
    else out[k] = v;
  }
  return out;
}

async function chSave(c) {
  const body = chBody(c);
  try { await send('api/channels/' + encodeURIComponent(c.id), body, 'PUT'); } catch (e) { toast('Not saved: ' + e.message, true, 9000); return; }
  await chLoad(); toast('Saved. A scene that is playing takes the change when it is started again.'); renderChannels();
}

async function chDelete(c) {
  if (!confirm(`Delete the channel "${c.name}"?`)) return;
  try { await api('api/channels/' + encodeURIComponent(c.id), { method: 'DELETE' }); } catch (e) { toast(e.message, true, 9000); return; }
  await chLoad(); renderChannels();
}

async function chReadNow(c, el) {
  try {
    const r = (await send('api/ha/read', { inputs: [{ name: c.id, channel: c.id }] }))[0];
    el.textContent = r.error ? r.error : r.raw === null ? 'no value (the default is used)' : `now ${r.raw} → ${r.value}`;
    el.className = r.error ? 'bad' : 'muted';
  } catch (e) { el.textContent = e.message; el.className = 'bad'; }
}

async function chMergePreview(c, into) {
  if (!into) { CH.merge = null; renderChannels(); return; }
  try { CH.merge = { from: c.id, into, p: await send(`api/channels/${encodeURIComponent(c.id)}/merge/preview`, { into }) }; } catch (e) { toast(e.message, true, 9000); return; }
  renderChannels();
}

async function chMerge(c) {
  const m = CH.merge; if (!m) return;
  if (!confirm(`Merge "${m.p.from.name}" into "${m.p.into.name}"? ${m.p.scenes.length} scene(s) and ${m.p.effects.length} effect(s) will read "${m.p.into.name}"; "${m.p.from.name}" is deleted.`)) return;
  try { await send(`api/channels/${encodeURIComponent(c.id)}/merge`, { into: m.into }); } catch (e) { toast('Not merged: ' + e.message, true, 9000); return; }
  CH.merge = null; await chLoad(); toast('Merged.'); renderChannels();
}

async function chCreate(body) {
  try { const c = await send('api/channels', body); CH.creating = false; CH.focus = c.id; await chLoad(); toast('Channel made.'); renderChannels(); } catch (e) { toast(e.message, true, 9000); }
}

function chField(c, k, label, props = {}) {  // one input bound to the draft of a channel
  const set = e => {
    const d = CH.draft[c.id] || (CH.draft[c.id] = {});
    d[k] = props.type === 'checkbox' ? e.target.checked : e.target.value;
    if (c.id) { const card = document.getElementById('ch-' + c.id); if (card) card.classList.add('dirty'); const b = document.getElementById('chs-' + c.id); if (b) b.disabled = false; }
  };
  const cur = chValue(c, k);
  const el = props.type === 'checkbox' ? h('input', { type: 'checkbox', checked: !!cur, onchange: set })
    : h('input', { type: props.type || 'text', step: 'any', value: cur === undefined || cur === null ? '' : cur, list: props.list, title: props.title, oninput: e => { set(e); if (props.suggest) chSuggest(e.target.value); } });
  return h('label', { class: props.wide ? 'wide' : '', title: props.title }, label, el);
}

function chCard(c) {
  const dirty = !!(CH.draft[c.id] && Object.keys(CH.draft[c.id]).length);
  const now = h('span', { class: 'muted' }, '');
  const others = CH.items.filter(x => (x.kind || 'value') === 'value' && x.id !== c.id);
  const m = CH.merge && CH.merge.from === c.id ? CH.merge : null;
  return h('div', { class: 'card ch-card' + (dirty ? ' dirty' : ''), id: 'ch-' + c.id },
    h('div', { class: 'row', style: 'margin-bottom:6px' },
      h('input', { type: 'text', value: chValue(c, 'name'), maxlength: 48, size: 28, title: 'the name of the channel (you can rename it)', oninput: e => { (CH.draft[c.id] || (CH.draft[c.id] = {})).name = e.target.value; const b = document.getElementById('chs-' + c.id); if (b) b.disabled = false; } }),
      c.personal ? h('span', { class: 'badge', title: 'only one scene uses this channel' }, 'personal') : null,
      h('span', { class: c.count ? 'muted' : 'warn' }, c.count ? `used in ${c.count} scene${c.count === 1 ? '' : 's'} and effects` : 'not used')),
    h('div', { class: 'ch-grid' },
      chField(c, 'entity', 'entity', { wide: true, list: 'ch-ents', suggest: true, title: 'sensor.power_total; empty = not bound (the default value is used)' }),
      chField(c, 'attribute', 'attribute', { wide: true, title: 'optional, e.g. elevation of sun.sun' }),
      chField(c, 'min', '→ 0', { type: 'number', title: 'the value that maps to 0' }), chField(c, 'max', '→ 1', { type: 'number', title: 'the value that maps to 1' }),
      chField(c, 'smooth', 'smooth s', { type: 'number', title: 'smoothing in seconds (0.3 to 0.5 for fast signals)' }),
      chField(c, 'kick', 'event', { type: 'number', title: 'event threshold: a jump of this share of the 0..1 range fires <name>_kick / _count' }),
      chField(c, 'default', 'default', { type: 'number', title: 'value 0..1 used when the channel is not bound, its entity is not available, or a scene is stored on the garland' }),
      chField(c, 'auto', 'auto range', { type: 'checkbox', title: 'the last 30 minutes of the sensor are mapped to 0..1 (the "→ 0" / "→ 1" values are only the starting guess)' })),
    h('details', { style: 'margin-top:6px' }, h('summary', { class: 'muted' }, 'more'),
      h('div', { class: 'ch-grid', style: 'margin-top:6px' },
        chField(c, 'span', 'min span', { type: 'number', title: 'smallest width of the auto range, in the units of the sensor (0 = a twentieth of the range)' }),
        chField(c, 'on_states', 'states that count as 1', { wide: true, title: 'for non-numeric states: states that count as 1, comma separated' }))),
    c.used_by.length ? h('details', { style: 'margin-top:6px' }, h('summary', { class: 'muted' }, 'who uses it'),
      h('ul', {}, c.used_by.map(u => h('li', {}, `${u.type === 'scene' ? 'scene' : 'effect'}: ${u.name}`)))) : null,
    h('div', { class: 'row', style: 'margin-top:8px' },
      h('button', { class: 'primary', id: 'chs-' + c.id, disabled: !dirty, onclick: () => chSave(c) }, 'Save'),
      h('button', { onclick: () => chReadNow(c, now), disabled: !CH.ha || !c.entity }, 'Read now'), now,
      h('select', { title: 'merge this channel into another one: the scenes that read it will read the other', onchange: e => chMergePreview(c, e.target.value) },
        h('option', { value: '' }, 'Merge into...'), others.map(o => h('option', { value: o.id, selected: m && m.into === o.id }, o.name))),
      h('button', { class: 'danger', disabled: c.count > 0, title: c.count ? 'in use: merge it into another channel or remove it from the scenes first' : '', onclick: () => chDelete(c) }, 'Delete')),
    m ? chMergeBox(c, m) : null);
}

function chMergeBox(c, m) {
  const p = m.p, fmt = v => Array.isArray(v) ? v.join(', ') : String(v);
  return h('div', { class: 'ch-merge' },
    h('b', {}, `Merge "${p.from.name}" into "${p.into.name}"`),
    p.identical ? h('div', { class: 'ok' }, 'The two channels have the same settings: nothing changes in how the scenes look.')
      : h('div', {}, h('div', { class: 'warn' }, 'The settings differ: the scenes that read the first channel will take the settings of the second.'),
        h('table', {}, h('tr', {}, h('th', {}, 'setting'), h('th', {}, p.from.name), h('th', {}, p.into.name)),
          p.diff.map(d => h('tr', {}, h('td', {}, d.field), h('td', {}, fmt(d.from)), h('td', {}, fmt(d.into)))))),
    h('div', { class: 'muted', style: 'margin-top:4px' }, p.scenes.length || p.effects.length ? 'This changes: ' + [...p.scenes.map(n => `scene ${n}`), ...p.effects.map(n => `effect ${n}`)].join(', ') : 'No scene uses it.'),
    h('div', { class: 'row', style: 'margin-top:6px' }, h('button', { class: 'primary', onclick: () => chMerge(c) }, 'Merge'), h('button', { onclick: () => { CH.merge = null; renderChannels(); } }, 'Cancel')));
}

function chSystemCard(c) {
  const isPace = c.kind === 'pace', d = CH.draft[c.id] || (CH.draft[c.id] = {});
  const src = d.source || c.source;
  const set = (k, v) => { d[k] = v; renderChannelsKeep(); };
  const fixed = d.fixed !== undefined ? d.fixed : c.fixed;
  return h('div', { class: 'card ch-card' }, h('div', { class: 'row', style: 'margin-bottom:6px' }, h('b', {}, c.name),
    h('span', { class: 'muted' }, isPace ? 'the speed multiplier of the scenes of a live round (0.6 to 1.6)' : 'the palette of the scenes of a live round (palette("theme", v))')),
    h('div', { class: 'ch-grid' },
      h('label', { class: 'wide', title: 'random: live:random picks one for every round, as before. fixed: always this one. Home Assistant: the value of an entity, read when a scene starts.' }, 'source',
        h('select', { onchange: e => set('source', e.target.value) }, [['random', 'random (every round)'], ['fixed', 'fixed'], ['ha', 'Home Assistant']].map(([v, t]) => h('option', { value: v, selected: v === src }, t)))),
      src !== 'random' ? (isPace
        ? h('label', {}, src === 'ha' ? 'when not available' : 'pace', h('input', { type: 'number', step: 0.05, min: CH.paceRange[0], max: CH.paceRange[1], value: fixed, oninput: e => { d.fixed = e.target.value; } }))
        : h('label', { class: 'wide' }, src === 'ha' ? 'when not available' : 'palette', h('select', { onchange: e => { d.fixed = e.target.value; } }, CH.palettes.map(n => h('option', { value: n, selected: n === fixed }, n))))) : null,
      src === 'ha' ? [
        h('label', { class: 'wide' }, 'entity', h('input', { type: 'text', list: 'ch-ents', value: d.entity !== undefined ? d.entity : c.entity, oninput: e => { d.entity = e.target.value; chSuggest(e.target.value); } })),
        h('label', { class: 'wide' }, 'attribute', h('input', { type: 'text', value: d.attribute !== undefined ? d.attribute : c.attribute, oninput: e => { d.attribute = e.target.value; } })),
        h('label', {}, '→ ' + (isPace ? '0.6' : 'first palette'), h('input', { type: 'number', step: 'any', value: d.min !== undefined ? d.min : c.min, oninput: e => { d.min = e.target.value; } })),
        h('label', {}, '→ ' + (isPace ? '1.6' : 'last palette'), h('input', { type: 'number', step: 'any', value: d.max !== undefined ? d.max : c.max, oninput: e => { d.max = e.target.value; } }))] : null),
    h('div', { class: 'row', style: 'margin-top:8px' }, h('button', { class: 'primary', onclick: async () => {
      const body = { ...d }; for (const k of ['min', 'max', 'fixed']) if (k in body && (k !== 'fixed' || isPace)) body[k] = Number(body[k]);
      try { await send('api/channels/' + c.id, body, 'PUT'); } catch (e) { toast('Not saved: ' + e.message, true, 9000); return; }
      await chLoad(); toast('Saved. It is used the next time a scene is started.'); renderChannels();
    } }, 'Save')));
}

function renderChannelsKeep() { renderChannels(true); }

function chNewForm() {
  const c = { id: '', name: '', entity: '', attribute: '', min: 0, max: 100, smooth: 0.4, default: 0.5, auto: true, span: 0, kick: 0.12, on_states: [] };
  CH.draft[''] = CH.draft[''] || {};
  return h('div', { class: 'card ch-card dirty' }, h('h3', {}, 'New channel'),
    h('div', { class: 'ch-grid' }, chField(c, 'name', 'name (empty = made from the entity)', { wide: true }), chField(c, 'entity', 'entity', { wide: true, list: 'ch-ents', suggest: true }), chField(c, 'attribute', 'attribute', { wide: true }),
      chField(c, 'min', '→ 0', { type: 'number' }), chField(c, 'max', '→ 1', { type: 'number' }), chField(c, 'smooth', 'smooth s', { type: 'number' }), chField(c, 'kick', 'event', { type: 'number' }),
      chField(c, 'default', 'default', { type: 'number' }), chField(c, 'auto', 'auto range', { type: 'checkbox' })),
    h('div', { class: 'row', style: 'margin-top:8px' },
      h('button', { class: 'primary', onclick: () => { const body = { ...{ min: 0, max: 100, smooth: 0.4, default: 0.5, auto: true, kick: 0.12 }, ...chBody(c) }; if (!body.name) delete body.name; chCreate(body); } }, 'Make'),
      h('button', { onclick: () => { CH.creating = false; CH.draft[''] = {}; renderChannels(); } }, 'Cancel')));
}

function renderChannels(keepScroll) {
  const root = document.getElementById('view-channels');
  const y = window.scrollY;
  root.replaceChildren();
  if (!CH.loaded) { root.textContent = 'Loading...'; chLoad().then(() => renderChannels()).catch(e => root.textContent = 'Failed to load: ' + e.message); return; }
  const sys = CH.items.filter(c => (c.kind || 'value') !== 'value'), vals = CH.items.filter(c => (c.kind || 'value') === 'value');
  const q = CH.filter.trim().toLowerCase();
  const shown = vals.filter(c => !q || c.name.toLowerCase().includes(q) || (c.entity || '').toLowerCase().includes(q) || (c.attribute || '').toLowerCase().includes(q));
  root.append(h('div', { class: 'card', style: 'margin-bottom:12px' },
    h('h2', {}, 'Channels'),
    h('div', { class: 'muted', style: 'margin-bottom:8px' }, 'A channel is a signal from Home Assistant (an entity and optionally an attribute) with the range that becomes 0..1, the smoothing, the event threshold and a default value. A formula input is a name and a channel, so a signal is set up once and shared by every scene that uses it: change it here and every scene that reads it follows. A channel that is not bound or whose entity is not available gives its default value. A channel marked "personal" is needed by one scene only.'),
    CH.ha ? null : h('div', { class: 'warn', style: 'margin-bottom:8px' }, 'Home Assistant data is not available here: entities cannot be searched and values cannot be read.'),
    h('div', { class: 'row' },
      h('input', { type: 'search', placeholder: 'filter by name or entity', value: CH.filter, oninput: e => { CH.filter = e.target.value; clearTimeout(CH.ft); CH.ft = setTimeout(() => renderChannels(true), 250); } }),
      h('button', { onclick: () => { CH.creating = true; renderChannels(); } }, '+ New channel'),
      h('span', { class: 'muted' }, `${vals.length} channels`)),
    h('datalist', { id: 'ch-ents' })));
  if (CH.creating) root.append(chNewForm());
  root.append(h('h3', {}, 'Theme of a live round'), ...sys.map(chSystemCard), h('h3', {}, 'Signals'),
    shown.length ? shown.map(chCard) : h('div', { class: 'card muted' }, vals.length ? 'No channel matches the filter.' : 'No channels yet: they are made when you take an example on the Formulas tab, or with "+ New channel".'));
  if (CH.focus) { const el = document.getElementById('ch-' + CH.focus); if (el) { el.scrollIntoView({ block: 'center' }); el.style.outline = '2px solid var(--acc)'; } CH.focus = null; }
  else if (keepScroll) window.scrollTo(0, y);
}
