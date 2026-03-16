export const pcmAudioWorkletCode = `
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    // 2048 frames at 16kHz is ~128ms of audio
    this.bufferSize = 2048;
    this.buffer = new Int16Array(this.bufferSize);
    this.bufferIndex = 0;
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (input && input.length > 0) {
      const channel = input[0];
      for (let i = 0; i < channel.length; i++) {
        // Clamp and convert Float32 to Int16
        let s = Math.max(-1, Math.min(1, channel[i]));
        this.buffer[this.bufferIndex++] = s < 0 ? s * 0x8000 : s * 0x7FFF;

        if (this.bufferIndex >= this.bufferSize) {
          // Send a copy of the buffer to the main thread
          const out = new Int16Array(this.buffer);
          this.port.postMessage(out.buffer, [out.buffer]);
          this.bufferIndex = 0;
        }
      }
    }
    // Keep processor alive
    return true;
  }
}

registerProcessor("pcm-processor", PCMProcessor);
`;

export function arrayBufferToBase64(buffer: ArrayBuffer): string {
  let binary = "";
  const bytes = new Uint8Array(buffer);
  const len = bytes.byteLength;
  for (let i = 0; i < len; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  if (typeof window !== "undefined") {
    return window.btoa(binary);
  }
  return Buffer.from(buffer).toString("base64");
}
