use std::path::PathBuf;
use std::sync::Arc;

use builder_server::runner::CargoRunner;
use builder_server::{AppState, router};

fn env_path(name: &str, default: &str) -> PathBuf {
    std::env::var_os(name).map_or_else(|| PathBuf::from(default), PathBuf::from)
}

#[tokio::main]
async fn main() {
    let registry = match std::env::var_os("BUILDER_SCHEMAS_DIR") {
        Some(dir) => builder_engine::Registry::from_dir(&PathBuf::from(dir)),
        None => builder_engine::Registry::embedded(),
    };
    let registry = match registry {
        Ok(r) => r,
        Err(e) => {
            eprintln!("error: {e}");
            std::process::exit(2);
        }
    };
    let work = env_path("BUILDER_WORK_DIR", "work");
    let runner = CargoRunner {
        firmware_dir: env_path("BUILDER_FIRMWARE_DIR", "firmware"),
        target_dir: work.join("target"),
        espflash: env_path("BUILDER_ESPFLASH", "espflash"),
    };
    let state = AppState::new(registry, work.join("jobs"), Arc::new(runner)).with_ui_dir(env_path("BUILDER_UI_DIR", "ui"));
    let bind = std::env::var("BUILDER_BIND").unwrap_or_else(|_| "0.0.0.0:8099".to_owned());
    let listener = match tokio::net::TcpListener::bind(&bind).await {
        Ok(l) => l,
        Err(e) => {
            eprintln!("error: cannot bind {bind}: {e}");
            std::process::exit(2);
        }
    };
    println!("builder-server {} listening on {bind}", env!("CARGO_PKG_VERSION"));
    if let Err(e) = axum::serve(listener, router(state)).await {
        eprintln!("error: {e}");
        std::process::exit(1);
    }
}
