import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { test } from 'node:test';
import { pinoutSvg } from '../lib/pinout.js';
import {
  fieldsFor, groupDiagnostics, idsOf, instancePath, maskSecrets, newInstance, pathSegments, resolveDiagPath, toConfig,
  toMaskedConfig, toYaml, usedPins,
} from '../lib/model.js';

const dir = new URL('../../schemas/', import.meta.url);
const load = (sub) => readdirSync(new URL(sub, dir)).map((f) => JSON.parse(readFileSync(new URL(sub + f, dir), 'utf8')));
const components = load('components/');
const boards = load('boards/');
// Obviously fake values, built at runtime (they are not credentials).
const WIFI_PW = 'fake'.repeat(3);
const AP_PW = 'dummy'.repeat(2);
const comp = (id) => components.find((c) => c.id === id);

test('every shipped component schema yields a field model', () => {
  for (const c of components) {
    const fields = fieldsFor(c.config, c.pins);
    assert.ok(fields.length > 0, c.id);
    assert.ok(!fields.some((f) => f.key === 'platform'), `${c.id}: platform is fixed`);
  }
});

test('field kinds follow the schema', () => {
  const kinds = (id) => Object.fromEntries(fieldsFor(comp(id).config, comp(id).pins).map((f) => [f.key, f.kind]));
  assert.deepEqual(kinds('wifi'), {
    ssid: 'string', password: 'secret', fallback_ap: 'object', reconnect_interval_s: 'integer',
  });
  assert.equal(kinds('gpio_switch').pin, 'pin');
  assert.equal(kinds('gpio_switch').restore_mode, 'enum');
  assert.equal(kinds('gpio_switch').inverted, 'boolean');
  assert.equal(kinds('bme280').i2c_id, 'ref');
  assert.equal(kinds('bme280').address, 'enum');
  assert.equal(kinds('i2c_bus').sda, 'pin');
  const pin = fieldsFor(comp('gpio_switch').config, comp('gpio_switch').pins).find((f) => f.key === 'pin');
  assert.deepEqual(pin.caps, ['output']);
  const wifi = fieldsFor(comp('wifi').config).find((f) => f.key === 'fallback_ap');
  assert.deepEqual(wifi.children.map((c) => c.kind), ['string', 'secret']);
  assert.equal(wifi.required, false);
});

test('diagnostic paths map to fields, walking up to the nearest known one', () => {
  assert.deepEqual(pathSegments('sensor[0].temperature.name'), ['sensor', '[0]', 'temperature', 'name']);
  const known = new Set(['sensor[0]', 'sensor[0].i2c_id', 'sensor[0].temperature', 'wifi', 'wifi.ssid', 'name']);
  assert.equal(resolveDiagPath('sensor[0].i2c_id', known), 'sensor[0].i2c_id');
  assert.equal(resolveDiagPath('sensor[0].temperature.name', known), 'sensor[0].temperature');
  assert.equal(resolveDiagPath('sensor[0].platform', known), 'sensor[0]');
  assert.equal(resolveDiagPath('wifi', known), 'wifi');
  assert.equal(resolveDiagPath('mqtt', known), '');
  assert.equal(resolveDiagPath('', known), '');
  const g = groupDiagnostics(
    [{ path: 'wifi.ssid', message: 'a' }, { path: 'wifi.ssid', message: 'b' }, { path: '', message: 'c' }], known);
  assert.equal(g.get('wifi.ssid').length, 2);
  assert.equal(g.get('').length, 1);
});

const model = () => ({
  board: 'esp32c6',
  name: 'living-room',
  sections: {
    wifi: { ssid: 'HomeNet', password: WIFI_PW },
    mqtt: { broker: '192.168.1.10' },
    i2c: [{ id: 'bus0', sda: 6, scl: 7 }],
    sensor: [{ platform: 'bme280', id: 'env', i2c_id: 'bus0', temperature: { name: 'Temperature' } }],
    switch: [{ platform: 'gpio', id: 'relay', name: 'Relay', pin: 10, inverted: false }],
  },
});

test('model -> config -> YAML', () => {
  const yaml = toYaml(toConfig(model(), components));
  assert.match(yaml, /^board: esp32c6\nname: living-room\n/);
  assert.match(yaml, new RegExp(`wifi:\\n {2}ssid: HomeNet\\n {2}password: ${WIFI_PW}`));
  assert.match(yaml, /i2c:\n {2}- id: bus0\n {4}sda: 6\n {4}scl: 7/);
  assert.match(yaml, /sensor:\n {2}- platform: bme280\n {4}id: env\n {4}i2c_id: bus0\n {4}temperature:\n {6}name: Temperature/);
  assert.match(yaml, /inverted: false/);
});

test('empty values are dropped and odd strings are quoted', () => {
  const m = model();
  m.sections.mqtt.username = '';
  m.sections.switch[0].name = 'on: "yes"';
  m.name = 'no';
  const yaml = toYaml(toConfig(m, components));
  assert.ok(!yaml.includes('username'));
  assert.match(yaml, /name: "on: \\"yes\\""/);
  assert.match(yaml, /^name: "no"$/m);
});

test('secrets are masked in the preview only', () => {
  const m = model();
  m.sections.wifi.fallback_ap = { ssid: 'AP', password: AP_PW };
  const masked = toYaml(toMaskedConfig(m, components));
  assert.ok(!masked.includes(WIFI_PW) && !masked.includes(AP_PW));
  assert.equal((masked.match(/\*\*\*/g) || []).length, 2);
  assert.ok(toYaml(toConfig(m, components)).includes(WIFI_PW));
  assert.deepEqual(maskSecrets({ a: 'x' }, { properties: { a: { 'x-secret': true } } }), { a: '***' });
});

test('used pins, ids and new instances come from the schemas', () => {
  const m = model();
  const used = usedPins(m, components);
  assert.deepEqual([...used.entries()].sort((a, b) => a[0] - b[0]), [[6, 'i2c[0].sda'], [7, 'i2c[0].scl'], [10, 'switch[0].pin']]);
  assert.deepEqual(idsOf(m, components, 'i2c_bus'), ['bus0']);
  assert.equal(instancePath(comp('wifi'), 0), 'wifi');
  assert.equal(instancePath(comp('bme280'), 2), 'sensor[2]');
  assert.deepEqual(newInstance(comp('gpio_switch'), new Set(['gpio_switch1'])), { platform: 'gpio', id: 'gpio_switch2' });
  assert.deepEqual(newInstance(comp('wifi'), new Set()), {});
});

test('pinout SVG is drawn from the board schema', () => {
  for (const b of boards) {
    const svg = pinoutSvg(b, new Map([[b.pins[0].gpio, 'x']]), ['output']);
    assert.equal((svg.match(/data-gpio=/g) || []).length, b.pins.filter((p) => p.ui).length, b.id);
    assert.match(svg, /class="pin[^"]*used/);
    assert.match(svg, /nofit|fits/);
    assert.match(svg, /flag-strapping/);
  }
});

test('WebSocket URL is relative to the page (ingress) and follows the scheme', async () => {
  const { wsUrl } = await import('../lib/api.js');
  assert.equal(wsUrl('7', new URL('http://h:8099/')), 'ws://h:8099/ws?job=7');
  assert.equal(wsUrl('7', new URL('https://ha.example/api/hassio_ingress/tok/index.html')), 'wss://ha.example/api/hassio_ingress/tok/ws?job=7');
});
