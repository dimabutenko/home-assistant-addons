//! builder-server: REST API, `/ws` build-log stream and firmware download on top of builder-engine.
//!
//! WebSocket protocol (`GET /ws?job=<id>`): every frame is a JSON text frame,
//! `{"type":"log","line":"..."}` or `{"type":"status","status":"queued|running|succeeded|failed"}`.
//! A subscriber first gets the buffered lines, then the current status, then live events; the
//! socket is closed after a final status (`succeeded` / `failed`).

pub mod jobs;
pub mod runner;
pub mod static_files;

use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use axum::Json;
use axum::Router;
use axum::extract::ws::{Message, WebSocket, WebSocketUpgrade};
use axum::extract::{DefaultBodyLimit, Path, Query, State};
use axum::http::{StatusCode, header};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use builder_engine::{Diagnostic, EngineError, Registry, Severity, build, generate, load_and_validate, validate_str};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use tokio::sync::broadcast::error::RecvError;

use crate::jobs::{Event, Job, Jobs, Status};
use crate::runner::{BuildRequest, Runner};

/// YAML bodies larger than this are rejected (HTTP 413).
pub const MAX_YAML_BYTES: usize = 256 * 1024;
/// A build running longer than this is killed and marked failed.
pub const BUILD_TIMEOUT: Duration = Duration::from_secs(30 * 60);

#[derive(Clone)]
pub struct AppState {
    registry: Arc<Registry>,
    jobs: Arc<Jobs>,
    runner: Arc<dyn Runner>,
    ui_dir: Arc<PathBuf>,
}

impl AppState {
    pub fn new(registry: Registry, jobs_dir: PathBuf, runner: Arc<dyn Runner>) -> Self {
        AppState {
            registry: Arc::new(registry),
            jobs: Arc::new(Jobs::new(jobs_dir)),
            runner,
            ui_dir: Arc::new(PathBuf::from("ui")),
        }
    }

    /// Folder the web UI is served from (default `ui`).
    #[must_use]
    pub fn with_ui_dir(mut self, dir: PathBuf) -> Self {
        self.ui_dir = Arc::new(dir);
        self
    }
}

pub fn router(state: AppState) -> Router {
    Router::new()
        .route("/api/boards", get(boards))
        .route("/api/components", get(components))
        .route("/api/validate", post(validate_cfg))
        .route("/api/generate", post(generate_cfg))
        .route("/api/build", post(start_build))
        .route("/api/jobs/{id}", get(job_status))
        .route("/api/jobs/{id}/firmware.bin", get(job_firmware))
        .route("/ws", get(ws))
        .fallback(get(static_files::serve))
        .layer(DefaultBodyLimit::max(MAX_YAML_BYTES))
        .with_state(state)
}

async fn boards(State(s): State<AppState>) -> Json<Vec<Value>> {
    Json(s.registry.boards.values().map(|b| b.raw.clone()).collect())
}

async fn components(State(s): State<AppState>) -> Json<Vec<Value>> {
    Json(s.registry.components.values().map(|c| c.raw.clone()).collect())
}

fn yaml_diag(e: &EngineError) -> Vec<Diagnostic> {
    vec![Diagnostic {
        severity: Severity::Error,
        path: String::new(),
        message: e.to_string(),
    }]
}

/// Parse + validate; `Err` carries every diagnostic (warnings included).
fn check(reg: &Registry, text: &str) -> Result<builder_engine::DeviceModel, Vec<Diagnostic>> {
    let report = validate_str(reg, text).map_err(|e| yaml_diag(&e))?;
    if report.has_errors() {
        return Err(report.diagnostics);
    }
    load_and_validate(reg, text).map_err(|r| r.diagnostics)
}

fn invalid(diags: Vec<Diagnostic>) -> Response {
    (StatusCode::UNPROCESSABLE_ENTITY, Json(diags)).into_response()
}

fn error(status: StatusCode, message: &str) -> Response {
    (status, Json(json!({ "error": message }))).into_response()
}

async fn validate_cfg(State(s): State<AppState>, body: String) -> Json<Vec<Diagnostic>> {
    Json(match validate_str(&s.registry, &body) {
        Ok(report) => report.diagnostics,
        Err(e) => yaml_diag(&e),
    })
}

async fn generate_cfg(State(s): State<AppState>, body: String) -> Response {
    let model = match check(&s.registry, &body) {
        Ok(m) => m,
        Err(d) => return invalid(d),
    };
    match generate(&model, &s.registry) {
        Ok(src) => ([(header::CONTENT_TYPE, "text/plain; charset=utf-8")], src).into_response(),
        Err(e) => error(StatusCode::INTERNAL_SERVER_ERROR, &e.to_string()),
    }
}

#[derive(Serialize)]
struct JobInfo {
    id: String,
    status: Status,
    artifact: Option<&'static str>,
}

fn info(job: &Job) -> JobInfo {
    JobInfo {
        id: job.id.clone(),
        status: job.status(),
        artifact: job.artifact().map(|_| "firmware.bin"),
    }
}

async fn start_build(State(s): State<AppState>, body: String) -> Response {
    let model = match check(&s.registry, &body) {
        Ok(m) => m,
        Err(d) => return invalid(d),
    };
    let Some(board) = s.registry.boards.get(&model.board).cloned() else {
        return error(StatusCode::UNPROCESSABLE_ENTITY, "unknown board");
    };
    let generated = match generate(&model, &s.registry) {
        Ok(g) => g,
        Err(e) => return error(StatusCode::INTERNAL_SERVER_ERROR, &e.to_string()),
    };
    let secrets = build::secrets(&model, &s.registry);
    let Some(job) = s.jobs.start() else {
        return error(StatusCode::CONFLICT, "a build is already running");
    };
    let id = job.id.clone();
    let req = BuildRequest { board, generated, secrets };
    let (jobs, runner) = (s.jobs.clone(), s.runner.clone());
    tokio::spawn(async move {
        job.set_status(Status::Running);
        let run = runner.run(job.clone(), req);
        match tokio::time::timeout(BUILD_TIMEOUT, run).await {
            Ok(Ok(artifact)) => {
                job.push_line("build succeeded");
                job.finish_ok(artifact);
            }
            Ok(Err(msg)) => {
                job.push_line(&format!("build failed: {msg}"));
                job.set_status(Status::Failed);
            }
            Err(_) => {
                job.push_line("build failed: timed out");
                job.set_status(Status::Failed);
            }
        }
        jobs.release();
    });
    (StatusCode::ACCEPTED, Json(json!({ "id": id }))).into_response()
}

async fn job_status(State(s): State<AppState>, Path(id): Path<String>) -> Response {
    match s.jobs.get(&id) {
        Some(job) => Json(info(&job)).into_response(),
        None => error(StatusCode::NOT_FOUND, "no such job"),
    }
}

async fn job_firmware(State(s): State<AppState>, Path(id): Path<String>) -> Response {
    let Some(job) = s.jobs.get(&id) else {
        return error(StatusCode::NOT_FOUND, "no such job");
    };
    let Some(path) = job.artifact() else {
        return error(StatusCode::NOT_FOUND, "job has no firmware image");
    };
    match tokio::fs::read(&path).await {
        Ok(bytes) => (
            [
                (header::CONTENT_TYPE, "application/octet-stream"),
                (header::CONTENT_DISPOSITION, "attachment; filename=\"firmware.bin\""),
            ],
            bytes,
        )
            .into_response(),
        Err(_) => error(StatusCode::NOT_FOUND, "firmware image is gone"),
    }
}

#[derive(Deserialize)]
struct WsQuery {
    job: String,
}

async fn ws(State(s): State<AppState>, Query(q): Query<WsQuery>, upgrade: WebSocketUpgrade) -> Response {
    match s.jobs.get(&q.job) {
        Some(job) => upgrade.on_upgrade(move |socket| stream_job(socket, job)),
        None => error(StatusCode::NOT_FOUND, "no such job"),
    }
}

fn frame(value: Value) -> Message {
    Message::text(value.to_string())
}

fn line_frame(line: &str) -> Message {
    frame(json!({ "type": "log", "line": line }))
}

fn status_frame(status: Status) -> Message {
    frame(json!({ "type": "status", "status": status }))
}

async fn stream_job(mut socket: WebSocket, job: Arc<Job>) {
    let mut sub = job.subscribe();
    for line in &sub.lines {
        if socket.send(line_frame(line)).await.is_err() {
            return;
        }
    }
    if socket.send(status_frame(sub.status)).await.is_err() || sub.status.is_final() {
        let _ = socket.send(Message::Close(None)).await;
        return;
    }
    loop {
        tokio::select! {
            ev = sub.rx.recv() => match ev {
                Ok(Event::Line(l)) => {
                    if socket.send(line_frame(&l)).await.is_err() {
                        return;
                    }
                }
                Ok(Event::Status(st)) => {
                    if socket.send(status_frame(st)).await.is_err() {
                        return;
                    }
                    if st.is_final() {
                        break;
                    }
                }
                Err(RecvError::Lagged(n)) => {
                    if socket.send(line_frame(&format!("... {n} lines skipped"))).await.is_err() {
                        return;
                    }
                }
                Err(RecvError::Closed) => break,
            },
            // Client went away (or sent something): stop streaming.
            msg = socket.recv() => match msg {
                None | Some(Err(_)) | Some(Ok(Message::Close(_))) => return,
                Some(Ok(_)) => {}
            },
        }
    }
    let _ = socket.send(Message::Close(None)).await;
}
