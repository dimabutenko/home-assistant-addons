//! Wi-Fi: station with DHCP (embassy-net), reconnect loop and an optional fallback access point.
//!
//! The radio driver (`esp-radio`) needs a heap; `main.rs` installs a small `esp-alloc` heap for it
//! (documented decision in HANDOFF). Nothing else in the runtime allocates.
//! Secrets (the passwords) are never logged.
use embassy_executor::Spawner;
use embassy_net::{Ipv4Address, Ipv4Cidr, Runner, Stack, StackResources, StaticConfigV4};
use embassy_sync::once_lock::OnceLock;
use embassy_time::Timer;
use esp_hal::peripherals::WIFI;
use esp_hal::rng::Rng;
use esp_radio::wifi::ap::AccessPointConfig;
use esp_radio::wifi::sta::StationConfig;
use esp_radio::wifi::{AuthenticationMethodConfig, Config as RadioConfig, ControllerConfig, Interface, WifiController};
use static_cell::StaticCell;

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

/// Failed connection attempts in a row before the fallback AP is raised.
const FALLBACK_AFTER_FAILURES: u32 = 3;
/// Static address of the fallback AP (there is no DHCP server: clients must use a static IP).
const AP_ADDRESS: Ipv4Address = Ipv4Address::new(192, 168, 4, 1);

static STA_RESOURCES: StaticCell<StackResources<6>> = StaticCell::new();
static AP_RESOURCES: StaticCell<StackResources<3>> = StaticCell::new();

/// `Stack` is `!Sync` (it wraps a `RefCell`). It is only ever touched from the single-core thread-mode
/// executor that runs every task, so sharing it through a `static` is sound here.
struct SharedStack(OnceLock<Stack<'static>>);
// SAFETY: single-core, single-executor firmware (see above); no interrupt handler touches the stack.
unsafe impl Sync for SharedStack {}
static STA_STACK: SharedStack = SharedStack(OnceLock::new());

/// The station network stack; resolves as soon as `start` has created it (the link may still be down:
/// use `Stack::wait_config_up`).
pub async fn stack() -> Stack<'static> {
    *STA_STACK.0.get().await
}

pub fn start(spawner: Spawner, cfg: &'static Config, wifi: WIFI<'static>) {
    let controller = match WifiController::new(wifi, ControllerConfig::default()) {
        Ok(c) => c,
        Err(e) => {
            log::error!("wifi: radio init failed: {:?}", e);
            return;
        }
    };
    let rng = Rng::new();
    let seed = (u64::from(rng.random()) << 32) | u64::from(rng.random());

    let Some(sta) = Interface::try_station() else {
        log::error!("wifi: station interface unavailable");
        return;
    };
    let (sta_stack, sta_runner) = embassy_net::new(
        sta,
        embassy_net::Config::dhcpv4(Default::default()),
        STA_RESOURCES.init(StackResources::new()),
        seed,
    );
    let _ = STA_STACK.0.init(sta_stack);
    spawn_net(spawner, sta_runner);

    if cfg.fallback_ap.is_some() {
        match Interface::try_access_point() {
            Some(ap) => {
                let (_ap_stack, ap_runner) = embassy_net::new(
                    ap,
                    embassy_net::Config::ipv4_static(StaticConfigV4 {
                        address: Ipv4Cidr::new(AP_ADDRESS, 24),
                        gateway: None,
                        dns_servers: Default::default(),
                    }),
                    AP_RESOURCES.init(StackResources::new()),
                    seed.rotate_left(17),
                );
                spawn_net(spawner, ap_runner);
            }
            None => log::error!("wifi: access point interface unavailable, fallback AP disabled"),
        }
    }

    match connection_task(controller, cfg) {
        Ok(token) => spawner.spawn(token),
        Err(_) => log::error!("wifi: cannot spawn the connection task"),
    }
}

fn spawn_net(spawner: Spawner, runner: Runner<'static, Interface>) {
    match net_task(runner) {
        Ok(token) => spawner.spawn(token),
        Err(_) => log::error!("wifi: cannot spawn a network task"),
    }
}

#[embassy_executor::task(pool_size = 2)]
async fn net_task(mut runner: Runner<'static, Interface>) {
    runner.run().await
}

fn authentication(password: &str) -> Option<AuthenticationMethodConfig> {
    if password.is_empty() {
        return Some(AuthenticationMethodConfig::Open);
    }
    password.try_into().ok().map(AuthenticationMethodConfig::WpaWpa2Personal)
}

fn station_config(cfg: &Config) -> Option<StationConfig> {
    Some(
        StationConfig::default()
            .with_ssid(cfg.ssid.try_into().ok()?)
            .with_authentication(authentication(cfg.password)?),
    )
}

fn access_point_config(ap: &FallbackApConfig) -> Option<AccessPointConfig> {
    let auth = match ap.password {
        Some(p) => authentication(p)?,
        None => AuthenticationMethodConfig::Open,
    };
    Some(AccessPointConfig::default().with_ssid(ap.ssid.try_into().ok()?).with_authentication(auth))
}

#[embassy_executor::task]
async fn connection_task(mut controller: WifiController<'static>, cfg: &'static Config) {
    let Some(sta) = station_config(cfg) else {
        log::error!("wifi: invalid station SSID or password (length), not connecting");
        return;
    };
    if let Err(e) = controller.set_config(&RadioConfig::Station(sta.clone())) {
        log::error!("wifi: cannot apply station config: {:?}", e);
        return;
    }
    let interval = u64::from(cfg.reconnect_interval_s.max(1));
    let mut failures: u32 = 0;
    let mut ap_up = false;
    loop {
        match controller.connect_async().await {
            Ok(_) => {
                failures = 0;
                log::info!("wifi: connected to `{}`", cfg.ssid);
                match controller.wait_for_disconnect_async().await {
                    Ok(info) => log::warn!("wifi: disconnected ({:?})", info.reason),
                    Err(e) => log::warn!("wifi: link lost ({:?})", e),
                }
            }
            Err(e) => {
                failures = failures.saturating_add(1);
                log::warn!("wifi: connect failed ({:?}), attempt {}", e, failures);
                if failures >= FALLBACK_AFTER_FAILURES && !ap_up {
                    ap_up = raise_fallback_ap(&mut controller, cfg, &sta);
                }
            }
        }
        Timer::after_secs(interval).await;
    }
}

/// Switches to station + access point. Returns `true` when the AP is up.
fn raise_fallback_ap(controller: &mut WifiController<'static>, cfg: &Config, sta: &StationConfig) -> bool {
    let Some(ap) = cfg.fallback_ap.as_ref() else {
        return false;
    };
    let Some(ap_cfg) = access_point_config(ap) else {
        log::error!("wifi: invalid fallback AP SSID or password (length)");
        return false;
    };
    match controller.set_config(&RadioConfig::AccessPointStation(sta.clone(), ap_cfg)) {
        Ok(()) => {
            log::warn!("wifi: fallback AP `{}` is up (192.168.4.1/24, static IP, no DHCP server)", ap.ssid);
            true
        }
        Err(e) => {
            log::error!("wifi: cannot start the fallback AP: {:?}", e);
            false
        }
    }
}
