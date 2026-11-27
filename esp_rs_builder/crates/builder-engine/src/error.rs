//! Error and diagnostic types. Every diagnostic carries a YAML path.

use std::fmt;

/// Fatal problems (cannot even attempt validation).
#[derive(Debug, thiserror::Error)]
pub enum EngineError {
    #[error("cannot read {path}: {source}")]
    Io {
        path: String,
        #[source]
        source: std::io::Error,
    },
    #[error("invalid schema file {file}: {message}")]
    Schema { file: String, message: String },
    #[error("invalid YAML: {0}")]
    Yaml(String),
    #[error("code generation failed: {0}")]
    Codegen(String),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Severity {
    Error,
    Warning,
}

/// One validation finding, located by a YAML path such as `sensor[0].i2c_id`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Diagnostic {
    pub severity: Severity,
    pub path: String,
    pub message: String,
}

impl fmt::Display for Diagnostic {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let sev = match self.severity {
            Severity::Error => "error",
            Severity::Warning => "warning",
        };
        let path = if self.path.is_empty() { "<root>" } else { &self.path };
        write!(f, "{sev}: {path}: {}", self.message)
    }
}

/// Result of validation: all diagnostics, errors first by insertion order.
#[derive(Debug, Default)]
pub struct Report {
    pub diagnostics: Vec<Diagnostic>,
}

impl Report {
    pub fn error(&mut self, path: impl Into<String>, message: impl Into<String>) {
        self.push(Severity::Error, path, message);
    }

    pub fn warn(&mut self, path: impl Into<String>, message: impl Into<String>) {
        self.push(Severity::Warning, path, message);
    }

    fn push(&mut self, severity: Severity, path: impl Into<String>, message: impl Into<String>) {
        self.diagnostics.push(Diagnostic {
            severity,
            path: path.into(),
            message: message.into(),
        });
    }

    pub fn has_errors(&self) -> bool {
        self.diagnostics.iter().any(|d| d.severity == Severity::Error)
    }

    pub fn errors(&self) -> impl Iterator<Item = &Diagnostic> {
        self.diagnostics.iter().filter(|d| d.severity == Severity::Error)
    }
}
