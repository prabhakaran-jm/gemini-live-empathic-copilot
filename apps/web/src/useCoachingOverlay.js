import { useEffect, useRef, useState } from 'react'

/** Tension is 0–100 from backend; 0–10 scale: 7+ = 70+, below 5 = 50- */
const HIGH_TENSION_THRESHOLD = 70   // >= 7 in 0–10
const LOW_TENSION_THRESHOLD = 50    // < 5 in 0–10
const HIGH_TENSION_HOLD_MS = 2000  // show overlay after 2s at high tension

/**
 * Monitors tension score: if >= 70 for 2s, show overlay; when < 50, hide (fade-out).
 * @param {number} tension - Current tension 0–100
 * @returns {{ showOverlay: boolean }}
 */
export function useCoachingOverlay(tension) {
  const [showOverlay, setShowOverlay] = useState(false)
  const qualifiedRef = useRef(false)  // true after 2s at high tension
  const timerRef = useRef(null)

  useEffect(() => {
    if (tension >= HIGH_TENSION_THRESHOLD) {
      if (!timerRef.current) {
        timerRef.current = setTimeout(() => {
          qualifiedRef.current = true
          setShowOverlay(true)
          timerRef.current = null
        }, HIGH_TENSION_HOLD_MS)
      }
    } else {
      if (timerRef.current) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
      if (tension < LOW_TENSION_THRESHOLD) {
        qualifiedRef.current = false
        setShowOverlay(false)
      }
    }
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [tension])

  return { showOverlay }
}
