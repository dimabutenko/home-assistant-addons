//! BME280 over `embedded-hal-async` I2C, forced mode, integer compensation from the Bosch datasheet (done in i128: cannot overflow).
use embassy_embedded_hal::shared_bus::asynch::i2c::I2cDevice;
use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_time::Timer;
use embedded_hal_async::i2c::I2c;

use crate::runtime::bus::i2c::Bus;
use crate::runtime::entity::{Registry, Slot};

pub const MAX_BME280: usize = 4;
/// Temperature in degrees C, humidity in %RH, pressure in hPa; keys `(id, "temperature" | "humidity" | "pressure")`.
pub static TEMPERATURE: Registry<f32, MAX_BME280> = Registry::new();
pub static HUMIDITY: Registry<f32, MAX_BME280> = Registry::new();
pub static PRESSURE: Registry<f32, MAX_BME280> = Registry::new();

pub struct TemperatureConfig {
    pub name: &'static str,
}
pub struct HumidityConfig {
    pub name: &'static str,
}
pub struct PressureConfig {
    pub name: &'static str,
}

pub struct Config {
    pub id: &'static str,
    pub address: u8,
    pub update_interval_s: u32,
    pub temperature: Option<TemperatureConfig>,
    pub humidity: Option<HumidityConfig>,
    pub pressure: Option<PressureConfig>,
}

const CHIP_ID: u8 = 0x60;
const REG_ID: u8 = 0xD0;
const REG_CALIB_A: u8 = 0x88; // 26 bytes
const REG_CALIB_B: u8 = 0xE1; // 7 bytes
const REG_CTRL_HUM: u8 = 0xF2;
const REG_CTRL_MEAS: u8 = 0xF4;
const REG_DATA: u8 = 0xF7; // 8 bytes
/// osrs_t = x1, osrs_p = x1, mode = forced.
const CTRL_MEAS_FORCED: u8 = 0b001_001_01;
/// Worst-case conversion time for x1/x1/x1 is about 10 ms.
const CONVERSION_MS: u64 = 15;

fn byte(b: &[u8], i: usize) -> i128 {
    i128::from(b.get(i).copied().unwrap_or(0))
}
fn u16_at(b: &[u8], i: usize) -> i128 {
    byte(b, i) | (byte(b, i + 1) << 8)
}
fn i16_at(b: &[u8], i: usize) -> i128 {
    i128::from(u16_at(b, i) as u16 as i16)
}
fn i8_at(b: &[u8], i: usize) -> i128 {
    i128::from(b.get(i).copied().unwrap_or(0) as i8)
}

struct Calib {
    t1: i128, t2: i128, t3: i128,
    p1: i128, p2: i128, p3: i128, p4: i128, p5: i128, p6: i128, p7: i128, p8: i128, p9: i128,
    h1: i128, h2: i128, h3: i128, h4: i128, h5: i128, h6: i128,
}

impl Calib {
    fn parse(a: &[u8; 26], b: &[u8; 7]) -> Self {
        Self {
            t1: u16_at(a, 0), t2: i16_at(a, 2), t3: i16_at(a, 4),
            p1: u16_at(a, 6), p2: i16_at(a, 8), p3: i16_at(a, 10), p4: i16_at(a, 12), p5: i16_at(a, 14),
            p6: i16_at(a, 16), p7: i16_at(a, 18), p8: i16_at(a, 20), p9: i16_at(a, 22),
            h1: byte(a, 25),
            h2: i16_at(b, 0), h3: byte(b, 2),
            h4: (i8_at(b, 3) << 4) | (byte(b, 4) & 0x0F),
            h5: (i8_at(b, 5) << 4) | (byte(b, 4) >> 4),
            h6: i8_at(b, 6),
        }
    }

    /// Returns `(temperature C, humidity %RH, pressure hPa)` from the raw 8 data bytes.
    fn compensate(&self, d: &[u8; 8]) -> (f32, f32, f32) {
        let adc_p = (byte(d, 0) << 12) | (byte(d, 1) << 4) | (byte(d, 2) >> 4);
        let adc_t = (byte(d, 3) << 12) | (byte(d, 4) << 4) | (byte(d, 5) >> 4);
        let adc_h = (byte(d, 6) << 8) | byte(d, 7);

        // Temperature (0.01 C) and t_fine.
        let v1 = (((adc_t >> 3) - (self.t1 << 1)) * self.t2) >> 11;
        let dt = (adc_t >> 4) - self.t1;
        let v2 = (((dt * dt) >> 12) * self.t3) >> 14;
        let t_fine = v1 + v2;
        let temp_c = ((t_fine * 5 + 128) >> 8) as f32 / 100.0;

        // Pressure (Q24.8 Pa); 0 means "invalid" (division by zero guard in the datasheet).
        let mut v1 = t_fine - 128_000;
        let mut v2 = v1 * v1 * self.p6;
        v2 += (v1 * self.p5) << 17;
        v2 += self.p4 << 35;
        v1 = ((v1 * v1 * self.p3) >> 8) + ((v1 * self.p2) << 12);
        v1 = (((1i128 << 47) + v1) * self.p1) >> 33;
        let pressure_hpa = if v1 == 0 {
            0.0
        } else {
            let mut p = 1_048_576 - adc_p;
            p = (((p << 31) - v2) * 3125) / v1;
            let v1 = (self.p9 * (p >> 13) * (p >> 13)) >> 25;
            let v2 = (self.p8 * p) >> 19;
            p = ((p + v1 + v2) >> 8) + (self.p7 << 4);
            p as f32 / 256.0 / 100.0
        };

        // Humidity (Q22.10 %RH).
        let mut x = t_fine - 76_800;
        x = ((((adc_h << 14) - (self.h4 << 20) - (self.h5 * x)) + 16_384) >> 15)
            * (((((((x * self.h6) >> 10) * (((x * self.h3) >> 11) + 32_768)) >> 10) + 2_097_152) * self.h2 + 8_192) >> 14);
        x -= ((((x >> 15) * (x >> 15)) >> 7) * self.h1) >> 4;
        let x = x.clamp(0, 419_430_400);
        let humidity = (x >> 12) as f32 / 1024.0;

        (temp_c, humidity, pressure_hpa)
    }
}

async fn load_calibration<D: I2c>(dev: &mut D, addr: u8) -> Result<Calib, D::Error> {
    let mut id = [0u8; 1];
    dev.write_read(addr, &[REG_ID], &mut id).await?;
    if id != [CHIP_ID] {
        log::warn!("bme280 @0x{:02x}: unexpected chip id 0x{:02x} (BMP280 has no humidity)", addr, id[0]);
    }
    let mut a = [0u8; 26];
    let mut b = [0u8; 7];
    dev.write_read(addr, &[REG_CALIB_A], &mut a).await?;
    dev.write_read(addr, &[REG_CALIB_B], &mut b).await?;
    Ok(Calib::parse(&a, &b))
}

async fn measure<D: I2c>(dev: &mut D, addr: u8, calib: &Calib) -> Result<(f32, f32, f32), D::Error> {
    dev.write(addr, &[REG_CTRL_HUM, 0x01]).await?; // humidity x1; takes effect after ctrl_meas write
    dev.write(addr, &[REG_CTRL_MEAS, CTRL_MEAS_FORCED]).await?;
    Timer::after_millis(CONVERSION_MS).await;
    let mut data = [0u8; 8];
    dev.write_read(addr, &[REG_DATA], &mut data).await?;
    Ok(calib.compensate(&data))
}

fn publish(slot: Option<&'static Slot<f32>>, value: f32) {
    if let Some(slot) = slot {
        slot.state.sender().send(value);
    }
}

pub async fn run(cfg: &'static Config, bus: &'static Bus) {
    let mut dev: I2cDevice<'static, CriticalSectionRawMutex, _> = I2cDevice::new(bus);
    let temperature = cfg.temperature.as_ref().and_then(|_| TEMPERATURE.claim(cfg.id, "temperature"));
    let humidity = cfg.humidity.as_ref().and_then(|_| HUMIDITY.claim(cfg.id, "humidity"));
    let pressure = cfg.pressure.as_ref().and_then(|_| PRESSURE.claim(cfg.id, "pressure"));
    let period_s = u64::from(cfg.update_interval_s.max(1));
    let mut calib: Option<Calib> = None;
    loop {
        if calib.is_none() {
            match load_calibration(&mut dev, cfg.address).await {
                Ok(c) => calib = Some(c),
                Err(e) => log::warn!("bme280 `{}`: calibration read failed: {:?}", cfg.id, e),
            }
        }
        if let Some(c) = calib.as_ref() {
            match measure(&mut dev, cfg.address, c).await {
                Ok((t, h, p)) => {
                    publish(temperature, t);
                    publish(humidity, h);
                    publish(pressure, p);
                }
                Err(e) => {
                    log::warn!("bme280 `{}`: measurement failed: {:?}", cfg.id, e);
                    calib = None; // re-read calibration after a bus error (device may have reset)
                }
            }
        }
        Timer::after_secs(period_s).await;
    }
}
