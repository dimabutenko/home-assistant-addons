// ESP RS Builder UI. Everything is rendered from the board / component schemas served by the
// builder-server; nothing here knows a specific component or board. State lives in memory only.
import { firmwareUrl, followJob, loadSchemas, startBuild, validate } from './lib/api.js';
import { flashImage, serialSupported } from './lib/flash.js';
import {
  fieldPath, fieldsFor, groupDiagnostics, idsOf, instancePath, newInstance, toConfig, toMaskedConfig, toYaml, usedPins,
} from './lib/model.js';
import { pinoutSvg } from './lib/pinout.js';

const $ = (id) => document.getElementById(id);
const LOG_MAX = 2000;

const state = {
  boards: [],
  components: [],
  model: { board: '', name: 'my-device', sections: {} },
  diags: [],
  activePin: null, // {path, caps} of the focused pin field
  jobId: null,
  busy: false,
};
let knownPaths = new Set();

const board = () => state.boards.find((b) => b.id === state.model.board);
const yamlText = () => `${toYaml(toConfig(state.model, state.components))}\n`;

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== false) e.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids) e.append(kid);
  return e;
}

// ---------- form rendering ----------

function setValue(obj, key, value) {
  if (value === undefined || value === '') delete obj[key];
  else obj[key] = value;
}

function renderField(f, obj, path, comp) {
  const wrap = el('div', { class: 'field', 'data-path': path });
  const label = el('label', {}, el('span', { class: f.required ? 'req' : '' }, f.title));
  const changed = () => update();
  let input;
  const def = f.default !== undefined ? `default: ${f.default}` : '';

  switch (f.kind) {
    case 'object': {
      const sub = el('div', { class: 'sub' });
      const draw = () => {
        sub.replaceChildren();
        if (obj[f.key]) for (const c of f.children) sub.append(renderField(c, obj[f.key], fieldPath(path, c.key), comp));
      };
      if (f.required) {
        obj[f.key] ??= {};
        wrap.append(el('strong', {}, f.title));
      } else {
        const cb = el('input', {
          type: 'checkbox',
          onchange: () => {
            if (cb.checked) obj[f.key] = {};
            else delete obj[f.key];
            draw();
            update();
          },
        });
        cb.checked = Boolean(obj[f.key]);
        wrap.append(el('label', {}, el('span', {}, `${f.title} `), cb));
      }
      draw();
      wrap.append(sub);
      return wrap;
    }
    case 'boolean':
      input = el('input', { type: 'checkbox', onchange: () => { obj[f.key] = input.checked; changed(); } });
      input.checked = obj[f.key] ?? f.default ?? false;
      break;
    case 'enum': {
      input = el('select', {
        onchange: () => {
          setValue(obj, f.key, input.value === '' ? undefined : JSON.parse(input.value));
          changed();
        },
      });
      input.append(el('option', { value: '' }, f.default !== undefined ? `(${def})` : '(not set)'));
      for (const o of f.options) {
        const opt = el('option', { value: JSON.stringify(o) }, String(o));
        if (obj[f.key] === o) opt.selected = true;
        input.append(opt);
      }
      break;
    }
    case 'ref':
      input = el('select', { 'data-ref': f.target, onchange: () => { setValue(obj, f.key, input.value); changed(); } });
      fillRefOptions(input, f.target, obj[f.key]);
      break;
    case 'integer':
    case 'number':
    case 'pin':
      input = el('input', {
        type: 'number', min: f.min, max: f.max, step: f.kind === 'number' ? 'any' : '1',
        placeholder: def, 'data-pin': f.kind === 'pin' ? '1' : undefined,
        oninput: () => { setValue(obj, f.key, input.value === '' ? undefined : Number(input.value)); changed(); },
      });
      if (f.kind === 'pin') {
        input.addEventListener('focus', () => { state.activePin = { path, caps: f.caps }; drawPinout(); });
      }
      if (obj[f.key] !== undefined) input.value = obj[f.key];
      break;
    default: // string, secret
      input = el('input', {
        type: f.kind === 'secret' ? 'password' : 'text', placeholder: def, autocomplete: 'off',
        minlength: f.minLength, maxlength: f.maxLength, pattern: f.pattern,
        oninput: () => { setValue(obj, f.key, input.value); changed(); },
      });
      input.value = obj[f.key] ?? '';
      if (f.key === 'id') input.addEventListener('change', refreshRefs);
  }
  label.append(input);
  wrap.append(label, el('div', { class: 'msgs' }));
  return wrap;
}

function fillRefOptions(select, target, current) {
  select.replaceChildren(el('option', { value: '' }, '(not set)'));
  for (const id of idsOf(state.model, state.components, target)) {
    const opt = el('option', { value: id }, id);
    if (id === current) opt.selected = true;
    select.append(opt);
  }
}

function refreshRefs() {
  for (const sel of document.querySelectorAll('select[data-ref]')) fillRefOptions(sel, sel.dataset.ref, sel.value);
  update();
}

function renderCards() {
  const cards = $('cards');
  cards.replaceChildren();
  state.activePin = null;
  knownPaths = new Set(['board', 'name']);
  for (const comp of state.components) {
    const sec = state.model.sections[comp.yaml_key];
    if (sec === undefined) continue;
    const items = comp.singleton ? [sec] : sec;
    items.forEach((cfg, i) => {
      const base = instancePath(comp, i);
      knownPaths.add(base);
      const fields = fieldsFor(comp.config, comp.pins);
      const registerPaths = (list, prefix) => {
        for (const f of list) {
          const p = fieldPath(prefix, f.key);
          knownPaths.add(p);
          if (f.children) registerPaths(f.children, p);
        }
      };
      registerPaths(fields, base);
      knownPaths.add(`${base}.platform`);
      const card = el('div', { class: 'card', 'data-path': base });
      card.append(
        el('div', { class: 'card-head' },
          el('h3', {}, comp.title || comp.id),
          el('button', { type: 'button', class: 'link', onclick: () => removeInstance(comp, i) }, 'Remove')),
        el('div', { class: 'msgs' }));
      for (const f of fields) card.append(renderField(f, cfg, fieldPath(base, f.key), comp));
      cards.append(card);
    });
  }
}

function removeInstance(comp, index) {
  if (comp.singleton) delete state.model.sections[comp.yaml_key];
  else state.model.sections[comp.yaml_key].splice(index, 1);
  renderCards();
  fillAddMenu();
  update();
}

function fillAddMenu() {
  const sel = $('add');
  sel.replaceChildren();
  for (const comp of state.components) {
    if (comp.singleton && state.model.sections[comp.yaml_key] !== undefined) continue;
    sel.append(el('option', { value: comp.id }, comp.title || comp.id));
  }
  $('add-btn').disabled = sel.options.length === 0;
}

function addComponent() {
  const comp = state.components.find((c) => c.id === $('add').value);
  if (!comp) return;
  const ids = new Set(state.components.flatMap((c) => idsOf(state.model, state.components, c.id)));
  const cfg = newInstance(comp, ids);
  if (comp.singleton) state.model.sections[comp.yaml_key] = cfg;
  else (state.model.sections[comp.yaml_key] ??= []).push(cfg);
  renderCards();
  fillAddMenu();
  update();
}

// ---------- pinout ----------

function drawPinout() {
  const b = board();
  const host = $('pinout');
  if (!b) {
    host.textContent = '';
    return;
  }
  host.innerHTML = pinoutSvg(b, usedPins(state.model, state.components), state.activePin?.caps || []);
}

$('pinout').addEventListener('click', (ev) => {
  const g = ev.target.closest('.pin');
  if (!g || !state.activePin) return;
  const input = document.querySelector(`[data-path="${CSS.escape(state.activePin.path)}"] input`);
  if (!input) return;
  input.value = g.dataset.gpio;
  input.dispatchEvent(new Event('input', { bubbles: true }));
});

// ---------- diagnostics ----------

function showDiagnostics() {
  for (const m of document.querySelectorAll('.msgs')) m.replaceChildren();
  for (const f of document.querySelectorAll('.field.invalid')) f.classList.remove('invalid');
  const groups = groupDiagnostics(state.diags, knownPaths);
  for (const [path, list] of groups) {
    const target = path ? document.querySelector(`[data-path="${CSS.escape(path)}"]`) : null;
    const box = target?.querySelector(':scope > .msgs, :scope > label > .msgs, :scope > .card-head ~ .msgs');
    if (!target) continue;
    if (list.some((d) => d.severity === 'error')) target.classList.add('invalid');
    for (const d of list) (box ?? target).append(el('p', { class: `msg ${d.severity}` }, d.message));
  }
  const ul = $('diags');
  ul.replaceChildren();
  if (!state.diags.length) ul.append(el('li', {}, 'No problems found.'));
  for (const d of state.diags) {
    ul.append(el('li', { class: d.severity }, d.message, d.path ? el('code', {}, ` (${d.path})`) : ''));
  }
  $('build').disabled = state.busy || state.diags.some((d) => d.severity === 'error');
}

// ---------- update loop ----------

let timer = 0;
let ctl = null;
function update() {
  $('yaml').textContent = `${toYaml(toMaskedConfig(state.model, state.components))}\n`;
  drawPinout();
  clearTimeout(timer);
  timer = setTimeout(runValidate, 400);
}

async function runValidate() {
  ctl?.abort();
  ctl = new AbortController();
  try {
    state.diags = await validate(yamlText(), ctl.signal);
  } catch (e) {
    if (e.name === 'AbortError') return;
    state.diags = [{ severity: 'error', path: '', message: `Validation request failed: ${e.message}` }];
  }
  showDiagnostics();
}

// ---------- build & flash ----------

const logLines = [];
let logQueued = false;
function pushLog(line) {
  logLines.push(line);
  if (logLines.length > LOG_MAX) logLines.splice(0, logLines.length - LOG_MAX);
  if (!logQueued) {
    logQueued = true;
    requestAnimationFrame(() => {
      logQueued = false;
      const pre = $('log');
      const atEnd = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 8;
      pre.textContent = logLines.join('\n');
      if (atEnd) pre.scrollTop = pre.scrollHeight;
    });
  }
}

function setStatus(text, cls = '') {
  const s = $('status');
  s.textContent = text;
  s.className = cls;
}

async function build() {
  state.busy = true;
  $('build').disabled = true;
  $('flash').disabled = true;
  $('download').hidden = true;
  logLines.length = 0;
  $('log').textContent = '';
  setStatus('Starting build...');
  try {
    const res = await startBuild(yamlText());
    if (res.status === 409) return setStatus('Another build is already running; try again when it has finished.', 'bad');
    if (res.status === 422) {
      state.diags = res.body;
      showDiagnostics();
      return setStatus('The configuration has errors; fix them first.', 'bad');
    }
    if (res.status !== 202) return setStatus(`Build request failed (HTTP ${res.status}).`, 'bad');
    state.jobId = res.body.id;
    const final = await followJob(state.jobId, { onLine: pushLog, onStatus: (s) => setStatus(`Build ${s}...`) });
    if (final === 'succeeded') {
      setStatus('Build succeeded.', 'ok');
      $('download').href = firmwareUrl(state.jobId);
      $('download').hidden = false;
      $('flash').disabled = false;
    } else {
      setStatus('Build failed; see the log.', 'bad');
    }
  } catch (e) {
    setStatus(`Build request failed: ${e.message}`, 'bad');
  } finally {
    state.busy = false;
    showDiagnostics();
  }
}

async function flash() {
  const bar = $('progress');
  $('flash').disabled = true;
  bar.hidden = false;
  bar.value = 0;
  try {
    const res = await fetch(firmwareUrl(state.jobId));
    if (!res.ok) throw new Error(`cannot download the image (HTTP ${res.status})`);
    const bytes = new Uint8Array(await res.arrayBuffer());
    setStatus('Flashing... pick the serial port of the board.');
    await flashImage(bytes, { log: pushLog, progress: (p) => { bar.value = p; } });
    setStatus('Flashed. The device restarted.', 'ok');
  } catch (e) {
    setStatus(`Flashing failed: ${e.message}`, 'bad');
    pushLog(`flash error: ${e.message}`);
  } finally {
    $('flash').disabled = false;
    bar.hidden = true;
  }
}

// ---------- start ----------

async function init() {
  $('add-btn').addEventListener('click', addComponent);
  $('build').addEventListener('click', build);
  $('flash').addEventListener('click', flash);
  $('name').addEventListener('input', () => { state.model.name = $('name').value; update(); });
  $('board').addEventListener('change', () => { state.model.board = $('board').value; update(); });
  if (!serialSupported()) {
    $('flash').title = 'Web Serial needs Chrome or Edge (over HTTPS or localhost); use "Download .bin" instead.';
  }
  try {
    const { boards, components } = await loadSchemas();
    state.boards = boards;
    state.components = components;
  } catch (e) {
    setStatus(`Cannot reach the builder: ${e.message}`, 'bad');
    return;
  }
  for (const b of state.boards) $('board').append(el('option', { value: b.id }, b.chip));
  state.model.board = state.boards[0]?.id ?? '';
  $('board').value = state.model.board;
  state.model.name = $('name').value;
  $('name').closest('label').dataset.path = 'name';
  $('board').closest('label').dataset.path = 'board';
  fillAddMenu();
  renderCards();
  update();
}

init();
