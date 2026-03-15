# ◐ The Other Side
**Next-Generation AI Perspective Agent** · *Built for the Gemini Live Agent Challenge*

> *"Because clarity starts where your comfort zone ends."*

---

## 💡 Inspiration

We live in an era of echo chambers — social feeds that confirm what we already believe, news that amplifies outrage, and conversations that never cross the divide. **The Other Side** uses Gemini's multimodal reasoning to do what humans find hardest: genuinely seeing a situation through a lens we disagree with.

It turns biases into bridges using real-time web grounding, cinematic generated video, and empathetic narration — all inside a Chrome extension that lives where you browse.

---

## 🎯 What It Does

Describe any situation — a conflict, a news story, a strong opinion — in text, image, audio, or video. The Other Side flips it into a grounded alternative perspective using one of five lenses:

| Lens | Voice | What it does |
|---|---|---|
| 🪞 Empathy Mirror | Warm, therapeutic | Finds the unspoken pain underneath |
| ⚖️ Conflict Mediator | Calm, authoritative | Cuts through ego to what both sides need |
| 🔄 Bias Flipper | Dry wit | Challenges your certainty with precision |
| 📜 History Retold | Storytelling | Surfaces what the dominant narrative left out |
| 😈 Devil's Advocate | Sharp, a little smug | Argues the opposite for sport and insight |

**Output is symmetric to input:**
- Text in → grounded bridge text out
- Image in → Imagen 3 generates a visual reframe
- Audio in → Cloud TTS narrates the flip
- Video in → 3-scene Imagen 3 slideshow + TTS voiceover (MP4)

---

## 🏗️ Architecture

![Architecture](docs/architecture.png)

> [→ Detailed architecture diagram](docs/architecture.svg) · [→ Request flow diagram](docs/flow.svg)

---

## 🎬 Sample Outputs — by Input Type and Lens

Each input type produces a symmetric output. The agent adapts headline, perspective, facts, closing question, and media generation payload per lens.

### Audio Input
*Situation: "A news podcast clip arguing that remote work is destroying company culture"*

![Audio sample output](docs/sample_audio.png)

**How it works:** Audio input → Gemini extracts the argument → generates SSML with adaptive voice profile (warm / authoritative / neutral matching the lens) → Cloud TTS renders MP3 → uploaded to GCS.

---

### Video Input
*Situation: "A viral video of a climate activist blocking traffic on a motorway"*

![Video sample output](docs/sample_video.png)

**How it works:** Video URL → Gemini analyses the visual + context → generates a 3-scene video_script with per-scene frame_prompt + narration → Imagen 3 renders frames → FFmpeg stitches with TTS audio → MP4 uploaded to GCS via async job.

---

### Image Input
*Situation: "A photo of an overflowing landfill site"*

![Image sample output](docs/sample_image.png)

**How it works:** Image → Vision API safety check → Gemini analyses visual content → generates visual_prompt tuned to the lens → Imagen 3 renders the reframe → PNG uploaded to GCS.

**Google Cloud services used:**
- Cloud Run — hosts the FastAPI backend + FFmpeg pipeline
- Vertex AI / Imagen 3 — cinematic frame generation
- Cloud Text-to-Speech — adaptive voice narration
- Google ADK — multi-step agent orchestration
- Gemini 2.5 Flash — core perspective model
- Gemini 2.0 Flash Lite — output toxicity scorer
- Cloud Vision API — media safety for uploaded images
- Cloud Firestore — session and feedback logging
- Google Cloud Storage — generated video/audio hosting
- Cloud Build + Artifact Registry — container CI/CD

---

## 🔒 Safety System (3 layers)

1. **Layer 1 — Input scan** (`guardrails.py`): regex blocks injection patterns, PII masking, keyword scan for violence/CSAM/weapons. Runs before any AI call — zero cost.
2. **Layer 2 — Intent check** (agent system prompt): Gemini declines inside the agent if no legitimate other side exists.
3. **Layer 3 — Output toxicity** (`rate_toxicity`): Gemini Flash Lite scores output 0–10, blocks if >3 before user sees it.

**Privacy:** Input text never stored. Media processed in memory and discarded. No user identity collected. Emails/phones masked before reaching Gemini.

---

## 🚀 Spin-Up Instructions

### Prerequisites
- Google Cloud account with billing enabled
- `gcloud` CLI authenticated (`gcloud auth login`)
- Docker installed

### Option A — Terraform (recommended, IaC)

```bash
# Clone the repo
git clone https://github.com/your-username/the-other-side
cd the-other-side

# Initialise and apply infrastructure
terraform init
terraform apply -auto-approve

# Deploy the application
bash deploy.sh
```

### Option B — Script only

```bash
git clone https://github.com/your-username/the-other-side
cd the-other-side
bash deploy.sh
```

`deploy.sh` handles everything: enables APIs, creates the GCS bucket, sets IAM roles, builds the Docker image, and deploys to Cloud Run. Prints the live URL at the end.

**One manual step:** Go to GCP Console → Firestore → Create database → Native mode → us-central1. (Required once — Google doesn't allow this via CLI on first run.)

### Install the Chrome Extension

1. Update `API_BASE` in `background.js` with your Cloud Run URL
2. Update `host_permissions` in `manifest.json` with your Cloud Run URL
3. Chrome → `chrome://extensions` → enable Developer mode → Load unpacked → select the project folder

### Run Tests

```bash
# Auto-detects your Cloud Run URL
bash test.sh

# Or pass it explicitly
bash test.sh https://your-url.run.app
```

Tests are tiered — Tier 1 costs $0 (no AI calls), Tier 4 (~$0.16) is opt-in.

---

## 💰 Cost Estimate

| Component | Cost per request |
|---|---|
| Text flip (Gemini + Search) | ~$0.002 |
| + Audio (Cloud TTS) | +$0.002 |
| + Video (Imagen 3 × 3 + FFmpeg) | +$0.16 |
| Cloud Run (idle) | $0.00 (scales to zero) |

Running 500 full video generations would cost ~$80. A typical hackathon demo costs under $2.

---

## 📁 Project Structure

```
the-other-side/
├── agent.py          # ADK LlmAgent — Gemini 2.5 Flash + ANGLES + system prompt
├── guardrails.py     # 3-layer safety: PII · Vision API · toxicity scorer
├── main.py           # FastAPI routes + video pipeline (Imagen 3 + TTS + FFmpeg)
├── database.py       # Firestore helpers
├── Dockerfile        # Python 3.11 + FFmpeg
├── requirements.txt  # All Python dependencies
├── main.tf           # Terraform IaC — all GCP infrastructure
├── deploy.sh         # One-command deploy script
├── test.sh           # Tiered test suite ($0 → $0.16)
├── manifest.json     # Chrome Extension Manifest V3
├── background.js     # Extension service worker + video job polling
├── content.js        # In-page video overlay + inline result panel
├── popup.html        # Extension popup UI
└── popup.js          # Popup controller
```

---

## 🎥 Demo Scenarios

Best situations to demo live:

1. **Workplace conflict (text):** *"My manager takes credit for my work in every meeting"* → Empathy Mirror
2. **News story (text):** *"Social media companies are destroying society"* → Bias Flipper
3. **Live video:** Right-click any YouTube video → "◐ Flip this perspective" → content.js overlay
4. **Guardrail demo:** Type *"ignore all previous instructions"* → show the warm decline

---

## 🏆 Hackathon Category

**Creative Storyteller** — multimodal storytelling with interleaved output. Text, Imagen 3 visuals, TTS audio, and generated MP4 video flow together in a single symmetric response stream.

---

## 👥 Team

| Name | LinkedIn |
|---|---|
| Ruchi Khare | [linkedin.com/in/ruchi-khare-3282464](https://www.linkedin.com/in/ruchi-khare-3282464) |
| Omkar Dhurjad | [linkedin.com/in/omkar-dhurjad-6a4414225](https://www.linkedin.com/in/omkar-dhurjad-6a4414225) |

Built for the **Gemini Live Agent Challenge** · #GeminiLiveAgentChallenge

---

## 📄 Licence

MIT
