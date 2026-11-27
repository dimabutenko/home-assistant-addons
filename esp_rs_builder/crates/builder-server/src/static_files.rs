//! Minimal static file handler for the web UI (no `tower-http` dependency).
//!
//! Only plain files below the UI directory are served; any request path with an empty, hidden
//! (`.x`), `..`, drive (`:`) or backslash segment is answered with 404.

use std::path::{Path, PathBuf};

use axum::extract::State;
use axum::http::{StatusCode, Uri, header};
use axum::response::{IntoResponse, Response};

use crate::AppState;

/// Map a URL path to a file below `root`; `None` if the path is not safe.
pub(crate) fn resolve(root: &Path, url_path: &str) -> Option<PathBuf> {
    let rel = url_path.strip_prefix('/').unwrap_or(url_path);
    let rel = if rel.is_empty() { "index.html" } else { rel };
    let mut out = root.to_path_buf();
    for seg in rel.split('/') {
        if seg.is_empty() || seg.starts_with('.') || seg.contains(['\\', ':', '\0']) {
            return None;
        }
        out.push(seg);
    }
    Some(out)
}

fn content_type(path: &Path) -> &'static str {
    match path.extension().and_then(|e| e.to_str()) {
        Some("html") => "text/html; charset=utf-8",
        Some("js" | "mjs") => "text/javascript; charset=utf-8",
        Some("css") => "text/css; charset=utf-8",
        Some("json") => "application/json",
        Some("svg") => "image/svg+xml",
        Some("txt" | "md") => "text/plain; charset=utf-8",
        _ => "application/octet-stream",
    }
}

pub async fn serve(State(s): State<AppState>, uri: Uri) -> Response {
    let Some(path) = resolve(&s.ui_dir, uri.path()) else {
        return StatusCode::NOT_FOUND.into_response();
    };
    match tokio::fs::read(&path).await {
        Ok(bytes) => (
            [
                (header::CONTENT_TYPE, content_type(&path)),
                (header::CACHE_CONTROL, "no-cache"),
                (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
            ],
            bytes,
        )
            .into_response(),
        Err(_) => StatusCode::NOT_FOUND.into_response(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolves_plain_paths_and_rejects_escapes() {
        let root = Path::new("ui");
        assert_eq!(resolve(root, "/"), Some(root.join("index.html")));
        assert_eq!(resolve(root, "/lib/model.js"), Some(root.join("lib").join("model.js")));
        for bad in ["/../secret", "/a/../b", "//x", "/.git/config", "/a\\b", "/C:/x", "/a//b"] {
            assert_eq!(resolve(root, bad), None, "{bad}");
        }
    }
}
