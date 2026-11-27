//! Shared async I2C bus. Devices use `embassy_embedded_hal::shared_bus::asynch::i2c::I2cDevice::new(bus)`.
use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::mutex::Mutex;
use esp_hal::gpio::AnyPin;
use esp_hal::i2c::master::{Config as HalConfig, I2c};
use esp_hal::peripherals::I2C0;
use esp_hal::time::Rate;
use esp_hal::Async;

pub struct Config {
    pub id: &'static str,
    pub frequency_hz: u32,
}

pub type Bus = Mutex<CriticalSectionRawMutex, I2c<'static, Async>>;

/// Argument order is fixed by codegen: config, peripheral, pins by role name (`scl`, then `sda`).
/// A bus that cannot be created is a fatal configuration error: log it and reset (retrying cannot help).
pub fn init(cfg: &Config, i2c: I2C0<'static>, scl: AnyPin<'static>, sda: AnyPin<'static>) -> Bus {
    let hal_cfg = HalConfig::default().with_frequency(Rate::from_hz(cfg.frequency_hz));
    match I2c::new(i2c, hal_cfg) {
        Ok(bus) => Mutex::new(bus.with_scl(scl).with_sda(sda).into_async()),
        Err(_) => {
            log::error!("i2c `{}`: invalid configuration ({} Hz), resetting", cfg.id, cfg.frequency_hz);
            esp_hal::system::software_reset()
        }
    }
}
