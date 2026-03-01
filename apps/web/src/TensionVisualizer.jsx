/**
 * Real-time Tension Meter — Stitch-aligned.
 * Maps backend score (0–100) to 0–10 display; gradient by zone:
 * Emerald (0–30), Soft Amber (31–60), Vibrant Coral/Red (61–100).
 * Pulse animation when score > 70.
 */
export default function TensionVisualizer({ score = 0 }) {
  const clamped = Math.min(100, Math.max(0, Number(score)))
  const percent = clamped
  const normalized = clamped / 10 // 0–10 for zones

  // Zone colors: Emerald 0–3, Amber 4–6, Coral/Red 7–10 (raw: 0–30, 31–60, 61–100)
  const getBarColor = () => {
    if (clamped <= 30) return 'var(--tension-emerald)'
    if (clamped <= 60) return 'var(--tension-amber)'
    return 'var(--tension-coral)'
  }

  const isHighTension = clamped > 70

  return (
    <div
      className={`tension-visualizer ${isHighTension ? 'tension-visualizer--pulse' : ''}`}
      role="img"
      aria-label={`Tension level ${Math.round(normalized * 10) / 10} out of 10`}
    >
      <div className="tension-visualizer__header">
        <span className="tension-visualizer__label">Tension</span>
        <span className="tension-visualizer__value" aria-hidden="true">
          {clamped}
        </span>
      </div>
      <div
        className="tension-visualizer__track"
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="tension-visualizer__fill"
          style={{
            width: `${percent}%`,
            background: getBarColor(),
          }}
        />
      </div>
    </div>
  )
}
