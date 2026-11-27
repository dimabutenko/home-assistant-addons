use builder_engine::{Registry, Report, Severity, validate_str};

const VALID: &str = include_str!("fixtures/valid_c6.yaml");

fn run(yaml: &str) -> Report {
    let reg = Registry::embedded().expect("embedded schemas load");
    validate_str(&reg, yaml).expect("yaml parses")
}

fn has_error(r: &Report, path: &str, needle: &str) -> bool {
    r.errors().any(|d| d.path == path && d.message.contains(needle))
}

#[test]
fn valid_config_passes() {
    let r = run(VALID);
    assert!(!r.has_errors(), "{:#?}", r.diagnostics);
}

#[test]
fn pin_conflict() {
    let r = run(&VALID.replace("pin: 11", "pin: 10"));
    assert!(has_error(&r, "switch[0].pin", "already used by `binary_sensor[0].pin`"), "{:#?}", r.diagnostics);
}

#[test]
fn bad_capability() {
    // Strip `output` from GPIO10 in the board schema: the switch must be rejected.
    let mut reg = Registry::embedded().expect("embedded schemas load");
    let board = reg.boards.get_mut("esp32c6").expect("c6 board");
    for pin in board.pins.iter_mut().filter(|p| p.gpio == 10) {
        pin.caps.retain(|c| c != "output");
    }
    let r = validate_str(&reg, VALID).expect("yaml parses");
    assert!(has_error(&r, "switch[0].pin", "lacks capability `output`"), "{:#?}", r.diagnostics);
}

#[test]
fn nonexistent_gpio() {
    let r = run(&VALID.replace("pin: 11", "pin: 99"));
    assert!(has_error(&r, "binary_sensor[0].pin", "does not exist"), "{:#?}", r.diagnostics);
}

#[test]
fn flash_pin_is_error_and_strapping_is_warning() {
    let r = run(&VALID.replace("pin: 10", "pin: 24"));
    assert!(has_error(&r, "switch[0].pin", "not usable"), "{:#?}", r.diagnostics);
    let r = run(&VALID.replace("pin: 10", "pin: 9"));
    assert!(!r.has_errors(), "{:#?}", r.diagnostics);
    assert!(r
        .diagnostics
        .iter()
        .any(|d| d.severity == Severity::Warning && d.path == "switch[0].pin"));
}

#[test]
fn unknown_bus_ref() {
    let r = run(&VALID.replace("i2c_id: bus0", "i2c_id: nope"));
    assert!(has_error(&r, "sensor[0].i2c_id", "unknown i2c_bus id `nope`"), "{:#?}", r.diagnostics);
}

#[test]
fn schema_violation_has_yaml_path() {
    let r = run(&VALID.replace("broker: 192.168.1.10", "broker: x\n  port: 70000"));
    assert!(r.errors().any(|d| d.path == "mqtt.port"), "{:#?}", r.diagnostics);
    let r = run(&VALID.replace("      name: Temperature", "      name: \"\""));
    assert!(r.errors().any(|d| d.path == "sensor[0].temperature.name"), "{:#?}", r.diagnostics);
}

#[test]
fn unknown_board_and_key() {
    let r = run(&VALID.replace("esp32c6", "esp32x"));
    assert!(r.errors().any(|d| d.path == "board"));
    let r = run(&format!("{VALID}\nbogus: 1\n"));
    assert!(r.errors().any(|d| d.path == "bogus"));
}
