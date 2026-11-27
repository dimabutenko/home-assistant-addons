//! Stub: the real Wi-Fi connect/reconnect/fallback AP is task 05.
use embassy_executor::Spawner;
use esp_hal::peripherals::WIFI;

pub struct FallbackApConfig {
    pub ssid: &'static str,
    pub password: Option<&'static str>,
}

pub struct Config {
    pub ssid: &'static str,
    pub password: &'static str,
    pub reconnect_interval_s: u32,
    pub fallback_ap: Option<FallbackApConfig>,
}

pub fn start(_spawner: Spawner, cfg: &'static Config, _wifi: WIFI<'static>) {
    log::info!("wifi stub: ssid `{}` (not connected, task 05)", cfg.ssid);
}
