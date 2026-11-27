use std::path::PathBuf;
use std::process::Command;

use builder_engine::{Registry, generate, load_and_validate};

const VALID: &str = include_str!("fixtures/valid_c6.yaml");

fn golden_path() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/valid_c6.generated.rs")
}

fn gen_valid() -> String {
    let reg = Registry::embedded().unwrap();
    let model = load_and_validate(&reg, VALID).expect("fixture is valid");
    generate(&model, &reg).expect("codegen succeeds")
}

#[test]
fn matches_golden_file() {
    let out = gen_valid();
    if std::env::var_os("UPDATE_GOLDEN").is_some() {
        std::fs::write(golden_path(), &out).unwrap();
    }
    let golden = std::fs::read_to_string(golden_path()).expect("golden file exists");
    assert_eq!(out, golden.replace("\r\n", "\n"));
}

#[test]
fn output_parses_and_is_deterministic() {
    let a = gen_valid();
    assert_eq!(a, gen_valid());
    syn::parse_file(&a).expect("generated code parses");
    assert!(a.contains("DO NOT EDIT"));
}

#[test]
fn invalid_config_is_refused() {
    let reg = Registry::embedded().unwrap();
    let bad = VALID.replace("i2c_id: bus0", "i2c_id: nope");
    let report = load_and_validate(&reg, &bad).expect_err("must be refused");
    assert!(report.has_errors());
    assert!(load_and_validate(&reg, "board: [").is_err());
}

#[test]
fn cli_generate_writes_file_and_refuses_invalid() {
    let dir = std::env::temp_dir().join(format!("builder-engine-gen-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let exe = env!("CARGO_BIN_EXE_builder-engine");

    let good = dir.join("good.yaml");
    std::fs::write(&good, VALID).unwrap();
    let out = dir.join("generated.rs");
    let status = Command::new(exe).arg("generate").arg(&good).arg("-o").arg(&out).status().unwrap();
    assert_eq!(status.code(), Some(0));
    assert_eq!(std::fs::read_to_string(&out).unwrap(), gen_valid());

    let bad = dir.join("bad.yaml");
    std::fs::write(&bad, VALID.replace("i2c_id: bus0", "i2c_id: nope")).unwrap();
    let out2 = dir.join("never.rs");
    let status = Command::new(exe).arg("generate").arg(&bad).arg("-o").arg(&out2).status().unwrap();
    assert_eq!(status.code(), Some(1));
    assert!(!out2.exists());
    let _ = std::fs::remove_dir_all(&dir);
}
