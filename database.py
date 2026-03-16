"""
The Other Side — Firestore helpers
database.py
"""
import time
from google.cloud import firestore

db = firestore.Client()


def log_feedback(data: dict):
    """Stores user feedback and shift score."""
    db.collection("feedback").document(data["session_id"]).set(data)


def save_session(session_id: str, lens: str, media_type: str):
    """Saves the initial flip request metadata (no input content)."""
    db.collection("sessions").document(session_id).set({
        "session_id": session_id,
        "lens":       lens,
        "media_type": media_type,
        "status":     "processing",
        "ts":         int(time.time()),
    })


def update_session(session_id: str, update: dict):
    """Updates an existing session document."""
    db.collection("sessions").document(session_id).update(update)
