"""
The Other Side — FastAPI Backend
main.py — ADK agent + Imagen 3 + Cloud TTS + FFmpeg video pipeline
"""
import asyncio
import base64
import json
import logging
import os
import subprocess
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import vertexai
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.sessions import InMemorySessionService
from google.cloud import storage, texttospeech, firestore
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from vertexai.preview.vision_models import ImageGenerationModel

from agent import ANGLES, root_agent
from guardrails import check_input_guardrail, sanitize_input, validate_output, check_media_safety

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("the-other-side")

APP_NAME    = "the_other_side"
APP_VERSION = "1.0.0"
PROJECT_ID  = os.environ.get("GOOGLE_CLOUD_PROJECT", "the-other-side-489308")
BUCKET_NAME = os.environ.get("GCS_BUCKET_NAME", "the-other-side-videos-489308")
REGION      = os.environ.get("REGION", "us-central1")

vertexai.init(project=PROJECT_ID, location=REGION)

ALLOWED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "video/mp4", "video/webm", "video/quicktime",
    "audio/mpeg", "audio/wav", "audio/ogg", "audio/webm",
}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

# ─────────────────────────────────────────────────────────────
# CLIENTS
# ─────────────────────────────────────────────────────────────

gcs_client = storage.Client()
tts_client = texttospeech.TextToSpeechClient()
db         = firestore.Client()

# ─────────────────────────────────────────────────────────────
# RATE LIMITER
# ─────────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)

# ─────────────────────────────────────────────────────────────
# SESSION SERVICE
# ─────────────────────────────────────────────────────────────

session_service = InMemorySessionService()

# ─────────────────────────────────────────────────────────────
# ADK APP
# ─────────────────────────────────────────────────────────────

adk_app = get_fast_api_app(
    agent_dir=".",
    session_service=session_service,
    allow_origins=["*"],
)

# ─────────────────────────────────────────────────────────────
# IN-MEMORY JOB STORE (for async video generation)
# ─────────────────────────────────────────────────────────────

jobs: dict = {}

# ─────────────────────────────────────────────────────────────
# LIFESPAN
# ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"◐ The Other Side v{APP_VERSION} starting")
    yield
    logger.info("◐ The Other Side shutting down")

# ─────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="The Other Side",
    description="Because clarity starts where your comfort zone ends.",
    version=APP_VERSION,
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/adk", adk_app)

# ─────────────────────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────────────────────

class FlipRequest(BaseModel):
    situation: str
    angle: str = "empathy"
    media_type: str = "text"   # text | image | audio | video
    session_id: Optional[str] = None

class FeedbackRequest(BaseModel):
    session_id: str
    perspective_new: bool
    fairness_score: int
    quality_score: int
    quality_issue: Optional[str] = None
    what_shifted: Optional[str] = None

class VideoRequest(BaseModel):
    headline: str
    the_other_side: str
    facts: list
    closing_prompt: str
    generation_payload: dict
    angle: str = "empathy"
    session_id: Optional[str] = None

# ─────────────────────────────────────────────────────────────
# GCS HELPERS
# ─────────────────────────────────────────────────────────────

def upload_to_gcs(content: bytes, content_type: str, extension: str) -> str:
    """Uploads bytes to GCS and returns the public URL."""
    bucket = gcs_client.bucket(BUCKET_NAME)
    filename = f"outputs/{uuid.uuid4()}.{extension}"
    blob = bucket.blob(filename)
    blob.upload_from_string(content, content_type=content_type)
    return f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"

# ─────────────────────────────────────────────────────────────
# IMAGEN 3 — image generation
# ─────────────────────────────────────────────────────────────

def generate_images(prompts: list[str]) -> list[bytes]:
    """
    Calls Imagen 3 for each prompt and returns raw image bytes.
    Falls back gracefully if a prompt fails.
    """
    model = ImageGenerationModel.from_pretrained("imagen-3.0-generate-001")
    results = []
    for prompt in prompts:
        try:
            response = model.generate_images(
                prompt=prompt,
                number_of_images=1,
                aspect_ratio="16:9",
            )
            results.append(response.generated_images[0]._image_bytes)
        except Exception as e:
            logger.error(f"Imagen 3 failed for prompt: {e}")
    return results

# ─────────────────────────────────────────────────────────────
# CLOUD TTS — audio generation
# ─────────────────────────────────────────────────────────────

def generate_tts(text: str, voice_profile: str = "warm") -> bytes:
    """
    Generates MP3 audio from text using Cloud TTS.
    Voice adapts to the lens voice_profile.
    """
    voice_map = {
        "warm":          ("en-US-Studio-O", texttospeech.SsmlVoiceGender.FEMALE),
        "authoritative": ("en-US-Studio-Q", texttospeech.SsmlVoiceGender.MALE),
        "neutral":       ("en-US-Neural2-C", texttospeech.SsmlVoiceGender.FEMALE),
    }
    voice_name, gender = voice_map.get(voice_profile, voice_map["warm"])

    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code="en-US",
        name=voice_name,
        ssml_gender=gender,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=0.95,
        pitch=-1.0,
    )
    response = tts_client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )
    return response.audio_content

# ─────────────────────────────────────────────────────────────
# FFMPEG VIDEO PIPELINE
# ─────────────────────────────────────────────────────────────

def build_video(image_bytes_list: list[bytes], audio_bytes: bytes, texts: list[str]) -> bytes:
    """
    Stitches Imagen 3 images + TTS audio into an MP4 using FFmpeg.
    Each image is shown for an equal slice of the audio duration.
    Returns raw MP4 bytes.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Write images to disk
        img_paths = []
        for i, img_bytes in enumerate(image_bytes_list):
            path = os.path.join(tmpdir, f"frame_{i:02d}.jpg")
            with open(path, "wb") as f:
                f.write(img_bytes)
            img_paths.append(path)

        # Write audio to disk
        audio_path = os.path.join(tmpdir, "narration.mp3")
        with open(audio_path, "wb") as f:
            f.write(audio_bytes)

        # Get audio duration
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            capture_output=True, text=True
        )
        try:
            duration = float(probe.stdout.strip())
        except Exception:
            duration = 30.0

        # Each image gets equal screen time
        per_image = duration / max(len(img_paths), 1)

        # Build FFmpeg concat input file
        concat_path = os.path.join(tmpdir, "concat.txt")
        with open(concat_path, "w") as f:
            for path in img_paths:
                f.write(f"file '{path}'\n")
                f.write(f"duration {per_image:.2f}\n")
            # FFmpeg concat needs the last image repeated without duration
            if img_paths:
                f.write(f"file '{img_paths[-1]}'\n")

        output_path = os.path.join(tmpdir, "output.mp4")

        # FFmpeg: slideshow + audio + scale to 1280x720 + text overlay
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", concat_path,
            "-i", audio_path,
            "-vf", (
                "scale=1280:720:force_original_aspect_ratio=decrease,"
                "pad=1280:720:(ow-iw)/2:(oh-ih)/2:black,"
                f"drawtext=text='◐ The Other Side':fontcolor=white:fontsize=28:"
                f"x=40:y=40:alpha=0.7"
            ),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest",
            "-movflags", "+faststart",
            output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr.decode()}")
            raise RuntimeError("Video generation failed")

        with open(output_path, "rb") as f:
            return f.read()

# ─────────────────────────────────────────────────────────────
# ASYNC VIDEO JOB
# ─────────────────────────────────────────────────────────────

async def process_video_job(job_id: str, req: VideoRequest):
    """
    Background task: Imagen 3 → TTS → FFmpeg → GCS.
    Updates jobs[job_id] with status as it progresses.
    """
    try:
        jobs[job_id] = {"status": "generating_images"}
        angle_cfg = ANGLES.get(req.angle, ANGLES["empathy"])
        payload = req.generation_payload or {}

        # Build image prompts
        video_script = payload.get("video_script", [])
        if video_script:
            prompts = [scene.get("frame_prompt", req.headline) for scene in video_script[:3]]
        else:
            visual_prompt = payload.get("visual_prompt") or req.headline
            prompts = [
                f"{visual_prompt} — establishing shot, cinematic, 4K",
                f"{visual_prompt} — close-up emotional detail, soft light",
                f"A bridge between two worlds. {req.closing_prompt}. Cinematic.",
            ]

        # Generate images in thread pool (blocking SDK call)
        loop = asyncio.get_event_loop()
        image_bytes_list = await loop.run_in_executor(None, generate_images, prompts)

        if not image_bytes_list:
            raise RuntimeError("Imagen 3 returned no images")

        jobs[job_id] = {"status": "generating_audio"}

        # Build narration script
        narration_parts = [req.headline, req.the_other_side]
        if video_script:
            narration_parts = [s.get("narration", "") for s in video_script if s.get("narration")]
        narration_parts.append(req.closing_prompt)
        narration = " ... ".join(filter(None, narration_parts))

        voice_profile = payload.get("voice_profile", angle_cfg["voice"])
        audio_bytes = await loop.run_in_executor(
            None, generate_tts, narration, voice_profile
        )

        jobs[job_id] = {"status": "assembling_video"}

        texts = [req.headline, req.the_other_side, req.closing_prompt]
        video_bytes = await loop.run_in_executor(
            None, build_video, image_bytes_list, audio_bytes, texts
        )

        jobs[job_id] = {"status": "uploading"}
        video_url = await loop.run_in_executor(
            None, upload_to_gcs, video_bytes, "video/mp4", "mp4"
        )

        jobs[job_id] = {"status": "completed", "video_url": video_url}
        logger.info(f"Video job {job_id} completed: {video_url}")

        # Log to Firestore
        try:
            db.collection("video_jobs").document(job_id).set({
                "session_id": req.session_id,
                "angle":      req.angle,
                "video_url":  video_url,
                "status":     "completed",
                "ts":         int(time.time()),
            })
        except Exception as e:
            logger.warning(f"Firestore log failed: {e}")

    except Exception as e:
        logger.error(f"Video job {job_id} failed: {e}")
        jobs[job_id] = {"status": "failed", "error": str(e)}

# ─────────────────────────────────────────────────────────────
# LOGGING HELPERS
# ─────────────────────────────────────────────────────────────

def log_session(entry: dict):
    logger.info(f"SESSION | {json.dumps(entry)}")
    try:
        db.collection("sessions").document(entry["session_id"]).set(entry)
    except Exception as e:
        logger.warning(f"Firestore session log failed: {e}")

def log_feedback(entry: dict):
    logger.info(f"FEEDBACK | {json.dumps(entry)}")
    try:
        db.collection("feedback").document(entry["session_id"]).set(entry)
    except Exception as e:
        logger.warning(f"Firestore feedback log failed: {e}")

# ─────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "service": "The Other Side",
        "version": APP_VERSION,
        "tagline": "Because clarity starts where your comfort zone ends.",
    }

@app.get("/health")
async def health():
    return {"status": "ok", "ts": int(time.time())}

@app.get("/angles")
async def get_angles():
    return {
        "angles": [
            {"id": k, "label": v["label"], "desc": v["desc"], "closing": v["closing"]}
            for k, v in ANGLES.items()
        ]
    }

@app.post("/flip")
@limiter.limit("10/minute")
async def flip(request: Request, body: FlipRequest):
    """
    Main endpoint. Runs Layer 1 guardrail, logs session,
    returns ADK payload for client to call /adk/run.
    """
    session_id = body.session_id or str(uuid.uuid4())

    # Layer 1 guardrail
    try:
        clean_situation = sanitize_input(body.situation)
    except ValueError as e:
        return JSONResponse(status_code=200, content={
            "session_id": session_id,
            "declined": True,
            "message": str(e),
            "output": None,
        })

    guardrail = check_input_guardrail(clean_situation)
    if not guardrail["safe"]:
        log_session({
            "session_id": session_id,
            "guardrail_triggered": True,
            "lens_used": body.angle,
            "ts": int(time.time()),
        })
        return JSONResponse(status_code=200, content={
            "session_id": session_id,
            "declined": True,
            "message": guardrail["reason"],
            "output": None,
        })

    log_session({
        "session_id": session_id,
        "guardrail_triggered": False,
        "lens_used": body.angle,
        "media_type": body.media_type,
        "ts": int(time.time()),
    })

    return {
        "session_id": session_id,
        "declined": False,
        "adk_run_endpoint": "/adk/run",
        "adk_run_payload": {
            "app_name":    APP_NAME,
            "user_id":     "anon",
            "session_id":  session_id,
            "new_message": {
                "role": "user",
                "parts": [{
                    "text": (
                        f"SITUATION:\n{clean_situation}\n\n"
                        f"ANGLE: {body.angle}\n"
                        f"MEDIA TYPE: {body.media_type}\n\n"
                        "Run describe_perspective → build_bridge. "
                        "Return the raw JSON only."
                    )
                }],
            },
        },
    }


@app.post("/generate-audio")
@limiter.limit("20/minute")
async def generate_audio_endpoint(request: Request, body: dict):
    """Generates TTS narration and returns GCS URL."""
    text = body.get("text", "")
    angle = body.get("angle", "empathy")
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    angle_cfg = ANGLES.get(angle, ANGLES["empathy"])
    try:
        loop = asyncio.get_event_loop()
        audio_bytes = await loop.run_in_executor(
            None, generate_tts, text, angle_cfg["voice"]
        )
        audio_url = await loop.run_in_executor(
            None, upload_to_gcs, audio_bytes, "audio/mp3", "mp3"
        )
        return {"audio_url": audio_url}
    except Exception as e:
        logger.error(f"Audio generation failed: {e}")
        raise HTTPException(status_code=500, detail="Audio generation failed")


@app.post("/generate-video")
@limiter.limit("5/minute")
async def generate_video_endpoint(
    request: Request,
    body: VideoRequest,
    background_tasks: BackgroundTasks,
):
    """
    Kicks off async video generation job.
    Returns job_id immediately — client polls /video-status/{job_id}.
    """
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "queued"}
    background_tasks.add_task(process_video_job, job_id, body)
    return {"job_id": job_id, "status": "queued"}


@app.get("/video-status/{job_id}")
async def video_status(job_id: str):
    """Poll this to check video generation progress."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@app.post("/upload-media")
@limiter.limit("20/minute")
async def upload_media(request: Request, file: UploadFile = File(...)):
    """
    Accepts image/video/audio for multimodal analysis.
    Runs Vision API safety check on images.
    Never written to disk — base64 in memory only.
    """
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=415, detail=f"Unsupported media type: {file.content_type}")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")

    # Vision API safety check for images
    if file.content_type.startswith("image/"):
        if not check_media_safety(content):
            raise HTTPException(status_code=400, detail="Media failed safety check")

    encoded = base64.b64encode(content).decode("utf-8")
    return {
        "media_type":  file.content_type,
        "filename":    file.filename,
        "size_bytes":  len(content),
        "base64_data": encoded,
        "privacy":     "Processed in memory and discarded. Nothing stored.",
    }


@app.post("/feedback")
@limiter.limit("30/minute")
async def submit_feedback(request: Request, body: FeedbackRequest):
    if not (1 <= body.fairness_score <= 5):
        raise HTTPException(status_code=400, detail="fairness_score must be 1-5")
    if not (1 <= body.quality_score <= 5):
        raise HTTPException(status_code=400, detail="quality_score must be 1-5")

    shift_score = round(
        (body.fairness_score / 5 * 4)
        + (body.quality_score  / 5 * 4)
        + (2 if body.perspective_new else 0),
        2,
    )

    log_feedback({
        "session_id":      body.session_id,
        "perspective_new": body.perspective_new,
        "fairness_score":  body.fairness_score,
        "quality_score":   body.quality_score,
        "quality_issue":   body.quality_issue,
        "what_shifted":    body.what_shifted,
        "shift_score":     shift_score,
        "ts":              int(time.time()),
    })

    return {"received": True, "session_id": body.session_id, "shift_score": shift_score}


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        reload=False,
        log_level="info",
    )
