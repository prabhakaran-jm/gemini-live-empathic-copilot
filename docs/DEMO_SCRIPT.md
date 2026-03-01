# Demo Script (≈90 seconds)

Scripted flow to reliably trigger the three MVP whisper rules: **slow_down**, **reflect_back**, **clarify_intent**.

**Cooldown:** There is a ~12 s cooldown between whispers. Space actions so each trigger falls after the previous whisper.

---

## Timing overview

| Phase | Approx. time | Goal |
|-------|--------------|------|
| Start + calm | 0:00–0:15 | Start session, speak calmly so tension stays low. |
| (a) Tension cross → slow_down | 0:15–0:35 | Raise voice; tension crosses into ≥40 → whisper "Taking a breath before the next sentence can help." |
| (b) 2× barge-in → reflect_back | 0:35–0:55 | Let agent start responding (or speak so Gemini responds); interrupt twice within ~5 s → whisper "It sounds like this is really important to you right now." |
| (c) Silence after escalation → clarify_intent | 0:55–1:30 | After a high-tension moment (tension ≥70 in last 10 s), stay silent >2.5 s → whisper "Would it help to say what you're hoping they take away?" |

---

## Script (step-by-step)

1. **0:00** — Click **Start session**, allow mic. Optional: say one calm line, e.g. *"I'm going to practice a difficult conversation."*

2. **0:15 — Trigger (a) slow_down**  
   Speak **louder and more emphatically** for 5–10 seconds (e.g. *"This is really frustrating and I need them to understand my side!"*).  
   **Look for:** Tension bar rising; when it crosses upward past ~40, a whisper should appear: *"Taking a breath before the next sentence can help."*

3. **0:35 — Trigger (b) reflect_back**  
   Say something that elicits a longer agent response (e.g. a question), or wait until the agent is speaking. Then **talk over the agent** (interrupt) **twice** within about 5 seconds (e.g. say *"Wait—"* or *"Actually—"* twice while it’s “speaking” or during response generation).  
   **Look for:** Event log shows `event: interrupted` (at least twice). Shortly after, whisper: *"It sounds like this is really important to you right now."*

4. **0:55 — Trigger (c) clarify_intent**  
   First create a high-tension moment: speak **loudly** for a few seconds so tension reaches ~70+ (check the bar). Then **stay completely silent** for at least **2.5 seconds** (better: 3–4 s).  
   **Look for:** After the silence threshold, whisper: *"Would it help to say what you're hoping they take away?"*

5. **1:25–1:30** — Click **Stop session**.

---

## Notes

- **Mic level:** Ensure the mic is unmuted and at a good level; tension is driven by RMS. If tension never rises, speak closer or louder.
- **Barge-in:** "Interrupted" is detected when the backend considers the user to be speaking over the agent; two such events within 5 s trigger **reflect_back**.
- **Silence:** **clarify_intent** needs (1) silence >2.5 s and (2) tension ≥70 at some point in the last 10 s. So do the “loud burst” first, then go silent.
- If a whisper doesn’t appear, wait for the 12 s cooldown and retry the trigger (e.g. raise voice again for slow_down, or two more interrupts for reflect_back).
