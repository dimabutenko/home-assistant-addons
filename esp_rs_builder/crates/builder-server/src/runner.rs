//! Executes a build. The real runner shells out to the fixed command lines of `builder_engine::build`.

use std::future::Future;
use std::path::PathBuf;
use std::pin::Pin;
use std::process::Stdio;
use std::sync::Arc;

use builder_engine::build::{self, Step};
use builder_engine::schema::Board;
use tokio::io::{AsyncBufReadExt, AsyncRead, BufReader};
use tokio::process::Command;

use crate::jobs::Job;

/// Everything a runner needs; the generated source exists only here and in the job directory.
pub struct BuildRequest {
    pub board: Board,
    pub generated: String,
    pub secrets: Vec<String>,
}

pub type RunFuture = Pin<Box<dyn Future<Output = Result<PathBuf, String>> + Send>>;

pub trait Runner: Send + Sync + 'static {
    /// Build the firmware, logging through `job`; returns the path of the flashable image.
    fn run(&self, job: Arc<Job>, req: BuildRequest) -> RunFuture;
}

/// Real runner: work copy of `firmware_dir`, `cargo build`, `espflash save-image`.
pub struct CargoRunner {
    pub firmware_dir: PathBuf,
    /// Shared cargo target directory (build cache between jobs).
    pub target_dir: PathBuf,
    pub espflash: PathBuf,
}

impl Runner for CargoRunner {
    fn run(&self, job: Arc<Job>, req: BuildRequest) -> RunFuture {
        let firmware_dir = self.firmware_dir.clone();
        let target_dir = self.target_dir.clone();
        let espflash = self.espflash.clone();
        Box::pin(async move {
            let dir = job.dir.clone();
            let generated = req.generated;
            let dest = dir.clone();
            tokio::task::spawn_blocking(move || build::prepare_work_copy(&firmware_dir, &dest, &generated))
                .await
                .map_err(|e| e.to_string())?
                .map_err(|e| e.to_string())?;
            let plan = build::plan(&req.board, &dir, &target_dir, &espflash);
            run_steps(&plan.steps, &job, &req.secrets).await?;
            if plan.artifact.is_file() {
                Ok(plan.artifact)
            } else {
                Err("build finished but produced no image".to_owned())
            }
        })
    }
}

/// Run steps one after another, streaming stdout/stderr (redacted) into the job log.
pub async fn run_steps(steps: &[Step], job: &Arc<Job>, secrets: &[String]) -> Result<(), String> {
    for step in steps {
        let name = step.program.to_string_lossy().into_owned();
        job.push_line(&build::redact(&format!("$ {name} {}", display_args(step)), secrets));
        let mut cmd = Command::new(&step.program);
        cmd.args(&step.args)
            .current_dir(&step.cwd)
            .envs(step.envs.iter().map(|(k, v)| (k, v)))
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        let mut child = cmd.spawn().map_err(|e| format!("cannot start {name}: {e}"))?;
        let out = child.stdout.take().map(|s| pump(s, job.clone(), secrets.to_vec()));
        let err = child.stderr.take().map(|s| pump(s, job.clone(), secrets.to_vec()));
        let status = child.wait().await.map_err(|e| format!("{name}: {e}"))?;
        if let Some(t) = out {
            let _ = t.await;
        }
        if let Some(t) = err {
            let _ = t.await;
        }
        if !status.success() {
            return Err(format!("{name} failed ({status})"));
        }
    }
    Ok(())
}

fn display_args(step: &Step) -> String {
    step.args.iter().map(|a| a.to_string_lossy()).collect::<Vec<_>>().join(" ")
}

fn pump<R: AsyncRead + Unpin + Send + 'static>(
    reader: R,
    job: Arc<Job>,
    secrets: Vec<String>,
) -> tokio::task::JoinHandle<()> {
    tokio::spawn(async move {
        let mut lines = BufReader::new(reader).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            job.push_line(&build::redact(&line, &secrets));
        }
    })
}
