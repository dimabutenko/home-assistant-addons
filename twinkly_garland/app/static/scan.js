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

  // Error correction for the code frames (a Hamming code over the bits of the Gray code): r extra "check" frames, each the XOR of a
  // subset of the code bits. A LED whose bits and checks do not agree was read wrongly (a merged blob, a flicker): one wrong bit is corrected,
  // anything worse is rejected instead of ending up at a wrong place. Every code bit gets its own non-zero r-bit signature (never a single 1,
  // those belong to the check bits themselves), so the signature of the disagreement says which bit is wrong.
  function eccLayout(nb) {
    let r = 2; while ((1 << r) - 1 - r < nb) r++;
    const cols = []; for (let v = 3; cols.length < nb; v++) if (v & (v - 1)) cols.push(v);
    return { r, cols, sets: Array.from({ length: r }, (_, j) => cols.map((c, k) => (c >> j) & 1 ? k : -1).filter(k => k >= 0)) };
  }
  const grayOf = i => i ^ (i >> 1);
  // LEDs lit in check frame j
  function checkLeds(n, nb, j) {
    const { sets } = eccLayout(nb), out = [];
    for (let i = 0; i < n; i++) { const g = grayOf(i); let p = 0; for (const k of sets[j]) p ^= (g >> k) & 1; if (p) out.push(i); }
    return out;
  }
  // bits: data bits read from the photos, checks: the check bits; returns the corrected data bits or null
  function eccDecode(bits, checks, nb) {
    const { cols, sets } = eccLayout(nb); let syn = 0;
    for (let j = 0; j < sets.length; j++) { let p = checks[j]; for (const k of sets[j]) p ^= bits[k]; syn |= p << j; }
    if (!syn) return { bits, fixed: false };
    const k = cols.indexOf(syn);
    if (k >= 0) { const b = bits.slice(); b[k] ^= 1; return { bits: b, fixed: true }; }
    if (!(syn & (syn - 1))) return { bits, fixed: false };  // a single check bit was read wrongly: the data are fine
    return null;
  }

  // Which LEDs are lit for code bit k: k < nb is bit k of the Gray code, the rest are the check bits.
  function bitLeds(n, nb, k) {
    if (k >= nb) return checkLeds(n, nb, k - nb);
    const out = []; for (let i = 0; i < n; i++) if ((grayOf(i) >> k) & 1) out.push(i);
    return out;
  }
  // Frames of the code: nb data bits + the check bits. In colour mode one frame carries three bits (red, green and blue of each LED
  // are three independent lamps), so a scan needs a third of the photos; bits[c] = the code bit carried by colour c (-1: none).
  function framePlan(nb, colour) {
    const total = nb + eccLayout(nb).r, per = colour ? 3 : 1, out = [];
    for (let f = 0; f < total; f += per) out.push({ bits: Array.from({ length: per }, (_, c) => f + c < total ? f + c : -1) });
    return out;
  }

  // Unmixing: the camera does not see "red LED -> red channel" exactly (crosstalk of the Bayer filter, white balance, a different order of
  // the LED colours). So every blob gets its own 3x3 response matrix B from three photos with all LEDs red / green / blue
  // (B[c][j] = camera channel c with LED colour j on). A code photo gives the blob's camera vector v, and B s = v gives how much of each
  // LED colour is on (about 0 or 1). Mono mode is the same with 1x1 matrices.
  function inv3(B) {
    const [[a, b, c], [d, e, f], [g, h, i]] = B;
    const A = e * i - f * h, Bq = -(d * i - f * g), C = d * h - e * g, det = a * A + b * Bq + c * C;
    if (!isFinite(det) || det === 0) return null;
    const r = [[A, -(b * i - c * h), b * f - c * e], [Bq, a * i - c * g, -(a * f - c * d)], [C, -(a * h - b * g), a * e - b * d]];
    return { m: r.map(row => row.map(x => x / det)), det };
  }

  // darkP: planes of the dark photo (1 plane = mono, 3 = R,G,B), dark / all: luma of the dark / all-on photo (all is used to find the blobs),
  // cal[j] = planes of the photo with LED colour j on everywhere (mono: [all planes]), frames[f] = { planes, bits } (see framePlan),
  // nb = number of data bits (the frames carry nb + check bits).
  function detect({ w, h, dark, all, darkP, cal, frames, nb, n }) {
    const N = w * h, ref = new Float32Array(N), d = darkP.length;
    for (let i = 0; i < N; i++) ref[i] = Math.max(0, all[i] - dark[i]);
    const blurred = blur3(ref, w, h);
    const peak = percentile(blurred, 99.9), T = Math.max(8, 0.25 * peak);
    const mask = new Uint8Array(N); for (let i = 0; i < N; i++) mask[i] = blurred[i] > T ? 1 : 0;
    const { labels, count } = components(mask, w, h);
    const area = new Float64Array(count + 1), sx = new Float64Array(count + 1), sy = new Float64Array(count + 1), sw = new Float64Array(count + 1);
    const calS = cal.map(ph => ph.map(() => new Float64Array(count + 1)));
    const frS = frames.map(f => f.planes.map(() => new Float64Array(count + 1)));
    for (let i = 0; i < N; i++) {
      const l = labels[i]; if (!l) continue;
      const x = i % w, y = (i - x) / w, r = ref[i];
      area[l]++; sx[l] += x * r; sy[l] += y * r; sw[l] += r;
      for (let j = 0; j < cal.length; j++) for (let c = 0; c < d; c++) calS[j][c][l] += Math.max(0, cal[j][c][i] - darkP[c][i]);
      for (let f = 0; f < frames.length; f++) for (let c = 0; c < d; c++) frS[f][c][l] += Math.max(0, frames[f].planes[c][i] - darkP[c][i]);
    }
    const comps = [];
    for (let l = 1; l <= count; l++) if (area[l] >= 2 && sw[l] > 0) comps.push(l);
    const areas = comps.map(l => area[l]).sort((a, b) => a - b), med = areas[areas.length >> 1] || 1;
    const total = frames.reduce((m, f) => Math.max(m, ...f.bits), -1) + 1;
    const ratios = Array.from({ length: total }, () => new Array(comps.length).fill(NaN));
    let ill = 0; const illSet = new Set();
    comps.forEach((l, ci) => {
      let inv = null;
      if (d === 1) { const b = calS[0][0][l]; if (b > 0) inv = { m: [[1 / b]] }; }
      else {
        const B = [0, 1, 2].map(c => [0, 1, 2].map(j => calS[j][c][l])), cols = [0, 1, 2].map(j => Math.hypot(B[0][j], B[1][j], B[2][j]));
        const iv = inv3(B);
        // Hadamard ratio: 1 for three independent colours, near 0 when two colours look the same to the camera (a saturated blob)
        if (iv && cols.every(x => x > 0) && Math.abs(iv.det) / (cols[0] * cols[1] * cols[2]) > 0.2) inv = iv;
      }
      if (!inv) { illSet.add(ci); return; }
      frames.forEach((f, fi) => {
        const v = frS[fi].map(a => a[l]);
        for (let j = 0; j < d; j++) {
          const k = f.bits[j]; if (k < 0) continue;
          let s = 0; for (let c = 0; c < d; c++) s += inv.m[j][c] * v[c];
          ratios[k][ci] = Math.max(-0.5, Math.min(1.5, s));
        }
      });
    });
    ill = illSet.size;
    const thr = ratios.map(r => otsu(r.filter(x => !isNaN(x))));
    const byIdx = new Map(); let invalid = 0, merged = 0, uncertain = 0, corrected = 0, rejected = 0;
    const nChecks = total - nb;
    comps.forEach((l, ci) => {
      if (area[l] > 5 * med) { merged++; return; }
      if (illSet.has(ci)) { uncertain++; return; }
      let rd = [], cd = [], margins = [];
      for (let k = 0; k < total; k++) {
        const bit = ratios[k][ci] > thr[k] ? 1 : 0; margins.push(Math.abs(ratios[k][ci] - thr[k]));
        (k < nb ? rd : cd).push(bit);
      }
      const doubtful = margins.filter(m => m < 0.15).length;
      // without check frames one doubtful bit is too many; with them one wrong bit is corrected, two are not
      if (nChecks ? doubtful > 1 : doubtful > 0) { uncertain++; return; }
      if (nChecks) {
        const dec = eccDecode(rd, cd, nb);
        if (!dec) { rejected++; return; }
        if (dec.fixed) corrected++;
        rd = dec.bits;
      }
      let code = 0; for (let k = 0; k < rd.length; k++) if (rd[k]) code |= 1 << k;
      const idx = grayDecode(code);
      if (idx >= n) { invalid++; return; }
      if (!byIdx.has(idx)) byIdx.set(idx, []);
      byIdx.get(idx).push({ u: sx[l] / sw[l], v: sy[l] / sw[l], area: area[l] });
    });
    const pts = new Array(n).fill(null); let conflicts = 0;
    for (const [idx, list] of byIdx) { if (list.length === 1) pts[idx] = { ...list[0], src: 'code' }; else conflicts++; }
    return { pts, peak, threshold: T, blobs: comps.length, merged, invalid, conflicts, uncertain, corrected, rejected, ill };
  }

  // Hue-coded frames, decoded pixel by pixel (the way the Twinkly app does it, with our own code): in every code frame EVERY LED is lit,
  // red for a 0 and blue for a 1 (nothing is switched off, so a LED is visible in every photo and no brightness threshold is needed:
  // the colour decides). Two photos with all LEDs red / all blue give every pixel its own response to the two colours; a code photo is
  // un-mixed with them (v = a * red + c * blue, least squares over the three camera channels): a pure 0 is (1, 0), a pure 1 is (0, 1),
  // a pixel between two LEDs of different colours is a mixture and is doubtful. Every pixel collects its bits over all frames,
  // the check bits correct one doubtful or wrong bit, and the pixel then "votes" for the LED whose code it carries. A LED is where its
  // pixels are (brightness-weighted centre of the pixels within a few pixels of their median): merged blobs do not matter, the pixels at
  // the centre of every LED still carry its own code and the pixels in between are dropped.
  // darkP: planes of the dark photo, calR / calB: planes of all-red / all-blue, frames[k]: planes of the photo carrying code bit k
  // (data bits first, then the check bits), dark / all: luma (all is only used for `peak`), exclude: pixels not to be used.
  function detectHue({ w, h, dark, all, darkP, calR, calB, frames, nb, n, exclude }) {
    const N = w * h, ref = new Float32Array(N), q = new Float32Array(N), sw = new Float32Array(N);
    for (let i = 0; i < N; i++) ref[i] = Math.max(0, all[i] - dark[i]);
    const peak = percentile(blur3(ref, w, h), 99.9);
    for (let i = 0; i < N; i++) {
      let a = 0, b = 0;
      for (let c = 0; c < 3; c++) { a += Math.max(0, calR[c][i] - darkP[c][i]); b += Math.max(0, calB[c][i] - darkP[c][i]); }
      q[i] = Math.min(a, b) / 3; sw[i] = (a + b) / 6;
    }
    const T = Math.max(6, 0.1 * percentile(q, 99.9)), total = frames.length, nChecks = total - nb;  // 0.1: tuned on real photos of a tree (0.2 left dim LEDs out)
    const R0 = Math.max(5, 0.012 * w), MIN_PIX = 2;
    const byIdx = new Map(); let pixels = 0, ill = 0, invalid = 0, uncertain = 0, corrected = 0, rejected = 0;
    const rv = [0, 0, 0], bv = [0, 0, 0];
    for (let i = 0; i < N; i++) {
      if (q[i] <= T || (exclude && exclude[i])) continue;
      pixels++;
      let rr = 0, bb = 0, rb = 0;
      for (let c = 0; c < 3; c++) {
        rv[c] = Math.max(0, calR[c][i] - darkP[c][i]); bv[c] = Math.max(0, calB[c][i] - darkP[c][i]);
        rr += rv[c] * rv[c]; bb += bv[c] * bv[c]; rb += rv[c] * bv[c];
      }
      const det = rr * bb - rb * rb;
      if (!(det > 0.05 * rr * bb)) { ill++; continue; }  // the two colours look the same here (a saturated pixel)
      const bits = new Array(total); let doubtful = 0, bad = false;
      for (let k = 0; k < total && !bad; k++) {
        const P = frames[k]; let rvv = 0, bvv = 0;
        for (let c = 0; c < 3; c++) { const v = Math.max(0, P[c][i] - darkP[c][i]); rvv += rv[c] * v; bvv += bv[c] * v; }
        const a = (bb * rvv - rb * bvv) / det, cc = (rr * bvv - rb * rvv) / det, t = a + cc;
        if (t < 0.3 || t > 2.5) { bad = true; break; }
        const d = (cc - a) / t, m = Math.abs(d);
        if (m < 0.4) { bad = true; break; }
        if (m < 0.7) doubtful++;
        bits[k] = cc > a ? 1 : 0;
      }
      if (bad || doubtful > (nChecks ? 2 : 0)) { uncertain++; continue; }
      let rd = bits.slice(0, nb);
      if (nChecks) {
        const dec = eccDecode(rd, bits.slice(nb), nb);
        if (!dec) { rejected++; continue; }
        if (dec.fixed) corrected++;
        rd = dec.bits;
      }
      let code = 0; for (let k = 0; k < rd.length; k++) if (rd[k]) code |= 1 << k;
      const idx = grayDecode(code);
      if (idx >= n) { invalid++; continue; }
      let L = byIdx.get(idx); if (!L) byIdx.set(idx, L = { x: [], y: [], w: [] });
      const x = i % w; L.x.push(x); L.y.push((i - x) / w); L.w.push(sw[i]);
    }
    const med = a => { const s = [...a].sort((u, v) => u - v); return s[s.length >> 1]; };
    const pts = new Array(n).fill(null); let conflicts = 0;
    for (const [idx, L] of byIdx) {
      const mx = med(L.x), my = med(L.y); let sx = 0, sy = 0, s = 0, kept = 0;
      for (let j = 0; j < L.x.length; j++) if (Math.hypot(L.x[j] - mx, L.y[j] - my) <= R0) { sx += L.x[j] * L.w[j]; sy += L.y[j] * L.w[j]; s += L.w[j]; kept++; }
      if (kept < MIN_PIX || s <= 0) continue;
      if (L.x.length - kept > kept) { conflicts++; continue; }  // two separate places claim this code: nobody is sure
      pts[idx] = { u: sx / s, v: sy / s, area: kept, src: 'code' };
    }
    return { pts, peak, threshold: T, blobs: byIdx.size, merged: 0, invalid, conflicts, uncertain, corrected, rejected, ill, pixels };
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

  // A LED that stands far from BOTH of its neighbours on the string while the neighbours stand close to each other is a spike (a
  // stray detection, an estimate that went wrong): it is put halfway between its neighbours. The ends are checked against their one
  // neighbour. keys: the coordinate names ('u','v' or 'x','y','z'). Works on the complete string, after the gaps are filled.
  function despike(pts, keys, { far = 8, near = 4, passes = 2 } = {}) {
    const out = pts.map(p => ({ ...p })), n = out.length, fixed = [];
    const d = (a, b) => Math.hypot(...keys.map(k => out[a][k] - out[b][k]));
    for (let pass = 0; pass < passes; pass++) {
      const st = []; for (let i = 0; i + 1 < n; i++) st.push(d(i, i + 1));
      const nz = st.filter(x => x > 1e-9).sort((a, b) => a - b), med = nz[nz.length >> 1] || 1e-9;
      let any = false;
      for (let i = 0; i < n; i++) {
        const a = i - 1, c = i + 1; let rep = null;
        if (a >= 0 && c < n) { if (Math.min(d(a, i), d(i, c)) > far * med && d(a, c) < near * med) rep = k => (out[a][k] + out[c][k]) / 2; }
        else if (i === 0 && n > 2) { if (d(0, 1) > far * med && d(1, 2) < near * med) rep = k => 2 * out[1][k] - out[2][k]; }
        else if (i === n - 1 && n > 2) { if (d(n - 1, n - 2) > far * med && d(n - 2, n - 3) < near * med) rep = k => 2 * out[n - 2][k] - out[n - 3][k]; }
        if (rep) { for (const k of keys) out[i][k] = rep(k); out[i].src = 'interp'; fixed.push(i); any = true; }
      }
      if (!any) break;
    }
    return { pts: out, fixed: [...new Set(fixed)] };
  }

  // How clearly the camera tells the all-red photo from the all-blue one, as the decoder needs it: over the lit pixels the sine of the angle between
  // the pixel's response to red and its response to blue (the three camera channels as a vector; 1 = completely different, 0 = the same
  // colour, which is what a blown-out white LED looks like). The decoder un-mixes the channels, so the crosstalk between them (a red LED
  // also lights the blue channel a bit) does not matter, only this angle does; it gives up below 0.22. And the share of lit pixels where a
  // channel is at its limit.
  function separation(darkP, calR, calB) {
    const N = calR[0].length, q = new Float32Array(N);
    for (let i = 0; i < N; i++) { let a = 0, b = 0; for (let c = 0; c < 3; c++) { a += Math.max(0, calR[c][i] - darkP[c][i]); b += Math.max(0, calB[c][i] - darkP[c][i]); } q[i] = Math.min(a, b) / 3; }
    const T = Math.max(6, 0.2 * percentile(q, 99.9)), sn = []; let lit = 0, clipped = 0;
    for (let i = 0; i < N; i++) {
      if (q[i] <= T) continue; lit++;
      let rr = 0, bb = 0, rb = 0;
      for (let c = 0; c < 3; c++) { const r = Math.max(0, calR[c][i] - darkP[c][i]), b = Math.max(0, calB[c][i] - darkP[c][i]); rr += r * r; bb += b * b; rb += r * b; }
      sn.push(Math.sqrt(Math.max(0, 1 - rb * rb / (rr * bb + 1e-9))));
      if (Math.max(calR[0][i], calR[1][i], calR[2][i], calB[0][i], calB[1][i], calB[2][i]) >= 250) clipped++;
    }
    sn.sort((u, v) => u - v);
    const m = sn.length ? sn[sn.length >> 1] : 0;
    return { sepR: m, sepB: m, sep: m, lit, satShare: lit ? clipped / lit : 0 };
  }

  // ---- a shaking phone -------------------------------------------------------------------------------------------------------------
  const lumaOf = planes => {
    if (planes.length === 1) return planes[0];
    const o = new Float32Array(planes[0].length); for (let i = 0; i < o.length; i++) o[i] = 0.299 * planes[0][i] + 0.587 * planes[1][i] + 0.114 * planes[2][i];
    return o;
  };
  function down2(a, w, h) {
    const W = w >> 1, H = h >> 1, o = new Float32Array(W * H);
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) { const i = 2 * y * w + 2 * x; o[y * W + x] = (a[i] + a[i + 1] + a[i + w] + a[i + w + 1]) / 4; }
    return { a: o, w: W, h: H };
  }
  // normalised correlation of A(x) with B(x + d) over the part where both exist
  function corr(A, B, w, h, dx, dy) {
    const x0 = Math.max(0, -dx), x1 = Math.min(w, w - dx), y0 = Math.max(0, -dy), y1 = Math.min(h, h - dy);
    let s = 0, na = 0, nb = 0;
    for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) { const a = A[y * w + x], b = B[(y + dy) * w + x + dx]; s += a * b; na += a * a; nb += b * b; }
    return s / Math.sqrt(na * nb + 1e-9);
  }
  // How far a photo is moved against a reference: img(x + d) matches ref(x). Both are the light of the LEDs (the dark photo taken off). Found
  // coarsely on a quarter-size picture (+-24 px at full size), refined on a half-size one and then with a parabola through the correlation
  // of the neighbours (about 0.1 px). null when the photo does not look like the reference (a score under 0.2).
  function estimateShift(ref, img, w, h, range = 6) {
    const r2 = down2(ref, w, h), i2 = down2(img, w, h), r4 = down2(r2.a, r2.w, r2.h), i4 = down2(i2.a, i2.w, i2.h);
    let best = -1, bx = 0, by = 0;
    for (let dy = -range; dy <= range; dy++) for (let dx = -range; dx <= range; dx++) { const c = corr(r4.a, i4.a, r4.w, r4.h, dx, dy); if (c > best) { best = c; bx = dx; by = dy; } }
    let cb = -1, cx = 0, cy = 0;
    for (let dy = 2 * by - 1; dy <= 2 * by + 1; dy++) for (let dx = 2 * bx - 1; dx <= 2 * bx + 1; dx++) { const c = corr(r2.a, i2.a, r2.w, r2.h, dx, dy); if (c > cb) { cb = c; cx = dx; cy = dy; } }
    if (cb < 0.2) return null;
    const par = (m, c, p) => { const d = m - 2 * c + p; return d < 0 ? Math.max(-1, Math.min(1, 0.5 * (m - p) / d)) : 0; };
    const sx = par(corr(r2.a, i2.a, r2.w, r2.h, cx - 1, cy), cb, corr(r2.a, i2.a, r2.w, r2.h, cx + 1, cy));
    const sy = par(corr(r2.a, i2.a, r2.w, r2.h, cx, cy - 1), cb, corr(r2.a, i2.a, r2.w, r2.h, cx, cy + 1));
    return { dx: 2 * (cx + sx), dy: 2 * (cy + sy), score: cb };
  }
  // the plane moved back: out(x) = plane(x + d), bilinear; what comes from outside the picture is 0
  function shiftPlane(p, w, h, dx, dy) {
    const out = new p.constructor(w * h), ix = Math.floor(dx), iy = Math.floor(dy), fx = dx - ix, fy = dy - iy, add = p.constructor === Uint8Array ? 0.5 : 0;
    for (let y = 0; y < h; y++) {
      const sy = y + iy; if (sy < 0 || sy + 1 >= h) continue;
      for (let x = 0; x < w; x++) {
        const sx = x + ix; if (sx < 0 || sx + 1 >= w) continue;
        const i = sy * w + sx;
        out[y * w + x] = ((p[i] * (1 - fx) + p[i + 1] * fx) * (1 - fy) + (p[i + w] * (1 - fx) + p[i + w + 1] * fx) * fy) + add;
      }
    }
    return out;
  }

  // How many LEDs the decoder can read at this brightness, counted from the all-red and the all-blue photo: the number of connected areas of
  // LED size (4 to 400 pixels) in which both photos are more than T above the dark photo, nothing is clipped (under 245) and the response to red and to
  // blue differ by an angle of at least minSin. The halo of an LED qualifies, its clipped core does not have to; the glow of the wall round the tree
  // forms a few huge areas that are not counted; LEDs that run into each other form one big area and are lost; LEDs that are too dim give no area. On
  // the real scans (exposure, LEDs found by the scan, count): 2.7 -> 168, 101; 48 -> 248, 233; automatic -> 302, 292.
  function readableBlobs(darkP, calR, calB, w, h, { T = 15, minSin = 0.3, clip = 245, minArea = 4, maxArea = 400 } = {}) {
    const N = w * h, mask = new Uint8Array(N);
    for (let i = 0; i < N; i++) {
      let sr = 0, sb = 0, rr = 0, bb = 0, rb = 0, mx = 0;
      for (let c = 0; c < 3; c++) {
        const r = Math.max(0, calR[c][i] - darkP[c][i]), b = Math.max(0, calB[c][i] - darkP[c][i]);
        sr += r; sb += b; rr += r * r; bb += b * b; rb += r * b; mx = Math.max(mx, calR[c][i], calB[c][i]);
      }
      if (Math.min(sr, sb) / 3 <= T || mx >= clip) continue;
      if (Math.sqrt(Math.max(0, 1 - rb * rb / (rr * bb + 1e-9))) >= minSin) mask[i] = 1;
    }
    const { labels, count } = components(mask, w, h), area = new Int32Array(count + 1);
    for (let i = 0; i < N; i++) if (labels[i]) area[labels[i]]++;
    let n = 0; for (let l = 1; l <= count; l++) if (area[l] >= minArea && area[l] <= maxArea) n++;
    return n;
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

  // Mislabelled or misplaced LEDs: neighbours on the string are about one step apart, so a LED whose distance per index to BOTH its
  // previous and its next known LED is far above the typical step is not on the string. The typical step is the median distance
  // between LEDs with consecutive numbers (taken from the inner ones); the limit is `factor` times that. The first and the last known LED
  // have only one neighbour and are never dropped. Repeated until nothing more is dropped.
  function filterOutliers(pts, { factor = 5, passes = 4 } = {}) {
    const out = pts.map(p => p && { ...p }), removed = [];
    for (let pass = 0; pass < passes; pass++) {
      const known = []; out.forEach((p, i) => p && known.push(i));
      if (known.length < 5) break;
      const dist = (a, b) => Math.hypot(out[a].u - out[b].u, out[a].v - out[b].v);
      let steps = []; for (let k = 1; k + 2 < known.length; k++) if (known[k + 1] - known[k] === 1) steps.push(dist(known[k], known[k + 1]));
      if (steps.length < 8) { steps = []; for (let k = 0; k + 1 < known.length; k++) if (known[k + 1] - known[k] <= 4) steps.push(dist(known[k], known[k + 1]) / (known[k + 1] - known[k])); }
      if (steps.length < 3) break;
      steps.sort((a, b) => a - b); const limit = factor * steps[steps.length >> 1], drop = [];
      for (let k = 1; k + 1 < known.length; k++) {
        const a = known[k - 1], b = known[k], c = known[k + 1];
        if (Math.min(dist(a, b) / (b - a), dist(b, c) / (c - b)) > limit) drop.push(b);
      }
      if (!drop.length) break;
      for (const i of drop) { out[i] = null; removed.push(i); }
    }
    return { pts: out, removed };
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

  // Catmull-Rom through four known LEDs (Barry-Goldman form, knots = LED numbers, so unevenly spaced neighbours are handled): the curve
  // runs through p1 and p2 and its direction there follows the neighbours p0 and p3, which a straight line ignores.
  function cr1(t0, t1, t2, t3, p0, p1, p2, p3, t) {
    const L = (ta, tb, pa, pb) => tb === ta ? pa : pa + (pb - pa) * (t - ta) / (tb - ta);
    const a1 = L(t0, t1, p0, p1), a2 = L(t1, t2, p1, p2), a3 = L(t2, t3, p2, p3);
    return L(t1, t2, L(t0, t2, a1, a2), L(t1, t3, a2, a3));
  }
  // value at LED i between known[pos] and known[pos+1]; get(idx) = the value of a known LED. At the ends the missing neighbour is a mirror image.
  function crAt(known, pos, get, i) {
    const a = known[pos], b = known[pos + 1], pa = get(a), pb = get(b);
    let t0, p0, t3, p3;
    if (pos > 0) { t0 = known[pos - 1]; p0 = get(t0); } else { t0 = a - (b - a); p0 = 2 * pa - pb; }
    if (pos + 2 < known.length) { t3 = known[pos + 2]; p3 = get(t3); } else { t3 = b + (b - a); p3 = 2 * pb - pa; }
    return cr1(t0, a, b, t3, p0, pa, pb, p3, i);
  }

  // Fill gaps along the string (neighbouring LEDs are physically adjacent) with a Catmull-Rom curve through the known LEDs on both sides
  // (a long gap between close neighbours must not swing wildly: the curve may leave the straight line by at most 0.4 of the gap's length).
  // With `arc` (a tree seen from one side) a long hidden run whose ends are far apart sideways is the string going round the back of the
  // tree: its x follows a half cosine (LEDs bunch up near the edges, as they do when they are spread evenly round a cone) while y is the curve.
  function interpolate(pts, { arc = false } = {}) {
    const out = pts.map(p => p && { ...p }), known = []; out.forEach((p, i) => p && known.push(i));
    if (!known.length) return out;
    const us = known.map(i => pts[i].u), width = Math.max(...us) - Math.min(...us);
    let pos = 0;
    for (let i = 0; i < out.length; i++) {
      if (out[i]) continue;
      while (pos + 1 < known.length && known[pos + 1] < i) pos++;
      if (known[pos] < i && pos + 1 < known.length) {
        const a = known[pos], b = known[pos + 1], t = (i - a) / (b - a), A = pts[a], B = pts[b];
        const round = arc && b - a >= 8 && Math.abs(B.u - A.u) > 0.4 * width;
        const lu = A.u + (B.u - A.u) * t, lv = A.v + (B.v - A.v) * t, lim = 0.4 * Math.hypot(B.u - A.u, B.v - A.v);
        let u = round ? A.u + (B.u - A.u) * (1 - Math.cos(Math.PI * t)) / 2 : crAt(known, pos, k => pts[k].u, i), v = crAt(known, pos, k => pts[k].v, i);
        const du = u - lu, dv = v - lv, m = Math.hypot(du, dv);
        if (m > lim) { const f = lim / m; u = lu + du * f; v = lv + dv * f; }
        out[i] = { u, v, src: 'interp' };
      } else { const k = known[pos] < i ? known[pos] : known[0]; out[i] = { u: out[k].u, v: out[k].v, src: 'interp' }; }  // beyond the ends: the nearest seen LED (a continuation of the string was tried on real photos and was worse)
    }
    return out;
  }

  // Camera pixels -> a frame with x to the right and y up: rot = quarter turns, flip = mirror x. Nothing scaled yet. Missing LEDs stay null.
  function orient(pts, { rot = 0, flip = false } = {}) {
    return pts.map(p => {
      if (!p) return null;
      let c = [p.u, -p.v];
      for (let r = 0; r < rot; r++) c = [-c[1], c[0]];
      if (flip) c = [-c[0], c[1]];
      return { x: c[0], y: c[1], src: p.src };
    });
  }

  // Camera pixels -> layout [-1,1] x [0,1] (y up). rot: quarter turns, flip: mirror x, mode: fit | stretch.
  function toLayout(pts, { rot = 0, flip = false, mode = 'fit' } = {}) {
    const c = orient(pts, { rot, flip }).map(p => [p.x, p.y]);
    const xs = c.map(p => p[0]), ys = c.map(p => p[1]);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const W = (x1 - x0) || 1, H = (y1 - y0) || 1;
    if (mode === 'stretch') return c.map(([x, y]) => ({ x: 2 * (x - x0) / W - 1, y: (y - y0) / H }));
    const s = Math.min(2 / W, 1 / H), xc = (x0 + x1) / 2;
    return c.map(([x, y]) => ({ x: (x - xc) * s, y: (y - y0) * s }));
  }

  const quant = (arr, q) => { const a = [...arr].sort((x, y) => x - y); return a[Math.min(a.length - 1, Math.max(0, Math.round(q * (a.length - 1))))]; };

  // A tree seen from the front and from the back (the phone on the opposite side, or the tree turned by 180 degrees) -> a 3D layout.
  // A, B: oriented points (see orient) of the two views, null where a LED was not seen. The back view is the front view mirrored, so it is
  // flipped in x and then moved and scaled onto the front view with the LEDs that BOTH views saw (a least-squares fit that throws out
  // the worst matches and repeats). With fewer than 6 of them the two outlines are laid over each other instead (the same height, the same
  // centre). Then the tree is taken as a cone: for every height the half width R(y) of what was seen (from the 95th percentile of the
  // distance from the axis in a band of heights, gaps filled, smoothed); a LED seen from the front sits on the circle of that radius at
  // z = +sqrt(R^2 - x^2), one seen from the back at z = -sqrt(...). A LED nobody saw is put between its known neighbours: the height by a
  // Catmull-Rom curve, the angle round the axis along the shorter arc, the radius from the profile (a spiral, as the Twinkly app does).
  function merge3d(A, B, { mode = 'fit' } = {}) {
    const n = A.length, Bm = B.map(p => p && { x: -p.x, y: p.y, src: p.src });
    const common = []; for (let i = 0; i < n; i++) if (A[i] && Bm[i]) common.push(i);
    const fit = idx => {
      const m = f => idx.reduce((s, i) => s + f(i), 0) / idx.length;
      const ax = m(i => A[i].x), ay = m(i => A[i].y), bx = m(i => Bm[i].x), by = m(i => Bm[i].y);
      let num = 0, den = 0; for (const i of idx) { num += (A[i].x - ax) * (Bm[i].x - bx) + (A[i].y - ay) * (Bm[i].y - by); den += (Bm[i].x - bx) ** 2 + (Bm[i].y - by) ** 2; }
      const s = den > 0 ? num / den : NaN;
      return { s, tx: ax - s * bx, ty: ay - s * by };
    };
    const res = (f, i) => Math.hypot(A[i].x - (f.s * Bm[i].x + f.tx), A[i].y - (f.s * Bm[i].y + f.ty));
    let T = null, align = 'common', rms = 0, used = 0;
    if (common.length >= 6) {
      let use = common, f = fit(use);
      for (let pass = 0; pass < 3 && isFinite(f.s); pass++) {
        const r = use.map(i => res(f, i)), m = quant(r, 0.5), keep = use.filter((_, k) => r[k] <= Math.max(2.5 * m, 1e-9));
        if (keep.length < 6 || keep.length === use.length) break;
        use = keep; f = fit(use);
      }
      if (isFinite(f.s) && f.s > 0.25 && f.s < 4) { T = f; used = use.length; rms = Math.sqrt(use.reduce((s, i) => s + res(f, i) ** 2, 0) / use.length); }
    }
    if (!T) {
      align = 'outline';
      const ext = P => { const a = P.filter(Boolean); return { y0: quant(a.map(p => p.y), 0.01), y1: quant(a.map(p => p.y), 0.99), x0: quant(a.map(p => p.x), 0.01), x1: quant(a.map(p => p.x), 0.99) }; };
      const ea = ext(A), eb = ext(Bm), s = ((ea.y1 - ea.y0) / (eb.y1 - eb.y0)) || 1;
      T = { s, tx: (ea.x0 + ea.x1) / 2 - s * (eb.x0 + eb.x1) / 2, ty: ea.y0 - s * eb.y0 };
    }
    const P = new Array(n).fill(null);
    for (let i = 0; i < n; i++) {
      const a = A[i], b = Bm[i] && { x: T.s * Bm[i].x + T.tx, y: T.s * Bm[i].y + T.ty };
      if (a && b) P[i] = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, side: 1, src: a.src };
      else if (a) P[i] = { x: a.x, y: a.y, side: 1, src: a.src };
      else if (b) P[i] = { x: b.x, y: b.y, side: -1, src: Bm[i].src };
    }
    const known = []; P.forEach((p, i) => p && known.push(i));
    if (known.length < 5) throw new Error('Too few LEDs were seen in the two views to build the tree.');
    const xs = known.map(i => P[i].x), cx = (quant(xs, 0.01) + quant(xs, 0.99)) / 2, ys = known.map(i => P[i].y);
    const y0 = Math.min(...ys), y1 = Math.max(...ys), H = (y1 - y0) || 1;
    // half width of the tree at every height
    const nb = Math.max(6, Math.min(30, Math.round(known.length / 10))), bands = Array.from({ length: nb }, () => []);
    for (const i of known) bands[Math.min(nb - 1, Math.floor((P[i].y - y0) / H * nb))].push(Math.abs(P[i].x - cx));
    let Rb = bands.map(b => b.length >= 3 ? quant(b, 0.95) : NaN);
    const have = Rb.map((v, k) => isNaN(v) ? -1 : k).filter(k => k >= 0);
    if (!have.length) throw new Error('Could not measure the width of the tree.');
    const Rraw = Rb;
    Rb = Rraw.map((v, k) => {
      if (!isNaN(v)) return v;
      const lo = have.filter(q => q < k).pop(), hi = have.find(q => q > k);
      if (lo === undefined) return Rraw[hi]; if (hi === undefined) return Rraw[lo];
      return Rraw[lo] + (Rraw[hi] - Rraw[lo]) * (k - lo) / (hi - lo);
    });
    const Rf = Rb; Rb = Rf.map((v, k) => (Rf[Math.max(0, k - 1)] + v + Rf[Math.min(nb - 1, k + 1)]) / 3);
    const Rmax = Math.max(...Rb), Rmin = 0.03 * Rmax;
    const R = y => { const q = (y - y0) / H * nb - 0.5, k = Math.max(0, Math.min(nb - 1, Math.floor(q))), k2 = Math.min(nb - 1, k + 1), f = Math.max(0, Math.min(1, q - k)); return Math.max(Rmin, Rb[k] + (Rb[k2] - Rb[k]) * f); };
    // known LEDs: on the circle of their height (height, angle)
    const Y = new Array(n), TH = new Array(n);
    for (const i of known) {
      const p = P[i], r = R(p.y), xr = Math.max(-1, Math.min(1, (p.x - cx) / r));
      Y[i] = p.y; TH[i] = Math.atan2(p.side * Math.sqrt(1 - xr * xr), xr);
    }
    const out = new Array(n); let pos = 0;
    for (let i = 0; i < n; i++) {
      let y, th; const src = P[i] ? P[i].src : 'interp';
      if (P[i]) { y = Y[i]; th = TH[i]; }
      else {
        while (pos + 1 < known.length && known[pos + 1] < i) pos++;
        if (known[pos] < i && pos + 1 < known.length) {
          const a = known[pos], b = known[pos + 1], t = (i - a) / (b - a);
          const ly = Y[a] + (Y[b] - Y[a]) * t; y = crAt(known, pos, k => Y[k], i);
          const lim = 0.4 * Math.abs(Y[b] - Y[a]); if (Math.abs(y - ly) > lim) y = ly + Math.sign(y - ly) * lim;
          let d = TH[b] - TH[a]; d -= 2 * Math.PI * Math.round(d / (2 * Math.PI));
          th = TH[a] + d * t;
        } else { const k = known[pos] < i ? known[pos] : known[0]; y = Y[k]; th = TH[k]; }
      }
      const r = R(y); out[i] = { x: r * Math.cos(th), y, z: r * Math.sin(th), src };
    }
    const maxX = Math.max(...out.map(p => Math.abs(p.x))) || 1;
    const s = mode === 'stretch' ? 1 / maxX : Math.min(1 / maxX, 1 / H), sy = mode === 'stretch' ? 1 / H : s;
    return { pts: out.map(p => ({ x: p.x * s, y: (p.y - y0) * sy, z: p.z * s, src: p.src })), common: common.length, used, align, rms: +rms.toFixed(2), scale: +T.s.toFixed(3) };
  }

  return { readableBlobs, lumaOf, estimateShift, shiftPlane, separation, despike, detect, detectHue, eccLayout, checkLeds, bitLeds, framePlan, suspicious, orient, merge3d, cr1, singleBlob, interpolate, searchRuns, filterOutliers, toLayout, percentile, blur3, maxArr, minArr, unstableMask, motion, roiOf };
})();

// ---- scan types ------------------------------------------------------------------------------------------------
// flat: a window or a wall, the camera sees every LED: all of them are found (by code, then one by one).
// tree: a tree seen from ONE side (a profile): only the LEDs facing the camera show up, the rest (the far side, behind branches) is
//       estimated along the string, so a low share of recognised LEDs is normal and the LEDs that stay hidden are not searched one by one.
// tree-fb: the same from the front and then from the back (the phone moves round the tree, or the tree is turned by 180 degrees); the
//       two views are joined by the LEDs both of them see and the result is a 3D layout (the tree is taken as a cone).
// tree-round (planned): four sides of a tree one after another. Not implemented yet.
const TREE = { minShare: 0.05, minCount: 30, refineHidden: false, aloneToo: false, refineLimit: 40, arc: true, searchRuns: true, searchLimit: 400, singleFactor: 0.3 };
const SCAN_MODES = {
  flat: { label: 'Flat wall or window: every LED is visible', minShare: 0.5, minCount: 20, refineHidden: true, aloneToo: true, refineLimit: 150, arc: false,
    hint: 'Put the phone on a tripod in front of the garland so that all of it is in view.' },
  tree: { label: 'Tree, one side (profile): the LEDs on the far side are estimated', ...TREE,
    hint: 'Put the phone on a tripod straight in front of the tree, the whole tree in view (top and bottom too), as dark as you can. The LEDs on the far side and behind the branches cannot be seen: they are estimated along the string.' },
  'tree-fb': { label: 'Tree, front and back (3D): two views are joined', ...TREE, searchLimit: 250, views: 2,
    nextHint: 'Front view done. Now move the phone to the OPPOSITE side of the tree (or turn the tree by 180 degrees): same distance, same height, the whole tree in view, the top up. Press "Next view" when it stands still.',
    hint: 'Two views of the whole tree, front and back, each as for "Tree, one side". The scan asks you to move the phone to the opposite side after the first view. The views are joined by the LEDs that both can see (at the edges of the tree), so both must show the whole tree from the bottom to the top.' },
  'tree-round': { label: 'Tree, all sides (planned, not available yet)', disabled: true },
};

// ---- UI ------------------------------------------------------------------------------------
const SC = { stream: null, video: null, running: false, cancel: false, waiting: false, resume: null, result: null, snap: null, opts: { rot: 0, flip: false, mode: 'fit' }, scanMode: 'flat', style: 'hue', stabilise: true, checkText: '', lockInfo: null, device: null, oldLayout: null, status: '' };
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

// What the camera lets the page control (Chrome on Android offers most, iPhones and Firefox offer almost nothing). The page puts the
// camera on manual at the values it has now, can then scale the exposure up or down (exposure time first, then ISO; or the exposure
// compensation where only that is offered), and freezes white balance and focus. `scale(f)` answers whether anything could be changed.
async function cameraControls() {
  const t = SC.stream.getVideoTracks()[0], caps = t.getCapabilities ? t.getCapabilities() : {}, st = t.getSettings ? t.getSettings() : {}, done = [], missing = [];
  const has = (m, v) => (caps[m] || []).includes(v);
  const apply = async c => { try { await t.applyConstraints({ advanced: [c] }); return true; } catch { return false; } };
  const clamp = (v, c) => Math.min(c.max, Math.max(c.min, v));
  const snap = (v, c) => c.step ? c.min + Math.round((v - c.min) / c.step) * c.step : v;
  const exp = { time: null, iso: null, comp: null }; let mode = null;
  if (has('exposureMode', 'manual') && caps.exposureTime && st.exposureTime) {
    exp.time = st.exposureTime; exp.iso = caps.iso && st.iso ? st.iso : null;
    if (await apply({ exposureMode: 'manual', exposureTime: exp.time, ...(exp.iso ? { iso: exp.iso } : {}) })) { done.push('exposure'); mode = 'manual'; } else missing.push('exposure');
  } else if (caps.exposureCompensation && st.exposureCompensation !== undefined) { exp.comp = st.exposureCompensation; mode = 'compensation'; done.push('exposure compensation'); }
  else missing.push('exposure');
  if (has('whiteBalanceMode', 'manual') && await apply({ whiteBalanceMode: 'manual', ...(st.colorTemperature ? { colorTemperature: st.colorTemperature } : {}) })) done.push('white balance'); else missing.push('white balance');
  if (st.focusDistance && has('focusMode', 'manual') && await apply({ focusMode: 'manual', focusDistance: st.focusDistance })) done.push('focus'); else if (st.focusDistance) missing.push('focus');
  return {
    done, missing,
    info: () => mode === 'manual' ? `exposure ${exp.time}${exp.iso ? ', ISO ' + exp.iso : ''}` : mode === 'compensation' ? `exposure compensation ${exp.comp}` : 'exposure automatic',
    async scale(f) {
      if (mode === 'manual') {
        const t0 = exp.time, i0 = exp.iso, time = snap(clamp(t0 * f, caps.exposureTime), caps.exposureTime);
        let iso = i0; if (iso) iso = snap(clamp(iso * (f * t0 / time), caps.iso), caps.iso);
        if (Math.abs(time * (iso || 1) / (t0 * (i0 || 1)) - 1) < 0.05) return false;
        if (!(await apply({ exposureTime: time, ...(iso ? { iso } : {}) }))) return false;
        exp.time = time; exp.iso = iso; return true;
      }
      if (mode === 'compensation') {
        const next = snap(clamp(exp.comp + Math.log2(f), caps.exposureCompensation), caps.exposureCompensation);
        if (Math.abs(next - exp.comp) < 0.05 || !(await apply({ exposureCompensation: next }))) return false;
        exp.comp = next; return true;
      }
      return false;
    },
  };
}

async function unlockExposure() {  // give the camera its automatics back
  const t = SC.stream && SC.stream.getVideoTracks()[0]; if (!t) return;
  for (const c of [{ exposureMode: 'continuous' }, { whiteBalanceMode: 'continuous' }, { focusMode: 'continuous' }]) {
    try { await t.applyConstraints({ advanced: [c] }); } catch { /* not supported */ }
  }
}

// Brightness. The brighter the LEDs are for the camera, the more of their halo the decoder can read and the more dim LEDs (turned away from the
// camera, behind branches) are seen at all; but beyond a point the halos run into each other and the colour is washed out. What counts is how
// many LEDs the decoder can read: the number of LED-sized readable areas in the all-red and all-blue photo (ScanLib.readableBlobs), which on the real
// scans went with the number of LEDs the scan found (101 -> 168, 233 -> 248, 292 -> 302). The exposure is searched like the top of a hill. (Two
// earlier aims were wrong: "few clipped pixels" lowered the exposure until the LEDs were too dim, "many usable pixels" and a fixed colour
// distinctness were fooled by the glow of the wall and by the fact that more light gives more LEDs even when the colour is a little worse.)
// The camera exposure is moved; where the browser does not allow that the LED brightness is (30..255).
async function tuneCamera({ cam, status, check, every, style = 'hue', frac = 0.06 }) {
  const MIN_LEVEL = 30; let level = 255;
  await pat({ kind: 'dark' }); await settle(); const dark = await shot();
  const measure = async () => {
    check();
    await pat({ kind: 'rgb', channels: [every, [], []], level }); await settle(); const red = await shot();
    await pat({ kind: 'rgb', channels: [[], [], every], level }); await settle(); const blue = await shot();
    const sep = ScanLib.separation(dark.rgb, red.rgb, blue.rgb);
    const m = { sep: sep.lit ? sep.sep : 0, lit: sep.lit, peak: Math.max(peakOf(red, dark, true), peakOf(blue, dark, true)), use: usableOf(red, dark) + usableOf(blue, dark), count: ScanLib.readableBlobs(dark.rgb, red.rgb, blue.rgb, red.w, red.h) };
    m.eff = m.sep >= 0.3 ? m.count : 0;  // washed-out colours (red and blue alike) count for nothing: the rings left at the edges of the halos would be counted
    status(`Setting the exposure: LED level ${level}, ${cam.info()}: ${m.count} LEDs readable, colour distinctness ${m.sep.toFixed(2)}, brightest channel ${m.peak} of 255...`, frac);
    note(`tune: level ${level}, ${cam.info()}, readable LEDs ${m.count}, distinctness ${m.sep.toFixed(2)}, lit ${m.lit}, clipped ${Math.round(100 * sep.satShare)}%, peak ${m.peak}, usable ${m.use}; brightest 0.5% of the red photo RGB ${topMean(red, dark)}, of the blue photo ${topMean(blue, dark)}; last wait ${SC.lastSettle ? SC.lastSettle.ms + ' ms' + (SC.lastSettle.gaveUp ? ' (gave up, picture still changing: ' + SC.lastSettle.changed + ' px)' : '') : '-'}`);
    return m;
  };
  // one step brighter / darker: the camera if it can, else the LEDs; returns how to undo it, or null when there is no room left
  const adjust = async f => {
    if (await cam.scale(f)) return async () => { await cam.scale(1 / f); };
    const nl = Math.max(MIN_LEVEL, Math.min(255, Math.round(level * f)));
    if (nl === level) return null;
    const old = level; level = nl; return async () => { level = old; };
  };
  if (style !== 'hue') {
    // codes that switch the LEDs on and off (colour bits, white): bright blobs, but not blown up (blown-up blobs merge): the brightest channel of the
    // all-on photo about 190-230 of 255
    let peak = 0;
    for (let t = 0; t < 10; t++) {
      check(); await pat({ kind: 'all', level }); await settle(); const a = await shot(); peak = peakOf(a, dark, true);
      status(`Setting the exposure: LED level ${level}, ${cam.info()}, brightest channel ${peak} of 255 (aim 150-230)...`, frac);
      if (peak >= 235) { if (!(await adjust(Math.max(0.1, 190 / peak)))) break; }
      else if (peak < 120) { if (!(await adjust(Math.min(4, 170 / Math.max(peak, 4))))) break; }
      else break;
    }
    return { level, peak, usable: undefined, sep: undefined };
  }
  // the top of a hill: one step in one direction while the number of readable LEDs grows (by 4% or more), if not, back and the other direction.
  // While nothing counts (no LED seen, or the colours washed out) the steps go on without waiting for an improvement.
  let best = await measure(), depth = 0;
  const dirs = best.lit === 0 || best.sep >= 0.3 ? [1.5, 1 / 1.5] : [1 / 1.5, 1.5];  // colours already washed out: darker first
  for (const f of dirs) {
    const stack = [];
    for (let t = 0; t < 8; t++) {
      const undo = await adjust(f); if (!undo) break;
      stack.push(undo); const m = await measure();
      if (m.eff > best.eff * 1.04 && m.eff > 0) { best = m; depth = stack.length; }
      else if (!(best.eff === 0 && m.eff === 0)) break;
    }
    for (let k = stack.length - 1; k >= depth; k--) await stack[k]();  // the steps after the best one are taken back
    if (depth > 0) break;                                              // it got better this way: do not try the other one
  }
  const m = best;
  return { level, peak: m.peak, usable: m.count, sep: m.sep };
}

// What the colour photos of a scan say about the setup, for the user.
function colourVerdict(sep, peak, count) {
  if (!sep || !sep.lit) return { ok: false, text: 'No LEDs were seen in the red and blue photos: is the garland in view?' };
  const s = sep.sep.toFixed(2), us = count !== undefined ? `, ${count} LEDs readable` : '';
  if (sep.sep < 0.3) return { ok: false, text: `Red and blue are hard to tell apart for the camera (distinctness ${s}, 1 = perfect, the decoder gives up below 0.22${us}): the LEDs are too bright for the camera or the camera mixes the colours. Move the phone farther away or darken further; the scan will try white patterns if it cannot read the colours.` };
  if (peak < 90) return { ok: false, text: `The LEDs are dim for the camera (brightest channel ${peak} of 255, distinctness ${s}${us}): move the phone closer.` };
  return { ok: true, text: `Colours are distinct (distinctness ${s}${us}, brightest channel ${peak} of 255).` };
}

// Quick check of the camera set-up without a scan: exposure, red against blue.
async function cameraCheck() {
  const dev = document.getElementById('scan-dev').value; SC.device = dev;
  SC.running = true; SC.cancel = false; renderScan();
  const check = () => { if (SC.cancel) throw new Error('cancelled'); };
  let cam = null, started = false;
  try {
    scanStatus('Switching the garland to scan mode...', 0.02);
    const info = await send('api/scan/start', { device: dev }); started = true;
    if (info.profile && info.profile !== 'RGB') throw new Error(`this garland has the LED profile ${info.profile}: it is scanned with white patterns, the red / blue check does not apply`);
    const every = Array.from({ length: info.leds }, (_, i) => i);
    cam = await cameraControls(); SC.lockInfo = { done: cam.done, missing: cam.missing };
    const { level, peak, usable } = await tuneCamera({ cam, status: scanStatus, check, every });
    await pat({ kind: 'dark' }); await settle(); const dark = await shot();
    await pat({ kind: 'rgb', channels: [every, [], []], level }); await settle(); const red = await shot();
    await pat({ kind: 'rgb', channels: [[], [], every], level }); await settle(); const blue = await shot();
    const v = colourVerdict(ScanLib.separation(dark.rgb, red.rgb, blue.rgb), peak, usable);
    note(`check: ${v.text} (${cam.info()}, LED level ${level}); brightest 0.5% of the red photo RGB ${topMean(red, dark)}, of the blue photo ${topMean(blue, dark)}`);
    SC.dump = { id: new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14) + 'c', w: red.w, h: red.h, n: info.leds, mode: 'check', style: 'check', level, device: dev, photos: [['dark', dark.rgb], ['calr', red.rgb], ['calb', blue.rgb]] };
    SC.checkText = `${v.ok ? 'Camera OK. ' : 'Check: '}${v.text} (${cam.info()}, LED level ${level}.)`;
    scanStatus(SC.checkText, 1);
  } catch (e) { scanStatus(e.message === 'cancelled' ? 'Cancelled.' : 'Camera check failed: ' + e.message, undefined); }
  finally { if (cam) await unlockExposure(); if (started) { try { await send('api/scan/stop', {}); } catch { /* ignore */ } } SC.running = false; renderScan(); }
}

// Wait until the camera shows the pattern that was just lit: at least `minMs` (the garland, the camera's own delay), then until the
// live picture stops changing (two looks 40 ms apart with fewer than 8 pixels changed by more than 20 and by more than a quarter of their value). This also waits out an automatic
// exposure that is still adapting. A function declaration so tests can replace it.
const sigCv = document.createElement('canvas');
function liveFrame() {
  const v = SC.video; sigCv.width = 320; sigCv.height = 180;
  const g = sigCv.getContext('2d', { willReadFrequently: true }); g.drawImage(v, 0, 0, 320, 180);
  const d = g.getImageData(0, 0, 320, 180).data, o = new Uint8Array(320 * 180);
  for (let i = 0; i < o.length; i++) o[i] = d[4 * i + 1];
  return o;
}
async function settle(minMs = 150, maxMs = 1500) {
  await sleep(minMs); const t0 = performance.now(); let prev = liveFrame(), calm = 0, worst = 0;
  while (performance.now() - t0 < maxMs) {
    await sleep(40); const cur = liveFrame(); let ch = 0;
    for (let i = 0; i < cur.length; i++) { const d = Math.abs(cur[i] - prev[i]); if (d > 20 && d > 0.25 * Math.max(cur[i], prev[i])) ch++; }  // noise of a bright pixel is no change
    prev = cur; worst = Math.max(worst, ch);
    if (ch < 8) { if (++calm >= 2) { SC.lastSettle = { ms: Math.round(minMs + performance.now() - t0), gaveUp: false, changed: ch }; return; } } else calm = 0;
  }
  SC.lastSettle = { ms: Math.round(minMs + performance.now() - t0), gaveUp: true, changed: worst };  // the picture never calmed down
}

// A line into the add-on log (what the camera measured), so that it can be read without the phone.
function note(text) { try { send('api/scan/note', { text }).catch(() => {}); } catch { /* a convenience */ } }

// Mean colour (R, G, B, the dark photo taken off) of the brightest 0.5% of the pixels of a photo: what the LEDs look like to the camera.
function topMean(a, dk) {
  const N = a.data.length, k = Math.max(50, Math.round(N * 0.005)), v = new Float32Array(N);
  for (let i = 0; i < N; i++) v[i] = Math.max(0, a.rgb[0][i] - dk.rgb[0][i]) + Math.max(0, a.rgb[1][i] - dk.rgb[1][i]) + Math.max(0, a.rgb[2][i] - dk.rgb[2][i]);
  const hist = new Uint32Array(766); for (let i = 0; i < N; i++) hist[Math.min(765, Math.round(v[i]))]++;
  let acc = 0, thr = 765; for (; thr > 0; thr--) { acc += hist[thr]; if (acc >= k) break; }
  let n = 0, r = 0, g = 0, b = 0;
  for (let i = 0; i < N; i++) if (v[i] >= thr) { n++; r += Math.max(0, a.rgb[0][i] - dk.rgb[0][i]); g += Math.max(0, a.rgb[1][i] - dk.rgb[1][i]); b += Math.max(0, a.rgb[2][i] - dk.rgb[2][i]); }
  return n ? [Math.round(r / n), Math.round(g / n), Math.round(b / n)] : [0, 0, 0];
}

const cvs = document.createElement('canvas');
// Average of two frames: { w, h, rgb: [R, G, B] (Uint8), data: luma (Uint8) }. A function declaration so tests can replace it.
async function shot() {
  const v = SC.video;
  for (let t = 0; t < 40 && !v.videoWidth; t++) await sleep(50);  // a freshly drawn page: the picture may need a moment
  const w = v.videoWidth, h = v.videoHeight; cvs.width = w; cvs.height = h;
  const ctx = cvs.getContext('2d', { willReadFrequently: true }), acc = [0, 1, 2].map(() => new Uint16Array(w * h));
  for (let n = 0; n < 2; n++) {
    ctx.drawImage(v, 0, 0, w, h); const d = ctx.getImageData(0, 0, w, h).data;
    for (let i = 0; i < w * h; i++) { acc[0][i] += d[4 * i]; acc[1][i] += d[4 * i + 1]; acc[2][i] += d[4 * i + 2]; }
    if (n === 0) await sleep(40);
  }
  const rgb = acc.map(a => { const o = new Uint8Array(w * h); for (let i = 0; i < o.length; i++) o[i] = (a[i] + 1) >> 1; return o; });
  const data = new Uint8Array(w * h); for (let i = 0; i < data.length; i++) data[i] = Math.round(0.299 * rgb[0][i] + 0.587 * rgb[1][i] + 0.114 * rgb[2][i]);
  return { w, h, rgb, data };
}

function pat(body) { return send('api/scan/pattern', body); }

function scanLoadMode(dev) {  // the scan type is remembered per garland
  SC.device = dev;
  try {
    const m = localStorage.getItem('scan-mode:' + dev); if (m && SCAN_MODES[m] && !SCAN_MODES[m].disabled) SC.scanMode = m;
    const c = localStorage.getItem('scan-style'); if (c === 'hue' || c === 'rgb' || c === 'mono') SC.style = c;
  } catch { /* no storage */ }
}

function scanSaveMode() { try {  localStorage.setItem('scan-mode:' + SC.device, SC.scanMode); localStorage.setItem('scan-style', SC.style); } catch { /* no storage */ } }

// Sends the photos of the last scan to the add-on (lossless PNGs, colour photos in colour + a small JSON) so that a scan that went wrong can be examined.
async function scanSendPhotos() {
  const d = SC.dump; if (!d) return;
  const cv = document.createElement('canvas'); cv.width = d.w; cv.height = d.h; const g = cv.getContext('2d');
  try {
    const put = async (name, body, type) => {
      const r = await fetch(`api/scan/dump/${d.id}/${name}`, { method: 'PUT', headers: { 'Content-Type': type }, body });
      if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
    };
    for (let k = 0; k < d.photos.length; k++) {
      const [name, planes] = d.photos[k]; scanStatus(`Sending photo ${k + 1} of ${d.photos.length}...`, k / d.photos.length);
      const img = g.createImageData(d.w, d.h), c3 = planes.length === 3;
      for (let i = 0; i < d.w * d.h; i++) {
        for (let c = 0; c < 3; c++) img.data[4 * i + c] = Math.max(0, Math.min(255, Math.round(planes[c3 ? c : 0][i])));
        img.data[4 * i + 3] = 255;
      }
      g.putImageData(img, 0, 0);
      await put(name + '.png', await new Promise(res => cv.toBlob(res, 'image/png')), 'image/png');
    }
    const meta = { device: d.device, mode: d.mode, style: d.style, lock: SC.lockInfo, n: d.n, w: d.w, h: d.h, level: d.level, pts: d.pts || null, stats: SC.result ? SC.result.stats : null, agent: navigator.userAgent };
    await put('meta.json', JSON.stringify(meta), 'application/json');
    d.sent = true; scanStatus(`Photos sent (${d.id}).`, 1); toast(`Photos sent: ${d.id}`); renderScan();
  } catch (e) { scanStatus('Sending failed: ' + e.message, undefined); toast('Sending failed: ' + e.message, true, 8000); }
}

function scanStatus(msg, frac) {
  SC.status = msg; const el = document.getElementById('scan-status'), bar = document.getElementById('scan-bar');
  if (el) el.textContent = msg; if (bar && frac !== undefined) bar.firstChild.style.width = `${Math.round(frac * 100)}%`;
}

// Number of pixels of a photo that the decoder can use: a channel at least 30 above the dark photo and no channel clipped (under 240).
function usableOf(a, dk) {
  let n = 0;
  for (let i = 0; i < a.data.length; i++) {
    const r = a.rgb[0][i], g = a.rgb[1][i], b = a.rgb[2][i];
    if (Math.max(r, g, b) < 240 && Math.max(r - dk.rgb[0][i], g - dk.rgb[1][i], b - dk.rgb[2][i]) >= 30) n++;
  }
  return n;
}

// Share of the lit pixels (a channel more than 60 above the dark photo) of a photo that are clipped (a channel at 250 or more): clipped LEDs
// turn white and lose their colour.
function clipOf(a, dk) {
  let lit = 0, clip = 0;
  for (let i = 0; i < a.data.length; i++) {
    const r = a.rgb[0][i], g = a.rgb[1][i], b = a.rgb[2][i];
    if (Math.max(r - dk.rgb[0][i], g - dk.rgb[1][i], b - dk.rgb[2][i]) <= 60) continue;
    lit++; if (Math.max(r, g, b) >= 250) clip++;
  }
  return lit ? clip / lit : 0;
}

// Strongest channel (or luma) of a photo minus the dark one, 99.9th percentile: tells whether the camera is dazzled.
function peakOf(a, dk, colour) {
  let pk = 0;
  for (const c of colour ? [0, 1, 2] : [-1]) {
    const x = c < 0 ? a.data : a.rgb[c], y = c < 0 ? dk.data : dk.rgb[c], d = new Float32Array(x.length);
    for (let i = 0; i < d.length; i++) d[i] = Math.max(0, x[i] - y[i]);
    pk = Math.max(pk, ScanLib.percentile(d, 99.9));
  }
  return pk;
}

// A shaking phone (a hand, a tripod that sags): every photo of the scan is moved back onto the first all-on photo. The shift of a photo is found by
// correlating the light of its LEDs with the reference (translation only), the planes are resampled. The closing all-on photo is moved too, and
// its shift (the latest one) is what the single-LED photos afterwards are corrected with.
function stabilise({ ref, dark, cap, all2, w, h }) {
  const light = planes => { const l = ScanLib.lumaOf(planes), o = new Float32Array(l.length); for (let i = 0; i < o.length; i++) o[i] = Math.max(0, l[i] - dark.data[i]); return o; };
  const refLight = light([ref.data]), shifts = []; let moved = 0;
  const fix = planes => {
    const d = ScanLib.estimateShift(refLight, light(planes), w, h);
    if (!d) return planes;
    shifts.push(d);
    if (Math.abs(d.dx) + Math.abs(d.dy) < 0.15) return planes;
    moved++; return planes.map(p => ScanLib.shiftPlane(p, w, h, d.dx, d.dy));
  };
  cap.cal = cap.cal.map(fix);
  cap.frames = cap.frames.map(f => Array.isArray(f) ? fix(f) : { ...f, planes: fix(f.planes) });
  const d2 = all2 ? ScanLib.estimateShift(refLight, light([all2.data]), w, h) : null;
  const all2L = d2 ? ScanLib.shiftPlane(all2.data, w, h, d2.dx, d2.dy) : all2 ? all2.data : null;
  const mag = shifts.concat(d2 ? [d2] : []).map(d => Math.hypot(d.dx, d.dy));
  return { all2L, last: d2 || { dx: 0, dy: 0 }, max: mag.length ? Math.max(...mag) : 0, moved, n: shifts.length };
}

// One view of the garland: photos -> positions of the LEDs found (null where nothing was found; nothing interpolated yet).
// style: 'hue' (every LED lit in every frame, red = 0, blue = 1, decoded pixel by pixel), 'rgb' (R, G, B on / off = three bits per frame)
// or 'mono' (white on / off, one bit per frame). When the chosen style is not read the scan repeats itself with 'mono'.
async function scanView({ dev, M, scanMode, style: wanted, check, status, v, dump }) {
  const tag = v ? `v${v}_` : '';
  status('Switching the garland to scan mode...', 0.02);
  const info = await send('api/scan/start', { device: dev }); const n = info.leds, nb = info.bits;
  dump.n = n;
  // colour patterns need red and blue LEDs: a garland with another LED profile (white / amber, red-blue-white) is scanned with white patterns
  const style = info.profile && info.profile !== 'RGB' ? 'mono' : wanted;
  if (style !== wanted) status(`This garland has the LED profile ${info.profile}: colour patterns need RGB, so white patterns are used.`, 0.03);
  let locked = false, colourShots = style !== 'mono';
  try {
    const take = async (name, body) => {  // light a pattern, wait until the camera shows it, photograph, keep for the dump
      check(); await pat(body); await settle(); const s = await shot();
      dump.w = s.w; dump.h = s.h; dump.photos.push([tag + name, colourShots ? s.rgb : [s.data]]);
      return s;
    };
    const everyLed = Array.from({ length: n }, (_, i) => i);
    await pat({ kind: 'dark' }); await settle();
    const cam = await cameraControls(); SC.lockInfo = { done: cam.done, missing: cam.missing }; locked = true;
    status('Setting the exposure...', 0.06);
    const { level, peak: camPeak, usable: camUsable } = await tuneCamera({ cam, status, check, every: everyLed, style });
    dump.level = level; SC.lockInfo.exposure = cam.info();
    let dark;
    status('Photo: everything off...', 0.1); dark = await take('dark', { kind: 'dark' });
    status('Photo: everything on...', 0.14); const all1 = await take('all', { kind: 'all', level });
    const capture = async st => {
      if (st === 'hue') {
        // two reference photos (all red, all blue), then one photo per code bit: every LED red (0) or blue (1)
        const total = nb + ScanLib.eccLayout(nb).r, frames = [], cal = [], steps = total + 2;
        status(`Photo: all LEDs red (1 of ${steps})...`, 0.18 + 0.4 / steps);
        cal.push((await take('calr', { kind: 'rgb', channels: [everyLed, [], []], level })).rgb);
        status(`Photo: all LEDs blue (2 of ${steps})...`, 0.18 + 0.4 * 2 / steps);
        cal.push((await take('calb', { kind: 'rgb', channels: [[], [], everyLed], level })).rgb);
        for (let k = 0; k < total; k++) {
          status(`Photo: code pattern ${k + 1} of ${total} (${k + 3} of ${steps})...`, 0.18 + 0.4 * (k + 3) / steps);
          const ones = ScanLib.bitLeds(n, nb, k), one = new Uint8Array(n); for (const i of ones) one[i] = 1;
          frames.push((await take('f' + k, { kind: 'rgb', channels: [everyLed.filter(i => !one[i]), [], ones], level })).rgb);
        }
        return { cal, frames };
      }
      // rgb: one frame carries three bits (red, green and blue of every LED on / off) after three photos with all LEDs red / green / blue
      // that tell the camera's response to each colour. mono: one bit per frame.
      const col = st === 'rgb', plan = ScanLib.framePlan(nb, col), cal = [], frames = [], steps = plan.length + (col ? 3 : 0); let done = 0;
      if (col) for (let j = 0; j < 3; j++) {
        status(`Photo: all LEDs ${['red', 'green', 'blue'][j]} (${++done} of ${steps})...`, 0.18 + 0.4 * done / steps);
        cal.push((await take('cal' + 'rgb'[j], { kind: 'rgb', channels: [0, 1, 2].map(c => c === j ? everyLed : []), level })).rgb);
      }
      for (let f = 0; f < plan.length; f++) {
        status(`Photo: ${col ? 'colour ' : ''}code pattern ${f + 1} of ${plan.length} (${++done} of ${steps})...`, 0.18 + 0.4 * done / steps);
        const bits = plan[f].bits;
        const s = await take('f' + f, col ? { kind: 'rgb', channels: bits.map(k => k < 0 ? [] : ScanLib.bitLeds(n, nb, k)), level } : { kind: 'leds', leds: ScanLib.bitLeds(n, nb, bits[0]), level });
        frames.push({ planes: col ? s.rgb : [s.data], bits });
      }
      return { cal, frames };
    };
    let st = style, cap = await capture(st), sep = null;
    if (st === 'hue') {
      sep = ScanLib.separation(dark.rgb, cap.cal[0], cap.cal[1]);
      const v = colourVerdict(sep, camPeak, camUsable); if (!v.ok) status(v.text, 0.58);
    }
    // second pair of photos at the end: only what is the same in both counts (drops flickering lights, passing cars)
    status('Photo: everything off, again...', 0.58); const dark2 = await take('dark2', { kind: 'dark' });
    status('Photo: everything on, again...', 0.6); const all2 = await take('all2', { kind: 'all', level });
    status('Recognising the LEDs...', 0.62); await sleep(30);
    const w = all1.w, h = all1.h;
    let mv, allL, lastShift = { dx: 0, dy: 0 };
    if (SC.stabilise) {
      status('Aligning the photos...', 0.61);
      const sh = stabilise({ ref: all1, dark, cap, all2, w, h });
      mv = { shift: sh.max }; allL = ScanLib.minArr(all1.data, sh.all2L); lastShift = sh.last;
      if (sh.max > 15) throw new Error(`The phone moved by up to ${sh.max.toFixed(0)} px during the scan, too much to put the photos back together. Put it on a tripod or a stable surface and try again.`);
    } else {
      mv = ScanLib.motion(w, h, dark.data, all1.data, dark2.data, all2.data);
      if (mv && mv.shift > 2) throw new Error(`The phone moved by about ${mv.shift.toFixed(1)} px during the scan. Put it on a tripod or a stable surface and try again.`);
      allL = ScanLib.minArr(all1.data, all2.data);
    }
    const darkL = ScanLib.maxArr(dark.data, dark2.data);
    const darkRGB = [0, 1, 2].map(c => ScanLib.maxArr(dark.rgb[c], dark2.rgb[c]));
    const unstable = ScanLib.unstableMask(dark.data, dark2.data, w, h);
    const decode = (s, k) => s === 'hue'
      ? ScanLib.detectHue({ w, h, dark: darkL, all: allL, darkP: darkRGB, calR: k.cal[0], calB: k.cal[1], frames: k.frames, nb, n, exclude: unstable })
      : ScanLib.detect({ w, h, dark: darkL, all: allL, darkP: s === 'rgb' ? darkRGB : [darkL], cal: s === 'rgb' ? k.cal : [[allL]], frames: k.frames, nb, n });
    let det = decode(st, cap), fellBack = false;
    let pts = det.pts, decoded = pts.filter(Boolean).length;
    const enough = () => decoded >= Math.max(M.minCount, n * M.minShare);
    if (st !== 'mono' && !enough()) {  // the colours were not read (a camera that mixes them, a very bright room): the same with white patterns
      status('The colour patterns were not recognised, repeating with white ones...', 0.62);
      st = 'mono'; colourShots = false; cap = await capture('mono'); if (SC.stabilise) stabilise({ ref: all1, dark, cap, all2: null, w, h }); det = decode('mono', cap); pts = det.pts; decoded = pts.filter(Boolean).length; fellBack = true;
    }
    if (!enough()) throw new Error(scanMode.startsWith('tree')
      ? `Only ${decoded} of ${n} LEDs could be recognised (${Math.round(100 * decoded / n)}%), too few even for a view from one side. Move the phone closer so that the tree fills the picture, darken the room, and check that the whole tree is in view.`
      : `Only ${decoded} of ${n} LEDs could be recognised. The phone probably moved (use a tripod), the garland is not fully in view, or the room is too bright. For a tree seen from one side choose the scan type "Tree, one side".`);
    const f1 = ScanLib.filterOutliers(pts); pts = f1.pts; let dropped = f1.removed.length;  // wrongly decoded LEDs do not stay on the string
    // refine: missing and suspicious LEDs one at a time
    const todo = [...new Set([...(M.refineHidden ? pts.map((p, i) => p ? -1 : i).filter(i => i >= 0) : []), ...ScanLib.suspicious(pts, M.aloneToo)])];
    const limit = Math.min(todo.length, M.refineLimit); let refined = 0;
    const roi = ScanLib.roiOf(pts, w, h);
    const lv = Math.max(level, 200);
    for (let q = 0; q < limit; q++) {
      check(); const i = todo[q]; status(`Checking LED ${i} separately (${q + 1} of ${limit}), brightness ${lv}...`, 0.62 + 0.36 * q / Math.max(1, limit));
      await pat({ kind: 'leds', leds: [i], level: lv }); await settle(120);
      const s = await shot(), b = ScanLib.singleBlob({ w, h, dark: darkL, frame: s.data, minPeak: Math.max(10, det.peak * 0.3), roi, exclude: unstable });
      pts[i] = b ? { ...b, u: b.u - lastShift.dx, v: b.v - lastShift.dy, src: 'single' } : null; if (b) refined++;  // a LED that does not show up alone was a false detection
    }
    if (M.searchRuns) {  // a tree: look for the LEDs that are visible but were too close together to be told apart by code
      const minPeak = Math.max(10, det.peak * M.singleFactor), roi2 = ScanLib.roiOf(pts, w, h, { x: 0.15, top: 0.6, bottom: 0.1 });
      const stat = await ScanLib.searchRuns(pts, async i => {
        await pat({ kind: 'leds', leds: [i], level: lv }); await settle(120); const s1 = await shot();
        const b1 = ScanLib.singleBlob({ w, h, dark: darkL, frame: s1.data, minPeak, roi: roi2, exclude: unstable });
        return b1 && { ...b1, u: b1.u - lastShift.dx, v: b1.v - lastShift.dy };
      }, { limit: M.searchLimit, check, progress: (u, l, i) => status(`Looking for LED ${i} on its own (${u} of at most ${l}), brightness ${lv}...`, 0.62 + 0.36 * u / l) });
      refined += stat.found;
    }
    const f2 = ScanLib.filterOutliers(pts); pts = f2.pts; dropped += f2.removed.length;
    return { pts, w, h, n, level, det, decoded, refined, dropped, mv, snap: all1.data, style: st, fellBack, sep };
  } finally {
    if (locked) await unlockExposure();
    try { await send('api/scan/stop', {}); } catch { /* ignore */ }
  }
}

// Between two views: the garland is back to normal while the phone is moved; "Next view" goes on.
async function waitForNextView(M, check) {
  SC.waiting = true; scanStatus(M.nextHint, 0.5); renderScan();
  await new Promise(res => { SC.resume = res; });
  SC.resume = null; SC.waiting = false; renderScan(); check();
}

const sumOf = (rs, f) => rs.reduce((s, r) => s + f(r), 0);

async function runScan() {
  const dev = document.getElementById('scan-dev').value;
  SC.device = dev;
  SC.running = true; SC.cancel = false; SC.waiting = false; SC.result = null; SC.device = dev; renderScan();
  const M = SCAN_MODES[SC.scanMode] || SCAN_MODES.flat, scanMode = SC.scanMode, nViews = M.views || 1, style = SC.style;
  const check = () => { if (SC.cancel) throw new Error('cancelled'); };
  const dump = SC.dump = { id: new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14), w: 0, h: 0, n: 0, mode: scanMode, style, level: 0, device: dev, photos: [] };
  try {
    const vs = [];
    for (let v = 0; v < nViews; v++) {
      if (v > 0) await waitForNextView(M, check);
      const status = (m, f) => scanStatus((nViews > 1 ? `View ${v + 1} of ${nViews}: ` : '') + m, f === undefined ? undefined : (v + f) / nViews);
      vs.push(await scanView({ dev, M, scanMode, style, check, status, v, dump }));
    }
    const r0 = vs[0], n = r0.n, w = r0.w, h = r0.h;
    const base = {
      mode: scanMode, n, decoded: sumOf(vs, r => r.decoded), refined: sumOf(vs, r => r.refined), dropped: sumOf(vs, r => r.dropped),
      shift: vs.some(r => r.mv) ? +Math.max(...vs.map(r => r.mv ? r.mv.shift : 0)).toFixed(1) : null,
      blobs: sumOf(vs, r => r.det.blobs), merged: sumOf(vs, r => r.det.merged), invalid: sumOf(vs, r => r.det.invalid), conflicts: sumOf(vs, r => r.det.conflicts),
      sep: vs[0].sep ? +vs[0].sep.sep.toFixed(2) : null, clipped: vs[0].sep ? Math.round(100 * vs[0].sep.satShare) : null,
      uncertain: sumOf(vs, r => r.det.uncertain), corrected: sumOf(vs, r => r.det.corrected), rejected: sumOf(vs, r => r.det.rejected), level: r0.level,
      styles: [...new Set(vs.map(r => r.style))], fellBack: vs.some(r => r.fellBack),
    };
    const views = vs.map(r => ({ w: r.w, h: r.h, pts: r.pts, snap: r.snap }));
    if (nViews === 1) {
      const hidden = r0.pts.filter(p => !p).length;
      const pts = ScanLib.interpolate(r0.pts, { arc: M.arc });
      if (pts.some(p => !p)) throw new Error('No LED was found. Make sure the garland is in view and the room is dark.');
      dump.pts = pts.map(p => ({ u: +p.u.toFixed(2), v: +p.v.toFixed(2), src: p.src }));
      views[0].pts = pts;
      SC.result = { pts, w, h, n, is3d: false, views, stats: { ...base, hidden } };
    } else {
      dump.pts = vs.map(r => r.pts.map(p => p && { u: +p.u.toFixed(2), v: +p.v.toFixed(2), src: p.src }));
      const res = { w, h, n, is3d: true, views, stats: base };
      const lay = buildLayout(res);  // joins the views now, so that a failure shows as a failed scan
      res.stats = { ...base, hidden: lay.filter(p => p.src === 'interp').length, decoded: lay.filter(p => p.src === 'code').length, refined: lay.filter(p => p.src === 'single').length, ...res.merge };
      SC.result = res;
    }
    SC.snap = { w, h, data: r0.snap };
    SC.oldLayout = await api(`api/devices/${encodeURIComponent(dev)}/layout`);
    scanStatus('Done. Check the result below, then apply it.', 1);
  } catch (e) {
    scanStatus(e.message === 'cancelled' ? 'Cancelled.' : 'Scan failed: ' + e.message, undefined);
    if (e.message !== 'cancelled') toast('Scan failed: ' + e.message, true, 8000);
  } finally {
    SC.running = false; SC.waiting = false; SC.resume = null; renderScan();
  }
}

// The layout of a result for the current rotate / mirror / scale options: x, y (and z for two views joined).
function buildLayout(r) {
  let lay, keys;
  if (!r.is3d) { lay = ScanLib.toLayout(r.views[0].pts, SC.opts).map((p, i) => ({ ...p, src: r.views[0].pts[i].src })); keys = ['x', 'y']; }
  else {
    const o = { rot: SC.opts.rot, flip: SC.opts.flip };
    const m = ScanLib.merge3d(ScanLib.orient(r.views[0].pts, o), ScanLib.orient(r.views[1].pts, o), { mode: SC.opts.mode });
    r.merge = { common: m.common, used: m.used, align: m.align, rms: m.rms, scale: m.scale };
    lay = m.pts; keys = ['x', 'y', 'z'];
  }
  const ds = ScanLib.despike(lay, keys);  // a LED far away from both its neighbours is not on the string: do not write it to the garland
  r.spikes = ds.fixed;
  return (r.layout = ds.pts);
}

// Shows by eye that the garland really lights what the scan asks for (no camera needed).
async function lightTest() {
  const dev = document.getElementById('scan-dev').value;
  SC.running = true; SC.cancel = false; renderScan();
  const hold = async (ms) => { const end = Date.now() + ms; while (Date.now() < end) { if (SC.cancel) throw new Error('cancelled'); await sleep(100); } };
  try {
    scanStatus('Switching the garland to scan mode...', 0.02);
    const info = await send('api/scan/start', { device: dev }), every = Array.from({ length: info.leds }, (_, i) => i);
    scanStatus('Look at the garland: everything on (3 s)...', 0.1); await pat({ kind: 'all', level: 200 }); await hold(3000);
    for (let j = 0; j < 3; j++) {
      scanStatus(`Everything ${['red', 'green', 'blue'][j]} (2 s): the colour patterns of the scan use these three colours separately...`, 0.15 + 0.05 * j);
      await pat({ kind: 'rgb', channels: [0, 1, 2].map(c => c === j ? every : []), level: 200 }); await hold(2000);
    }
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

function drawCamera(cam, vw, snapData) {
  cam.width = 480; cam.height = Math.round(480 * vw.h / vw.w); const k = cam.width / vw.w, g = cam.getContext('2d');
  const img = g.createImageData(vw.w, vw.h), tmp = document.createElement('canvas'); tmp.width = vw.w; tmp.height = vw.h;
  let mx = 1; for (let i = 0; i < vw.w * vw.h; i++) mx = Math.max(mx, snapData[i]);
  for (let i = 0; i < vw.w * vw.h; i++) { const v = Math.min(255, snapData[i] * 255 / mx * 0.8); img.data[4 * i] = img.data[4 * i + 1] = img.data[4 * i + 2] = v; img.data[4 * i + 3] = 255; }
  tmp.getContext('2d').putImageData(img, 0, 0); g.drawImage(tmp, 0, 0, cam.width, cam.height);
  g.strokeStyle = 'rgba(255,255,255,.25)'; g.beginPath(); let pen = false;
  vw.pts.forEach(p => { if (!p) { pen = false; return; } pen ? g.lineTo(p.u * k, p.v * k) : g.moveTo(p.u * k, p.v * k); pen = true; }); g.stroke();
  vw.pts.forEach(p => { if (!p) return; g.fillStyle = SRC_COLOR[p.src]; g.beginPath(); g.arc(p.u * k, p.v * k, 2.2, 0, 6.2832); g.fill(); });
}

function drawResults() {
  const r = SC.result; if (!r) return;
  const lay = document.getElementById('scan-new'), old = document.getElementById('scan-old'), top = document.getElementById('scan-top');
  if (!lay) return;
  // camera views: snapshot with the detected string
  r.views.forEach((vw, k) => {
    const cam = document.getElementById('scan-cam' + k); if (!cam) return;
    drawCamera(cam, vw, vw.snap);
  });
  // layouts
  let nl;
  try { nl = buildLayout(r); } catch (e) { scanStatus('Cannot join the views: ' + e.message, undefined); return; }
  drawScatter(lay, nl.map(p => [p.x, p.y]), nl.map(p => SRC_COLOR[p.src]));
  if (top && r.is3d) drawScatter(top, nl.map(p => [p.x, p.z]), nl.map(p => SRC_COLOR[p.src]));
  if (SC.oldLayout) drawScatter(old, SC.oldLayout);
}

async function applyScan() {
  const r = SC.result; if (!r) return;
  const n = r.layout.length, est = r.layout.filter(p => p.src === 'interp').length, pct = Math.round(100 * est / n);
  const warn = pct >= 30 ? `

CAREFUL: ${est} of ${n} LEDs (${pct}%) were not seen by the camera and are only guessed along the string. A layout that is half guessed can look wrong on the garland. Check the picture first (the grey line should run smoothly).` : '';
  if (!confirm(`Write the scanned layout to ${SC.device}? The current layout is saved as a backup first and can be restored below.${warn}`)) return;
  try {
    const res = await send('api/scan/apply', { device: SC.device, scan_type: r.stats.mode, coordinates: r.layout.map(p => r.is3d ? { x: p.x, y: p.y, z: p.z } : { x: p.x, y: p.y }) });
    toast(`Layout written (${res.leds} LEDs). Backup: ${res.backup}`, false, 8000); scanLoadBackups();
    SC.oldLayout = await api(`api/devices/${encodeURIComponent(SC.device)}/layout`); drawResults(); loadGallery();
  } catch (e) { toast('Not applied: ' + e.message, true, 8000); }
}

// Saved layouts of the selected garland (every write saves the layout it replaces): restore one if a scan wrote something wrong.
async function scanLoadBackups() {
  const el = document.getElementById('scan-backups'), dev = SC.device; if (!el || !dev) return;
  let list = [];
  try { list = await api(`api/devices/${encodeURIComponent(dev)}/layout/backups`); } catch (e) { el.textContent = 'Could not read the backups: ' + e.message; return; }
  if (!list.length) { el.textContent = 'No saved layouts yet: the first write of a scan saves the layout that was on the garland.'; return; }
  const sel = h('select', { id: 'scan-backup-sel' }, list.map((b, i) => h('option', { value: b.name }, `${b.time} (${b.leds} LEDs)${i === list.length - 1 ? ' - the oldest: before your first scan' : ''}`)));
  el.replaceChildren(h('div', { class: 'row' }, sel, h('button', { onclick: async () => {
    const name = sel.value; if (!confirm(`Write the layout saved at ${name.split('backup-')[1]} back to ${dev}? The layout that is on the garland now is saved first.`)) return;
    try {
      const res = await send('api/scan/restore', { device: dev, backup: name });
      toast(`Layout restored (${res.leds} LEDs).`, false, 8000);
      SC.oldLayout = await api(`api/devices/${encodeURIComponent(dev)}/layout`); drawResults(); loadGallery(); scanLoadBackups();
    } catch (e) { toast('Not restored: ' + e.message, true, 8000); }
  } }, 'Restore this layout')));
}

// Photos of the last scans that were sent for analysis, as zip files to save (a normal browser saves them; the Home Assistant app may not).
async function scanLoadDumps() {
  const el = document.getElementById('scan-dumps'); if (!el) return;
  let list = [];
  try { list = await api('api/scan/dump'); } catch (e) { el.textContent = 'Could not read the list: ' + e.message; return; }
  if (!list.length) { el.textContent = 'No photos were sent yet: press "Send the photos of the last scan for analysis" after a scan.'; return; }
  el.replaceChildren(...list.map(d => h('div', {}, h('a', { href: `api/scan/dump/${d.id}.zip`, download: `${d.id}.zip`, target: '_blank' }, `${d.time} - ${d.id}.zip`), h('span', { class: 'muted' }, `  ${d.files.length} files, ${(d.bytes / 1e6).toFixed(1)} MB`))));
}

function renderScan() {
  const root = document.getElementById('view-scan'); root.replaceChildren();
  const devs = (S.status || []).map(d => d.name);
  if (devs.length && !SC.running && SC.device !== (S.previewDevice || devs[0])) scanLoadMode(S.previewDevice || devs[0]);
  const video = h('video', { playsinline: '', muted: '', autoplay: '', style: 'width:100%;max-width:480px;border-radius:8px;background:#000' }); video.muted = true;
  SC.video = video; if (SC.stream) { video.srcObject = SC.stream; video.play().catch(() => {}); }
  const st = SC.result && SC.result.stats, r = SC.result, canvasStyle = 'max-width:100%;background:#000;border-radius:6px';
  const STYLE_NAME = { hue: 'hue-coded patterns (LEDs always lit)', rgb: 'colour-bit patterns', mono: 'white patterns' };
  const how = st && st.styles.map(x => STYLE_NAME[x]).join(' + ') + (st.fellBack ? ' (the chosen style was not read)' : ''), unit = st && st.styles.includes('hue') ? ' px' : '';
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
        h('label', { title: 'How the garland codes the LEDs. Hue: every LED is lit in every photo, red = 0, blue = 1, read pixel by pixel (most robust, dense strings). Colour bits: red, green and blue switched on / off, three bits per photo (fewest photos). White: on / off, one bit per photo. If the chosen style is not read the scan repeats itself with white.' },
          'Patterns ', h('select', { id: 'scan-style', disabled: SC.running, onchange: e => { SC.style = e.target.value; scanSaveMode(); } },
            [['hue', 'Hue, LEDs always lit (robust)'], ['rgb', 'Colour bits (fewest photos)'], ['mono', 'White on / off']].map(([k, t]) => h('option', { value: k, selected: k === SC.style }, t)))),
        h('button', { disabled: SC.running, onclick: async () => { try { await scanOpenCamera(); toast('Camera ready.'); renderScan(); } catch (e) { toast(e.message, true, 9000); } } }, 'Open camera'),
        h('button', { class: 'primary', disabled: SC.running || !SC.stream, onclick: runScan }, 'Start scan'),
        SC.waiting ? h('button', { class: 'primary', onclick: () => SC.resume && SC.resume() }, 'Next view') : null,
        h('button', { disabled: SC.running || !SC.stream, title: 'Sets the camera exposure and checks that red and blue LEDs look different to it, without a scan. Do this first, in the dark, with the garland in view.', onclick: cameraCheck }, 'Camera check'),
        h('button', { disabled: SC.running, title: 'Lights the garland step by step so you can check it by eye. No camera needed.', onclick: lightTest }, 'Light test'),
        h('button', { disabled: !SC.running, onclick: () => { SC.cancel = true; if (SC.resume) SC.resume(); } }, 'Cancel')),
      h('div', { class: 'bar', id: 'scan-bar', style: 'margin-top:8px' }, h('div', { style: 'width:0%' })),
      h('div', { id: 'scan-status', class: 'muted' }, SC.status || 'Idle.'),
      SC.checkText ? h('div', { class: 'muted', style: 'margin-top:4px' }, 'Last camera check: ' + SC.checkText) : null),
    h('div', { class: 'card', style: 'margin-bottom:12px' }, h('h3', {}, 'Camera'), video,
      SC.dump && SC.dump.photos.length ? h('div', { class: 'row', style: 'margin-top:8px' }, h('button', { disabled: SC.running, onclick: scanSendPhotos, title: 'Uploads the photos of the last scan to the add-on, to find out why a scan went wrong' }, `Send the photos of the last scan for analysis (${SC.dump.photos.length})`),
        SC.dump.sent ? h('a', { href: `api/scan/dump/${SC.dump.id}.zip`, download: `${SC.dump.id}.zip`, style: 'align-self:center' }, 'Download the sent photos (.zip)') : null) : ''),
    r ? h('div', { class: 'card' },
      h('h2', {}, 'Result'),
      h('div', {}, `${st.n} LEDs: ${st.decoded} recognised by code, ${st.refined} found one by one, ${st.dropped} dropped as outliers, `, h('b', { class: st.hidden && !st.mode.startsWith('tree') ? 'warn' : 'ok' }, `${st.hidden} not visible (estimated from their neighbours${st.mode.startsWith('tree') ? ', as expected for the far side of a tree' : ''})`),
        h('span', { class: 'muted' }, `  ·  ${how}: ${st.styles.includes('hue') ? 'LEDs with pixels' : 'blobs'} ${st.blobs}, merged ${st.merged}, invalid ${st.invalid}${unit}, ambiguous ${st.conflicts}, doubtful ${st.uncertain}${unit}, corrected ${st.corrected}${unit}, rejected by the check ${st.rejected}${unit}, brightness ${st.level}`)),
      r.is3d && r.merge ? h('div', { class: r.merge.align === 'common' ? 'muted' : 'warn' },
        r.merge.align === 'common' ? `The two views were joined by ${r.merge.used} LEDs that both saw (of ${r.merge.common}), mean mismatch ${r.merge.rms} px.`
          : `Fewer than 6 LEDs were seen in both views (${r.merge.common}), so the views were joined by their outlines only: the result is less exact. Frame the whole tree the same way in both views.`) : null,
      st.sep !== null && st.sep !== undefined ? h('div', { class: st.sep < 0.3 ? 'warn' : 'muted' }, `Red against blue: distinctness ${st.sep} (1 = perfect, the decoder gives up below 0.22; the bright cores of the LEDs are clipped, ${st.clipped}% of the lit pixels, which does not matter: the colour is in the halo). ${SC.lockInfo && SC.lockInfo.exposure ? 'Camera set to ' + SC.lockInfo.exposure + '.' : ''}`) : null,
      r.spikes && r.spikes.length ? h('div', { class: 'warn' }, `${r.spikes.length} LED${r.spikes.length > 1 ? 's' : ''} (${r.spikes.slice(0, 8).join(', ')}${r.spikes.length > 8 ? ', ...' : ''}) stood far away from both neighbours on the string and were put between them: a stray detection, most likely.`) : null,
      SC.lockInfo ? h('div', { class: SC.lockInfo.missing.length ? 'warn' : 'muted' }, `Camera: ${SC.lockInfo.done.length ? 'locked ' + SC.lockInfo.done.join(', ') : 'nothing could be locked'}${SC.lockInfo.missing.length ? '; not lockable here: ' + SC.lockInfo.missing.join(', ') + ' (the phone may change them during the scan; Chrome on Android locks the most)' : ''}.`) : null,
      st.shift > 1.2 ? h('div', { class: st.shift > 6 ? 'warn' : 'muted' }, `The phone moved by up to ${st.shift} px during the scan; every photo was moved back into place, but a tripod is still more exact.`) : null,
      h('div', { class: 'muted' }, 'Green = recognised, blue = found separately, orange = estimated. The grey line is the string in LED order and should run smoothly.'),
      h('div', { class: 'row', style: 'margin:8px 0' },
        h('label', {}, 'Rotate ', h('select', { onchange: e => { SC.opts.rot = Number(e.target.value); drawResults(); } }, [0, 1, 2, 3].map(q => h('option', { value: q, selected: q === SC.opts.rot }, `${q * 90}°`)))),
        h('label', {}, h('input', { type: 'checkbox', checked: SC.opts.flip, onchange: e => { SC.opts.flip = e.target.checked; drawResults(); } }), 'Mirror'),
        h('label', {}, 'Scale ', h('select', { onchange: e => { SC.opts.mode = e.target.value; drawResults(); } }, [['fit', 'keep proportions'], ['stretch', 'fill the unit box']].map(([v, t]) => h('option', { value: v, selected: v === SC.opts.mode }, t))))),
      h('div', { class: 'row', style: 'align-items:flex-start' },
        ...r.views.map((_, k) => h('div', {}, h('div', { class: 'muted' }, r.is3d ? (k ? 'Camera view: back' : 'Camera view: front') : 'Camera view'), h('canvas', { id: 'scan-cam' + k, style: canvasStyle }))),
        h('div', {}, h('div', { class: 'muted' }, 'Scanned layout (x: -1..1, y: 0..1)'), h('canvas', { id: 'scan-new', width: 360, height: 300, style: 'max-width:100%;background:#0b0b0d;border-radius:6px' })),
        r.is3d ? h('div', {}, h('div', { class: 'muted' }, 'Seen from above (x, z)'), h('canvas', { id: 'scan-top', width: 300, height: 300, style: 'max-width:100%;background:#0b0b0d;border-radius:6px' })) : null,
        h('div', {}, h('div', { class: 'muted' }, 'Layout now on the device'), h('canvas', { id: 'scan-old', width: 360, height: 300, style: 'max-width:100%;background:#0b0b0d;border-radius:6px' }))),
      h('div', { class: 'row', style: 'margin-top:8px' }, h('button', { class: 'primary', onclick: applyScan }, 'Apply to the garland'))) : '');
  root.append(h('div', { class: 'card', style: 'margin-top:12px' }, h('h3', {}, 'Saved layouts (restore)'), h('div', { id: 'scan-backups', class: 'muted' }, 'Loading...')),
    h('div', { class: 'card', style: 'margin-top:12px' }, h('h3', {}, 'Photos of the last scans (download)'), h('div', { id: 'scan-dumps', class: 'muted' }, 'Loading...')));
  if (!SC.running) { const el = document.getElementById('scan-status'); if (el) el.textContent = SC.status || 'Idle.'; }
  drawResults(); scanLoadBackups(); scanLoadDumps();
}

window.addEventListener('beforeunload', () => { if (SC.running) navigator.sendBeacon('api/scan/stop'); });
