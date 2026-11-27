//! Typed IR between validation and codegen.

use serde_json::Value;

use crate::error::Report;
use crate::schema::Registry;
use crate::validate::{collect_instances, parse_yaml, validate};

/// A validated device: the board plus every declared component in stable order
/// (yaml key alphabetically, then declaration order).
#[derive(Debug, Clone, PartialEq)]
pub struct DeviceModel {
    pub board: String,
    pub name: String,
    pub components: Vec<ComponentModel>,
}

/// One declared component occurrence.
#[derive(Debug, Clone, PartialEq)]
pub struct ComponentModel {
    /// Component schema id (`bme280`, `wifi`, ...).
    pub component: String,
    /// YAML path of the entry (`sensor[0]`, `wifi`).
    pub path: String,
    /// The entry exactly as written in the YAML (defaults are applied by codegen from the schema).
    pub config: Value,
}

/// Parse and validate YAML text; returns the model only when there are no validation errors.
/// Warnings are not part of the result; call [`crate::validate_str`] to see them.
pub fn load_and_validate(reg: &Registry, text: &str) -> Result<DeviceModel, Report> {
    let root = match parse_yaml(text) {
        Ok(v) => v,
        Err(e) => {
            let mut report = Report::default();
            report.error("", e.to_string());
            return Err(report);
        }
    };
    let report = validate(reg, &root);
    if report.has_errors() {
        return Err(report);
    }
    let mut scratch = Report::default();
    let map = root.as_object().cloned().unwrap_or_default();
    let components = collect_instances(reg, &map, &mut scratch)
        .into_iter()
        .map(|i| ComponentModel {
            component: i.comp.id.clone(),
            path: i.path,
            config: i.cfg.clone(),
        })
        .collect();
    let text_of = |key: &str| map.get(key).and_then(Value::as_str).unwrap_or_default().to_owned();
    Ok(DeviceModel {
        board: text_of("board"),
        name: text_of("name"),
        components,
    })
}
