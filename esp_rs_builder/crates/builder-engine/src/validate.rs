//! Device-config validation: JSON Schema, board/pin rules, pin conflicts, references.

use std::collections::{BTreeMap, BTreeSet};

use jsonschema::Validator;
use serde_json::Value;

use crate::error::{EngineError, Report};
use crate::schema::{Board, Component, Registry};

/// One declared component occurrence in the YAML.
pub(crate) struct Instance<'a> {
    pub(crate) path: String,
    pub(crate) comp: &'a Component,
    pub(crate) cfg: &'a Value,
}

/// Parse YAML text into a JSON-shaped value.
pub fn parse_yaml(text: &str) -> Result<Value, EngineError> {
    serde_yaml::from_str::<Value>(text).map_err(|e| EngineError::Yaml(e.to_string()))
}

/// Parse and validate YAML text. Only an unparsable document is an `Err`;
/// everything else is reported through the returned [`Report`].
pub fn validate_str(reg: &Registry, text: &str) -> Result<Report, EngineError> {
    let root = parse_yaml(text)?;
    Ok(validate(reg, &root))
}

pub fn validate(reg: &Registry, root: &Value) -> Report {
    let mut report = Report::default();
    let Some(map) = root.as_object() else {
        report.error("", "config must be a YAML mapping");
        return report;
    };

    // Top-level keys.
    let known_keys = reg.yaml_keys();
    for key in map.keys() {
        if key != "board" && key != "name" && !known_keys.contains(&key.as_str()) {
            report.error(key.as_str(), format!("unknown top-level key `{key}`"));
        }
    }
    match map.get("name") {
        Some(Value::String(s)) if !s.is_empty() => {}
        Some(_) => report.error("name", "`name` must be a non-empty string"),
        None => report.error("name", "missing required key `name`"),
    }
    let board = match map.get("board") {
        Some(Value::String(id)) => match reg.boards.get(id) {
            Some(b) => Some(b),
            None => {
                let known: Vec<&str> = reg.boards.keys().map(String::as_str).collect();
                report.error("board", format!("unknown board `{id}` (known: {})", known.join(", ")));
                None
            }
        },
        Some(_) => {
            report.error("board", "`board` must be a string");
            None
        }
        None => {
            report.error("board", "missing required key `board`");
            None
        }
    };

    let instances = collect_instances(reg, map, &mut report);
    check_schemas(&instances, &mut report);
    if let Some(board) = board {
        check_pins(board, &instances, &mut report);
        if !board.wifi {
            for inst in instances.iter().filter(|i| i.comp.kind == "network" && i.comp.id == "wifi") {
                report.error(&inst.path, format!("board `{}` has no Wi-Fi", board.id));
            }
        }
    }
    check_references(&instances, &mut report);
    report
}

pub(crate) fn collect_instances<'a>(
    reg: &'a Registry,
    map: &'a serde_json::Map<String, Value>,
    report: &mut Report,
) -> Vec<Instance<'a>> {
    let mut out = Vec::new();
    for key in reg.yaml_keys() {
        let Some(section) = map.get(key) else { continue };
        let any_singleton = reg.components.values().any(|c| c.yaml_key == key && c.singleton);
        let items: Vec<(String, &Value)> = if any_singleton {
            vec![(key.to_owned(), section)]
        } else if let Some(list) = section.as_array() {
            list.iter().enumerate().map(|(i, v)| (format!("{key}[{i}]"), v)).collect()
        } else {
            report.error(key, format!("`{key}` must be a list of entries"));
            continue;
        };
        for (path, cfg) in items {
            let Some(obj) = cfg.as_object() else {
                report.error(&path, "entry must be a mapping");
                continue;
            };
            let platform = match obj.get("platform") {
                Some(Value::String(p)) => Some(p.as_str()),
                Some(_) => {
                    report.error(format!("{path}.platform"), "`platform` must be a string");
                    continue;
                }
                None => None,
            };
            match reg.find_component(key, platform) {
                Some(comp) => out.push(Instance { path, comp, cfg }),
                None => match platform {
                    Some(p) => report.error(format!("{path}.platform"), format!("unknown platform `{p}` for `{key}`")),
                    None => report.error(&path, format!("missing `platform` for `{key}`")),
                },
            }
        }
    }
    out
}

fn check_schemas(instances: &[Instance<'_>], report: &mut Report) {
    let mut cache: BTreeMap<&str, Option<Validator>> = BTreeMap::new();
    for inst in instances {
        let validator = cache
            .entry(inst.comp.id.as_str())
            .or_insert_with(|| jsonschema::validator_for(&inst.comp.config).ok());
        let Some(validator) = validator else {
            report.error(&inst.path, format!("schema of component `{}` is not a valid JSON Schema", inst.comp.id));
            continue;
        };
        for err in validator.iter_errors(inst.cfg) {
            let path = join_pointer(&inst.path, &err.instance_path().to_string());
            report.error(path, err.to_string());
        }
    }
}

fn check_pins(board: &Board, instances: &[Instance<'_>], report: &mut Report) {
    let mut used: BTreeMap<u32, String> = BTreeMap::new();
    for inst in instances {
        for (role, spec) in &inst.comp.pins {
            let Some(raw) = inst.cfg.get(role) else { continue };
            let path = format!("{}.{role}", inst.path);
            let Some(gpio) = raw.as_u64().and_then(|n| u32::try_from(n).ok()) else {
                continue; // type problem is already reported by the JSON Schema check
            };
            let Some(pin) = board.pin(gpio) else {
                report.error(&path, format!("GPIO{gpio} does not exist on board `{}`", board.id));
                continue;
            };
            for cap in &spec.caps {
                if !pin.caps.contains(cap) {
                    report.error(&path, format!("GPIO{gpio} lacks capability `{cap}` required by `{role}`"));
                }
            }
            for flag in pin.flags.iter().filter(|f| !spec.allow_flags.contains(f)) {
                match flag.as_str() {
                    "strapping" => report.warn(&path, format!("GPIO{gpio} is a strapping pin; it may affect boot")),
                    "uart0_console" => {
                        report.warn(&path, format!("GPIO{gpio} is used by the UART0 console / logging"))
                    }
                    "usb" | "flash" | "reserved" => {
                        report.error(&path, format!("GPIO{gpio} is not usable: flagged `{flag}` on `{}`", board.id))
                    }
                    other => report.warn(&path, format!("GPIO{gpio} has flag `{other}`")),
                }
            }
            match used.get(&gpio) {
                Some(first) => report.error(&path, format!("GPIO{gpio} is already used by `{first}`")),
                None => {
                    used.insert(gpio, path);
                }
            }
        }
    }
}

fn check_references(instances: &[Instance<'_>], report: &mut Report) {
    // Declared ids per component id; duplicate ids are an error.
    let mut ids: BTreeMap<&str, (&str, &str)> = BTreeMap::new(); // id -> (component id, path)
    for inst in instances {
        if let Some(id) = inst.cfg.get("id").and_then(Value::as_str) {
            if let Some((_, first)) = ids.get(id) {
                report.error(format!("{}.id", inst.path), format!("duplicate id `{id}` (first used at `{first}`)"));
            } else {
                ids.insert(id, (inst.comp.id.as_str(), inst.path.as_str()));
            }
        }
    }
    for inst in instances {
        for (prop, target) in inst.comp.refs() {
            let Some(val) = inst.cfg.get(&prop).and_then(Value::as_str) else { continue };
            let path = format!("{}.{prop}", inst.path);
            match ids.get(val) {
                None => report.error(path, format!("unknown {target} id `{val}`")),
                Some((comp, _)) if *comp != target => {
                    report.error(path, format!("`{val}` is a `{comp}`, expected `{target}`"))
                }
                Some(_) => {}
            }
        }
    }
    let present: BTreeSet<&str> = instances.iter().map(|i| i.comp.id.as_str()).collect();
    for inst in instances {
        for req in &inst.comp.requires {
            if !present.contains(req.as_str()) {
                report.error(&inst.path, format!("`{}` requires a `{req}` to be configured", inst.comp.id));
            }
        }
    }
}

/// Turn a base path plus a JSON pointer (`/temperature/name`, `/0/x`) into `base.temperature.name`.
fn join_pointer(base: &str, pointer: &str) -> String {
    let mut out = base.to_owned();
    for seg in pointer.split('/').filter(|s| !s.is_empty()) {
        let seg = seg.replace("~1", "/").replace("~0", "~");
        if seg.chars().all(|c| c.is_ascii_digit()) {
            out.push_str(&format!("[{seg}]"));
        } else {
            out.push('.');
            out.push_str(&seg);
        }
    }
    out
}
