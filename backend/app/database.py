"""Firestore access helpers for meetings, transcripts, summaries, and users."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.config import BACKEND_DIR, settings


def initialize_firebase() -> firebase_admin.App:
    """Return the default Firebase app, creating it from configured credentials."""
    try:
        return firebase_admin.get_app()
    except ValueError:
        pass

    if settings.firebase_service_account_json:
        try:
            service_account = json.loads(settings.firebase_service_account_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON") from exc
        return firebase_admin.initialize_app(credentials.Certificate(service_account))

    if settings.firebase_service_account_path:
        service_account_path = Path(settings.firebase_service_account_path).expanduser()
        if not service_account_path.is_absolute():
            service_account_path = BACKEND_DIR / service_account_path
        return firebase_admin.initialize_app(credentials.Certificate(service_account_path))

    # This supports credentials supplied by a cloud runtime's default identity.
    return firebase_admin.initialize_app()


@lru_cache
def get_firestore_client() -> Any:
    initialize_firebase()
    return firestore.client()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def store_transcript_chunk(
    meeting_id: str,
    start_time: datetime,
    end_time: datetime,
    text: str,
    speaker: str | None,
    confidence: float | None,
) -> str:
    """Persist one finalized transcription chunk and return its document ID."""
    db = get_firestore_client()
    now = datetime.now(timezone.utc)

    # Keep an inexpensive meeting document for listing and future access checks.
    db.collection("meetings").document(meeting_id).set(
        {"updated_at": now}, merge=True
    )

    document = db.collection("transcripts").document()
    document.set(
        {
            "meeting_id": meeting_id,
            "start_time": _as_utc(start_time),
            "end_time": _as_utc(end_time),
            "text": text,
            "speaker": speaker,
            "confidence": confidence,
            "created_at": now,
        }
    )
    return document.id


def get_transcripts_between(
    meeting_id: str, start_dt: datetime, end_dt: datetime
) -> list[str]:
    """Return transcript texts whose complete interval lies in the requested range."""
    if end_dt < start_dt:
        raise ValueError("end_dt must be on or after start_dt")

    query = (
        get_firestore_client()
        .collection("transcripts")
        .where(filter=FieldFilter("meeting_id", "==", meeting_id))
        .where(filter=FieldFilter("start_time", ">=", _as_utc(start_dt)))
        .where(filter=FieldFilter("end_time", "<=", _as_utc(end_dt)))
        .order_by("start_time")
    )
    return [
        data["text"]
        for snapshot in query.stream()
        if (data := snapshot.to_dict()) and isinstance(data.get("text"), str)
    ]


def store_summary(meeting_id: str, summary_data: dict[str, Any]) -> None:
    """Create or update the current summary document for a meeting."""
    now = datetime.now(timezone.utc)
    payload = dict(summary_data)
    payload.update({"meeting_id": meeting_id, "updated_at": now})

    db = get_firestore_client()
    db.collection("meetings").document(meeting_id).set(
        {"updated_at": now}, merge=True
    )
    db.collection("summaries").document(meeting_id).set(payload, merge=True)


def get_user_preferences(user_id: str) -> dict[str, Any]:
    """Return a user's ``preferences`` object, or an empty object if absent."""
    snapshot = get_firestore_client().collection("users").document(user_id).get()
    if not snapshot.exists:
        return {}

    preferences = (snapshot.to_dict() or {}).get("preferences", {})
    return dict(preferences) if isinstance(preferences, dict) else {}
