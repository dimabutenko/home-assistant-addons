//! Stub: the real MQTT client with Home Assistant discovery is task 05.
use embassy_executor::Spawner;

pub struct Config {
    pub broker: &'static str,
    pub port: u16,
    pub username: Option<&'static str>,
    pub password: Option<&'static str>,
    pub client_id: Option<&'static str>,
    pub topic_prefix: &'static str,
    pub discovery: bool,
    pub discovery_prefix: &'static str,
}

pub fn start(_spawner: Spawner, cfg: &'static Config) {
    log::info!("mqtt stub: broker {}:{} (not connected, task 05)", cfg.broker, cfg.port);
}
