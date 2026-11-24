// LED position scan: detection library (pure functions, testable) + the Scan tab UI.
'use strict';

const ScanLib = (() => {
  const grayDecode = g => { let b = 0; for (; g; g >>= 1) b ^= g; return b; };

  function blur3(src, w, h) {
    const tmp = new Float32Array(w * h), out = new Float32Array(w * h);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const i = y * w + x;
      tmp[i] = (src[i - (x > 0 ? 1 : 0)] + src[i] + src[i + (x < w - 1 ? 1 : 0)]) / 3;
    }
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const i = y * w + x;
      out[i] = (tmp[i - (y > 0 ? w : 0)] + tmp[i] + tmp[i + (y < h - 1 ? w : 0)]) / 3;
    }
    return out;
  }

  function percentile(arr, p) {
    const hist = new Uint32Array(256);
    for (let i = 0; i < arr.length; i++) hist[Math.min(255, Math.round(arr[i]))]++;
    let target = arr.length * p / 100, acc = 0;
    for (let v = 0; v < 256; v++) { acc += hist[v]; if (acc >= target) return v; }
    return 255;
  }

  // Connected components (8-neighbourhood) of mask; returns labels (0 = background) and the count.
  function components(mask, w, h) {
    const labels = new Int32Array(w * h);
    let count = 0; const stack = [];
    for (let s = 0; s < w * h; s++) {
      if (!mask[s] || labels[s]) continue;
      count++; labels[s] = count; stack.push(s);
      while (stack.length) {
        const i = stack.pop(), x = i % w, y = (i - x) / w;
        for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
          const nx = x + dx, ny = y + dy;
          if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
          const j = ny * w + nx;
          if (mask[j] && !labels[j]) { labels[j] = count; stack.push(j); }
        }
      }
    }
    return { labels, count };
  }

  function otsu(values, lo = 0.25, hi = 0.75) {
    if (values.length < 4) return 0.5;
    const bins = 32, hist = new Array(bins).fill(0);
    for (const v of values) hist[Math.min(bins - 1, Math.max(0, Math.floor(v * bins)))]++;
    const total = values.length; let sum = 0; for (let i = 0; i < bins; i++) sum += i * hist[i];
    let wB = 0, sumB = 0, best = 0, thr = bins / 2;
    for (let i = 0; i < bins; i++) {
      wB += hist[i]; if (!wB) continue;
      const wF = total - wB; if (!wF) break;
      sumB += i * hist[i];
      const mB = sumB / wB, mF = (sum - sumB) / wF, between = wB * wF * (mB - mF) ** 2;
      if (between > best) { best = between; thr = i + 1; }
    }
    return Math.min(hi, Math.max(lo, thr / bins));
  }

  // dark, all: gray frames (Uint8/Float arrays). bits[k]: frame where LED i is on if bit k of gray(i) is set.
  function detect({ w, h, dark, all, bits, n }) {
    const N = w * h, ref = new Float32Array(N);
    for (let i = 0; i < N; i++) ref[i] = Math.max(0, all[i] - dark[i]);
    const blurred = blur3(ref, w, h);
    const peak = percentile(blurred, 99.9), T = Math.max(8, 0.25 * peak);
    const mask = new Uint8Array(N); for (let i = 0; i < N; i++) mask[i] = blurred[i] > T ? 1 : 0;
    const { labels, count } = components(mask, w, h);
    const area = new Float64Array(count + 1), sx = new Float64Array(count + 1), sy = new Float64Array(count + 1), sw = new Float64Array(count + 1);
    const sp = bits.map(() => new Float64Array(count + 1));
    for (let i = 0; i < N; i++) {
      const l = labels[i]; if (!l) continue;
      const x = i % w, y = (i - x) / w, r = ref[i];
      area[l]++; sx[l] += x * r; sy[l] += y * r; sw[l] += r;
      for (let k = 0; k < bits.length; k++) sp[k][l] += Math.max(0, bits[k][i] - dark[i]);
    }
    const comps = [];
    for (let l = 1; l <= count; l++) if (area[l] >= 2 && sw[l] > 0) comps.push(l);
    const areas = comps.map(l => area[l]).sort((a, b) => a - b), med = areas[areas.length >> 1] || 1;
    const ratios = bits.map((_, k) => comps.map(l => Math.min(1.5, sp[k][l] / sw[l])));
    const thr = ratios.map(r => otsu(r));
    const byIdx = new Map(); let invalid = 0, merged = 0, uncertain = 0;
    comps.forEach((l, ci) => {
      if (area[l] > 5 * med) { merged++; return; }
      let code = 0, margin = 1;
      for (let k = 0; k < bits.length; k++) { if (ratios[k][ci] > thr[k]) code |= 1 << k; margin = Math.min(margin, Math.abs(ratios[k][ci] - thr[k])); }
      if (margin < 0.15) { uncertain++; return; }  // a bit is close to the threshold: check this LED separately
      const idx = grayDecode(code);
      if (idx >= n) { invalid++; return; }
      if (!byIdx.has(idx)) byIdx.set(idx, []);
      byIdx.get(idx).push({ u: sx[l] / sw[l], v: sy[l] / sw[l], area: area[l] });
    });
    const pts = new Array(n).fill(null); let conflicts = 0;
    for (const [idx, list] of byIdx) { if (list.length === 1) pts[idx] = { ...list[0], src: 'code' }; else conflicts++; }
    return { pts, peak, threshold: T, blobs: comps.length, merged, invalid, conflicts, uncertain };
  }

  // LEDs worth checking one by one: far from their neighbours on the string (a wrongly decoded
  // blob) or standing alone in a run of missing LEDs (nothing to compare with).
  function suspicious(pts, aloneToo = true) {
    const known = []; pts.forEach((p, i) => p && known.push(i));
    const d = [];
    for (let i = 0; i + 1 < pts.length; i++) if (pts[i] && pts[i + 1]) d.push(Math.hypot(pts[i].u - pts[i + 1].u, pts[i].v - pts[i + 1].v));
    d.sort((a, b) => a - b); const med = d[d.length >> 1] || 1, out = [];
    known.forEach((i, k) => {
      const a = known[k - 1], b = known[k + 1];
      const da = a === undefined ? null : Math.hypot(pts[i].u - pts[a].u, pts[i].v - pts[a].v) / (i - a);
      const db = b === undefined ? null : Math.hypot(pts[i].u - pts[b].u, pts[i].v - pts[b].v) / (b - i);
      const far = (da === null || da > 3 * med) && (db === null || db > 3 * med) && (da !== null || db !== null);
      const alone = (a === undefined || i - a > 1) && (b === undefined || b - i > 1);
      if (far || (aloneToo && alone)) out.push(i);
    });
    return out;
  }

  const maxArr = (a, b) => { const o = new Float32Array(a.length); for (let i = 0; i < a.length; i++) o[i] = Math.max(a[i], b[i]); return o; };
  const minArr = (a, b) => { const o = new Float32Array(a.length); for (let i = 0; i < a.length; i++) o[i] = Math.min(a[i], b[i]); return o; };

  // Pixels that changed between two "everything off" photos: flickering lights, a moving phone. Grown by 3 px.
  function unstableMask(d1, d2, w, h, thr = 25) {
    const m = new Uint8Array(w * h), out = new Uint8Array(w * h);
    for (let i = 0; i < m.length; i++) m[i] = Math.abs(d1[i] - d2[i]) > thr ? 1 : 0;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      if (!m[y * w + x]) continue;
      for (let dy = -3; dy <= 3; dy++) for (let dx = -3; dx <= 3; dx++) { const nx = x + dx, ny = y + dy; if (nx >= 0 && ny >= 0 && nx < w && ny < h) out[ny * w + nx] = 1; }
    }
    return out;
  }

  function blobCentres(w, h, dark, all) {
    const N = w * h, ref = new Float32Array(N);
    for (let i = 0; i < N; i++) ref[i] = Math.max(0, all[i] - dark[i]);
    const b = blur3(ref, w, h), T = Math.max(8, 0.25 * percentile(b, 99.9)), mask = new Uint8Array(N);
    for (let i = 0; i < N; i++) mask[i] = b[i] > T ? 1 : 0;
    const { labels, count } = components(mask, w, h), sx = new Float64Array(count + 1), sy = new Float64Array(count + 1), sw = new Float64Array(count + 1), ar = new Float64Array(count + 1);
    for (let i = 0; i < N; i++) { const l = labels[i]; if (!l) continue; const x = i % w, y = (i - x) / w; sx[l] += x * ref[i]; sy[l] += y * ref[i]; sw[l] += ref[i]; ar[l]++; }
    const out = []; for (let l = 1; l <= count; l++) if (ar[l] >= 2 && sw[l] > 0) out.push([sx[l] / sw[l], sy[l] / sw[l]]);
    return out;
  }

  // How far did the phone move between two sets of photos (median shift of the LED blobs, px)?
  function motion(w, h, dark1, all1, dark2, all2) {
    const c1 = blobCentres(w, h, dark1, all1), c2 = blobCentres(w, h, dark2, all2), dx = [], dy = [];
    if (c1.length < 20 || c2.length < 20) return null;
    for (const [x, y] of c1) {
      let best = null, bd = 1e9;
      for (const [u, v] of c2) { const d = Math.hypot(u - x, v - y); if (d < bd) { bd = d; best = [u - x, v - y]; } }
      if (bd < 15) { dx.push(best[0]); dy.push(best[1]); }
    }
    if (dx.length < 20) return null;
    dx.sort((a, b) => a - b); dy.sort((a, b) => a - b);
    const mx = dx[dx.length >> 1], my = dy[dy.length >> 1];
    return { dx: mx, dy: my, shift: Math.hypot(mx, my), n: dx.length };
  }

  // Bounding box (with a margin) of the LEDs found so far: single-LED shots look only there.
  function roiOf(pts, w, h, grow = null) {
    const got = pts.filter(Boolean); if (got.length < 40) return null;
    const us = got.map(p => p.u).sort((a, b) => a - b), vs = got.map(p => p.v).sort((a, b) => a - b), q = Math.floor(got.length * 0.01);
    const mx = Math.max(30, 0.08 * w), my = Math.max(30, 0.08 * h);
    const bw = us[us.length - 1 - q] - us[q], bh = vs[vs.length - 1 - q] - vs[q];
    // a tree: what was recognised by code may stop well short of the top (dense, merged blobs), so the search area is stretched upwards
    const gx = grow ? Math.max(mx, grow.x * bw) : mx, gt = grow ? Math.max(my, grow.top * bh) : my, gb = grow ? Math.max(my, grow.bottom * bh) : my;
    return { x0: Math.max(0, us[q] - gx), x1: Math.min(w - 1, us[us.length - 1 - q] + gx), y0: Math.max(0, vs[q] - gt), y1: Math.min(h - 1, vs[vs.length - 1 - q] + gb) };
  }

  // Brightest blob of (frame - dark) inside `roi` (if given) and outside `exclude` (if given); null if nothing stands out.
  function singleBlob({ w, h, dark, frame, minPeak, roi, exclude }) {
    const N = w * h, d = new Float32Array(N);
    for (let i = 0; i < N; i++) d[i] = Math.max(0, frame[i] - dark[i]);
    if (roi || exclude) for (let i = 0; i < N; i++) {
      const x = i % w, y = (i - x) / w;
      if ((roi && (x < roi.x0 || x > roi.x1 || y < roi.y0 || y > roi.y1)) || (exclude && exclude[i])) d[i] = 0;
    }
    const b = blur3(d, w, h); let peak = 0; for (let i = 0; i < N; i++) if (b[i] > peak) peak = b[i];
    if (peak < minPeak) return null;
    const T = Math.max(6, 0.4 * peak), mask = new Uint8Array(N); for (let i = 0; i < N; i++) mask[i] = b[i] > T ? 1 : 0;
    const { labels, count } = components(mask, w, h);
    if (!count) return null;
    const sx = new Float64Array(count + 1), sy = new Float64Array(count + 1), sw = new Float64Array(count + 1);
    for (let i = 0; i < N; i++) { const l = labels[i]; if (!l) continue; const x = i % w, y = (i - x) / w; sx[l] += x * d[i]; sy[l] += y * d[i]; sw[l] += d[i]; }
    let best = 1; for (let l = 2; l <= count; l++) if (sw[l] > sw[best]) best = l;
    return { u: sx[best] / sw[best], v: sy[best] / sw[best] };
  }

  // Tree seen from one side: among the LEDs nobody recognised by code some are only too close together (merged blobs) and a photo of
  // each one alone finds them, others are really hidden and nothing will ever show. Every run of missing LEDs along the string is probed
  // with a stride of 3; between two probes that both show nothing the LEDs are taken as hidden (the far side comes in long blocks),
  // next to a hit the LEDs in between are searched too.
  async function searchRuns(pts, probe, { limit = 400, stride = 3, check = () => {}, progress = () => {} } = {}) {
    const runs = []; let a = -1;
    for (let i = 0; i <= pts.length; i++) {
      const miss = i < pts.length && !pts[i];
      if (miss && a < 0) a = i;
      if (!miss && a >= 0) { runs.push([a, i - 1]); a = -1; }
    }
    let used = 0, found = 0, skipped = 0;
    const tryOne = async i => { check(); used++; progress(used, limit, i); const b = await probe(i); if (b) { pts[i] = { ...b, src: 'single' }; found++; } return !!b; };
    for (const [s0, e0] of runs) {
      const idx = []; for (let i = s0; i <= e0; i += stride) idx.push(i); if (idx[idx.length - 1] !== e0) idx.push(e0);
      if (used + idx.length > limit) return { used, found, skipped, truncated: true };
      const hit = []; for (const i of idx) hit.push(await tryOne(i));
      for (let k = 0; k + 1 < idx.length; k++) {
        const gap = idx[k + 1] - idx[k] - 1; if (gap <= 0) continue;
        if (!hit[k] && !hit[k + 1]) { skipped += gap; continue; }
        for (let i = idx[k] + 1; i < idx[k + 1]; i++) { if (used >= limit) return { used, found, skipped, truncated: true }; await tryOne(i); }
      }
    }
    return { used, found, skipped };
  }

  // Fill gaps along the string (neighbouring LEDs are physically adjacent). With `arc` (a tree seen from one side) a long hidden run
  // whose ends are far apart sideways is the string going round the back of the tree: its x follows a half cosine (LEDs bunch up near
  // the edges, as they do when they are spread evenly round a cone) while y moves straight.
  function interpolate(pts, { arc = false } = {}) {
    const out = pts.map(p => p && { ...p }), known = []; out.forEach((p, i) => p && known.push(i));
    if (!known.length) return out;
    const us = known.map(i => pts[i].u), width = Math.max(...us) - Math.min(...us);
    for (let i = 0; i < out.length; i++) {
      if (out[i]) continue;
      let a = -1, b = -1; for (const k of known) { if (k < i) a = k; else { b = k; break; } }
      if (a >= 0 && b >= 0) {
        const t = (i - a) / (b - a), round = arc && b - a >= 8 && Math.abs(out[b].u - out[a].u) > 0.4 * width;
        const tu = round ? (1 - Math.cos(Math.PI * t)) / 2 : t;
        out[i] = { u: out[a].u + (out[b].u - out[a].u) * tu, v: out[a].v + (out[b].v - out[a].v) * t, src: 'interp' };
      } else { const k = a >= 0 ? a : b; out[i] = { u: out[k].u, v: out[k].v, src: 'interp' }; }
    }
    return out;
  }

  // Camera pixels -> layout [-1,1] x [0,1] (y up). rot: quarter turns, flip: mirror x, mode: fit | stretch.
  function toLayout(pts, { rot = 0, flip = false, mode = 'fit' } = {}) {
    let c = pts.map(p => [p.u, -p.v]);
    for (let r = 0; r < rot; r++) c = c.map(([x, y]) => [-y, x]);
    if (flip) c = c.map(([x, y]) => [-x, y]);
    const xs = c.map(p => p[0]), ys = c.map(p => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const W = (x1 - x0) || 1, H = (y1 - y0) || 1;
    if (mode === 'stretch') return c.map(([x, y]) => ({ x: 2 * (x - x0) / W - 1, y: (y - y0) / H }));
    const s = Math.min(2 / W, 1 / H), xc = (x0 + x1) / 2;
    return c.map(([x, y]) => ({ x: (x - xc) * s, y: (y - y0) * s }));
  }

  return { detect, suspicious, singleBlob, interpolate, searchRuns, toLayout, percentile, blur3, maxArr, minArr, unstableMask, motion, roiOf };
})();

// ---- scan types ------------------------------------------------------------------------------------------------
// flat: a window or a wall, the camera sees every LED: all of them are found (by code, then one by one).
// tree: a tree seen from ONE side (a profile): only the LEDs facing the camera show up, the rest (the far side, behind branches) is
//       estimated along the string, so a low share of recognised LEDs is normal and the LEDs that stay hidden are not searched one by one.
// tree-round (planned): several sides of a tree one after another, merged into a 3D layout. Not implemented yet.
const SCAN_MODES = {
  flat: { label: 'Flat wall or window: every LED is visible', minShare: 0.5, minCount: 20, refineHidden: true, aloneToo: true, refineLimit: 150, arc: false,
    hint: 'Put the phone on a tripod in front of the garland so that all of it is in view.' },
  tree: { label: 'Tree, one side (profile): the LEDs on the far side are estimated', minShare: 0.05, minCount: 30, refineHidden: false, aloneToo: false, refineLimit: 40, arc: true, searchRuns: true, searchLimit: 400, singleFactor: 0.3,
    hint: 'Put the phone on a tripod straight in front of the tree, the whole tree in view (top and bottom too), as dark as you can. The LEDs on the far side and behind the branches cannot be seen: they are estimated along the string.' },
  'tree-round': { label: 'Tree, several sides (planned, not available yet)', disabled: true },
};

// ---- UI ------------------------------------------------------------------------------------
const SC = { stream: null, video: null, running: false, cancel: false, result: null, snap: null, opts: { rot: 0, flip: false, mode: 'fit' }, scanMode: 'flat', device: null, oldLayout: null, status: '' };
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function scanStopCamera() {
  if (SC.stream) { SC.stream.getTracks().forEach(t => t.stop()); SC.stream = null; }
}

async function scanOpenCamera() {
  if (!window.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia)
    throw new Error(`The camera needs a secure (https) address, but this page is on ${location.protocol}//${location.host}. Open Home Assistant through its https address.`);
  SC.stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false });
  SC.video.srcObject = SC.stream; await SC.video.play();
}

async function lockExposure() {  // keep the brightness constant while patterns change (best effort)
  try { await SC.stream.getVideoTracks()[0].applyConstraints({ advanced: [{ exposureMode: 'manual' }] }); } catch { /* not supported */ }
}

const cvs = document.createElement('canvas');
async function shot() {  // average of two frames, as luma (a function declaration so tests can replace it)
  const v = SC.video, w = v.videoWidth, h = v.videoHeight; cvs.width = w; cvs.height = h;
  const ctx = cvs.getContext('2d', { willReadFrequently: true }), acc = new Float32Array(w * h);
  for (let n = 0; n < 2; n++) {
    ctx.drawImage(v, 0, 0, w, h); const d = ctx.getImageData(0, 0, w, h).data;
    for (let i = 0; i < w * h; i++) acc[i] += 0.299 * d[4 * i] + 0.587 * d[4 * i + 1] + 0.114 * d[4 * i + 2];
    if (n === 0) await sleep(120);
  }
  for (let i = 0; i < acc.length; i++) acc[i] /= 2;
  return { w, h, data: acc };
}

function pat(body) { return send('api/scan/pattern', body); }

function scanLoadMode(dev) {  // the scan type is remembered per garland
  SC.device = dev;
  try { const m = localStorage.getItem('scan-mode:' + dev); if (m && SCAN_MODES[m] && !SCAN_MODES[m].disabled) SC.scanMode = m; } catch { /* no storage */ }
}

function scanSaveMode() { try { localStorage.setItem('scan-mode:' + SC.device, SC.scanMode); } catch { /* no storage */ } }

// Sends the photos of the last scan to the add-on (lossless grey PNGs + a small JSON) so that a scan that went wrong can be examined.
async function scanSendPhotos() {
  const d = SC.dump; if (!d) return;
  const cv = document.createElement('canvas'); cv.width = d.w; cv.height = d.h; const g = cv.getContext('2d');
  try {
    const put = async (name, body, type) => {
      const r = await fetch(`api/scan/dump/${d.id}/${name}`, { method: 'PUT', headers: { 'Content-Type': type }, body });
      if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
    };
    for (let k = 0; k < d.photos.length; k++) {
      const [name, data] = d.photos[k]; scanStatus(`Sending photo ${k + 1} of ${d.photos.length}...`, k / d.photos.length);
      const img = g.createImageData(d.w, d.h);
      for (let i = 0; i < d.w * d.h; i++) { const v = Math.max(0, Math.min(255, Math.round(data[i]))); img.data[4 * i] = img.data[4 * i + 1] = img.data[4 * i + 2] = v; img.data[4 * i + 3] = 255; }
      g.putImageData(img, 0, 0);
      await put(name + '.png', await new Promise(res => cv.toBlob(res, 'image/png')), 'image/png');
    }
    const meta = { device: d.device, mode: d.mode, n: d.n, w: d.w, h: d.h, level: d.level, pts: d.pts || null, stats: SC.result ? SC.result.stats : null, agent: navigator.userAgent };
    await put('meta.json', JSON.stringify(meta), 'application/json');
    scanStatus(`Photos sent (${d.id}).`, 1); toast(`Photos sent: ${d.id}`);
  } catch (e) { scanStatus('Sending failed: ' + e.message, undefined); toast('Sending failed: ' + e.message, true, 8000); }
}

function scanStatus(msg, frac) {
  SC.status = msg; const el = document.getElementById('scan-status'), bar = document.getElementById('scan-bar');
  if (el) el.textContent = msg; if (bar && frac !== undefined) bar.firstChild.style.width = `${Math.round(frac * 100)}%`;
}

async function runScan() {
  const dev = document.getElementById('scan-dev').value;
  SC.device = dev;
  SC.running = true; SC.cancel = false; SC.result = null; SC.device = dev; renderScan();
  const M = SCAN_MODES[SC.scanMode] || SCAN_MODES.flat, scanMode = SC.scanMode;
  const check = () => { if (SC.cancel) throw new Error('cancelled'); };
  try {
    scanStatus('Switching the garland to scan mode...', 0.02);
    const info = await send('api/scan/start', { device: dev }); const n = info.leds, nb = info.bits;
    // LED brightness (1-255). A saturated blob centre is fine for locating an LED, so do not dim the LEDs
    // below MIN_LEVEL just because the camera is dazzled: a dim LED cannot be seen by eye either.
    const MIN_LEVEL = 100;
    let level = 200;
    await pat({ kind: 'dark' }); await sleep(600); let dark = await shot();
    scanStatus('Setting the LED brightness...', 0.06);
    for (let t = 0; t < 3; t++) {
      check(); await pat({ kind: 'all', level }); await sleep(600); const a = await shot();
      const d = new Float32Array(a.data.length); for (let i = 0; i < d.length; i++) d[i] = Math.max(0, a.data[i] - dark.data[i]);
      const peak = ScanLib.percentile(d, 99.9);
      scanStatus(`Setting the LED brightness: ${level} (camera peak ${peak})...`, 0.06);
      if (peak >= 250 && level > MIN_LEVEL) level = Math.max(MIN_LEVEL, Math.round(level * 0.7));
      else if (peak < 60 && level < 255) level = Math.min(255, Math.round(level * 1.6));
      else break;
    }
    await lockExposure();
    scanStatus('Photo: everything off...', 0.1); await pat({ kind: 'dark' }); await sleep(600); dark = await shot();
    scanStatus('Photo: everything on...', 0.14); await pat({ kind: 'all', level }); await sleep(600); const all1 = await shot();
    const bits = [];
    for (let k = 0; k < nb; k++) {
      check(); scanStatus(`Photo: pattern ${k + 1} of ${nb}...`, 0.18 + 0.4 * k / nb);
      await pat({ kind: 'bit', bit: k, level }); await sleep(600); bits.push((await shot()).data);
    }
    // second pair of photos at the end: only what is the same in both counts (drops flickering lights, passing cars)
    scanStatus('Photo: everything off, again...', 0.58); await pat({ kind: 'dark' }); await sleep(600); const dark2 = await shot();
    scanStatus('Photo: everything on, again...', 0.6); await pat({ kind: 'all', level }); await sleep(600); const all2 = await shot();
    scanStatus('Recognising the LEDs...', 0.62); await sleep(30);
    const w = all1.w, h = all1.h;
    SC.dump = { id: new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14), w, h, n, mode: scanMode, level, device: dev,
      photos: [['dark', dark.data], ['all', all1.data], ...bits.map((b, k) => ['bit' + k, b]), ['dark2', dark2.data], ['all2', all2.data]] };
    const mv = ScanLib.motion(w, h, dark.data, all1.data, dark2.data, all2.data);
    if (mv && mv.shift > 2) throw new Error(`The phone moved by about ${mv.shift.toFixed(1)} px during the scan. Put it on a tripod or a stable surface and try again.`);
    const dmax = ScanLib.maxArr(dark.data, dark2.data), all = { data: ScanLib.minArr(all1.data, all2.data) };
    const unstable = ScanLib.unstableMask(dark.data, dark2.data, w, h);
    dark = { w, h, data: dmax };
    const det = ScanLib.detect({ w, h, dark: dark.data, all: all.data, bits, n });
    let pts = det.pts;
    const decoded = pts.filter(Boolean).length;
    if (decoded < Math.max(M.minCount, n * M.minShare)) throw new Error(scanMode === 'tree'
      ? `Only ${decoded} of ${n} LEDs could be recognised (${Math.round(100 * decoded / n)}%), too few even for a view from one side. Move the phone closer so that the tree fills the picture, darken the room, and check that the whole tree is in view.`
      : `Only ${decoded} of ${n} LEDs could be recognised. The phone probably moved (use a tripod), the garland is not fully in view, or the room is too bright. For a tree seen from one side choose the scan type "Tree, one side".`);
    // refine: missing and suspicious LEDs one at a time
    const todo = [...new Set([...(M.refineHidden ? pts.map((p, i) => p ? -1 : i).filter(i => i >= 0) : []), ...ScanLib.suspicious(pts, M.aloneToo)])];
    const limit = Math.min(todo.length, M.refineLimit); let refined = 0;
    const roi = ScanLib.roiOf(pts, w, h);
    for (let q = 0; q < limit; q++) {
      check(); const i = todo[q]; scanStatus(`Checking LED ${i} separately (${q + 1} of ${limit}), brightness ${Math.max(level, 200)}...`, 0.62 + 0.36 * q / Math.max(1, limit));
      await pat({ kind: 'leds', leds: [i], level: Math.max(level, 200) }); await sleep(450);
      const s = await shot(), b = ScanLib.singleBlob({ w, h, dark: dark.data, frame: s.data, minPeak: Math.max(10, det.peak * 0.3), roi, exclude: unstable });
      pts[i] = b ? { ...b, src: 'single' } : null; if (b) refined++;  // a LED that does not show up alone was a false detection
    }
    if (M.searchRuns) {  // a tree: look for the LEDs that are visible but were too close together to be told apart by code
      const minPeak = Math.max(10, det.peak * M.singleFactor), roi2 = ScanLib.roiOf(pts, w, h, { x: 0.15, top: 0.6, bottom: 0.1 }), lv = Math.max(level, 200);
      const stat = await ScanLib.searchRuns(pts, async i => {
        await pat({ kind: 'leds', leds: [i], level: lv }); await sleep(450); const s1 = await shot();
        return ScanLib.singleBlob({ w, h, dark: dark.data, frame: s1.data, minPeak, roi: roi2, exclude: unstable });
      }, { limit: M.searchLimit, check, progress: (u, l, i) => scanStatus(`Looking for LED ${i} on its own (${u} of at most ${l}), brightness ${lv}...`, 0.62 + 0.36 * u / l) });
      refined += stat.found;
    }
    const hidden = pts.filter(p => !p).length;
    pts = ScanLib.interpolate(pts, { arc: M.arc });
    if (pts.some(p => !p)) throw new Error('No LED was found. Make sure the garland is in view and the room is dark.');
    SC.dump.pts = pts.map(p => ({ u: +p.u.toFixed(2), v: +p.v.toFixed(2), src: p.src }));
    SC.result = { pts, w, h, n, stats: { mode: scanMode, n, decoded, refined, hidden, shift: mv ? +mv.shift.toFixed(1) : null, blobs: det.blobs, merged: det.merged, invalid: det.invalid, conflicts: det.conflicts, uncertain: det.uncertain, level } };
    SC.snap = { w, h, data: all1.data };
    SC.oldLayout = await api(`api/devices/${encodeURIComponent(dev)}/layout`);
    scanStatus('Done. Check the result below, then apply it.', 1);
  } catch (e) {
    scanStatus(e.message === 'cancelled' ? 'Cancelled.' : 'Scan failed: ' + e.message, undefined);
    if (e.message !== 'cancelled') toast('Scan failed: ' + e.message, true, 8000);
  } finally {
    try { await send('api/scan/stop', {}); } catch { /* ignore */ }
    SC.running = false; renderScan();
  }
}

// Shows by eye that the garland really lights what the scan asks for (no camera needed).
async function lightTest() {
  const dev = document.getElementById('scan-dev').value;
  SC.running = true; SC.cancel = false; renderScan();
  const hold = async (ms) => { const end = Date.now() + ms; while (Date.now() < end) { if (SC.cancel) throw new Error('cancelled'); await sleep(100); } };
  try {
    scanStatus('Switching the garland to scan mode...', 0.02);
    const info = await send('api/scan/start', { device: dev });
    scanStatus('Look at the garland: everything on (3 s)...', 0.1); await pat({ kind: 'all', level: 200 }); await hold(3000);
    scanStatus('Pattern 1 of the code: every second LED (3 s)...', 0.3); await pat({ kind: 'bit', bit: 0, level: 200 }); await hold(3000);
    const picks = [0, Math.floor(info.leds / 4), Math.floor(info.leds / 2), Math.floor(info.leds * 3 / 4), info.leds - 1];
    for (let k = 0; k < picks.length; k++) {
      scanStatus(`One LED only: number ${picks[k]} (2 s)... you should see a single point`, 0.5 + 0.1 * k);
      await pat({ kind: 'leds', leds: [picks[k]], level: 255 }); await hold(2000);
    }
    scanStatus('Test finished. If you saw the garland follow these steps, scanning will work.', 1);
  } catch (e) { scanStatus(e.message === 'cancelled' ? 'Cancelled.' : 'Test failed: ' + e.message, undefined); }
  finally { try { await send('api/scan/stop', {}); } catch { /* ignore */ } SC.running = false; renderScan(); }
}

function drawScatter(canvas, layout, colors) {
  const W = canvas.width, H = canvas.height, g = canvas.getContext('2d');
  g.clearRect(0, 0, W, H);
  const xs = layout.map(p => p[0]), ys = layout.map(p => p[1]), x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const pad = 10, sc = Math.min((W - 2 * pad) / ((x1 - x0) || 1), (H - 2 * pad) / ((y1 - y0) || 1));
  const ox = (W - (x1 - x0) * sc) / 2, oy = (H - (y1 - y0) * sc) / 2;
  layout.forEach((p, i) => { g.fillStyle = colors ? colors[i] : '#ccc'; g.beginPath(); g.arc(ox + (p[0] - x0) * sc, H - oy - (p[1] - y0) * sc, 2.4, 0, 6.2832); g.fill(); });
}

const SRC_COLOR = { code: '#4caf50', single: '#29b6f6', interp: '#ff9800' };

function drawResults() {
  const r = SC.result; if (!r) return;
  const cam = document.getElementById('scan-cam'), lay = document.getElementById('scan-new'), old = document.getElementById('scan-old');
  if (!cam) return;
  // camera view: snapshot with the detected string
  cam.width = 480; cam.height = Math.round(480 * r.h / r.w); const k = cam.width / r.w, g = cam.getContext('2d');
  const img = g.createImageData(r.w, r.h), tmp = document.createElement('canvas'); tmp.width = r.w; tmp.height = r.h;
  let mx = 1; for (let i = 0; i < r.w * r.h; i++) mx = Math.max(mx, SC.snap.data[i]);
  for (let i = 0; i < r.w * r.h; i++) { const v = Math.min(255, SC.snap.data[i] * 255 / mx * 0.8); img.data[4 * i] = img.data[4 * i + 1] = img.data[4 * i + 2] = v; img.data[4 * i + 3] = 255; }
  tmp.getContext('2d').putImageData(img, 0, 0); g.drawImage(tmp, 0, 0, cam.width, cam.height);
  g.strokeStyle = 'rgba(255,255,255,.25)'; g.beginPath(); r.pts.forEach((p, i) => i ? g.lineTo(p.u * k, p.v * k) : g.moveTo(p.u * k, p.v * k)); g.stroke();
  r.pts.forEach(p => { g.fillStyle = SRC_COLOR[p.src]; g.beginPath(); g.arc(p.u * k, p.v * k, 2.2, 0, 6.2832); g.fill(); });
  // layouts
  const nl = ScanLib.toLayout(r.pts, SC.opts); r.layout = nl;
  drawScatter(lay, nl.map(p => [p.x, p.y]), r.pts.map(p => SRC_COLOR[p.src]));
  if (SC.oldLayout) drawScatter(old, SC.oldLayout);
}

async function applyScan() {
  const r = SC.result; if (!r) return;
  if (!confirm(`Write the scanned layout to ${SC.device}? The current layout is saved as a backup first.`)) return;
  try {
    const res = await send('api/scan/apply', { device: SC.device, scan_type: r.stats.mode, coordinates: r.layout.map(p => ({ x: p.x, y: p.y })) });
    toast(`Layout written (${res.leds} LEDs). Backup: ${res.backup}`, false, 8000);
    SC.oldLayout = await api(`api/devices/${encodeURIComponent(SC.device)}/layout`); drawResults(); loadGallery();
  } catch (e) { toast('Not applied: ' + e.message, true, 8000); }
}

function renderScan() {
  const root = document.getElementById('view-scan'); root.replaceChildren();
  const devs = (S.status || []).map(d => d.name);
  if (devs.length && !SC.running && SC.device !== (S.previewDevice || devs[0])) scanLoadMode(S.previewDevice || devs[0]);
  const video = h('video', { playsinline: '', muted: '', autoplay: '', style: 'width:100%;max-width:480px;border-radius:8px;background:#000' }); video.muted = true;
  SC.video = video; if (SC.stream) { video.srcObject = SC.stream; video.play().catch(() => {}); }
  const st = SC.result && SC.result.stats;
  root.append(
    h('div', { class: 'card', style: 'margin-bottom:12px' },
      h('h2', {}, 'Scan LED positions with the phone camera'),
      h('ol', { class: 'muted', style: 'margin:0 0 8px;padding-left:18px' },
        h('li', {}, 'Open this page on the phone through the https address of Home Assistant.'),
        h('li', {}, 'Darken the room. Put the phone on something steady so the whole garland is in view.'),
        h('li', {}, 'Press "Open camera", then "Start scan". The garland flashes patterns for about a minute; do not move the phone.'),
        h('li', {}, 'Check the result and press "Apply to the garland". The old layout is saved as a backup.')),
      h('div', { class: 'muted', style: 'margin-bottom:8px' }, (SCAN_MODES[SC.scanMode] || SCAN_MODES.flat).hint),
      !window.isSecureContext ? h('div', { class: 'bad' }, `This page is not on https (${location.protocol}//${location.host}), so the browser will not give it the camera.`) : null,
      h('div', { class: 'row' },
        h('label', {}, 'Garland ', h('select', { id: 'scan-dev', disabled: SC.running, onchange: e => { setPreviewDevice(e.target.value); scanLoadMode(e.target.value); renderScan(); } }, devs.map(d => h('option', { value: d, selected: d === SC.device }, d)))),
        h('label', {}, 'Scan type ', h('select', { id: 'scan-mode', disabled: SC.running, onchange: e => { SC.scanMode = e.target.value; scanSaveMode(); renderScan(); } },
          Object.entries(SCAN_MODES).map(([k, m]) => h('option', { value: k, disabled: !!m.disabled, selected: k === SC.scanMode }, m.label)))),
        h('button', { disabled: SC.running, onclick: async () => { try { await scanOpenCamera(); toast('Camera ready.'); renderScan(); } catch (e) { toast(e.message, true, 9000); } } }, 'Open camera'),
        h('button', { class: 'primary', disabled: SC.running || !SC.stream, onclick: runScan }, 'Start scan'),
        h('button', { disabled: SC.running, title: 'Lights the garland step by step so you can check it by eye. No camera needed.', onclick: lightTest }, 'Light test'),
        h('button', { disabled: !SC.running, onclick: () => { SC.cancel = true; } }, 'Cancel')),
      h('div', { class: 'bar', id: 'scan-bar', style: 'margin-top:8px' }, h('div', { style: 'width:0%' })),
      h('div', { id: 'scan-status', class: 'muted' }, SC.status || 'Idle.')),
    h('div', { class: 'card', style: 'margin-bottom:12px' }, h('h3', {}, 'Camera'), video,
      SC.dump ? h('div', { class: 'row', style: 'margin-top:8px' }, h('button', { disabled: SC.running, onclick: scanSendPhotos, title: 'Uploads the photos of the last scan to the add-on, to find out why a scan went wrong' }, `Send the photos of the last scan for analysis (${SC.dump.photos.length})`)) : ''),
    SC.result ? h('div', { class: 'card' },
      h('h2', {}, 'Result'),
      h('div', {}, `${st.n} LEDs: ${st.decoded} recognised by code, ${st.refined} found one by one, `, h('b', { class: st.hidden && st.mode !== 'tree' ? 'warn' : 'ok' }, `${st.hidden} not visible (estimated from their neighbours${st.mode === 'tree' ? ', as expected for the far side of a tree' : ''})`),
        h('span', { class: 'muted' }, `  ·  blobs ${st.blobs}, merged ${st.merged}, invalid ${st.invalid}, ambiguous ${st.conflicts}, doubtful ${st.uncertain}, brightness ${st.level}`)),
      st.shift > 1.2 ? h('div', { class: 'warn' }, `The phone moved about ${st.shift} px during the scan. Use a tripod for a more accurate result.`) : null,
      h('div', { class: 'muted' }, 'Green = recognised, blue = found separately, orange = estimated. The grey line is the string in LED order and should run smoothly.'),
      h('div', { class: 'row', style: 'margin:8px 0' },
        h('label', {}, 'Rotate ', h('select', { onchange: e => { SC.opts.rot = Number(e.target.value); drawResults(); } }, [0, 1, 2, 3].map(q => h('option', { value: q, selected: q === SC.opts.rot }, `${q * 90}°`)))),
        h('label', {}, h('input', { type: 'checkbox', checked: SC.opts.flip, onchange: e => { SC.opts.flip = e.target.checked; drawResults(); } }), 'Mirror'),
        h('label', {}, 'Scale ', h('select', { onchange: e => { SC.opts.mode = e.target.value; drawResults(); } }, [['fit', 'keep proportions'], ['stretch', 'fill the unit box']].map(([v, t]) => h('option', { value: v, selected: v === SC.opts.mode }, t))))),
      h('div', { class: 'row', style: 'align-items:flex-start' },
        h('div', {}, h('div', { class: 'muted' }, 'Camera view'), h('canvas', { id: 'scan-cam', style: 'max-width:100%;background:#000;border-radius:6px' })),
        h('div', {}, h('div', { class: 'muted' }, 'Scanned layout (x: -1..1, y: 0..1)'), h('canvas', { id: 'scan-new', width: 360, height: 300, style: 'max-width:100%;background:#0b0b0d;border-radius:6px' })),
        h('div', {}, h('div', { class: 'muted' }, 'Layout now on the device'), h('canvas', { id: 'scan-old', width: 360, height: 300, style: 'max-width:100%;background:#0b0b0d;border-radius:6px' }))),
      h('div', { class: 'row', style: 'margin-top:8px' }, h('button', { class: 'primary', onclick: applyScan }, 'Apply to the garland'))) : '');
  if (!SC.running) { const el = document.getElementById('scan-status'); if (el) el.textContent = SC.status || 'Idle.'; }
  drawResults();
}

window.addEventListener('beforeunload', () => { if (SC.running) navigator.sendBeacon('api/scan/stop'); });
