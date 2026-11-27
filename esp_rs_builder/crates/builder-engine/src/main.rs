use std::path::PathBuf;
use std::process::ExitCode;

use builder_engine::{EngineError, Registry, generate, load_and_validate, validate_str};

const DEFAULT_OUT: &str = "firmware/src/generated.rs";

fn registry() -> Result<Registry, EngineError> {
    match std::env::var_os("BUILDER_SCHEMAS_DIR") {
        Some(dir) => Registry::from_dir(&PathBuf::from(dir)),
        None => Registry::embedded(),
    }
}

fn read(file: &str) -> Result<String, EngineError> {
    std::fs::read_to_string(file).map_err(|e| EngineError::Io {
        path: file.to_owned(),
        source: e,
    })
}

/// Print all diagnostics; returns `true` when there are no errors.
fn check(reg: &Registry, file: &str, text: &str) -> Result<bool, EngineError> {
    let report = validate_str(reg, text)?;
    for d in &report.diagnostics {
        eprintln!("{d}");
    }
    if report.has_errors() {
        eprintln!("{file}: validation failed");
    }
    Ok(!report.has_errors())
}

fn run(args: &[String]) -> Result<bool, EngineError> {
    match args {
        [cmd, file] if cmd == "validate" => {
            let text = read(file)?;
            let ok = check(&registry()?, file, &text)?;
            if ok {
                println!("{file}: OK");
            }
            Ok(ok)
        }
        [cmd, file, rest @ ..] if cmd == "generate" => {
            let out = match rest {
                [] => DEFAULT_OUT,
                [flag, path] if flag == "-o" => path.as_str(),
                _ => return Ok(usage(false)),
            };
            let text = read(file)?;
            let reg = registry()?;
            if !check(&reg, file, &text)? {
                eprintln!("{file}: generation refused");
                return Ok(false);
            }
            let Ok(model) = load_and_validate(&reg, &text) else {
                return Err(EngineError::Codegen("config became invalid between validation passes".into()));
            };
            let source = generate(&model, &reg)?;
            std::fs::write(out, source).map_err(|e| EngineError::Io {
                path: out.to_owned(),
                source: e,
            })?;
            println!("{file}: generated {out}");
            Ok(true)
        }
        _ => Ok(usage(args.is_empty())),
    }
}

fn usage(ok: bool) -> bool {
    println!("builder-engine {}", env!("CARGO_PKG_VERSION"));
    println!("usage: builder-engine validate <config.yaml>");
    println!("       builder-engine generate <config.yaml> [-o {DEFAULT_OUT}]");
    println!("env:   BUILDER_SCHEMAS_DIR=<dir> to use schemas from disk instead of the embedded copy");
    ok
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match run(&args) {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => ExitCode::from(1),
        Err(e) => {
            eprintln!("error: {e}");
            ExitCode::from(2)
        }
    }
}
