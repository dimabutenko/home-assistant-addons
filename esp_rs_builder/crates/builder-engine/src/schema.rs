//! Typed loading of `schemas/boards/*.json` and `schemas/components/*.json`.

use std::collections::BTreeMap;
use std::path::Path;

use serde::Deserialize;
use serde_json::Value;

use crate::error::EngineError;

#[derive(Debug, Clone, Deserialize)]
pub struct Board {
    pub id: String,
    pub chip: String,
    pub target: String,
    pub feature: String,
    #[serde(default)]
    pub wifi: bool,
    pub pins: Vec<Pin>,
    /// The schema file exactly as written (served to the UI, which needs fields such as pin coordinates).
    #[serde(skip)]
    pub raw: Value,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Pin {
    pub gpio: u32,
    #[serde(default)]
    pub caps: Vec<String>,
    #[serde(default)]
    pub flags: Vec<String>,
}

impl Board {
    pub fn pin(&self, gpio: u32) -> Option<&Pin> {
        self.pins.iter().find(|p| p.gpio == gpio)
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct PinRole {
    #[serde(default)]
    pub caps: Vec<String>,
    /// Pin flags that this role explicitly tolerates (e.g. `strapping`).
    #[serde(default)]
    pub allow_flags: Vec<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Component {
    pub id: String,
    pub kind: String,
    pub yaml_key: String,
    #[serde(default)]
    pub platform: Option<String>,
    #[serde(default)]
    pub singleton: bool,
    /// JSON Schema (2020-12) of the YAML block.
    pub config: Value,
    #[serde(default)]
    pub pins: BTreeMap<String, PinRole>,
    #[serde(default)]
    pub requires: Vec<String>,
    /// How codegen wires the component into the firmware runtime.
    #[serde(default)]
    pub firmware: Option<Firmware>,
    /// The schema file exactly as written (served to the UI).
    #[serde(skip)]
    pub raw: Value,
}

/// The `firmware` block of a component schema.
#[derive(Debug, Clone, Deserialize)]
pub struct Firmware {
    /// Rust module path of the runtime implementation, e.g. `runtime::wifi`.
    pub module: String,
    /// Chip peripherals (fields of `Peripherals`) handed to the component, e.g. `WIFI`.
    #[serde(default)]
    pub peripherals: Vec<String>,
    /// Peripheral family allocated one per instance in declaration order, e.g. `I2C` -> `I2C0`, `I2C1`.
    #[serde(default)]
    pub indexed_peripheral: Option<String>,
}

impl Component {
    /// Properties of the config schema that carry an `x-ref` to another component id.
    pub fn refs(&self) -> Vec<(String, String)> {
        let mut out = Vec::new();
        if let Some(props) = self.config.get("properties").and_then(Value::as_object) {
            for (name, def) in props {
                if let Some(target) = def.get("x-ref").and_then(Value::as_str) {
                    out.push((name.clone(), target.to_owned()));
                }
            }
        }
        out
    }
}

/// All known boards and components.
#[derive(Debug, Default)]
pub struct Registry {
    pub boards: BTreeMap<String, Board>,
    pub components: BTreeMap<String, Component>,
}

const EMBEDDED_BOARDS: &[(&str, &str)] = &[
    ("esp32c6", include_str!("../../../schemas/boards/esp32c6.json")),
    ("esp32s3", include_str!("../../../schemas/boards/esp32s3.json")),
];
const EMBEDDED_COMPONENTS: &[(&str, &str)] = &[
    ("wifi", include_str!("../../../schemas/components/wifi.json")),
    ("mqtt", include_str!("../../../schemas/components/mqtt.json")),
    ("i2c_bus", include_str!("../../../schemas/components/i2c_bus.json")),
    ("gpio_switch", include_str!("../../../schemas/components/gpio_switch.json")),
    (
        "gpio_binary_sensor",
        include_str!("../../../schemas/components/gpio_binary_sensor.json"),
    ),
    ("bme280", include_str!("../../../schemas/components/bme280.json")),
];

impl Registry {
    /// Schemas compiled into the binary (copied from `schemas/` at build time).
    pub fn embedded() -> Result<Self, EngineError> {
        let mut reg = Registry::default();
        for (name, text) in EMBEDDED_BOARDS {
            reg.add_board(name, text)?;
        }
        for (name, text) in EMBEDDED_COMPONENTS {
            reg.add_component(name, text)?;
        }
        Ok(reg)
    }

    /// Read `<dir>/boards/*.json` and `<dir>/components/*.json`.
    pub fn from_dir(dir: &Path) -> Result<Self, EngineError> {
        let mut reg = Registry::default();
        for text in read_json_dir(&dir.join("boards"))? {
            reg.add_board(&text.0, &text.1)?;
        }
        for text in read_json_dir(&dir.join("components"))? {
            reg.add_component(&text.0, &text.1)?;
        }
        Ok(reg)
    }

    fn add_board(&mut self, name: &str, text: &str) -> Result<(), EngineError> {
        let schema_err = |e: serde_json::Error| EngineError::Schema {
            file: format!("boards/{name}.json"),
            message: e.to_string(),
        };
        let mut board: Board = serde_json::from_str(text).map_err(schema_err)?;
        board.raw = serde_json::from_str(text).map_err(schema_err)?;
        self.boards.insert(board.id.clone(), board);
        Ok(())
    }

    fn add_component(&mut self, name: &str, text: &str) -> Result<(), EngineError> {
        let schema_err = |e: serde_json::Error| EngineError::Schema {
            file: format!("components/{name}.json"),
            message: e.to_string(),
        };
        let mut comp: Component = serde_json::from_str(text).map_err(schema_err)?;
        comp.raw = serde_json::from_str(text).map_err(schema_err)?;
        self.components.insert(comp.id.clone(), comp);
        Ok(())
    }

    /// Find the component that handles `yaml_key` (+ `platform` when the key is shared).
    pub fn find_component(&self, yaml_key: &str, platform: Option<&str>) -> Option<&Component> {
        self.components.values().find(|c| {
            c.yaml_key == yaml_key
                && match (&c.platform, platform) {
                    (None, _) => true,
                    (Some(p), Some(q)) => p == q,
                    (Some(_), None) => false,
                }
        })
    }

    pub fn yaml_keys(&self) -> Vec<&str> {
        let mut keys: Vec<&str> = self.components.values().map(|c| c.yaml_key.as_str()).collect();
        keys.sort_unstable();
        keys.dedup();
        keys
    }
}

fn read_json_dir(dir: &Path) -> Result<Vec<(String, String)>, EngineError> {
    let io = |e: std::io::Error| EngineError::Io {
        path: dir.display().to_string(),
        source: e,
    };
    let mut out = Vec::new();
    for entry in std::fs::read_dir(dir).map_err(io)? {
        let path = entry.map_err(io)?.path();
        if path.extension().and_then(|e| e.to_str()) == Some("json") {
            let name = path.file_stem().and_then(|s| s.to_str()).unwrap_or_default().to_owned();
            let text = std::fs::read_to_string(&path).map_err(|e| EngineError::Io {
                path: path.display().to_string(),
                source: e,
            })?;
            out.push((name, text));
        }
    }
    out.sort();
    Ok(out)
}
