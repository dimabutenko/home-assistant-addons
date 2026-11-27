//! MQTT client task (`rust-mqtt`, MQTT 5, static `bump` buffer, no heap) + the Home Assistant link.
//!
//! One session = TCP connect -> MQTT CONNECT (with a retained `offline` last will) -> `online` ->
//! discovery -> subscribe to the switch command topics -> publish state changes / apply commands.
//! Any error ends the session; the task waits and starts a new one.
use core::net::Ipv4Addr;
use core::num::NonZero;
use core::str::FromStr;

use embassy_executor::Spawner;
use embassy_futures::select::{select, Either};
use embassy_net::dns::DnsQueryType;
use embassy_net::tcp::TcpSocket;
use embassy_net::{IpAddress, Stack};
use embassy_time::{Duration, Instant, Timer};
use rust_mqtt::buffer::BumpBuffer;
use rust_mqtt::client::event::Event;
use rust_mqtt::client::options::{
    ConnectOptions, PublicationOptions, SubscriptionOptions, TopicReference, WillOptions,
};
use rust_mqtt::client::Client;
use rust_mqtt::config::KeepAlive;
use rust_mqtt::types::{MqttBinary, MqttString, TopicFilter, TopicName};
use rust_mqtt::Bytes;

use crate::generated::{BOARD, DEVICE_NAME};
use crate::runtime::ha::{self, Entity, HomeAssistantLink, StateTracker, Topics};
use crate::runtime::wifi;

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

const KEEP_ALIVE_S: u16 = 30;
/// How often state changes are collected while the link is idle.
const TICK_MS: u64 = 250;
const RETRY_DELAY_S: u64 = 5;
const SOCKET_BUF: usize = 1024;
const PACKET_BUF: usize = 1024;

type Mqtt<'a, 'c> = Client<'a, 'c, TcpSocket<'a>, BumpBuffer<'c>, 4, 2, 2, 0, 0, 0, 0>;

pub fn start(spawner: Spawner, cfg: &'static Config) {
    match mqtt_task(cfg) {
        Ok(token) => spawner.spawn(token),
        Err(_) => log::error!("mqtt: cannot spawn the client task"),
    }
}

#[embassy_executor::task]
async fn mqtt_task(cfg: &'static Config) {
    let stack = wifi::stack().await;
    loop {
        stack.wait_config_up().await;
        log::info!("mqtt: connecting to {}:{}", cfg.broker, cfg.port);
        match session(stack, cfg).await {
            Ok(()) => log::warn!("mqtt: session closed"),
            Err(why) => log::warn!("mqtt: session ended: {}", why),
        }
        Timer::after_secs(RETRY_DELAY_S).await;
    }
}

async fn resolve(stack: Stack<'static>, host: &str) -> Result<IpAddress, &'static str> {
    if let Ok(ip) = Ipv4Addr::from_str(host) {
        return Ok(IpAddress::Ipv4(ip));
    }
    let found = stack.dns_query(host, DnsQueryType::A).await.map_err(|_| "dns lookup failed")?;
    found.first().copied().ok_or("dns returned no address")
}

/// Publishes through the MQTT client.
struct MqttLink<'l, 'a, 'c> {
    client: &'l mut Mqtt<'a, 'c>,
    topics: Topics,
    board: &'static str,
}

impl MqttLink<'_, '_, '_> {
    async fn publish(&mut self, topic: &str, payload: &[u8], retain: bool) -> Result<(), &'static str> {
        let name = MqttString::try_from(topic).ok().and_then(TopicName::new).ok_or("bad topic")?;
        let mut options = PublicationOptions::new(TopicReference::Name(name));
        if retain {
            options = options.retain();
        }
        self.client.publish(&options, Bytes::from(payload)).await.map_err(|e| {
            log::warn!("mqtt: publish failed: {:?}", e);
            "publish failed"
        })?;
        Ok(())
    }
}

impl HomeAssistantLink for MqttLink<'_, '_, '_> {
    type Error = &'static str;

    async fn publish_discovery(&mut self, entity: &Entity) -> Result<(), Self::Error> {
        let topic = self.topics.discovery(entity);
        let payload = ha::discovery_payload(&self.topics, self.board, entity).ok_or("discovery payload too large")?;
        self.publish(&topic, payload.as_bytes(), true).await
    }

    async fn publish_state(&mut self, entity: &Entity, state: &str) -> Result<(), Self::Error> {
        let topic = self.topics.state(entity);
        self.publish(&topic, state.as_bytes(), true).await
    }
}

async fn session(stack: Stack<'static>, cfg: &'static Config) -> Result<(), &'static str> {
    let topics = Topics { prefix: cfg.topic_prefix, device: DEVICE_NAME, discovery_prefix: cfg.discovery_prefix };
    let ip = resolve(stack, cfg.broker).await?;

    let mut rx = [0u8; SOCKET_BUF];
    let mut tx = [0u8; SOCKET_BUF];
    let mut socket = TcpSocket::new(stack, &mut rx, &mut tx);
    socket.set_timeout(Some(Duration::from_secs(u64::from(KEEP_ALIVE_S) * 2)));
    socket.connect((ip, cfg.port)).await.map_err(|_| "tcp connect failed")?;

    let mut packet = [0u8; PACKET_BUF];
    let mut buffer = BumpBuffer::new(&mut packet);
    let mut client: Mqtt<'_, '_> = Client::new(&mut buffer);

    let availability = topics.availability();
    let will_topic = MqttString::try_from(availability.as_str()).ok().and_then(TopicName::new).ok_or("bad topic")?;
    let will = WillOptions::new(will_topic, MqttBinary::try_from("offline").map_err(|_| "bad will")?).retain();
    let keep_alive = NonZero::new(KEEP_ALIVE_S).map(KeepAlive::Seconds).unwrap_or_default();
    let mut options = ConnectOptions::new().clean_start().keep_alive(keep_alive).will(will);
    if let Some(user) = cfg.username {
        options = options.user_name(MqttString::try_from(user).map_err(|_| "bad username")?);
    }
    if let Some(pass) = cfg.password {
        options = options.password(MqttBinary::try_from(pass).map_err(|_| "bad password")?);
    }
    let client_id = MqttString::try_from(cfg.client_id.unwrap_or(DEVICE_NAME)).map_err(|_| "bad client id")?;
    client.connect(socket, &options, Some(client_id)).await.map_err(|e| {
        log::warn!("mqtt: connect rejected: {:?}", e);
        "mqtt connect failed"
    })?;
    log::info!("mqtt: connected");

    let mut tracker = StateTracker::new();
    {
        let mut link = MqttLink { client: &mut client, topics, board: BOARD };
        link.publish(&availability, b"online", true).await?;
        if cfg.discovery {
            tracker.announce(&mut link).await?;
        }
    }

    let filter = topics.command_filter();
    let filter = MqttString::try_from(filter.as_str()).ok().and_then(TopicFilter::new).ok_or("bad topic")?;
    client.subscribe(filter, &SubscriptionOptions::new()).await.map_err(|e| {
        log::warn!("mqtt: subscribe failed: {:?}", e);
        "subscribe failed"
    })?;

    let ping_every = Duration::from_secs(u64::from(KEEP_ALIVE_S / 2));
    let mut next_ping = Instant::now() + ping_every;
    loop {
        match select(client.poll_header(), Timer::after_millis(TICK_MS)).await {
            Either::First(header) => {
                let header = header.map_err(|e| {
                    log::warn!("mqtt: receive failed: {:?}", e);
                    "receive failed"
                })?;
                let event = client.poll_body(header).await.map_err(|e| {
                    log::warn!("mqtt: bad packet: {:?}", e);
                    "bad packet"
                })?;
                if let Event::Publish(p) = event {
                    if let Some(topic) = p.topic.name() {
                        ha::apply_command(&topics, topic.as_ref().as_str(), &p.message);
                    }
                }
                // SAFETY: the event (the only borrower of the bump buffer) was dropped above.
                unsafe { client.buffer_mut().reset() };
            }
            Either::Second(()) => {
                let mut link = MqttLink { client: &mut client, topics, board: BOARD };
                tracker.flush(&mut link).await?;
                if Instant::now() >= next_ping {
                    client.ping().await.map_err(|_| "ping failed")?;
                    next_ping = Instant::now() + ping_every;
                }
            }
        }
    }
}
