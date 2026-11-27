//! Runtime: the surface called by `generated.rs` (see ARCHITECTURE "Codegen contract").
//! Wi-Fi and MQTT are stubs until task 05.
// Registries and stub config fields are consumed by the MQTT/HA link in task 05.
#![allow(dead_code)]

pub mod bus;
pub mod drivers;
pub mod entity;
pub mod gpio;
pub mod mqtt;
pub mod wifi;
