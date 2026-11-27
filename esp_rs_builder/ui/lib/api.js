// Server API client. All URLs are relative (no leading slash) so the UI works behind the HA ingress path.

async function json(res) {
  const body = await res.json().catch(() => null);
  return { status: res.status, body };
}

export async function loadSchemas() {
  const [b, c] = await Promise.all([fetch('api/boards'), fetch('api/components')]);
  if (!b.ok || !c.ok) throw new Error(`cannot load schemas (HTTP ${b.status}/${c.status})`);
  return { boards: await b.json(), components: await c.json() };
}

/** Always 200 with an array of diagnostics. */
export async function validate(yaml, signal) {
  const res = await fetch('api/validate', { method: 'POST', body: yaml, headers: { 'Content-Type': 'text/plain' }, signal });
  if (!res.ok) throw new Error(`validate failed (HTTP ${res.status})`);
  return res.json();
}

/** -> {status: 202, body:{id}} | {status: 409|422|413, body} */
export async function startBuild(yaml) {
  const res = await fetch('api/build', { method: 'POST', body: yaml, headers: { 'Content-Type': 'text/plain' } });
  return json(res);
}

export async function jobInfo(id) {
  const res = await fetch(`api/jobs/${encodeURIComponent(id)}`);
  return res.ok ? res.json() : null;
}

export function firmwareUrl(id) {
  return `api/jobs/${encodeURIComponent(id)}/firmware.bin`;
}

/** WebSocket URL derived from the page location (ws:/wss:), relative to the ingress path. */
export function wsUrl(id, loc = location) {
  const u = new URL(`ws?job=${encodeURIComponent(id)}`, loc.href);
  u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:';
  return u.toString();
}

/**
 * Follow a build. Calls onLine(text) / onStatus(status); resolves with the final status
 * ('succeeded' | 'failed'). Falls back to polling when the socket cannot be used.
 */
export function followJob(id, { onLine, onStatus }) {
  return new Promise((resolve) => {
    let finished = false;
    const done = (s) => {
      if (!finished) {
        finished = true;
        resolve(s);
      }
    };
    const poll = async () => {
      for (let i = 0; i < 3600 && !finished; i++) {
        const info = await jobInfo(id).catch(() => null);
        if (info) {
          onStatus(info.status);
          if (info.status === 'succeeded' || info.status === 'failed') return done(info.status);
        }
        await new Promise((r) => setTimeout(r, 2000));
      }
    };
    let ws;
    try {
      ws = new WebSocket(wsUrl(id));
    } catch {
      poll();
      return;
    }
    ws.onmessage = (ev) => {
      let m;
      try {
        m = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (m.type === 'log') onLine(m.line);
      else if (m.type === 'status') {
        onStatus(m.status);
        if (m.status === 'succeeded' || m.status === 'failed') done(m.status);
      }
    };
    ws.onclose = () => {
      if (!finished) poll(); // closed without a final status: ask the job directly
    };
    ws.onerror = () => {};
  });
}
