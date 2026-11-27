//! Home Assistant link: topic layout, MQTT Auto-Discovery payloads, state formatting and the
//! bridge between the entity registries and a transport.
//!
//! Everything here is transport independent: a backend (MQTT today, a native HA API or Matter later)
//! implements [`HomeAssistantLink`]. No heap: payloads are built in fixed `heapless` buffers.
use core::fmt::Write;

use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::watch::Receiver;
use heapless::{String, Vec};

use crate::runtime::drivers::bme280::{HUMIDITY, MAX_BME280, PRESSURE, TEMPERATURE};
use crate::runtime::entity::{Meta, Slot};
use crate::runtime::gpio::binary_sensor::{MAX_BINARY_SENSORS, SENSORS};
use crate::runtime::gpio::switch::{MAX_SWITCHES, SWITCHES};

pub const TOPIC_CAP: usize = 128;
pub const PAYLOAD_CAP: usize = 640;
/// Must match `entity::WATCH_RECEIVERS`.
const RECEIVERS: usize = 3;
const MAX_NUMERIC: usize = 3 * MAX_BME280;

pub type Topic = String<TOPIC_CAP>;
pub type Payload = String<PAYLOAD_CAP>;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Kind {
    Switch,
    BinarySensor,
    Sensor,
}

impl Kind {
    /// Home Assistant MQTT component name.
    pub const fn component(self) -> &'static str {
        match self {
            Kind::Switch => "switch",
            Kind::BinarySensor => "binary_sensor",
            Kind::Sensor => "sensor",
        }
    }
}

/// One entity as seen by a link.
#[derive(Clone, Copy)]
pub struct Entity {
    pub kind: Kind,
    pub id: &'static str,
    /// `"switch"`, `"binary_sensor"`, `"temperature"`, ...
    pub aspect: &'static str,
    pub meta: Meta,
}

impl Entity {
    /// Unique object id inside the device: sensors with several aspects get `<id>_<aspect>`.
    fn write_object_id(&self, out: &mut impl Write) -> core::fmt::Result {
        match self.kind {
            Kind::Sensor => write!(out, "{}_{}", self.id, self.aspect),
            _ => out.write_str(self.id),
        }
    }
}

/// Transport-independent contract of a Home Assistant backend.
#[allow(async_fn_in_trait)]
pub trait HomeAssistantLink {
    type Error: core::fmt::Debug;
    /// Publish the (retained) discovery message of one entity.
    async fn publish_discovery(&mut self, entity: &Entity) -> Result<(), Self::Error>;
    /// Publish the state of one entity (`ON`/`OFF` or a decimal number).
    async fn publish_state(&mut self, entity: &Entity, state: &str) -> Result<(), Self::Error>;
}

/// Topic layout: `<prefix>/<device>/...`; discovery under `<discovery_prefix>/<component>/<device>_<object>/config`.
#[derive(Clone, Copy)]
pub struct Topics {
    pub prefix: &'static str,
    pub device: &'static str,
    pub discovery_prefix: &'static str,
}

impl Topics {
    pub fn availability(&self) -> Topic {
        let mut t = Topic::new();
        let _ = write!(t, "{}/{}/status", self.prefix, self.device);
        t
    }

    pub fn state(&self, e: &Entity) -> Topic {
        let mut t = Topic::new();
        let _ = write!(t, "{}/{}/{}/", self.prefix, self.device, e.kind.component());
        let _ = e.write_object_id(&mut t);
        let _ = t.push_str("/state");
        t
    }

    pub fn command(&self, e: &Entity) -> Topic {
        let mut t = Topic::new();
        let _ = write!(t, "{}/{}/{}/{}/set", self.prefix, self.device, e.kind.component(), e.id);
        t
    }

    /// Subscription filter that covers the command topic of every switch.
    pub fn command_filter(&self) -> Topic {
        let mut t = Topic::new();
        let _ = write!(t, "{}/{}/switch/+/set", self.prefix, self.device);
        t
    }

    pub fn discovery(&self, e: &Entity) -> Topic {
        let mut t = Topic::new();
        let _ = write!(t, "{}/{}/{}_", self.discovery_prefix, e.kind.component(), self.device);
        let _ = e.write_object_id(&mut t);
        let _ = t.push_str("/config");
        t
    }

    /// Returns the switch id when `topic` is `<prefix>/<device>/switch/<id>/set`.
    pub fn command_target<'t>(&self, topic: &'t str) -> Option<&'t str> {
        let mut head = Topic::new();
        write!(head, "{}/{}/switch/", self.prefix, self.device).ok()?;
        let id = topic.strip_prefix(head.as_str())?.strip_suffix("/set")?;
        (!id.is_empty() && !id.contains('/')).then_some(id)
    }
}

/// Writes `s` as a JSON string literal (quotes included).
fn json_str(out: &mut impl Write, s: &str) -> core::fmt::Result {
    out.write_char('"')?;
    for c in s.chars() {
        match c {
            '"' => out.write_str("\\\"")?,
            '\\' => out.write_str("\\\\")?,
            c if (c as u32) < 0x20 => write!(out, "\\u{:04x}", c as u32)?,
            c => out.write_char(c)?,
        }
    }
    out.write_char('"')
}

/// Builds the Auto-Discovery payload. `None` if it does not fit the buffer.
pub fn discovery_payload(topics: &Topics, board: &str, e: &Entity) -> Option<Payload> {
    let mut p = Payload::new();
    build_discovery(&mut p, topics, board, e).ok()?;
    Some(p)
}

fn build_discovery(p: &mut Payload, topics: &Topics, board: &str, e: &Entity) -> core::fmt::Result {
    p.write_str("{\"name\":")?;
    json_str(p, e.meta.name)?;
    p.write_str(",\"uniq_id\":\"")?;
    p.write_str(topics.device)?;
    p.write_char('_')?;
    e.write_object_id(p)?;
    p.write_str("\",\"stat_t\":")?;
    json_str(p, &topics.state(e))?;
    p.write_str(",\"avty_t\":")?;
    json_str(p, &topics.availability())?;
    if e.kind == Kind::Switch {
        p.write_str(",\"cmd_t\":")?;
        json_str(p, &topics.command(e))?;
    }
    if e.kind != Kind::Sensor {
        p.write_str(",\"pl_on\":\"ON\",\"pl_off\":\"OFF\"")?;
    }
    if e.kind == Kind::Switch {
        p.write_str(",\"stat_on\":\"ON\",\"stat_off\":\"OFF\"")?;
    }
    if !e.meta.device_class.is_empty() {
        p.write_str(",\"dev_cla\":")?;
        json_str(p, e.meta.device_class)?;
    }
    if e.kind == Kind::Sensor {
        p.write_str(",\"stat_cla\":\"measurement\"")?;
        if !e.meta.unit.is_empty() {
            p.write_str(",\"unit_of_meas\":")?;
            json_str(p, e.meta.unit)?;
        }
    }
    p.write_str(",\"dev\":{\"ids\":[")?;
    json_str(p, topics.device)?;
    p.write_str("],\"name\":")?;
    json_str(p, topics.device)?;
    p.write_str(",\"mf\":\"esp_rs_builder\",\"mdl\":")?;
    json_str(p, board)?;
    p.write_str("}}")?;
    Ok(())
}

/// `ON` / `OFF` command payload (case-insensitive, as sent by Home Assistant).
pub fn parse_command(payload: &[u8]) -> Option<bool> {
    if payload.eq_ignore_ascii_case(b"ON") {
        Some(true)
    } else if payload.eq_ignore_ascii_case(b"OFF") {
        Some(false)
    } else {
        None
    }
}

/// Applies a command received on `topic` to the matching switch. Returns `true` if it was applied.
pub fn apply_command(topics: &Topics, topic: &str, payload: &[u8]) -> bool {
    let Some(id) = topics.command_target(topic) else {
        return false;
    };
    let Some(on) = parse_command(payload) else {
        log::warn!("ha: ignoring a command with an invalid payload for `{}`", id);
        return false;
    };
    match SWITCHES.find(id, "switch") {
        Some(slot) => {
            slot.command.signal(on);
            true
        }
        None => {
            log::warn!("ha: command for unknown switch `{}`", id);
            false
        }
    }
}

type Rx<T> = Receiver<'static, CriticalSectionRawMutex, T, RECEIVERS>;

/// Receivers of every registered entity. Create one per link session: a fresh tracker reports every
/// current value once, so a reconnect republishes all states.
pub struct StateTracker {
    switches: Vec<(Entity, Rx<bool>), MAX_SWITCHES>,
    binary: Vec<(Entity, Rx<bool>), MAX_BINARY_SENSORS>,
    numeric: Vec<(Entity, Rx<f32>), MAX_NUMERIC>,
}

fn track<T: Clone + 'static, const N: usize>(
    out: &mut Vec<(Entity, Rx<T>), N>,
    slots: impl Iterator<Item = &'static Slot<T>>,
    kind: Kind,
) {
    for slot in slots {
        let (Some((id, aspect)), Some(meta)) = (slot.key(), slot.meta()) else {
            continue; // not fully initialised yet (its task has not run): picked up on the next session
        };
        let Some(rx) = slot.state.receiver() else {
            log::warn!("ha: no free state receiver for `{}`", id);
            continue;
        };
        if out.push((Entity { kind, id, aspect, meta }, rx)).is_err() {
            log::warn!("ha: too many entities, `{}` is not tracked", id);
        }
    }
}

impl StateTracker {
    pub fn new() -> Self {
        let mut t = Self { switches: Vec::new(), binary: Vec::new(), numeric: Vec::new() };
        track(&mut t.switches, SWITCHES.iter(), Kind::Switch);
        track(&mut t.binary, SENSORS.iter(), Kind::BinarySensor);
        track(&mut t.numeric, TEMPERATURE.iter(), Kind::Sensor);
        track(&mut t.numeric, HUMIDITY.iter(), Kind::Sensor);
        track(&mut t.numeric, PRESSURE.iter(), Kind::Sensor);
        t
    }

    pub fn entities(&self) -> impl Iterator<Item = Entity> + '_ {
        self.switches
            .iter()
            .map(|(e, _)| *e)
            .chain(self.binary.iter().map(|(e, _)| *e))
            .chain(self.numeric.iter().map(|(e, _)| *e))
    }

    /// Publishes the discovery message of every tracked entity.
    pub async fn announce<L: HomeAssistantLink>(&self, link: &mut L) -> Result<(), L::Error> {
        for e in self.entities() {
            link.publish_discovery(&e).await?;
        }
        Ok(())
    }

    /// Publishes every state that changed since the last call (all of them on the first call).
    pub async fn flush<L: HomeAssistantLink>(&mut self, link: &mut L) -> Result<(), L::Error> {
        for (e, rx) in self.switches.iter_mut().chain(self.binary.iter_mut()) {
            if let Some(on) = rx.try_changed() {
                link.publish_state(e, if on { "ON" } else { "OFF" }).await?;
            }
        }
        for (e, rx) in self.numeric.iter_mut() {
            if let Some(v) = rx.try_changed() {
                let mut s: String<24> = String::new();
                if v.is_finite() && write!(s, "{:.2}", v).is_ok() {
                    link.publish_state(e, &s).await?;
                }
            }
        }
        Ok(())
    }
}
