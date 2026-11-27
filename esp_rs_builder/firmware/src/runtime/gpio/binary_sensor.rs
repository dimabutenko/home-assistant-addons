use embassy_time::Timer;
use esp_hal::gpio::{AnyPin, Input, InputConfig, Pull as HalPull};

use crate::runtime::entity::Registry;

pub const MAX_BINARY_SENSORS: usize = 8;
/// Latest state of every binary sensor, by `(id, "binary_sensor")`.
pub static SENSORS: Registry<bool, MAX_BINARY_SENSORS> = Registry::new();

#[derive(Clone, Copy)]
pub enum Pull {
    None,
    Up,
    Down,
}

#[derive(Clone, Copy)]
pub enum DeviceClass {
    Motion,
    Door,
    Window,
    Opening,
    Occupancy,
    Presence,
    Moisture,
    Smoke,
    None,
}

impl DeviceClass {
    /// Home Assistant `device_class` (empty = none).
    pub const fn ha_name(self) -> &'static str {
        match self {
            DeviceClass::Motion => "motion",
            DeviceClass::Door => "door",
            DeviceClass::Window => "window",
            DeviceClass::Opening => "opening",
            DeviceClass::Occupancy => "occupancy",
            DeviceClass::Presence => "presence",
            DeviceClass::Moisture => "moisture",
            DeviceClass::Smoke => "smoke",
            DeviceClass::None => "",
        }
    }
}

pub struct Config {
    pub id: &'static str,
    pub name: &'static str,
    pub pull: Pull,
    pub inverted: bool,
    pub debounce_ms: u32,
    pub device_class: DeviceClass,
}

pub async fn run(cfg: &'static Config, pin: AnyPin<'static>) {
    let Some(slot) = SENSORS.claim(cfg.id, "binary_sensor") else {
        log::error!("binary_sensor `{}`: no free slot (max {})", cfg.id, MAX_BINARY_SENSORS);
        return;
    };
    slot.describe(cfg.name, cfg.device_class.ha_name(), "");
    let pull = match cfg.pull {
        Pull::None => HalPull::None,
        Pull::Up => HalPull::Up,
        Pull::Down => HalPull::Down,
    };
    let mut input = Input::new(pin, InputConfig::default().with_pull(pull));
    let state = slot.state.sender();
    let read = |input: &Input<'_>| input.is_high() != cfg.inverted;
    let mut last = read(&input);
    state.send(last);
    loop {
        input.wait_for_any_edge().await;
        // Debounce: let the line settle, then publish only a real change.
        Timer::after_millis(u64::from(cfg.debounce_ms)).await;
        let now = read(&input);
        if now != last {
            last = now;
            state.send(now);
        }
    }
}
