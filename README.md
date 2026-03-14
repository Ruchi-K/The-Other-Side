# The-Other-Side
**Next-Generation AI Perspective Agent**
A multimodal AI Agent built with Google ADK and Gemini that deconstructs cognitive bias by generating "other-side" perspectives via cinematic video, grounded search, and empathetic narration.

### 💡 Inspiration
We are living in an era of "echo chambers." **The Other Side** uses Gemini's multimodal reasoning to do what humans find hardest: seeing a situation through a lens we disagree with. It turns biases into bridges using cinematic video, grounded facts, and empathetic narration.

### 🏗️ Technical Architecture
- **Agent Framework:** [Google ADK](https://github.com/google/adk) for multi-step reasoning.
- **Core Model:** `gemini-2.5-flash` for high-speed perspective shifting.
- **Symmetric Multimodality:** - **Vision:** Imagen 3 for cinematic scene generation.
  - **Audio:** Cloud TTS with dynamic voice profiles (Warm, Authoritative, Neutral).
  - **Video:** Custom FFmpeg pipeline running on Cloud Run.
- **Safety:** Multi-layer guardrails including `gemini-2.0-flash-lite` for output toxicity scoring.

### 🚀 Automated Deployment
This project uses **Terraform** for Infrastructure-as-Code and a dedicated deployment script.

**1. Infrastructure Spin-up:**
```bash
terraform init
terraform apply -auto-approve
