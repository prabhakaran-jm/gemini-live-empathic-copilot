/**
 * First-run onboarding: short guided steps. Shown once per device (localStorage).
 * Traps focus inside the modal for accessibility (Tab cycles within the dialog).
 */
import { useEffect, useRef } from 'react'

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

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

export default function OnboardingModal({ onDismiss }) {
  const cardRef = useRef(null)

  const handleBackdropClick = (e) => {
    if (e.target === e.currentTarget) onDismiss()
  }

  useEffect(() => {
    const card = cardRef.current
    if (!card) return
    const focusables = card.querySelectorAll(FOCUSABLE)
    const first = focusables[0]
    const last = focusables[focusables.length - 1]
    const handleKeyDown = (e) => {
      if (e.key !== 'Tab') return
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault()
          last?.focus()
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault()
          first?.focus()
        }
      }
    }
    card.addEventListener('keydown', handleKeyDown)
    return () => card.removeEventListener('keydown', handleKeyDown)
  }, [])

  return (
    <div
      className="onboarding-modal"
      role="dialog"
      aria-labelledby="onboarding-title"
      aria-modal="true"
      onClick={handleBackdropClick}
    >
      <div ref={cardRef} className="onboarding-modal__card" onClick={(e) => e.stopPropagation()}>
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
