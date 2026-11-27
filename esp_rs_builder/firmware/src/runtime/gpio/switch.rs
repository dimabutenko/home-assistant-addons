use esp_hal::gpio::{AnyPin, Level, Output, OutputConfig};

use crate::runtime::entity::Registry;

pub const MAX_SWITCHES: usize = 8;
/// State (`state`) and commands (`command`) of every switch, by `(id, "switch")`.
pub static SWITCHES: Registry<bool, MAX_SWITCHES> = Registry::new();

#[derive(Clone, Copy)]
pub enum RestoreMode {
    AlwaysOff,
    AlwaysOn,
    /// Persistent storage is not available yet: behaves like `AlwaysOff` (logged).
    Restore,
}

pub struct Config {
    pub id: &'static str,
    pub name: &'static str,
    pub inverted: bool,
    pub restore_mode: RestoreMode,
}

pub async fn run(cfg: &'static Config, pin: AnyPin<'static>) {
    let Some(slot) = SWITCHES.claim(cfg.id, "switch") else {
        log::error!("switch `{}`: no free slot (max {})", cfg.id, MAX_SWITCHES);
        return;
    };
    let mut on = match cfg.restore_mode {
        RestoreMode::AlwaysOn => true,
        RestoreMode::AlwaysOff => false,
        RestoreMode::Restore => {
            log::warn!("switch `{}`: restore is not implemented, starting off", cfg.id);
            false
        }
    };
    let level = |on: bool| if on != cfg.inverted { Level::High } else { Level::Low };
    let mut out = Output::new(pin, level(on), OutputConfig::default());
    let state = slot.state.sender();
    state.send(on);
    loop {
        on = slot.command.wait().await;
        out.set_level(level(on));
        state.send(on);
    }
}
