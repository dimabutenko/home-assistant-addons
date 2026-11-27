//! Per-entity state/command channels without heap: a fixed array of slots per entity type.
//! A task claims a slot by `(id, aspect)`; later tasks (MQTT / HA) look slots up with `find`.
use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::once_lock::OnceLock;
use embassy_sync::signal::Signal;
use embassy_sync::watch::Watch;

/// Receivers per `Watch` (MQTT publisher + HA link + spare).
const WATCH_RECEIVERS: usize = 3;

pub struct Slot<T: Clone> {
    key: OnceLock<(&'static str, &'static str)>,
    /// Latest value (state).
    pub state: Watch<CriticalSectionRawMutex, T, WATCH_RECEIVERS>,
    /// Latest command (only used by actuators such as switches).
    pub command: Signal<CriticalSectionRawMutex, T>,
}

impl<T: Clone> Slot<T> {
    pub const fn new() -> Self {
        Self { key: OnceLock::new(), state: Watch::new(), command: Signal::new() }
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

    pub fn find(&'static self, id: &str, aspect: &str) -> Option<&'static Slot<T>> {
        self.slots
            .iter()
            .find(|slot| matches!(slot.key.try_get(), Some((i, a)) if *i == id && *a == aspect))
    }
}
