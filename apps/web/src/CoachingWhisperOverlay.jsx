/**
 * Coaching Whisper overlay — Stitch glassmorphism, top-right, soft indigo.
 * Slide-in-right entrance; fade-out exit when tension drops.
 * Does not block Start Session or Event Log (positioned top-right, click-through outside card).
 */
const PLACEHOLDER_TIP =
  'Tension is rising. Try acknowledging their perspective or pausing for 3 seconds.'

export default function CoachingWhisperOverlay({ visible, exiting }) {
  if (!visible && !exiting) return null

  return (
    <div
      className={`coaching-overlay coaching-overlay--${visible && !exiting ? 'visible' : 'exiting'}`}
      aria-live="polite"
      aria-label="Coaching tip"
    >
      <div className="coaching-overlay__card">
        <div className="coaching-overlay__icon" aria-hidden="true">
          <span className="coaching-overlay__pulse" />
          <span className="coaching-overlay__dot" />
        </div>
        <p className="coaching-overlay__text">{PLACEHOLDER_TIP}</p>
      </div>
    </div>
  )
}
