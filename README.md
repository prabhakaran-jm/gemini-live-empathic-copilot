# Empathic Co-Pilot
Empathic Co-Pilot is a real-time multimodal Live Agent built with Gemini Live API on Google Cloud. It augments difficult human conversations by providing subtle, interruptible whisper coaching based on conversational signals such as tone shifts, pauses, and turn-taking dynamics.  
Instead of replacing one side of the interaction, Empathic Co-Pilot acts as an invisible social prosthetic—supporting the user with grounded communication strategies derived from active listening and nonviolent communication principles.  
  
## Key Features  
  
🎙 Live bidirectional audio streaming (Gemini Live API)  
🔁 Interruptible coaching (barge-in support)  
📊 Real-time tension indicator  
🧠 Signal-based conversational analysis (volume spikes, silence, overlap)  
🎧 Whisper-style short coaching prompts  
☁ Hosted on Google Cloud (Cloud Run + Vertex AI)  
  
## Architecture  
Browser (Mic) → WebSocket → Cloud Run → Gemini Live API (Vertex AI) → Coaching Engine → Audio Whisper + Tension Bar UI  
  
## Why This Matters  
Empathic Co-Pilot redefines AI interaction by moving beyond text chat into real-time conversational augmentation—helping users navigate difficult conversations with clarity and composure.
