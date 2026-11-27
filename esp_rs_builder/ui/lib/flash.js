// Web Serial flasher (Chromium only) on top of the vendored esptool-js 0.7.1.
// The firmware is a merged flash image (bootloader + partition table + app), written at offset 0x0.

export function serialSupported() {
  return typeof navigator !== 'undefined' && 'serial' in navigator;
}

/**
 * @param bytes Uint8Array merged image
 * @param log(line) text output; progress(percent) 0..100
 */
export async function flashImage(bytes, { log, progress }) {
  if (!serialSupported()) throw new Error('Web Serial is not available in this browser (use Chrome or Edge over HTTPS or localhost).');
  const { ESPLoader, Transport } = await import('../vendor/esptool-js.js');
  const port = await navigator.serial.requestPort();
  const transport = new Transport(port, false);
  const terminal = {
    clean() {},
    writeLine: (s) => log(s),
    write: (s) => log(s),
  };
  const loader = new ESPLoader({ transport, baudrate: 460800, terminal });
  try {
    const chip = await loader.main();
    log(`Connected: ${chip}`);
    await loader.writeFlash({
      fileArray: [{ data: bytes, address: 0x0 }],
      // keep the header of the merged image as built (mode / frequency / size)
      flashMode: 'keep',
      flashFreq: 'keep',
      flashSize: 'keep',
      eraseAll: false,
      compress: true,
      reportProgress: (_i, written, total) => progress(Math.round((written / total) * 100)),
    });
    await loader.after('hard_reset');
    log('Flashing finished; the device was reset.');
  } finally {
    try {
      await transport.disconnect();
    } catch {
      // the port may already be gone
    }
  }
}
