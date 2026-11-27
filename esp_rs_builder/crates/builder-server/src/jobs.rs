//! Job state: one build at a time, bounded log ring buffer, broadcast to WebSocket subscribers.

use std::collections::VecDeque;
use std::path::PathBuf;
use std::sync::{Arc, Mutex, MutexGuard};

use serde::Serialize;
use tokio::sync::broadcast;

/// Lines kept per job for late subscribers.
pub const LOG_CAPACITY: usize = 2000;
/// Longer lines are cut (cargo can print very long lines).
pub const MAX_LINE_LEN: usize = 4096;
/// Finished jobs (and their work directories) kept.
pub const KEEP_JOBS: usize = 5;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Status {
    Queued,
    Running,
    Succeeded,
    Failed,
}

impl Status {
    pub fn is_final(self) -> bool {
        matches!(self, Status::Succeeded | Status::Failed)
    }
}

#[derive(Debug, Clone)]
pub enum Event {
    Line(String),
    Status(Status),
}

struct Inner {
    status: Status,
    lines: VecDeque<String>,
    artifact: Option<PathBuf>,
}

pub struct Job {
    pub id: String,
    pub dir: PathBuf,
    inner: Mutex<Inner>,
    tx: broadcast::Sender<Event>,
}

/// Late-subscriber view: buffered lines, the status at that moment and the live stream.
pub struct Subscription {
    pub lines: Vec<String>,
    pub status: Status,
    pub rx: broadcast::Receiver<Event>,
}

fn lock<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

impl Job {
    fn new(id: String, dir: PathBuf) -> Self {
        let (tx, _) = broadcast::channel(256);
        Job {
            id,
            dir,
            inner: Mutex::new(Inner {
                status: Status::Queued,
                lines: VecDeque::new(),
                artifact: None,
            }),
            tx,
        }
    }

    pub fn status(&self) -> Status {
        lock(&self.inner).status
    }

    pub fn artifact(&self) -> Option<PathBuf> {
        lock(&self.inner).artifact.clone()
    }

    pub fn push_line(&self, line: &str) {
        let mut line = line.to_owned();
        if line.len() > MAX_LINE_LEN {
            let mut cut = MAX_LINE_LEN;
            while !line.is_char_boundary(cut) {
                cut -= 1;
            }
            line.truncate(cut);
            line.push_str(" …");
        }
        let mut g = lock(&self.inner);
        if g.lines.len() == LOG_CAPACITY {
            g.lines.pop_front();
        }
        g.lines.push_back(line.clone());
        // Sent under the lock so a subscriber never sees a gap or a duplicate.
        let _ = self.tx.send(Event::Line(line));
    }

    pub fn set_status(&self, status: Status) {
        let mut g = lock(&self.inner);
        g.status = status;
        let _ = self.tx.send(Event::Status(status));
    }

    pub fn finish_ok(&self, artifact: PathBuf) {
        let mut g = lock(&self.inner);
        g.artifact = Some(artifact);
        g.status = Status::Succeeded;
        let _ = self.tx.send(Event::Status(Status::Succeeded));
    }

    pub fn subscribe(&self) -> Subscription {
        let g = lock(&self.inner);
        Subscription {
            lines: g.lines.iter().cloned().collect(),
            status: g.status,
            rx: self.tx.subscribe(),
        }
    }
}

struct Store {
    jobs: VecDeque<Arc<Job>>,
    next: u64,
    busy: bool,
}

pub struct Jobs {
    root: PathBuf,
    store: Mutex<Store>,
}

impl Jobs {
    /// `root` holds one directory per job; leftovers of a previous run are removed.
    pub fn new(root: PathBuf) -> Self {
        let _ = std::fs::remove_dir_all(&root);
        Jobs {
            root,
            store: Mutex::new(Store {
                jobs: VecDeque::new(),
                next: 1,
                busy: false,
            }),
        }
    }

    /// Register a new job, or `None` while another one is queued or running.
    pub fn start(&self) -> Option<Arc<Job>> {
        let mut s = lock(&self.store);
        if s.busy {
            return None;
        }
        s.busy = true;
        let id = s.next.to_string();
        s.next += 1;
        let job = Arc::new(Job::new(id.clone(), self.root.join(&id)));
        s.jobs.push_back(job.clone());
        while s.jobs.len() > KEEP_JOBS {
            if let Some(old) = s.jobs.pop_front() {
                let _ = std::fs::remove_dir_all(&old.dir);
            }
        }
        Some(job)
    }

    /// Called when a job reached a final status.
    pub fn release(&self) {
        lock(&self.store).busy = false;
    }

    pub fn get(&self, id: &str) -> Option<Arc<Job>> {
        lock(&self.store).jobs.iter().find(|j| j.id == id).cloned()
    }
}
