/**
 * Minimal mic level meter for Advanced card — Stitch-aligned.
 * Horizontal level bar + optional sparkline of recent RMS.
 */
const RMS_SPARKLINE_LEN = 24
const RMS_CAP = 0.5

export default function RmsLevelMeter({ rms = 0, sparklineData = [] }) {
  const fillPercent = Math.min(100, (rms / RMS_CAP) * 100)
  const points = Array.isArray(sparklineData) ? sparklineData.slice(-RMS_SPARKLINE_LEN) : []

  return (
    <div className="rms-level-meter" aria-label="Microphone level">
      <div className="rms-level-meter__label">Mic level</div>
      <div className="rms-level-meter__bar-wrap">
        <div
          className="rms-level-meter__bar"
          style={{ width: `${fillPercent}%` }}
          role="progressbar"
          aria-valuenow={rms}
          aria-valuemin={0}
          aria-valuemax={RMS_CAP}
        />
      </div>
      {points.length > 0 && (
        <div className="rms-level-meter__sparkline" aria-hidden="true">
          {points.map((v, i) => (
            <div
              key={i}
              className="rms-level-meter__sparkline-seg"
              style={{ height: `${Math.min(100, (v / RMS_CAP) * 100)}%` }}
            />
          ))}
        </div>
      )}
    </div>
  )
}
