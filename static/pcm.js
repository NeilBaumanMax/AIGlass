class Utterance extends AudioWorkletProcessor {
  constructor() { super(); this.buffer = []; this.silent = 0; this.active = false; }
  process(inputs) {
    const samples = inputs[0]?.[0]; if (!samples) return true;
    let energy = 0; for (const value of samples) energy += value * value;
    const loud = energy / samples.length > 0.00008;
    this.active ||= loud;
    this.silent = loud ? 0 : this.silent + samples.length;
    this.buffer.push(samples.slice());
    if (!this.active && this.buffer.length > 24) this.buffer.shift();
    if (this.active && (this.silent > sampleRate * 0.55 || this.buffer.length * samples.length > sampleRate * 12)) {
      const data = new Int16Array(this.buffer.reduce((n, frame) => n + frame.length, 0));
      let i = 0; for (const frame of this.buffer) for (const x of frame) data[i++] = Math.max(-1, Math.min(1, x)) * 32767;
      this.port.postMessage(data.buffer, [data.buffer]); this.buffer = []; this.active = false; this.silent = 0;
    }
    return true;
  }
}
registerProcessor('utterance', Utterance);
