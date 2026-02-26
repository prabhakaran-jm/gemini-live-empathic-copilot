/**
 * WebSocket hook for Empathic Co-Pilot protocol.
 * Set VITE_WS_URL to ws://localhost:8765/ws for real backend, or use mock.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

const DEFAULT_WS_URL = (import.meta.env.VITE_WS_URL || '').trim() || null
const USE_MOCK = import.meta.env.VITE_USE_MOCK_WS === 'true'

function getWsUrl() {
  if (DEFAULT_WS_URL) return DEFAULT_WS_URL
  if (typeof window !== 'undefined' && window.location) {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    return `${proto}//${host}/ws`
  }
  return 'ws://localhost:8765/ws'
}

/** In-browser mock: no server needed. Sends ready, then periodic tension + whispers. */
function createMockWebSocket(onMessage) {
  let closed = false
  const open = () => {
    onMessage({ type: 'ready' })
    const interval = setInterval(() => {
      if (closed) {
        clearInterval(interval)
        return
      }
      onMessage({
        type: 'tension',
        score: 20 + Math.floor(Math.random() * 50),
        ts: Date.now(),
      })
    }, 1500)
    const whisperInterval = setInterval(() => {
      if (closed) {
        clearInterval(whisperInterval)
        return
      }
      const moves = [
        { move: 'reflect_back', text: "It sounds like this is really important to you right now." },
        { move: 'clarify_intent', text: "Would it help to say what you're hoping they take away?" },
        { move: 'slow_down', text: "Taking a breath before the next sentence can help." },
        { move: 'deescalate_tone', text: "A softer tone might make it easier for them to hear you." },
        { move: 'invite_perspective', text: "You could ask how they're seeing it so far." },
      ]
      const m = moves[Math.floor(Math.random() * moves.length)]
      onMessage({ type: 'whisper', ...m, ts: Date.now() })
    }, 6000)
  }
  setTimeout(open, 100)
  return {
    send: (obj) => {
      try {
        const msg = typeof obj === 'string' ? JSON.parse(obj) : obj
        if (msg.type === 'stop') {
          closed = true
          onMessage({ type: 'stopped' })
        }
      } catch (_) {}
    },
    close: () => { closed = true },
    readyState: 1,
  }
}

export function useWebSocket({ onMessage, onOutbound, useMock = USE_MOCK }) {
  const [connected, setConnected] = useState(false)
  const [lastError, setLastError] = useState(null)
  const wsRef = useRef(null)
  const onMessageRef = useRef(onMessage)
  const onOutboundRef = useRef(onOutbound)
  onMessageRef.current = onMessage
  onOutboundRef.current = onOutbound

  const connect = useCallback(() => {
    if (useMock) {
      const mock = createMockWebSocket((msg) => onMessageRef.current?.(msg))
      wsRef.current = mock
      setConnected(true)
      setLastError(null)
      onOutboundRef.current?.({ type: 'start' })
      return
    }
    const url = getWsUrl()
    const ws = new WebSocket(url)
    ws.onopen = () => {
      setConnected(true)
      setLastError(null)
      const startMsg = { type: 'start' }
      ws.send(JSON.stringify(startMsg))
      onOutboundRef.current?.(startMsg)
    }
    ws.onclose = () => setConnected(false)
    ws.onerror = () => setLastError('WebSocket error')
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        onMessageRef.current?.(msg)
      } catch (_) {}
    }
    wsRef.current = ws
  }, [useMock])

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    setConnected(false)
  }, [])

  const send = useCallback((obj) => {
    if (wsRef.current?.readyState === 1) {
      wsRef.current.send(JSON.stringify(obj))
    }
  }, [])

  useEffect(() => {
    return () => {
      if (wsRef.current) wsRef.current.close()
    }
  }, [])

  return { connected, lastError, connect, disconnect, send }
}
