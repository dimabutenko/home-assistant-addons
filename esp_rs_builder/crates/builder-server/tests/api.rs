use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use axum::Router;
use axum::body::Body;
use axum::http::{Method, Request, StatusCode};
use builder_engine::build::Step;
use builder_engine::{Registry, generate, load_and_validate};
use builder_server::jobs::{Jobs, LOG_CAPACITY, Status};
use builder_server::runner::{BuildRequest, RunFuture, Runner, run_steps};
use builder_server::{AppState, router};
use futures_util::StreamExt;
use http_body_util::BodyExt;
use serde_json::Value;
use tokio::sync::Notify;
use tower::ServiceExt;

const VALID: &str = include_str!("../../builder-engine/tests/fixtures/valid_c6.yaml");
const GOLDEN: &str = include_str!("../../builder-engine/tests/fixtures/valid_c6.generated.rs");
const IMAGE: &[u8] = b"fake-image";

/// Logs a line, signals `started`, waits for `gate`, logs another line and "builds" a file.
struct FakeRunner {
    started: Arc<Notify>,
    gate: Option<Arc<Notify>>,
}

impl Runner for FakeRunner {
    fn run(&self, job: Arc<builder_server::jobs::Job>, req: BuildRequest) -> RunFuture {
        let (started, gate) = (self.started.clone(), self.gate.clone());
        Box::pin(async move {
            job.push_line(&format!("one ({} bytes of source)", req.generated.len()));
            started.notify_one();
            if let Some(g) = gate {
                g.notified().await;
            }
            job.push_line("two");
            tokio::fs::create_dir_all(&job.dir).await.map_err(|e| e.to_string())?;
            let path = job.dir.join("firmware.bin");
            tokio::fs::write(&path, IMAGE).await.map_err(|e| e.to_string())?;
            Ok(path)
        })
    }
}

fn temp_dir(name: &str) -> PathBuf {
    std::env::temp_dir().join(format!("builder-server-test-{name}-{}", std::process::id()))
}

fn app(name: &str, gate: Option<Arc<Notify>>) -> (Router, Arc<Notify>) {
    let started = Arc::new(Notify::new());
    let runner = FakeRunner { started: started.clone(), gate };
    let state = AppState::new(Registry::embedded().unwrap(), temp_dir(name), Arc::new(runner));
    (router(state), started)
}

async fn call(app: &Router, method: Method, uri: &str, body: &str) -> (StatusCode, Vec<u8>) {
    let req = Request::builder()
        .method(method)
        .uri(uri)
        .body(Body::from(body.to_owned()))
        .unwrap();
    let res = app.clone().oneshot(req).await.unwrap();
    let status = res.status();
    (status, res.into_body().collect().await.unwrap().to_bytes().to_vec())
}

fn json(bytes: &[u8]) -> Value {
    serde_json::from_slice(bytes).unwrap()
}

async fn wait_final(app: &Router, id: &str) -> Value {
    for _ in 0..200 {
        let (_, body) = call(app, Method::GET, &format!("/api/jobs/{id}"), "").await;
        let v = json(&body);
        if v["status"] == "succeeded" || v["status"] == "failed" {
            return v;
        }
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
    panic!("job {id} did not finish");
}

#[tokio::test]
async fn lists_boards_and_components() {
    let (app, _) = app("lists", None);
    let (st, body) = call(&app, Method::GET, "/api/boards", "").await;
    assert_eq!(st, StatusCode::OK);
    let boards = json(&body);
    assert!(boards.as_array().unwrap().iter().any(|b| b["id"] == "esp32c6" && b["pins"][0]["ui"].is_object()));
    let (_, body) = call(&app, Method::GET, "/api/components", "").await;
    assert!(json(&body).as_array().unwrap().iter().any(|c| c["id"] == "bme280"));
}

#[tokio::test]
async fn validate_valid_and_invalid() {
    let (app, _) = app("validate", None);
    let (st, body) = call(&app, Method::POST, "/api/validate", VALID).await;
    assert_eq!(st, StatusCode::OK);
    assert!(json(&body).as_array().unwrap().iter().all(|d| d["severity"] != "error"));

    let bad = VALID.replace("board: esp32c6", "board: nope");
    let (st, body) = call(&app, Method::POST, "/api/validate", &bad).await;
    assert_eq!(st, StatusCode::OK);
    let diags = json(&body);
    assert!(diags.as_array().unwrap().iter().any(|d| d["severity"] == "error" && d["path"] == "board"));

    let (st, body) = call(&app, Method::POST, "/api/validate", "a: [").await;
    assert_eq!(st, StatusCode::OK);
    assert_eq!(json(&body)[0]["severity"], "error");
}

#[tokio::test]
async fn generate_matches_engine_and_rejects_invalid() {
    let (app, _) = app("generate", None);
    let (st, body) = call(&app, Method::POST, "/api/generate", VALID).await;
    assert_eq!(st, StatusCode::OK);
    let text = String::from_utf8(body).unwrap();
    let reg = Registry::embedded().unwrap();
    let model = load_and_validate(&reg, VALID).unwrap();
    assert_eq!(text, generate(&model, &reg).unwrap());
    assert_eq!(text, GOLDEN);

    let bad = VALID.replace("board: esp32c6", "board: nope");
    let (st, body) = call(&app, Method::POST, "/api/generate", &bad).await;
    assert_eq!(st, StatusCode::UNPROCESSABLE_ENTITY);
    assert!(!json(&body).as_array().unwrap().is_empty());
}

#[tokio::test]
async fn oversized_yaml_is_rejected() {
    let (app, _) = app("big", None);
    let big = "x".repeat(300 * 1024);
    let (st, _) = call(&app, Method::POST, "/api/validate", &big).await;
    assert_eq!(st, StatusCode::PAYLOAD_TOO_LARGE);
}

#[tokio::test]
async fn invalid_build_is_422_and_second_concurrent_build_is_409() {
    let gate = Arc::new(Notify::new());
    let (app, started) = app("busy", Some(gate.clone()));
    let bad = VALID.replace("board: esp32c6", "board: nope");
    let (st, _) = call(&app, Method::POST, "/api/build", &bad).await;
    assert_eq!(st, StatusCode::UNPROCESSABLE_ENTITY);

    let (st, body) = call(&app, Method::POST, "/api/build", VALID).await;
    assert_eq!(st, StatusCode::ACCEPTED);
    let id = json(&body)["id"].as_str().unwrap().to_owned();
    started.notified().await;
    let (st, _) = call(&app, Method::POST, "/api/build", VALID).await;
    assert_eq!(st, StatusCode::CONFLICT);

    // No image before the build finishes.
    let (st, _) = call(&app, Method::GET, &format!("/api/jobs/{id}/firmware.bin"), "").await;
    assert_eq!(st, StatusCode::NOT_FOUND);

    gate.notify_one();
    let done = wait_final(&app, &id).await;
    assert_eq!(done["status"], "succeeded");
    assert_eq!(done["artifact"], "firmware.bin");
    let (st, bin) = call(&app, Method::GET, &format!("/api/jobs/{id}/firmware.bin"), "").await;
    assert_eq!(st, StatusCode::OK);
    assert_eq!(bin, IMAGE);

    // The server is free again.
    let (st, _) = call(&app, Method::POST, "/api/build", VALID).await;
    assert_eq!(st, StatusCode::ACCEPTED);
    let (st, _) = call(&app, Method::GET, "/api/jobs/999", "").await;
    assert_eq!(st, StatusCode::NOT_FOUND);
}

#[tokio::test]
async fn websocket_streams_buffered_and_live_lines_then_final_status() {
    let gate = Arc::new(Notify::new());
    let (app, started) = app("ws", Some(gate.clone()));
    // The router clone shares the job store, so the job can be started in-process.
    let (st, body) = call(&app, Method::POST, "/api/build", VALID).await;
    assert_eq!(st, StatusCode::ACCEPTED);
    let id = json(&body)["id"].as_str().unwrap().to_owned();
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    started.notified().await;

    let (mut ws, _) = tokio_tungstenite::connect_async(format!("ws://{addr}/ws?job={id}")).await.unwrap();
    let mut frames: Vec<Value> = Vec::new();
    let mut released = false;
    while let Some(msg) = ws.next().await {
        let msg = msg.unwrap();
        if msg.is_close() {
            break;
        }
        let v: Value = serde_json::from_str(msg.to_text().unwrap()).unwrap();
        if !released && v["type"] == "status" {
            // Buffered part received ("one" + current status running): let the build go on.
            gate.notify_one();
            released = true;
        }
        frames.push(v);
    }
    let lines: Vec<&str> = frames.iter().filter(|f| f["type"] == "log").map(|f| f["line"].as_str().unwrap()).collect();
    assert!(lines[0].starts_with("one"), "{lines:?}");
    assert!(lines.contains(&"two"));
    assert_eq!(*lines.last().unwrap(), "build succeeded");
    let last = frames.last().unwrap();
    assert_eq!(last["type"], "status");
    assert_eq!(last["status"], "succeeded");
}

#[tokio::test]
async fn websocket_unknown_job_is_404() {
    let (app, _) = app("ws404", None);
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    let err = tokio_tungstenite::connect_async(format!("ws://{addr}/ws?job=42")).await.unwrap_err();
    match err {
        tokio_tungstenite::tungstenite::Error::Http(res) => assert_eq!(res.status(), StatusCode::NOT_FOUND),
        other => panic!("unexpected error: {other:?}"),
    }
}

#[test]
fn log_buffer_is_bounded() {
    let jobs = Jobs::new(temp_dir("ring"));
    let job = jobs.start().unwrap();
    for i in 0..LOG_CAPACITY + 10 {
        job.push_line(&format!("line {i}"));
    }
    let sub = job.subscribe();
    assert_eq!(sub.lines.len(), LOG_CAPACITY);
    assert_eq!(sub.lines[0], "line 10");
    assert_eq!(sub.status, Status::Queued);
    assert!(jobs.start().is_none(), "second job while busy");
    jobs.release();
    assert!(jobs.start().is_some());
}

#[tokio::test]
async fn step_output_is_streamed_and_secrets_redacted() {
    let jobs = Jobs::new(temp_dir("steps"));
    let job = jobs.start().unwrap();
    let step = Step {
        program: "cargo".into(),
        args: vec!["--version".into()],
        cwd: std::env::temp_dir(),
        envs: Vec::new(),
    };
    run_steps(&[step], &job, &["cargo".to_owned()]).await.unwrap();
    let lines = job.subscribe().lines;
    assert!(lines.len() >= 2, "{lines:?}");
    assert!(lines.iter().all(|l| !l.contains("cargo")), "{lines:?}");
    assert!(lines.iter().any(|l| l.contains("***")));

    let missing = Step {
        program: "definitely-not-a-program".into(),
        args: Vec::new(),
        cwd: std::env::temp_dir(),
        envs: Vec::new(),
    };
    assert!(run_steps(&[missing], &job, &[]).await.is_err());
}

#[tokio::test]
async fn serves_ui_files_and_hides_everything_else() {
    let dir = temp_dir("ui");
    std::fs::create_dir_all(dir.join("lib")).unwrap();
    std::fs::write(dir.join("index.html"), "<h1>ui</h1>").unwrap();
    std::fs::write(dir.join("lib").join("a.js"), "export {}").unwrap();
    let state = AppState::new(Registry::embedded().unwrap(), temp_dir("ui-jobs"), Arc::new(FakeRunner { started: Arc::new(Notify::new()), gate: None }))
        .with_ui_dir(dir);
    let app = router(state);
    let (st, body) = call(&app, Method::GET, "/", "").await;
    assert_eq!((st, body.as_slice()), (StatusCode::OK, &b"<h1>ui</h1>"[..]));
    let (st, _) = call(&app, Method::GET, "/lib/a.js", "").await;
    assert_eq!(st, StatusCode::OK);
    assert_eq!(call(&app, Method::GET, "/lib/missing.js", "").await.0, StatusCode::NOT_FOUND);
    assert_eq!(call(&app, Method::GET, "/..%2f..%2fCargo.toml", "").await.0, StatusCode::NOT_FOUND);
    assert_eq!(call(&app, Method::GET, "/api/boards", "").await.0, StatusCode::OK);
}
