import { useCallback, useEffect, useRef, useState } from 'react'
import { useWebSocket } from './useWebSocket'
import { startAudioCapture } from './audioCapture'
import './App.css'

const MAX_TRANSCRIPT_LEN = 2000

// AudioContext for playing raw PCM backchannel audio from Gemini Live
let _audioCtx = null
function getAudioCtx() {
  if (!_audioCtx) _audioCtx = new AudioContext({ sampleRate: 24000 })
  return _audioCtx
}

function playBackchannelAudio(base64Audio, mime) {
  try {
    const ctx = getAudioCtx()
    const raw = atob(base64Audio)
    const bytes = new Uint8Array(raw.length)
    for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i)

    // Gemini Live native audio outputs PCM16 at 24kHz mono
    const int16 = new Int16Array(bytes.buffer)
    const float32 = new Float32Array(int16.length)
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768.0

    const buffer = ctx.createBuffer(1, float32.length, 24000)
    buffer.getChannelData(0).set(float32)
    const source = ctx.createBufferSource()
    source.buffer = buffer
    // Play at lower volume so it doesn't overpower the conversation
    const gain = ctx.createGain()
    gain.gain.value = 0.3
    source.connect(gain)
    gain.connect(ctx.destination)
    source.start()
  } catch (e) {
    console.warn('Backchannel audio playback failed:', e)
  }
}

function speakWhisper(text) {
  if (!('speechSynthesis' in window)) return
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.rate = 0.85
  utterance.pitch = 0.9
  utterance.volume = 0.35
  const voices = window.speechSynthesis.getVoices()
  const preferred = voices.find(v =>
    v.name.includes('Samantha') || v.name.includes('Google UK English Female')
  )
  if (preferred) utterance.voice = preferred
  window.speechSynthesis.speak(utterance)
}

export default function App() {
  const [sessionActive, setSessionActive] = useState(false)
  const [tension, setTension] = useState(0)
  const [whisper, setWhisper] = useState(null)
  const [logs, setLogs] = useState([])
  const [showLogs, setShowLogs] = useState(false)
  const [liveRms, setLiveRms] = useState(0)
  const [transcript, setTranscript] = useState('')
  const captureRef = useRef(null)

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
      speakWhisper(msg.text)
      addLog('in', { type: 'whisper', text: msg.text, move: msg.move })
    } else if (msg.type === 'stopped') {
      setSessionActive(false)
      setWhisper(null)
      setTranscript('')
      addLog('in', { type: 'stopped' })
    } else if (msg.type === 'transcript' && msg.delta != null) {
      setTranscript((prev) => (prev + msg.delta).slice(-MAX_TRANSCRIPT_LEN))
    } else if (msg.type === 'backchannel_audio' && msg.base64) {
      playBackchannelAudio(msg.base64, msg.mime)
    } else if (msg.type === 'event') {
      addLog('in', { type: 'event', name: msg.name })
    } else if (msg.type === 'error') {
      addLog('in', { type: 'error', message: msg.message })
    }
  }, [addLog])

  const { connected, lastError, connect, disconnect, send, useMock, backendSource } = useWebSocket({
    onMessage,
    onOutbound,
    useMock: import.meta.env.VITE_USE_MOCK_WS === 'true',
  })

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

  const handleStart = () => {
    connect()
  }

  const handleStop = () => {
    window.speechSynthesis?.cancel()
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

  const onOutbound = useCallback((msg) => {
    addLog('out', msg)
  }, [addLog])

  return (
    <div className="app">
      <header className="header">
        <h1>Empathic Co-Pilot</h1>
        <p className="subtitle">Real-time conversation coaching, whispered when it matters</p>
        {!useMock && (
          <p className="backend-indicator" aria-label="Backend source">
            {backendSource === 'cloudrun' ? 'Cloud Run' : 'Local'}
          </p>
        )}
      </header>

      <section className="controls">
        {!sessionActive ? (
          <>
            <button className="btn btn-start" onClick={handleStart} disabled={connected && sessionActive}>
              Start session
            </button>
            <p className="onboarding-text">
              Start a session, then have your conversation. The co-pilot listens and whispers
              coaching when tension rises.
            </p>
          </>
        ) : (
          <>
            <button className="btn btn-stop" onClick={handleStop}>
              Stop session
            </button>
            <div className="listening-indicator">
              <span className="listening-dot" />
              <span>Listening...</span>
            </div>
          </>
        )}
        {lastError && <span className="error">{lastError}</span>}
      </section>

      {sessionActive && (
        <section className="tension-section">
          <div className="tension-label">
            <span>Tension</span>
            <span className="tension-value">{tension}</span>
          </div>
          <div className="tension-bar-wrap">
            <div
              className="tension-bar"
              style={{ width: `${Math.min(100, Math.max(0, tension))}%` }}
            />
          </div>
        </section>
      )}

      {!useMock && transcript !== '' && (
        <section className="transcript-section" aria-label="Live transcript">
          <h2 className="transcript-heading">Live Transcript</h2>
          <div className="transcript-text">{transcript}</div>
        </section>
      )}

      {whisper && (
        <section className="whisper-box" key={whisper.text}>
          <div className="whisper-move">{whisper.move}</div>
          <div className="whisper-text">"{whisper.text}"</div>
        </section>
      )}

      <section className="logs-section">
        <button className="logs-toggle" onClick={() => setShowLogs(s => !s)}>
          {showLogs ? 'Hide' : 'Show'} event log ({logs.length})
        </button>
        {showLogs && (
          <div className="logs-list">
            {logs.length === 0 && <div className="logs-empty">No events yet.</div>}
            {logs.map((entry) => (
              <div key={entry.id} className={`log-entry log-${entry.direction}`}>
                <span className="log-ts">{entry.ts}</span>
                <span className="log-dir">{entry.direction === 'in' ? '\u2190' : '\u2192'}</span>
                <span className="log-text">{entry.text}</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
