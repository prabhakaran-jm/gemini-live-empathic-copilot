/**
 * WebSocket hook for Empathic Co-Pilot protocol.
 * If VITE_WS_URL is set, use it as the WebSocket endpoint (ws/wss corrected). Otherwise use proxy for localhost dev.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

const RAW_WS_URL = (import.meta.env.VITE_WS_URL || '').trim() || null
const USE_MOCK = import.meta.env.VITE_USE_MOCK_WS === 'true'

/** Normalize URL to ws: or wss: based on http(s): or existing ws(s): */
function normalizeWsUrl(url) {
  if (!url) return null
  const u = url.replace(/^https:\/\//i, 'wss://').replace(/^http:\/\//i, 'ws://')
  return u.startsWith('ws://') || u.startsWith('wss://') ? u : `wss://${u}`
}

function getWsUrl() {
  if (RAW_WS_URL) return normalizeWsUrl(RAW_WS_URL)
  if (typeof window !== 'undefined' && window.location) {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    return `${proto}//${host}/ws`
  }
  return 'ws://localhost:8765/ws'
}

/** 'cloudrun' when using an explicit VITE_WS_URL that is not localhost; otherwise 'local' */
function getBackendSource() {
  if (!RAW_WS_URL) return 'local'
  const u = RAW_WS_URL.toLowerCase()
  return (u.includes('localhost') || u.includes('127.0.0.1')) ? 'local' : 'cloudrun'
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

const RECONNECT_DELAY_MS = 2000
const RECONNECT_MAX_ATTEMPTS = 5

export function useWebSocket({ onMessage, onOutbound, useMock = USE_MOCK }) {
  const [connected, setConnected] = useState(false)
  const [lastError, setLastError] = useState(null)
  const wsRef = useRef(null)
  const onMessageRef = useRef(onMessage)
  const onOutboundRef = useRef(onOutbound)
  const intentionalCloseRef = useRef(false)
  const lastStartConfigRef = useRef(null)
  const reconnectTimeoutRef = useRef(null)
  const reconnectAttemptRef = useRef(0)
  onMessageRef.current = onMessage
  onOutboundRef.current = onOutbound

  const connect = useCallback((initialStartConfig = null) => {
    intentionalCloseRef.current = false
    reconnectAttemptRef.current = 0
    const startPayload = initialStartConfig && typeof initialStartConfig === 'object'
      ? { type: 'start', config: initialStartConfig }
      : { type: 'start' }
    lastStartConfigRef.current = initialStartConfig

    if (useMock) {
      const mock = createMockWebSocket((msg) => onMessageRef.current?.(msg))
      wsRef.current = mock
      setConnected(true)
      setLastError(null)
      onOutboundRef.current?.(startPayload)
      return
    }

    const url = getWsUrl()
    const ws = new WebSocket(url)

    const tryReconnect = () => {
      if (intentionalCloseRef.current || reconnectAttemptRef.current >= RECONNECT_MAX_ATTEMPTS) return
      reconnectAttemptRef.current += 1
      setLastError('Connection lost. Reconnecting…')
      reconnectTimeoutRef.current = setTimeout(() => {
        connect(lastStartConfigRef.current)
      }, RECONNECT_DELAY_MS)
    }

    ws.onopen = () => {
      reconnectAttemptRef.current = 0
      setConnected(true)
      setLastError(null)
      ws.send(JSON.stringify(startPayload))
      onOutboundRef.current?.(startPayload)
    }
    ws.onclose = () => {
      setConnected(false)
      wsRef.current = null
      if (!intentionalCloseRef.current && lastStartConfigRef.current != null) {
        tryReconnect()
      }
    }
    ws.onerror = () => {
      setLastError('WebSocket error')
    }
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        onMessageRef.current?.(msg)
      } catch (_) {}
    }
    wsRef.current = ws
  }, [useMock])

  const disconnect = useCallback(() => {
    intentionalCloseRef.current = true
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    lastStartConfigRef.current = null
    reconnectAttemptRef.current = RECONNECT_MAX_ATTEMPTS
    setConnected(false)
    setLastError(null)
  }, [])

  const send = useCallback((obj) => {
    if (wsRef.current?.readyState === 1) {
      wsRef.current.send(JSON.stringify(obj))
    }
  }, [])

  useEffect(() => {
    return () => {
      intentionalCloseRef.current = true
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (wsRef.current) wsRef.current.close()
    }
  }, [])

  return { connected, lastError, connect, disconnect, send, useMock, backendSource: getBackendSource() }
}
