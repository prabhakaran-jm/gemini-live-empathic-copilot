/**
 * First-run onboarding: short guided steps. Shown once per device (localStorage).
 */
export const ONBOARDING_STORAGE_KEY = 'empathic-copilot-onboarding-dismissed'

export function getOnboardingSeen() {
  if (typeof window === 'undefined') return true
  try {
    return window.localStorage.getItem(ONBOARDING_STORAGE_KEY) === '1'
  } catch {
    return true
  }
}

export function setOnboardingSeen() {
  try {
    window.localStorage.setItem(ONBOARDING_STORAGE_KEY, '1')
  } catch (_) {}
}

const STEPS = [
  'Click **Start session** and allow microphone access when prompted.',
  'Speak naturally — the tension bar and whispered coaching will guide you.',
  'Optional: turn on **Include webcam** for vision-aware coaching.',
]

function StepText({ text }) {
  const parts = text.split(/\*\*/)
  return (
    <>
      {parts.map((part, j) =>
        j % 2 === 1 ? <strong key={j}>{part}</strong> : part
      )}
    </>
  )
}

export default function OnboardingModal({ onDismiss }) {
  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget) onDismiss()
  }

  return (
    <div
      className="onboarding-modal"
      role="dialog"
      aria-labelledby="onboarding-title"
      aria-modal="true"
      onClick={handleBackdropClick}
    >
      <div className="onboarding-modal__card" onClick={(e) => e.stopPropagation()}>
        <h2 id="onboarding-title" className="onboarding-modal__title">
          Quick start
        </h2>
        <ol className="onboarding-modal__steps">
          {STEPS.map((step, i) => (
            <li key={i} className="onboarding-modal__step">
              <StepText text={step} />
            </li>
          ))}
        </ol>
        <button
          type="button"
          className="onboarding-modal__btn"
          onClick={onDismiss}
          autoFocus
        >
          Got it
        </button>
      </div>
    </div>
  )
}
