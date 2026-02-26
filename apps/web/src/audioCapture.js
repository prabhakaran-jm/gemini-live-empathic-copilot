/**
 * Microphone capture: PCM16 mono 16 kHz, with RMS per chunk.
 * Uses ScriptProcessor (fallback); AudioWorklet can be added for production.
 * Chunks are 20–100 ms (configurable); backend expects base64 PCM + optional telemetry.rms.
 */

const TARGET_SAMPLE_RATE = 16000
const CHUNK_MS = 40
const CHUNK_SAMPLES_16K = Math.round((TARGET_SAMPLE_RATE * CHUNK_MS) / 1000)

/**
 * Resample Float32 mono to 16 kHz and convert to Int16.
 * inRate is the AudioContext sample rate (e.g. 48000).
 */
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

/**
 * Compute RMS of Float32 buffer (0..1 normalized).
 */
function computeRms(float32) {
  let sum = 0
  for (let i = 0; i < float32.length; i++) {
    sum += float32[i] * float32[i]
  }
  const rms = Math.sqrt(sum / float32.length)
  return Math.min(1, rms)
}

/**
 * Start microphone capture. Returns { stop, stream }.
 * onChunk({ pcmBase64, rms }) is called for each chunk (PCM16 mono 16 kHz).
 * Uses ScriptProcessor; use AudioWorklet when available for production.
 */
export async function startAudioCapture({ onChunk }) {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  const audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 48000 })
  const source = audioContext.createMediaStreamSource(stream)
  const inRate = audioContext.sampleRate

  // Buffer to accumulate input until we have enough for one 16 kHz chunk
  const inputSamplesPerChunk = Math.ceil((CHUNK_SAMPLES_16K * inRate) / TARGET_SAMPLE_RATE)
  let buffer = new Float32Array(0)
  let bufferOffset = 0

  const bufferSize = 2048
  const scriptNode = audioContext.createScriptProcessor(bufferSize, 1, 1)
  scriptNode.onaudioprocess = (e) => {
    const input = e.inputBuffer.getChannelData(0)
    const newLen = bufferOffset + input.length
    if (buffer.length < newLen) {
      const next = new Float32Array(newLen)
      next.set(buffer.subarray(0, bufferOffset))
      buffer = next
    }
    buffer.set(input, bufferOffset)
    bufferOffset += input.length

    while (bufferOffset >= inputSamplesPerChunk) {
      const slice = buffer.subarray(0, inputSamplesPerChunk)
      const int16 = resampleTo16kMono(slice, inRate)
      const rms = computeRms(slice)
      const bytes = new Uint8Array(int16.buffer)
      let binary = ''
      for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
      const pcmBase64 = btoa(binary)
      onChunk({ pcmBase64, rms, bytesLength: bytes.length })

      const remain = bufferOffset - inputSamplesPerChunk
      buffer.copyWithin(0, inputSamplesPerChunk, bufferOffset)
      bufferOffset = remain
    }
  }

  source.connect(scriptNode)
  scriptNode.connect(audioContext.destination)

  return {
    stop() {
      scriptNode.disconnect()
      source.disconnect()
      stream.getTracks().forEach((t) => t.stop())
      try {
        audioContext.close()
      } catch (_) {}
    },
    stream,
  }
}
