import { useCallback, useState } from 'react'
import { useWebSocket } from './useWebSocket'
import './App.css'

export default function App() {
  const [sessionActive, setSessionActive] = useState(false)
  const [tension, setTension] = useState(0)
  const [whisper, setWhisper] = useState(null)
  const [logs, setLogs] = useState([])

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
      addLog('in', { type: 'whisper', text: msg.text, move: msg.move })
    } else if (msg.type === 'stopped') {
      setSessionActive(false)
      setWhisper(null)
      addLog('in', { type: 'stopped' })
    } else if (msg.type === 'error') {
      addLog('in', { type: 'error', message: msg.message })
    }
  }, [addLog])

  const { connected, lastError, connect, disconnect, send } = useWebSocket({
    onMessage,
    onOutbound,
    useMock: import.meta.env.VITE_USE_MOCK_WS === 'true',
  })

  const handleStart = () => {
    connect()
  }

  const handleStop = () => {
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
        <p className="subtitle">Live tension + coaching whispers (MVP)</p>
      </header>

      <section className="controls">
        {!sessionActive ? (
          <button className="btn btn-start" onClick={handleStart} disabled={connected && sessionActive}>
            Start session
          </button>
        ) : (
          <button className="btn btn-stop" onClick={handleStop}>
            Stop session
          </button>
        )}
        {lastError && <span className="error">{lastError}</span>}
      </section>

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

      {whisper && (
        <section className="whisper-box">
          <div className="whisper-move">{whisper.move}</div>
          <div className="whisper-text">"{whisper.text}"</div>
        </section>
      )}

      <section className="logs-section">
        <h2>Event log</h2>
        <div className="logs-list">
          {logs.length === 0 && <div className="logs-empty">No events yet. Start a session.</div>}
          {logs.map((entry) => (
            <div key={entry.id} className={`log-entry log-${entry.direction}`}>
              <span className="log-ts">{entry.ts}</span>
              <span className="log-dir">{entry.direction === 'in' ? '←' : '→'}</span>
              <span className="log-text">{entry.text}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
