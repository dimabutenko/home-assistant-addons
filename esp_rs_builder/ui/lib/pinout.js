// Board pinout as an SVG string, drawn only from the board schema (`pins[].ui`, `caps`, `flags`).

const W = 260;
const BODY_X = 70;
const BODY_W = 120;

/** CSS classes of one pin: flags, usage and (when a pin field is active) capability match. */
export function pinClasses(pin, { used, need }) {
  const cls = ['pin'];
  for (const f of pin.flags || []) cls.push(`flag-${f}`);
  if (used) cls.push('used');
  if (need && need.length) {
    cls.push(need.every((c) => (pin.caps || []).includes(c)) ? 'fits' : 'nofit');
  }
  return cls.join(' ');
}

/**
 * @param board raw board schema
 * @param used Map gpio -> field path
 * @param need capabilities required by the focused pin field (or [])
 */
export function pinoutSvg(board, used, need = []) {
  const pins = (board.pins || []).filter((p) => p.ui);
  const maxY = pins.reduce((m, p) => Math.max(m, p.ui.y), 0);
  const H = maxY + 40;
  const parts = [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(board.chip)} pinout">`,
    `<rect class="body" x="${BODY_X}" y="4" width="${BODY_W}" height="${H - 8}" rx="8"/>`,
    `<text class="chip" x="${W / 2}" y="${H / 2}" text-anchor="middle">${esc(board.chip)}</text>`,
  ];
  for (const p of pins) {
    const left = p.ui.side === 'left';
    const cx = left ? BODY_X - 14 : BODY_X + BODY_W + 14;
    const cy = p.ui.y + 20;
    const tx = left ? cx - 10 : cx + 10;
    const cls = pinClasses(p, { used: used.has(p.gpio), need });
    const title = `GPIO${p.gpio}: ${(p.caps || []).join(', ')}${p.flags?.length ? ` [${p.flags.join(', ')}]` : ''}${used.has(p.gpio) ? ` (used by ${used.get(p.gpio)})` : ''}`;
    parts.push(
      `<g class="${cls}" data-gpio="${p.gpio}"><title>${esc(title)}</title>`,
      `<circle cx="${cx}" cy="${cy}" r="6"/>`,
      `<text x="${tx}" y="${cy + 4}" text-anchor="${left ? 'end' : 'start'}">${p.gpio}</text></g>`,
    );
  }
  parts.push('</svg>');
  return parts.join('');
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
}
