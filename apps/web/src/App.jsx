import { useCallback, useEffect, useRef, useState } from 'react'
import { useWebSocket } from './useWebSocket'
import { startAudioCapture, listAudioDevices } from './audioCapture'
import { useWebcam, CAPTURE_INTERVAL_MS } from './useWebcam'
import TensionVisualizer from './TensionVisualizer'
import RmsLevelMeter from './RmsLevelMeter'
import CoachingWhisperOverlay from './CoachingWhisperOverlay'
import { useCoachingOverlay } from './useCoachingOverlay'
import OnboardingModal, { getOnboardingSeen, setOnboardingSeen } from './OnboardingModal'
import './App.css'

const MAX_TRANSCRIPT_LEN = 2000

/** Render log entry text; if valid JSON, highlight keys/values per Stitch high-contrast theme */
function LogEntryText({ text }) {
  let parsed
  try {
    parsed = JSON.parse(text)
  } catch {
    return (
      <span className="log-text">
        <span className="log-text-plain">{text}</span>
      </span>
    )
  }
  const parts = []
  const obj = typeof parsed === 'object' && parsed !== null ? parsed : { value: parsed }
  Object.entries(obj).forEach(([k, v], i) => {
    parts.push(
      <span key={`k-${i}`} className="log-json-key">"{k}"</span>,
      <span key={`c-${i}`}>: </span>,
      <span key={`v-${i}`} className="log-json-value">
        {typeof v === 'string' ? `"${v}"` : JSON.stringify(v)}
      </span>
    )
    if (i < Object.keys(obj).length - 1) parts.push(<span key={`comma-${i}`}>, </span>)
  })
  return <span className="log-text">{parts}</span>
}

/**
 * Speak whisper text via Web Speech API. No-op if TTS is missing or fails; coaching text still shows.
 * Returns true if speak was attempted successfully, false if skipped or failed.
 */
function speakWhisper(text) {
  if (!text || typeof text !== 'string') return false
  if (!('speechSynthesis' in window)) return false
  try {
    window.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.rate = 0.85
    utterance.pitch = 0.9
    utterance.volume = 0.20
    const voices = window.speechSynthesis.getVoices()
    const preferred = voices.find(v =>
      v.name.includes('Samantha') || v.name.includes('Google UK English Female')
    )
    if (preferred) utterance.voice = preferred
    window.speechSynthesis.speak(utterance)
    return true
  } catch (err) {
    if (typeof console !== 'undefined' && console.debug) {
      console.debug('TTS unavailable or failed; whisper text still shown:', err?.message || err)
    }
    return false
  }
}

let currentWhisperAudioCtx = null
let lastWhisperPlayedAt = 0

function playWhisperAudio(base64Pcm) {
  try {
    const raw = atob(base64Pcm)
    const buf = new ArrayBuffer(raw.length)
    const view = new Uint8Array(buf)
    for (let i = 0; i < raw.length; i += 1) view[i] = raw.charCodeAt(i)

    // Guard against odd-length buffers (must be divisible by 2 for Int16)
    if (buf.byteLength % 2 !== 0) return false

    const AudioCtx = window.AudioContext || window.webkitAudioContext
    if (!AudioCtx) return false
    // Stop any previous whisper audio before starting a new one
    if (currentWhisperAudioCtx) {
      try {
        currentWhisperAudioCtx.close()
      } catch {
        // ignore
      }
      currentWhisperAudioCtx = null
    }
    const ctx = new AudioCtx({ sampleRate: 24000 })
    currentWhisperAudioCtx = ctx

    const int16 = new Int16Array(buf)
    const float32 = new Float32Array(int16.length)
    for (let i = 0; i < int16.length; i += 1) {
      float32[i] = int16[i] / 32768
    }

    const audioBuffer = ctx.createBuffer(1, float32.length, 24000)
    audioBuffer.getChannelData(0).set(float32)

    const source = ctx.createBufferSource()
    const gain = ctx.createGain()
    gain.gain.value = 0.6
    source.buffer = audioBuffer
    source.connect(gain).connect(ctx.destination)
    source.onended = () => {
      ctx.close()
    }
    source.start()
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn('Live audio playback failed, falling back to Web Speech', err)
    return false
  }
  return true
}

let currentBackchannelCtx = null

function playBackchannelAudio(base64Pcm) {
  try {
    // Suppress if a coaching whisper played in the last 5 seconds
    if (Date.now() - lastWhisperPlayedAt < 5000) return true // swallow silently

    const raw = atob(base64Pcm)
    const buf = new ArrayBuffer(raw.length)
    const view = new Uint8Array(buf)
    for (let i = 0; i < raw.length; i += 1) view[i] = raw.charCodeAt(i)

    if (buf.byteLength % 2 !== 0) return false

    const AudioCtx = window.AudioContext || window.webkitAudioContext
    if (!AudioCtx) return false

    // Stop previous backchannel if still playing
    if (currentBackchannelCtx) {
      try {
        currentBackchannelCtx.close()
      } catch {
        /* ignore */
      }
      currentBackchannelCtx = null
    }

    const ctx = new AudioCtx({ sampleRate: 24000 })
    currentBackchannelCtx = ctx

    const int16 = new Int16Array(buf)
    const float32 = new Float32Array(int16.length)
    for (let i = 0; i < int16.length; i += 1) {
      float32[i] = int16[i] / 32768
    }

    const audioBuffer = ctx.createBuffer(1, float32.length, 24000)
    audioBuffer.getChannelData(0).set(float32)

    const source = ctx.createBufferSource()
    const gain = ctx.createGain()
    gain.gain.value = 0.08 // Barely audible — background acknowledgment, not foreground
    source.buffer = audioBuffer
    source.connect(gain).connect(ctx.destination)
    source.onended = () => {
      ctx.close()
      if (currentBackchannelCtx === ctx) currentBackchannelCtx = null
    }
    source.start()
  } catch (err) {
    // eslint-disable-next-line no-console
    console.debug('Backchannel audio playback failed (non-critical)', err)
    return false
  }
  return true
}

/** True when URL has ?debug=1 (show Advanced + Event log). */
function isDebugUrl() {
  if (typeof window === 'undefined') return false
  return new URLSearchParams(window.location.search).get('debug') === '1'
}

export default function App() {
  const isDebugMode = isDebugUrl()
  const [onboardingDismissed, setOnboardingDismissed] = useState(() => getOnboardingSeen())
  const [sessionActive, setSessionActive] = useState(false)
  const [tension, setTension] = useState(0)
  const [whisper, setWhisper] = useState(null)
  const [logs, setLogs] = useState([])
  const [showLogs, setShowLogs] = useState(false)
  const [liveRms, setLiveRms] = useState(0)
  const [transcript, setTranscript] = useState('')
  const [useVision, setUseVision] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [rmsHistory, setRmsHistory] = useState([])
  const [overlayExiting, setOverlayExiting] = useState(false)
  const [audioDevices, setAudioDevices] = useState([])
  const [selectedDeviceId, setSelectedDeviceId] = useState('')
  const { showOverlay: showCoachingOverlay } = useCoachingOverlay(tension)
  const captureRef = useRef(null)
  const webcam = useWebcam()
  const frameIntervalRef = useRef(null)
  const liveRmsRef = useRef(0)
  liveRmsRef.current = liveRms

  const addLog = useCallback((direction, msg) => {
    const entry = {
      id: Date.now() + Math.random(),
      ts: new Date().toISOString().slice(11, 23),
      direction,
      text: typeof msg === 'string' ? msg : JSON.stringify(msg),
    }
    setLogs((prev) => [entry, ...prev].slice(0, 100))
  }, [])

  const onMessage = useCallback((msg) => {
    if (msg.type === 'ready') {
      setSessionActive(true)
      addLog('in', { type: 'ready' })
    } else if (msg.type === 'tension') {
      setTension(msg.score ?? 0)
      addLog('in', { type: 'tension', score: msg.score })
    } else if (msg.type === 'whisper') {
      setWhisper({ text: msg.text, move: msg.move })
      lastWhisperPlayedAt = Date.now()
      // Prefer Gemini Live audio; fall back to Web Speech API
      if (msg.audio_base64) {
        const ok = playWhisperAudio(msg.audio_base64)
        if (!ok) speakWhisper(msg.text)
      } else {
        speakWhisper(msg.text)
      }
      addLog('in', { type: 'whisper', text: msg.text, move: msg.move })
    } else if (msg.type === 'stopped') {
      setSessionActive(false)
      setWhisper(null)
      setTranscript('')
      addLog('in', { type: 'stopped' })
    } else if (msg.type === 'transcript') {
      if (typeof msg.full === 'string' && msg.full.length > 0) {
        setTranscript(msg.full.slice(-MAX_TRANSCRIPT_LEN))
      } else if (msg.delta != null) {
        setTranscript((prev) => (prev + msg.delta).slice(-MAX_TRANSCRIPT_LEN))
      }
    } else if (msg.type === 'backchannel_audio') {
      if (msg.audio_base64) playBackchannelAudio(msg.audio_base64)
    } else if (msg.type === 'event') {
      addLog('in', { type: 'event', name: msg.name })
    } else if (msg.type === 'error') {
      addLog('in', { type: 'error', message: msg.message })
    }
  }, [addLog])

  const onOutbound = useCallback((msg) => {
    addLog('out', msg)
  }, [addLog])

  const { connected, lastError, connect, disconnect, send, useMock, backendSource } = useWebSocket({
    onMessage,
    onOutbound,
    useMock: import.meta.env.VITE_USE_MOCK_WS === 'true',
  })

  // Enumerate audio devices on mount (need a temp getUserMedia to get labels)
  useEffect(() => {
    navigator.mediaDevices.getUserMedia({ audio: true })
      .then((s) => {
        s.getTracks().forEach((t) => t.stop())
        return listAudioDevices()
      })
      .then(setAudioDevices)
      .catch(() => {})
  }, [])

  // Sample RMS for sparkline (every 200ms when session active)
  useEffect(() => {
    if (!sessionActive) {
      setRmsHistory([])
      return
    }
    const id = setInterval(() => {
      const r = liveRmsRef.current
      setRmsHistory((prev) => [...prev.slice(-23), r].filter((v) => v != null))
    }, 200)
    return () => clearInterval(id)
  }, [sessionActive])

  // Coaching overlay: start exit animation when overlay should hide
  useEffect(() => {
    if (!showCoachingOverlay) setOverlayExiting(true)
    else setOverlayExiting(false)
  }, [showCoachingOverlay])
  useEffect(() => {
    if (!overlayExiting) return
    const id = setTimeout(() => setOverlayExiting(false), 320)
    return () => clearTimeout(id)
  }, [overlayExiting])

  // Auto-dismiss whisper after 8 seconds
  useEffect(() => {
    if (!whisper) return
    const timer = setTimeout(() => setWhisper(null), 8000)
    return () => clearTimeout(timer)
  }, [whisper])

  // When session is ready and not mock: start mic capture and stream audio chunks over WS
  useEffect(() => {
    if (!sessionActive || useMock) return
    let cancelled = false
    let chunkCount = 0
    startAudioCapture({
      deviceId: selectedDeviceId || undefined,
      onChunk: ({ pcmBase64, rms, bytesLength }) => {
        if (cancelled) return
        setLiveRms((prev) => (rms > 0 ? rms : prev * 0.95))
        send({
          type: 'audio',
          base64: pcmBase64,
          telemetry: { rms },
        })
        chunkCount += 1
        if (chunkCount === 1 || chunkCount % 25 === 0) {
          addLog('out', { audio_chunk_sent: true, rms, bytesLength })
        }
      },
    })
      .then((capture) => {
        if (cancelled) {
          capture.stop()
          return
        }
        captureRef.current = capture
      })
      .catch((err) => {
        if (!cancelled) addLog('in', { type: 'error', message: 'Mic: ' + (err?.message || String(err)) })
      })
    return () => {
      cancelled = true
      if (captureRef.current) {
        captureRef.current.stop()
        captureRef.current = null
      }
      setLiveRms(0)
    }
  }, [sessionActive, useMock, send, addLog])

  // When session is active and vision enabled: send webcam frame periodically for vision-aware coaching
  useEffect(() => {
    if (!sessionActive || useMock || !useVision || !webcam.active) return
    const id = setInterval(() => {
      const frame = webcam.captureFrame()
      if (frame) send({ type: 'frame', base64: frame })
    }, CAPTURE_INTERVAL_MS)
    frameIntervalRef.current = id
    return () => {
      clearInterval(id)
      frameIntervalRef.current = null
    }
  }, [sessionActive, useMock, useVision, webcam.active, webcam.captureFrame, send])

  const handleStart = async () => {
    if (useVision) {
      const ok = await webcam.start()
      if (!ok) {
        addLog('in', { type: 'error', message: 'Webcam: ' + (webcam.error || 'denied') })
        return
      }
      // Let first frame be ready
      await new Promise((r) => setTimeout(r, 600))
      const frame = webcam.captureFrame()
      if (frame) {
        connect({ image: frame })
      } else {
        connect()
      }
    } else {
      connect()
    }
  }

  const handleStop = () => {
    window.speechSynthesis?.cancel()
    if (currentBackchannelCtx) {
      try {
        currentBackchannelCtx.close()
      } catch {
        /* ignore */
      }
      currentBackchannelCtx = null
    }
    if (frameIntervalRef.current) {
      clearInterval(frameIntervalRef.current)
      frameIntervalRef.current = null
    }
    if (useVision && webcam.active) webcam.stop()
    if (captureRef.current) {
      captureRef.current.stop()
      captureRef.current = null
    }
    setLiveRms(0)
    setTranscript('')
    addLog('out', { type: 'stop' })
    send({ type: 'stop' })
    disconnect()
    setSessionActive(false)
    setWhisper(null)
  }

  const handleOnboardingDismiss = useCallback(() => {
    setOnboardingSeen()
    setOnboardingDismissed(true)
  }, [])

  return (
    <div className="app">
      {!onboardingDismissed && (
        <OnboardingModal onDismiss={handleOnboardingDismiss} />
      )}
      {(showCoachingOverlay || overlayExiting) && (
        <CoachingWhisperOverlay
          visible={showCoachingOverlay}
          exiting={overlayExiting && !showCoachingOverlay}
        />
      )}
      {/* Header */}
      <header className="header">
        <h1>Empathic Co-Pilot</h1>
        <p className="subtitle">Real-time conversation coaching, whispered when it matters</p>
        {!useMock && (
          <p
            className={`backend-indicator ${sessionActive ? 'pill-active' : ''}`}
            aria-label="Backend source"
          >
            {backendSource === 'cloudrun' ? 'Cloud Run' : 'Local'}
          </p>
        )}
      </header>

      {/* Webcam: hidden until session active, then shown as preview */}
      {useVision && (
        <div className={sessionActive ? 'webcam-preview' : 'webcam-preview webcam-preview--hidden'}>
          <video
            ref={webcam.videoRef}
            muted
            playsInline
            autoPlay
            className="webcam-preview__video"
            aria-label="Webcam preview for vision-aware coaching"
          />
          {sessionActive && <span className="webcam-preview__label">Webcam (vision)</span>}
        </div>
      )}

      {/* Start card: unified CTA + Tension Meter */}
      <section className="start-card" aria-label="Session control">
        <TensionVisualizer score={tension} />
        <div className="controls-row">
          {!sessionActive ? (
            <>
              {!useMock && audioDevices.length > 1 && (
                <label className="vision-toggle">
                  <span>Mic: </span>
                  <select
                    value={selectedDeviceId}
                    onChange={(e) => setSelectedDeviceId(e.target.value)}
                    aria-label="Select microphone"
                    style={{ maxWidth: 200, fontSize: '0.85rem' }}
                  >
                    <option value="">Default</option>
                    {audioDevices.map((d) => (
                      <option key={d.deviceId} value={d.deviceId}>
                        {d.label}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {!useMock && (
                <label className="vision-toggle">
                  <input
                    type="checkbox"
                    checked={useVision}
                    onChange={(e) => setUseVision(e.target.checked)}
                    aria-label="Include webcam for vision-aware coaching"
                  />
                  <span>Include webcam (vision)</span>
                </label>
              )}
              <button
                className="btn btn-start"
                onClick={handleStart}
                disabled={connected && sessionActive}
              >
                Start session
              </button>
              <p className="onboarding-text">
                Start a session, then have your conversation. The co-pilot listens and whispers
                coaching when tension rises. Speak clearly near the mic for consistent tension and transcription.
              </p>
            </>
          ) : (
            <>
              <button className="btn btn-stop" onClick={handleStop}>
                Stop session
              </button>
              <div className="listening-indicator">
                <span className="listening-dot" aria-hidden />
                <span>Listening...</span>
              </div>
            </>
          )}
          {lastError && <span className="error">{lastError}</span>}
        </div>
      </section>

      {/* Status cards: transcript, whisper (tension is in start card via TensionVisualizer) */}
      <div className="status-cards">
        {!useMock && (
          <section className="transcript-section" aria-label="Live transcript" aria-live="polite">
            <h2 className="transcript-heading">Live Transcript</h2>
            <div className="transcript-text" title={transcript || 'Speak to see live transcription.'} aria-live="polite">
              {transcript || (sessionActive ? 'Listening…' : '')}
            </div>
            {sessionActive && (
              <p className="transcript-hint">Transcription may appear in chunks or after short pauses.</p>
            )}
          </section>
        )}

        {whisper && (
          <section className="whisper-box" key={whisper.text} aria-live="polite">
            <div className="whisper-move">{whisper.move}</div>
            <div className="whisper-text">"{whisper.text}"</div>
          </section>
        )}
      </div>

      {/* Advanced: RMS meter (collapsible) — only when ?debug=1 */}
      {isDebugMode && (
        <section className="advanced">
          <button
            type="button"
            className="advanced-toggle"
            onClick={() => setShowAdvanced((a) => !a)}
            aria-expanded={showAdvanced}
            aria-controls="advanced-content"
          >
            <span>Advanced</span>
            <span aria-hidden>{showAdvanced ? '−' : '+'}</span>
          </button>
          {showAdvanced && (
            <div id="advanced-content" className="advanced-content">
              <RmsLevelMeter rms={liveRms} sparklineData={rmsHistory} />
              <p className="advanced-tip">
                Tension and mic level depend on volume and distance. Speak clearly near the mic for consistent scores and transcription.
              </p>
            </div>
          )}
        </section>
      )}

      {/* Event log — only when ?debug=1 */}
      {isDebugMode && (
        <div className="logs-section">
          <button
            type="button"
            className="logs-toggle"
            onClick={() => setShowLogs((s) => !s)}
            aria-expanded={showLogs}
          >
            {showLogs ? 'Hide' : 'Show'} event log ({logs.length})
          </button>
          {showLogs && (
            <div className="logs-list" role="log" aria-label="Event log">
              {logs.length === 0 && <div className="logs-empty">No events yet.</div>}
              {logs.map((entry) => (
                <div key={entry.id} className={`log-entry log-${entry.direction}`}>
                  <span className="log-ts">{entry.ts}</span>
                  <span className="log-dir">{entry.direction === 'in' ? '←' : '→'}</span>
                  <LogEntryText text={entry.text} />
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
