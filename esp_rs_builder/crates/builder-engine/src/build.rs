//! Build driver: work-copy preparation and the fixed `cargo` / `espflash` command lines.
//!
//! Nothing here is shell-interpreted and no argument comes from user input:
//! target triple and cargo feature come from the board schema, paths from the server.

use std::ffi::OsString;
use std::path::{Path, PathBuf};

use serde_json::Value;

use crate::error::EngineError;
use crate::model::DeviceModel;
use crate::schema::{Board, Registry};

/// One external command to run (no shell).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Step {
    pub program: OsString,
    pub args: Vec<OsString>,
    pub cwd: PathBuf,
    pub envs: Vec<(String, String)>,
}

/// The commands of one firmware build plus the file they produce.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Plan {
    pub steps: Vec<Step>,
    /// Flashable image written by the last step.
    pub artifact: PathBuf,
}

/// Build plan for a board: `cargo build --release` in the work copy, then `espflash save-image`.
///
/// `target_dir` is the shared cargo target directory (build cache across jobs).
pub fn plan(board: &Board, work_copy: &Path, target_dir: &Path, espflash: &Path) -> Plan {
    let elf = target_dir.join(&board.target).join("release").join("firmware");
    let artifact = work_copy.join("firmware.bin");
    let cargo = Step {
        program: "cargo".into(),
        args: ["build", "--release", "--target", board.target.as_str(), "--features", board.feature.as_str()]
            .iter()
            .map(OsString::from)
            .collect(),
        cwd: work_copy.to_path_buf(),
        envs: vec![
            ("CARGO_TARGET_DIR".into(), target_dir.display().to_string()),
            ("CARGO_TERM_COLOR".into(), "never".into()),
        ],
    };
    let image = Step {
        program: espflash.as_os_str().to_owned(),
        args: vec![
            "save-image".into(),
            "--chip".into(),
            chip_arg(&board.chip).into(),
            "--merge".into(),
            elf.as_os_str().to_owned(),
            artifact.as_os_str().to_owned(),
        ],
        cwd: work_copy.to_path_buf(),
        envs: Vec::new(),
    };
    Plan {
        steps: vec![cargo, image],
        artifact,
    }
}

/// `ESP32-C6` -> `esp32c6` (the spelling espflash expects).
fn chip_arg(chip: &str) -> String {
    chip.chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .map(|c| c.to_ascii_lowercase())
        .collect()
}

/// Copy the firmware sources into `dest` (without `target/` and the shared `generated.rs`)
/// and write `generated` as `src/generated.rs`.
pub fn prepare_work_copy(firmware_dir: &Path, dest: &Path, generated: &str) -> Result<(), EngineError> {
    copy_tree(firmware_dir, dest, true)?;
    let gen_path = dest.join("src").join("generated.rs");
    std::fs::write(&gen_path, generated).map_err(|e| io_err(&gen_path, e))
}

fn copy_tree(src: &Path, dst: &Path, top: bool) -> Result<(), EngineError> {
    std::fs::create_dir_all(dst).map_err(|e| io_err(dst, e))?;
    for entry in std::fs::read_dir(src).map_err(|e| io_err(src, e))? {
        let entry = entry.map_err(|e| io_err(src, e))?;
        let name = entry.file_name();
        if top && name == "target" {
            continue;
        }
        let from = entry.path();
        let to = dst.join(&name);
        let kind = entry.file_type().map_err(|e| io_err(&from, e))?;
        if kind.is_dir() {
            copy_tree(&from, &to, false)?;
        } else if kind.is_file() {
            std::fs::copy(&from, &to).map_err(|e| io_err(&from, e))?;
        }
    }
    Ok(())
}

fn io_err(path: &Path, source: std::io::Error) -> EngineError {
    EngineError::Io {
        path: path.display().to_string(),
        source,
    }
}

/// Every string value the component schemas mark `x-secret`, as written in the config.
/// Used to redact build output.
pub fn secrets(model: &DeviceModel, reg: &Registry) -> Vec<String> {
    let mut out = Vec::new();
    for comp in &model.components {
        if let Some(schema) = reg.components.get(&comp.component) {
            collect(&schema.config, &comp.config, &mut out);
        }
    }
    out.retain(|s| !s.is_empty());
    out.sort();
    out.dedup();
    out
}

fn collect(schema: &Value, value: &Value, out: &mut Vec<String>) {
    let (Some(props), Some(obj)) = (schema.get("properties").and_then(Value::as_object), value.as_object()) else {
        return;
    };
    for (name, def) in props {
        let Some(v) = obj.get(name) else { continue };
        if def.get("x-secret").and_then(Value::as_bool) == Some(true) {
            if let Some(s) = v.as_str() {
                out.push(s.to_owned());
            }
        } else {
            collect(def, v, out);
        }
    }
}

/// Replace every secret occurrence in `line` with `***`.
pub fn redact(line: &str, secrets: &[String]) -> String {
    let mut out = line.to_owned();
    for s in secrets {
        out = out.replace(s.as_str(), "***");
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plan_uses_board_target_and_feature() {
        let reg = Registry::embedded().unwrap();
        let board = &reg.boards["esp32c6"];
        let p = plan(board, Path::new("job"), Path::new("tgt"), Path::new("espflash"));
        let args: Vec<_> = p.steps[0].args.iter().map(|a| a.to_string_lossy().into_owned()).collect();
        assert_eq!(
            args,
            ["build", "--release", "--target", "riscv32imac-unknown-none-elf", "--features", "esp32c6"]
        );
        let flash: Vec<_> = p.steps[1].args.iter().map(|a| a.to_string_lossy().into_owned()).collect();
        assert_eq!(&flash[..4], ["save-image", "--chip", "esp32c6", "--merge"]);
        assert!(p.artifact.ends_with("firmware.bin"));
    }

    #[test]
    fn redacts_secrets() {
        let secrets = vec!["supersecret1".to_owned()];
        assert_eq!(redact("let p = \"supersecret1\";", &secrets), "let p = \"***\";");
    }
}
