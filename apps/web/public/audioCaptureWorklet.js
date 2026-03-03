/**
 * AudioWorklet processor: capture mic input, resample to 16 kHz mono, compute RMS.
 * Runs on the audio thread. Posts { pcm: ArrayBuffer, rms: number } to main thread.
 * Main thread converts PCM to base64 and calls onChunk.
 */
const TARGET_SAMPLE_RATE = 16000
const CHUNK_MS = 40
const CHUNK_SAMPLES_16K = Math.round((TARGET_SAMPLE_RATE * CHUNK_MS) / 1000)

function resampleTo16kMono(float32, inRate) {
  const ratio = inRate / TARGET_SAMPLE_RATE
  const outLength = Math.floor(float32.length / ratio)
  const int16 = new Int16Array(outLength)
  for (let i = 0; i < outLength; i++) {
    const srcIdx = i * ratio
    const idx0 = Math.floor(srcIdx)
    const idx1 = Math.min(idx0 + 1, float32.length - 1)
    const t = srcIdx - idx0
    const sample = float32[idx0] * (1 - t) + float32[idx1] * t
    const s16 = Math.max(-32768, Math.min(32767, Math.round(sample * 32767)))
    int16[i] = s16
  }
  return int16
}

function computeRms(float32) {
  let sum = 0
  for (let i = 0; i < float32.length; i++) {
    sum += float32[i] * float32[i]
  }
  const rms = Math.sqrt(sum / float32.length)
  return Math.min(1, rms)
}

class CaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super()
    const inRate = (options.processorOptions && options.processorOptions.sampleRate) || sampleRate
    this.inRate = inRate
    this.inputSamplesPerChunk = Math.ceil((CHUNK_SAMPLES_16K * inRate) / TARGET_SAMPLE_RATE)
    this.buffer = new Float32Array(this.inputSamplesPerChunk * 2)
    this.bufferOffset = 0
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0] && inputs[0][0]
    if (!input || input.length === 0) return true

    const need = this.inputSamplesPerChunk - this.bufferOffset
    const toCopy = Math.min(input.length, need)
    this.buffer.set(input.subarray(0, toCopy), this.bufferOffset)
    this.bufferOffset += toCopy

    if (this.bufferOffset >= this.inputSamplesPerChunk) {
      const slice = this.buffer.subarray(0, this.inputSamplesPerChunk)
      const int16 = resampleTo16kMono(slice, this.inRate)
      const rms = computeRms(slice)
      this.port.postMessage({ pcm: int16.buffer, rms }, [int16.buffer])
      const remainInInput = input.length - toCopy
      if (remainInInput > 0) {
        this.buffer.set(input.subarray(toCopy))
        this.bufferOffset = remainInInput
      } else {
        this.bufferOffset = 0
      }
    }
    return true
  }
}

registerProcessor('capture-processor', CaptureProcessor)
