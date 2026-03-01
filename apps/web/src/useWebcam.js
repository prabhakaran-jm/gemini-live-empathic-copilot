/**
 * Optional webcam capture for vision-aware coaching (P3).
 * Captures JPEG frames for sending to backend as context for Gemini Flash.
 */
import { useCallback, useRef, useState } from 'react'

const CAPTURE_INTERVAL_MS = 5000
const JPEG_QUALITY = 0.7

export function useWebcam() {
  const videoRef = useRef(null)
  const streamRef = useRef(null)
  const [error, setError] = useState(null)
  const [active, setActive] = useState(false)

  const start = useCallback(async () => {
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480, facingMode: 'user' },
        audio: false,
      })
      streamRef.current = stream
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        await videoRef.current.play()
      }
      setActive(true)
      return true
    } catch (e) {
      setError(e?.message || 'Webcam access failed')
      setActive(false)
      return false
    }
  }, [])

  const stop = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null
    }
    setActive(false)
    setError(null)
  }, [])

  const captureFrame = useCallback(() => {
    const video = videoRef.current
    if (!video || !streamRef.current || video.readyState < 2) return null
    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    ctx.drawImage(video, 0, 0)
    const dataUrl = canvas.toDataURL('image/jpeg', JPEG_QUALITY)
    const base64 = dataUrl.replace(/^data:image\/jpeg;base64,/, '')
    return base64
  }, [])

  return {
    videoRef,
    start,
    stop,
    captureFrame,
    active,
    error,
  }
}

export { CAPTURE_INTERVAL_MS }
