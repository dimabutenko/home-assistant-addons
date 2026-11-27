//! Per-entity state/command channels without heap: a fixed array of slots per entity type.
//! A task claims a slot by `(id, aspect)`; later tasks (MQTT / HA) look slots up with `find`.
use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::once_lock::OnceLock;
use embassy_sync::signal::Signal;
use embassy_sync::watch::Watch;

/// Receivers per `Watch` (MQTT publisher + HA link + spare).
const WATCH_RECEIVERS: usize = 3;

/// Human-facing description of an entity, set once by the task that owns the slot.
#[derive(Clone, Copy)]
pub struct Meta {
    pub name: &'static str,
    /// Home Assistant `device_class` (empty = none).
    pub device_class: &'static str,
    /// Unit of measurement (empty = none).
    pub unit: &'static str,
}

pub struct Slot<T: Clone> {
    key: OnceLock<(&'static str, &'static str)>,
    meta: OnceLock<Meta>,
    /// Latest value (state).
    pub state: Watch<CriticalSectionRawMutex, T, WATCH_RECEIVERS>,
    /// Latest command (only used by actuators such as switches).
    pub command: Signal<CriticalSectionRawMutex, T>,
}

impl<T: Clone> Slot<T> {
    /// `(id, aspect)` once claimed.
    pub fn key(&self) -> Option<(&'static str, &'static str)> {
        self.key.try_get().copied()
    }

    /// Description set by `describe` (`None` until the owner task has run).
    pub fn meta(&self) -> Option<Meta> {
        self.meta.try_get().copied()
    }

    /// Sets the description once; a second call is ignored.
    pub fn describe(&self, name: &'static str, device_class: &'static str, unit: &'static str) {
        let _ = self.meta.init(Meta { name, device_class, unit });
    }

    pub const fn new() -> Self {
        Self { key: OnceLock::new(), meta: OnceLock::new(), state: Watch::new(), command: Signal::new() }
    }
}

pub struct Registry<T: Clone + 'static, const N: usize> {
    slots: [Slot<T>; N],
}

impl<T: Clone + 'static, const N: usize> Registry<T, N> {
    pub const fn new() -> Self {
        Self { slots: [const { Slot::new() }; N] }
    }

    /// Claims a free slot for `(id, aspect)`. `None` if the registry is full or the key is taken.
    pub fn claim(&'static self, id: &'static str, aspect: &'static str) -> Option<&'static Slot<T>> {
        if self.find(id, aspect).is_some() {
            return None;
        }
        self.slots.iter().find(|slot| slot.key.init((id, aspect)).is_ok())
    }

    /// All claimed slots in claim order of the array (stable).
    pub fn iter(&'static self) -> impl Iterator<Item = &'static Slot<T>> {
        self.slots.iter().filter(|slot| slot.key.try_get().is_some())
    }

    pub fn find(&'static self, id: &str, aspect: &str) -> Option<&'static Slot<T>> {
        self.slots
            .iter()
            .find(|slot| matches!(slot.key.try_get(), Some((i, a)) if *i == id && *a == aspect))
    }
}
