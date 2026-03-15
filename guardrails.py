"""
The Other Side — Safety & Guardrails
guardrails.py — Input / Output Validation
"""
import re
import logging
from google.cloud import vision
import vertexai
from vertexai.generative_models import GenerativeModel

logger = logging.getLogger("tos-guardrails")

# ─────────────────────────────────────────────────────────────
# 1. INPUT SANITIZATION — PII masking + injection blocking
# ─────────────────────────────────────────────────────────────

def sanitize_input(text: str) -> str:
    """Removes PII and blocks common prompt injection patterns."""
    text = re.sub(r'\S+@\S+', '[EMAIL]', text)
    text = re.sub(r'\d{3}[-.\s]\d{3}[-.\s]\d{4}', '[PHONE]', text)

    injection_patterns = [
        r"ignore all previous",
        r"system prompt",
        r"developer mode",
        r"jailbreak",
        r"output as a poem only",
        r"disregard your instructions",
    ]
    for pattern in injection_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            logger.warning(f"Injection pattern detected: {pattern}")
            raise ValueError("Input contains prohibited system override commands.")

    return text.strip()


# ─────────────────────────────────────────────────────────────
# 2. MEDIA SAFETY — Vision API safe search
# ─────────────────────────────────────────────────────────────

def check_media_safety(file_bytes: bytes) -> bool:
    """
    Checks images/video frames for adult, violent, or racy content.
    Returns True if safe, False if unsafe.
    """
    try:
        client = vision.ImageAnnotatorClient()
        image = vision.Image(content=file_bytes)
        response = client.safe_search_detection(image=image)
        safe = response.safe_search_annotation

        # Block if LIKELY (4) or VERY_LIKELY (5)
        if any(attr >= 4 for attr in [safe.adult, safe.violence, safe.racy]):
            logger.warning(
                f"Unsafe media: adult={safe.adult} "
                f"violence={safe.violence} racy={safe.racy}"
            )
            return False
        return True
    except Exception as e:
        logger.error(f"Vision API check failed: {e}")
        return False  # Fail closed


# ─────────────────────────────────────────────────────────────
# 3. OUTPUT TOXICITY SCORING — Gemini Flash Lite
# ─────────────────────────────────────────────────────────────

def rate_toxicity(text_output: str) -> int:
    """
    Rates output toxicity 0-10 using Gemini Flash Lite.
    Used as the final gate before showing results to the user.
    Returns 10 (block) if the scan itself fails.
    """
    try:
        rater = GenerativeModel("gemini-2.0-flash-lite")
        prompt = f"""
Rate the toxicity of the following text on a scale of 0 to 10.
Criteria: targeted harm, hate speech, radicalization, or dangerous misinformation.
0 = completely safe. 10 = extremely harmful.
Respond with only the integer.

Text: "{text_output}"
""".strip()
        response = rater.generate_content(prompt)
        score = int(response.text.strip())
        logger.info(f"Toxicity score: {score}")
        return max(0, min(10, score))  # Clamp to 0-10
    except Exception as e:
        logger.error(f"Toxicity scan failed: {e}")
        return 10  # Fail closed


# ─────────────────────────────────────────────────────────────
# 4. OUTPUT VALIDATION — structure + safety
# ─────────────────────────────────────────────────────────────

def validate_output(agent_json: dict) -> tuple[bool, str]:
    """
    Final check before result is returned to the user.
    Returns (is_valid, reason).
    """
    required_keys = ["headline", "the_other_side", "facts", "media_type", "closing_prompt"]
    for key in required_keys:
        if key not in agent_json:
            return False, f"Missing required field: {key}"

    text_to_check = (
        f"{agent_json.get('headline', '')} "
        f"{agent_json.get('the_other_side', '')}"
    )

    score = rate_toxicity(text_to_check)
    if score > 3:
        return False, "This one's outside what I can help with — the output didn't pass our safety check."

    return True, "ok"


# ─────────────────────────────────────────────────────────────
# 5. SIMPLE TEXT GUARDRAIL — fast keyword scan (Layer 1)
# ─────────────────────────────────────────────────────────────

def check_input_guardrail(text: str) -> dict:
    """
    Fast Layer 1 check — runs before the ADK agent is called.
    Returns {"safe": bool, "reason": str}.
    """
    blocked_patterns = [
        (r"\b(kill|murder|bomb|shoot)\b.{0,30}\b(person|people|human)\b", "promotes violence"),
        (r"\b(child|minor|underage)\b.{0,20}\b(sex|nude|naked|porn)\b", "CSAM"),
        (r"\b(make|build|create|synthesize)\b.{0,20}\b(weapon|explosive|drug)\b", "dangerous instructions"),
    ]
    text_lower = text.lower()
    for pattern, reason in blocked_patterns:
        if re.search(pattern, text_lower, re.IGNORECASE):
            logger.warning(f"Layer 1 guardrail triggered: {reason}")
            return {
                "safe": False,
                "reason": f"This one's outside what I can help with. ({reason})",
            }

    if len(text) > 4000:
        return {"safe": False, "reason": "Input is too long. Please keep it under 4000 characters."}

    return {"safe": True, "reason": ""}
