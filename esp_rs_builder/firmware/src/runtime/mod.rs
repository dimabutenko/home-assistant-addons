//! Runtime: the surface called by `generated.rs` (see ARCHITECTURE "Codegen contract").
// Some registry/meta accessors are only used by the HA link of particular configurations.
#![allow(dead_code)]

pub mod bus;
pub mod drivers;
pub mod entity;
pub mod gpio;
pub mod ha;
pub mod mqtt;
pub mod wifi;
