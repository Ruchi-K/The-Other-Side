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
import wave
from contextlib import asynccontextmanager
from typing import Optional

import vertexai
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google.adk.cli.fast_api import get_fast_api_app
from google.cloud import storage, texttospeech, firestore
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from vertexai.preview.vision_models import ImageGenerationModel

from agent import ANGLES, root_agent
from guardrails import check_input_guardrail, sanitize_input, validate_output, check_media_safety

# CONFIG
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
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

gcs_client = storage.Client()
tts_client = texttospeech.TextToSpeechClient()
db         = firestore.Client()
limiter = Limiter(key_func=get_remote_address)

# FIXED ADK INITIALIZATION
adk_app = get_fast_api_app(agent_dir=".", web=False)

jobs: dict = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"◐ The Other Side v{APP_VERSION} starting")
    yield
    logger.info("◐ The Other Side shutting down")

app = FastAPI(
    title="The Other Side",
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

# MODELS
class FlipRequest(BaseModel):
    situation: str
    angle: str = "empathy"
    media_type: str = "text"
    session_id: Optional[str] = None

class FeedbackRequest(BaseModel):
    session_id: str
    perspective_new: bool
    fairness_score: int
    quality_score: int
    quality_issue: Optional[str] = None
    what_shifted: Optional[str] = None

class AudioRequest(BaseModel):
    headline: str
    the_other_side: str
    closing_prompt: str
    generation_payload: dict = {}
    angle: str = "empathy"
    session_id: Optional[str] = None

class VideoRequest(BaseModel):
    headline: str
    the_other_side: str
    facts: list = []
    closing_prompt: str
    generation_payload: dict = {}
    angle: str = "empathy"
    session_id: Optional[str] = None

# HELPERS
def upload_to_gcs(content: bytes, content_type: str, extension: str) -> str:
    bucket = gcs_client.bucket(BUCKET_NAME)
    filename = f"outputs/{uuid.uuid4()}.{extension}"
    blob = bucket.blob(filename)
    blob.upload_from_string(content, content_type=content_type)
    return f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"

def generate_images(prompts: list[str]) -> list[bytes]:
    model = ImageGenerationModel.from_pretrained("imagen-3.0-generate-001")
    results = []
    for prompt in prompts:
        try:
            response = model.generate_images(
                prompt=prompt,
                number_of_images=1,
                aspect_ratio="16:9"
            )
            results.append(response.generated_images[0]._image_bytes)
        except Exception as e:
            logger.error(f"Imagen failed: {e}")
    return results

def generate_tts(text: str) -> bytes:
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code="en-US",
        name="en-US-Studio-O"
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3
    )
    response = tts_client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config
    )
    return response.audio_content

# ROUTES
@app.get("/")
async def root():
    return {"service": "The Other Side"}

@app.get("/angles")
async def get_angles():
    return {
        "angles": [
            {"id": key, "label": value["label"], "desc": value["desc"]}
            for key, value in ANGLES.items()
        ]
    }

@app.post("/flip")
@limiter.limit("10/minute")
async def flip(request: Request, body: FlipRequest, background_tasks: BackgroundTasks):
    import httpx

    session_id = body.session_id or str(uuid.uuid4())
    clean_situation = sanitize_input(body.situation)
    user_id = "ruchi"
    prompt = f"Shift {clean_situation} using {body.angle}"

    async with httpx.AsyncClient(timeout=120.0) as client:
        session_url = f"http://localhost:8080/adk/apps/{APP_NAME}/users/{user_id}/sessions/{session_id}"
        await client.post(session_url, json={})

        run_resp = await client.post(
            "http://localhost:8080/adk/run",
            json={
                "app_name": APP_NAME,
                "user_id": user_id,
                "session_id": session_id,
                "new_message": {
                    "role": "user",
                    "parts": [{"text": prompt}]
                },
                "streaming": False
            }
        )
        run_resp.raise_for_status()
        events = run_resp.json()

    final_text = None
    for event in reversed(events):
        content = event.get("content") or {}
        for part in (content.get("parts") or []):
            if part.get("text"):
                final_text = part["text"]
                break
        if final_text:
            break

    if not final_text:
        raise HTTPException(500, "ADK returned no text output")

    try:
        cleaned = final_text.strip()

        if cleaned.startswith("```"):
            cleaned = cleaned.replace("```json", "", 1)
            cleaned = cleaned.replace("```", "")
            cleaned = cleaned.strip()

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            cleaned = cleaned[start:end + 1]

        parsed = json.loads(cleaned)

        facts = parsed.get("facts", [])
        if isinstance(facts, list):
            normalized_facts = []
            for item in facts:
                if isinstance(item, str):
                    normalized_facts.append({
                        "fact": item,
                        "confidence": "moderate",
                        "source_hint": ""
                    })
                elif isinstance(item, dict):
                    normalized_facts.append({
                        "fact": item.get("fact", ""),
                        "confidence": item.get("confidence", "moderate"),
                        "source_hint": item.get("source_hint", "")
                    })
                else:
                    normalized_facts.append({
                        "fact": str(item),
                        "confidence": "moderate",
                        "source_hint": ""
                    })
        else:
            normalized_facts = []

        return {
            "session_id": session_id,
            "perspective": parsed.get("the_other_side") or cleaned,
            "headline": parsed.get("headline"),
            "the_other_side": parsed.get("the_other_side"),
            "facts": normalized_facts,
            "category": parsed.get("category"),
            "media_type": parsed.get("media_type", body.media_type),
            "generation_payload": parsed.get("generation_payload", {}),
            "angle_label": parsed.get("angle_label"),
            "closing_prompt": parsed.get("closing_prompt"),
            "declined": parsed.get("declined", False),
        }
    except Exception:
        return {
            "session_id": session_id,
            "perspective": final_text,
            "media_type": body.media_type,
            "raw_response": final_text,
        }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080))
    )

# -------- MEDIA INGESTION IMPORTS --------
import trafilatura
import subprocess
from urllib.parse import urlparse
import yt_dlp
from google.cloud import speech

# -------- MEDIA INGESTION HELPERS --------

speech_client = speech.SpeechClient()

def extract_article_text(url: str) -> str:
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise Exception("Could not download article")

    text = trafilatura.extract(downloaded)

    if not text:
        raise Exception("Could not extract article text")

    return text


def extract_audio_from_video(video_path: str) -> str:
    audio_path = video_path + ".wav"

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            audio_path,
        ],
        check=True,
    )

    return audio_path


def download_youtube_audio(url: str) -> str:
    output_path = "/tmp/youtube_audio.%(ext)s"

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_path,
        "quiet": True,
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        downloaded = ydl.prepare_filename(info)

    return downloaded


def convert_to_wav(input_path: str) -> str:
    output_path = "/tmp/converted_audio.wav"

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-ar",
            "16000",
            "-ac",
            "1",
            "-f",
            "wav",
            output_path,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    return output_path


def upload_file_to_gcs(local_path: str, extension: str = "wav") -> str:
    bucket = gcs_client.bucket(BUCKET_NAME)
    filename = f"transcripts/{uuid.uuid4()}.{extension}"
    blob = bucket.blob(filename)
    blob.upload_from_filename(local_path)
    return f"gs://{BUCKET_NAME}/{filename}"


def transcribe_audio(audio_file: str) -> str:
    with wave.open(audio_file, "rb") as w:
        sample_rate = w.getframerate()
        frames = w.getnframes()
        duration_seconds = frames / float(sample_rate) if sample_rate else 0

    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=sample_rate,
        language_code="en-US",
    )

    file_size = os.path.getsize(audio_file)

    # Use async for anything over ~55 seconds or larger files
    if duration_seconds <= 55 and file_size <= 9 * 1024 * 1024:
        with open(audio_file, "rb") as f:
            content = f.read()

        audio = speech.RecognitionAudio(content=content)
        response = speech_client.recognize(config=config, audio=audio)
    else:
        gcs_uri = upload_file_to_gcs(audio_file, "wav")
        audio = speech.RecognitionAudio(uri=gcs_uri)
        operation = speech_client.long_running_recognize(config=config, audio=audio)
        response = operation.result(timeout=600)

    transcript = ""

    for result in response.results:
        transcript += result.alternatives[0].transcript + " "

    return transcript.strip()


# -------- MEDIA INGESTION ENDPOINT --------

@app.post("/ingest")
async def ingest(
    situation: str = Form(None),
    url: str = Form(None),
    file: UploadFile = File(None),
):

    if situation:
        text_input = situation

    elif url:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()

        if "youtube.com" in host or "youtu.be" in host:
            audio_path = download_youtube_audio(url)
            wav_path = convert_to_wav(audio_path)
            text_input = transcribe_audio(wav_path)
        else:
            text_input = extract_article_text(url)

    elif file:

        temp_path = f"/tmp/{file.filename}"

        with open(temp_path, "wb") as f:
            f.write(await file.read())

        logger.info(f"ingest upload filename={file.filename} content_type={file.content_type}")

        content_type = (file.content_type or "").lower()
        filename = (file.filename or "").lower()

        if content_type.startswith("video") or filename.endswith((".mp4", ".mov", ".webm", ".mkv")):

            audio_path = extract_audio_from_video(temp_path)
            text_input = transcribe_audio(audio_path)

        elif (
            content_type.startswith("audio")
            or content_type in ("application/octet-stream", "audio/wav", "audio/x-wav")
            or filename.endswith((".wav", ".mp3", ".m4a", ".ogg"))
        ):

            text_input = transcribe_audio(temp_path)

        else:
            raise HTTPException(400, f"Unsupported file type: {file.content_type}")

    else:
        raise HTTPException(400, "No input provided")

    if not text_input or not text_input.strip():
        return {
            "input_summary": "",
            "perspective": "No usable text could be extracted.",
            "full_text_available": False,
            "transcript_length": 0,
        }

    import httpx

    session_id = str(uuid.uuid4())
    user_id = "ruchi"
    angle = "empathy"
    clean_situation = sanitize_input(text_input[:4000])
    prompt = f"Shift {clean_situation} using {angle}"

    async with httpx.AsyncClient(timeout=120.0) as client:
        session_url = f"http://localhost:8080/adk/apps/{APP_NAME}/users/{user_id}/sessions/{session_id}"
        await client.post(session_url, json={})

        run_resp = await client.post(
            "http://localhost:8080/adk/run",
            json={
                "app_name": APP_NAME,
                "user_id": user_id,
                "session_id": session_id,
                "new_message": {
                    "role": "user",
                    "parts": [{"text": prompt}]
                },
                "streaming": False
            }
        )
        run_resp.raise_for_status()
        events = run_resp.json()

    final_text = None
    for event in reversed(events):
        content = event.get("content") or {}
        for part in (content.get("parts") or []):
            if part.get("text"):
                final_text = part["text"]
                break
        if final_text:
            break

    if not final_text:
        raise HTTPException(500, "ADK returned no text output")

    try:
        cleaned = final_text.strip()

        if cleaned.startswith("```"):
            cleaned = cleaned.replace("```json", "", 1)
            cleaned = cleaned.replace("```", "")
            cleaned = cleaned.strip()

        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1:
            cleaned = cleaned[start:end + 1]

        parsed = json.loads(cleaned)

        facts = parsed.get("facts", [])
        if isinstance(facts, list):
            normalized_facts = []
            for item in facts:
                if isinstance(item, str):
                    normalized_facts.append({
                        "fact": item,
                        "confidence": "moderate",
                        "source_hint": ""
                    })
                elif isinstance(item, dict):
                    normalized_facts.append({
                        "fact": item.get("fact", ""),
                        "confidence": item.get("confidence", "moderate"),
                        "source_hint": item.get("source_hint", "")
                    })
                else:
                    normalized_facts.append({
                        "fact": str(item),
                        "confidence": "moderate",
                        "source_hint": ""
                    })
        else:
            normalized_facts = []

        return {
            "session_id": session_id,
            "input_summary": text_input[:500],
            "full_text_available": True,
            "transcript_length": len(text_input or ""),
            "perspective": parsed.get("the_other_side") or cleaned,
            "headline": parsed.get("headline"),
            "the_other_side": parsed.get("the_other_side"),
            "facts": normalized_facts,
            "category": parsed.get("category"),
            "media_type": parsed.get("media_type", "text"),
            "generation_payload": parsed.get("generation_payload", {}),
            "angle_label": parsed.get("angle_label"),
            "closing_prompt": parsed.get("closing_prompt"),
            "declined": parsed.get("declined", False),
        }
    except Exception:
        return {
            "session_id": session_id,
            "input_summary": text_input[:500],
            "full_text_available": True,
            "transcript_length": len(text_input or ""),
            "perspective": final_text,
            "media_type": "text",
            "raw_response": final_text,
        }

