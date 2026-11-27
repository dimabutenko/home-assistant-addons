#![no_std]
#![no_main]

mod generated;
mod runtime;

use embassy_executor::Spawner;
use embassy_time::Timer;
use esp_hal::timer::timg::TimerGroup;

use esp_backtrace as _; // panic handler

esp_bootloader_esp_idf::esp_app_desc!();

#[esp_rtos::main]
async fn main(spawner: Spawner) {
    let p = esp_hal::init(esp_hal::Config::default());

    // The RTOS scheduler needs TIMG0 and FROM_CPU_INTR0. Generated code never uses them (no component
    // schema lists them in `firmware.peripherals`), so a second handle to each is sound.
    // SAFETY: neither peripheral is handed to any component by `generated::setup`.
    let (timg0, int0) = unsafe { (p.TIMG0.clone_unchecked(), p.FROM_CPU_INTR0.clone_unchecked()) };
    let timg0 = TimerGroup::new(timg0);
    esp_rtos::start(timg0.timer0, int0);

    log::info!("boot: {} on {}", generated::DEVICE_NAME, generated::BOARD);
    generated::setup(spawner, p).await;

    // All work happens in spawned tasks; keep the main task alive and idle.
    loop {
        Timer::after_secs(3600).await;
    }
}
