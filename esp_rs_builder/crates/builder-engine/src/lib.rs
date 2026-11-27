//! builder-engine: YAML parsing, schema/pin validation, codegen, build driver.
//! Implemented incrementally; see docs/tasks/.

pub mod codegen;
pub mod error;
pub mod model;
pub mod schema;
pub mod validate;

pub use codegen::generate;
pub use error::{Diagnostic, EngineError, Report, Severity};
pub use model::{ComponentModel, DeviceModel, load_and_validate};
pub use schema::Registry;
pub use validate::{validate, validate_str};
