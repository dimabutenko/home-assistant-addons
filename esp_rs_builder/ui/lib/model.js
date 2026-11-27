// Pure logic: component schema -> field model, device model -> YAML, diagnostics -> field paths.
// No DOM access here, so everything is unit-testable with `node --test`.

/** Build a flat list of field descriptors from a component `config` JSON Schema. */
export function fieldsFor(config, pinRoles = {}) {
  const required = new Set(config.required || []);
  const out = [];
  for (const [key, p] of Object.entries(config.properties || {})) {
    if ('const' in p) continue; // `platform` etc. are fixed by the component, not edited
    const f = {
      key,
      title: p.title || key,
      required: required.has(key),
      default: p.default,
      description: p.description,
    };
    if (p.type === 'object') {
      Object.assign(f, { kind: 'object', children: fieldsFor(p, {}) });
    } else if (key in pinRoles) {
      Object.assign(f, { kind: 'pin', caps: pinRoles[key].caps || [] });
    } else if (p['x-ref']) {
      Object.assign(f, { kind: 'ref', target: p['x-ref'] });
    } else if (Array.isArray(p.enum)) {
      Object.assign(f, { kind: 'enum', options: p.enum });
    } else if (p.type === 'boolean') {
      f.kind = 'boolean';
    } else if (p.type === 'integer' || p.type === 'number') {
      Object.assign(f, { kind: p.type, min: p.minimum, max: p.maximum });
    } else {
      Object.assign(f, {
        kind: p['x-secret'] ? 'secret' : 'string',
        minLength: p.minLength,
        maxLength: p.maxLength,
        pattern: p.pattern,
      });
    }
    out.push(f);
  }
  return out;
}

/** Path of one instance in the YAML (`wifi`, `sensor[0]`), as the validator reports it. */
export function instancePath(comp, index) {
  return comp.singleton ? comp.yaml_key : `${comp.yaml_key}[${index}]`;
}

/** Path of a field inside an instance, e.g. `sensor[0].temperature.name`. */
export function fieldPath(base, ...keys) {
  return [base, ...keys].join('.');
}

/** Split a diagnostic path into segments: `sensor[0].i2c_id` -> ['sensor', '[0]', 'i2c_id']. */
export function pathSegments(path) {
  return path.match(/\[\d+\]|[^.[\]]+/g) || [];
}

function joinSegments(segs) {
  return segs.reduce((acc, s) => (s.startsWith('[') ? acc + s : acc ? `${acc}.${s}` : s), '');
}

/** Resolve a diagnostic path to the deepest known field path (walks up when the exact one is unknown). */
export function resolveDiagPath(path, known) {
  let segs = pathSegments(path);
  while (segs.length) {
    const candidate = joinSegments(segs);
    if (known.has(candidate)) return candidate;
    segs = segs.slice(0, -1);
  }
  return '';
}

/** Group diagnostics by the field path they belong to (`''` = the config as a whole). */
export function groupDiagnostics(diags, known) {
  const map = new Map();
  for (const d of diags) {
    const key = resolveDiagPath(d.path, known);
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(d);
  }
  return map;
}

/** A fresh instance for a component: only the fixed `platform` plus an id; other values stay unset. */
export function newInstance(comp, existingIds) {
  const cfg = {};
  const props = comp.config.properties || {};
  if (props.platform && 'const' in props.platform) cfg.platform = props.platform.const;
  if (props.id) {
    let n = 1;
    const base = comp.id.replace(/[^a-z0-9_]/g, '_');
    while (existingIds.has(`${base}${n}`)) n++;
    cfg.id = `${base}${n}`;
  }
  return cfg;
}

/** Remove unset values (`undefined`, `''`, `null`). Returns a new value. */
export function clean(value) {
  if (Array.isArray(value)) return value.map(clean);
  if (value && typeof value === 'object') {
    const out = {};
    for (const [k, v] of Object.entries(value)) {
      if (v === undefined || v === '' || v === null) continue;
      out[k] = clean(v);
    }
    return out;
  }
  return value;
}

/** Device model `{board, name, sections}` -> plain config object in the YAML layout the server expects. */
export function toConfig(model, components) {
  const cfg = { board: model.board, name: model.name };
  for (const comp of components) {
    const sec = model.sections[comp.yaml_key];
    if (sec === undefined) continue;
    if (comp.singleton) {
      cfg[comp.yaml_key] = clean(sec);
    } else if (sec.length) {
      cfg[comp.yaml_key] = sec.map(clean);
    }
  }
  return clean(cfg);
}

/** Replace every `x-secret` value of an instance with `***` (for the on-screen preview). */
export function maskSecrets(cfg, schema) {
  if (!cfg || typeof cfg !== 'object') return cfg;
  const out = {};
  for (const [k, v] of Object.entries(cfg)) {
    const p = schema?.properties?.[k];
    if (p?.['x-secret'] && typeof v === 'string') out[k] = '***';
    else if (p?.type === 'object') out[k] = maskSecrets(v, p);
    else out[k] = v;
  }
  return out;
}

/** Same as `toConfig`, with secrets masked; singleton and list sections use the right schema. */
export function toMaskedConfig(model, components) {
  const cfg = toConfig(model, components);
  for (const comp of components) {
    const sec = cfg[comp.yaml_key];
    if (sec === undefined) continue;
    cfg[comp.yaml_key] = comp.singleton
      ? maskSecrets(sec, comp.config)
      : sec.map((i) => maskSecrets(i, comp.config));
  }
  return cfg;
}

// ---- YAML emitter (block style, enough for the config layout) ----

const PLAIN = /^[A-Za-z_][A-Za-z0-9_.-]*$/;
const RESERVED = /^(true|false|yes|no|on|off|null|y|n)$/i;

function scalar(v) {
  if (typeof v === 'string') return PLAIN.test(v) && !RESERVED.test(v) ? v : JSON.stringify(v);
  return String(v);
}

export function toYaml(value, indent = 0) {
  const pad = ' '.repeat(indent);
  const lines = [];
  for (const [k, v] of Object.entries(value)) {
    if (Array.isArray(v)) {
      lines.push(`${pad}${k}:`);
      for (const item of v) {
        const sub = toYaml(item, indent + 4).split('\n');
        sub[0] = `${pad}  - ${sub[0].trimStart()}`;
        lines.push(...sub);
      }
    } else if (v && typeof v === 'object') {
      lines.push(`${pad}${k}:`, toYaml(v, indent + 2));
    } else {
      lines.push(`${pad}${k}: ${scalar(v)}`);
    }
  }
  return lines.join('\n');
}

/** GPIO numbers used by the config: every component pin role whose value is set. gpio -> field path. */
export function usedPins(model, components) {
  const used = new Map();
  for (const comp of components) {
    const sec = model.sections[comp.yaml_key];
    if (sec === undefined) continue;
    const items = comp.singleton ? [sec] : sec;
    items.forEach((cfg, i) => {
      for (const role of Object.keys(comp.pins || {})) {
        const g = cfg[role];
        if (Number.isInteger(g)) used.set(g, fieldPath(instancePath(comp, i), role));
      }
    });
  }
  return used;
}

/** Declared ids of instances of a component (for `x-ref` selects). */
export function idsOf(model, components, compId) {
  const ids = [];
  for (const comp of components.filter((c) => c.id === compId)) {
    const sec = model.sections[comp.yaml_key];
    if (!sec) continue;
    for (const cfg of comp.singleton ? [sec] : sec) if (cfg.id) ids.push(cfg.id);
  }
  return ids;
}
