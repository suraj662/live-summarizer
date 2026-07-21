"""FastAPI server for live meeting audio ingestion."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, TypedDict
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.auth import get_current_user, verify_firebase_token
from app.config import settings
from app.database import (
    get_transcripts_between,
    get_user_preferences,
    store_summary,
    store_transcript_chunk,
)
from app.transcription import transcribe_audio
from app.summarization import generate_summary


logger = logging.getLogger(__name__)


class Session(TypedDict):
    meeting_id: str
    user_id: str
    audio_buffer: bytearray
    connected_at: float
    next_chunk_start_time: datetime
    audio_chunks_received: int
    total_audio_bytes_received: int


# A connection gets its own session so multiple participants can join one meeting.
sessions: dict[str, Session] = {}
transcription_tasks: set[asyncio.Task[None]] = set()


class SummarizeRequest(BaseModel):
    meeting_id: str = Field(min_length=1)
    duration: float = Field(gt=0, description="Summary window length in minutes")
    from_time: datetime | None = Field(
        default=None, description="Optional start timestamp for the summary window"
    )


class FirebaseAuthenticationMiddleware(BaseHTTPMiddleware):
    """Authentication integration point for HTTP requests.

    Health checks and API documentation are public. All other HTTP routes must
    use a Firebase bearer token. WebSocket authentication is handled separately
    because HTTP middleware does not run for WebSocket connections.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method == "OPTIONS" or request.url.path in {
            "/health",
            "/docs",
            "/openapi.json",
            "/redoc",
        }:
            return await call_next(request)

        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Use an Authorization: Bearer <Firebase ID token> header."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            request.state.user = verify_firebase_token(token)
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=exc.headers,
            )
        return await call_next(request)


app = FastAPI(title="Live Meeting Summarizer API")
app.add_middleware(FirebaseAuthenticationMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/users/me/preferences")
async def user_preferences(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, dict[str, Any]]:
    preferences = await asyncio.to_thread(get_user_preferences, current_user["uid"])
    return {"preferences": preferences}


@app.get("/meetings/{meeting_id}/transcripts")
async def meeting_transcripts(
    meeting_id: str,
    start_dt: datetime,
    end_dt: datetime,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, list[str]]:
    if end_dt < start_dt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="end_dt must be on or after start_dt.",
        )
    chunks = await asyncio.to_thread(
        get_transcripts_between, meeting_id, start_dt, end_dt
    )
    return {"chunks": chunks}


@app.put("/meetings/{meeting_id}/summary")
async def save_meeting_summary(
    meeting_id: str,
    summary_data: dict[str, Any],
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, str]:
    await asyncio.to_thread(store_summary, meeting_id, summary_data)
    return {"status": "stored"}


@app.post("/api/summarize")
async def summarize_meeting(
    request: SummarizeRequest,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """Generate and persist a summary for a transcript time window."""
    if request.from_time is None:
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=request.duration)
    else:
        start_time = request.from_time
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        else:
            start_time = start_time.astimezone(timezone.utc)
        end_time = start_time + timedelta(minutes=request.duration)

    # Check before generation to distinguish a missing transcript from an LLM
    # timeout or malformed model response. generate_summary fetches the chunks
    # itself to keep it useful as a standalone service function.
    chunks = await asyncio.to_thread(
        get_transcripts_between, request.meeting_id, start_time, end_time
    )
    if not any(chunk.strip() for chunk in chunks):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No transcript is available for the requested meeting time range.",
        )

    summary = await asyncio.to_thread(
        generate_summary,
        request.meeting_id,
        start_time,
        end_time,
        request.duration,
    )
    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The local Ollama model could not generate a valid summary.",
        )

    stored_summary = {
        **summary,
        "start_time": start_time,
        "end_time": end_time,
        "duration_minutes": request.duration,
    }
    await asyncio.to_thread(store_summary, request.meeting_id, stored_summary)
    return summary


async def trigger_transcription(
    *,
    meeting_id: str,
    user_id: str,
    audio_pcm: bytes,
    start_time: datetime,
    end_time: datetime,
) -> None:
    """Transcribe and persist one complete audio buffer outside the event loop."""
    try:
        text, confidence = await asyncio.to_thread(
            transcribe_audio, audio_pcm, settings.audio_sample_rate
        )
        if not text:
            logger.debug("No speech detected (meeting=%s, user=%s)", meeting_id, user_id)
            return

        transcript_id = await persist_transcription_chunk(
            meeting_id=meeting_id,
            start_time=start_time,
            end_time=end_time,
            text=text,
            speaker=user_id,
            confidence=confidence,
        )
        logger.info(
            "Stored transcript %s (meeting=%s, user=%s)",
            transcript_id,
            meeting_id,
            user_id,
        )
    except Exception:
        logger.exception(
            "Transcription failed (meeting=%s, user=%s)", meeting_id, user_id
        )


async def persist_transcription_chunk(
    *,
    meeting_id: str,
    start_time: datetime,
    end_time: datetime,
    text: str,
    speaker: str | None = None,
    confidence: float | None = None,
) -> str:
    """Persist a Whisper result without blocking the WebSocket event loop."""
    return await asyncio.to_thread(
        store_transcript_chunk,
        meeting_id,
        start_time,
        end_time,
        text,
        speaker,
        confidence,
    )


def queue_transcription(
    *,
    meeting_id: str,
    user_id: str,
    audio_pcm: bytes,
    start_time: datetime,
    end_time: datetime,
) -> None:
    task = asyncio.create_task(
        trigger_transcription(
            meeting_id=meeting_id,
            user_id=user_id,
            audio_pcm=audio_pcm,
            start_time=start_time,
            end_time=end_time,
        ),
        name=f"transcribe-{meeting_id}-{user_id}",
    )
    transcription_tasks.add(task)
    task.add_done_callback(transcription_tasks.discard)


@app.websocket("/ws/{meeting_id}")
async def meeting_audio_socket(websocket: WebSocket, meeting_id: str) -> None:
    """Accept 16 kHz, mono, signed 16-bit PCM chunks from one participant."""
    user_id = websocket.query_params.get("user_id")
    if not user_id:
        await websocket.close(code=1008, reason="The user_id query parameter is required")
        return

    # TODO: validate a Firebase ID token here before accepting the WebSocket.
    # HTTP middleware does not run for WebSocket connections. Use a short-lived
    # query token or WebSocket subprotocol, then ensure its uid matches user_id.
    await websocket.accept()

    session_id = str(uuid4())
    first_chunk_start_time = datetime.now(timezone.utc)
    sessions[session_id] = {
        "meeting_id": meeting_id,
        "user_id": user_id,
        "audio_buffer": bytearray(),
        "connected_at": asyncio.get_running_loop().time(),
        "next_chunk_start_time": first_chunk_start_time,
        "audio_chunks_received": 0,
        "total_audio_bytes_received": 0,
    }

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break

            audio_chunk = message.get("bytes")
            if not isinstance(audio_chunk, bytes):
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "Only binary PCM audio chunks are supported.",
                    }
                )
                continue

            session = sessions[session_id]
            session["audio_buffer"].extend(audio_chunk)
            session["audio_chunks_received"] += 1
            session["total_audio_bytes_received"] += len(audio_chunk)

            transcription_batches_queued = 0
            while len(session["audio_buffer"]) >= settings.audio_buffer_bytes:
                audio_to_transcribe = bytes(
                    session["audio_buffer"][: settings.audio_buffer_bytes]
                )
                del session["audio_buffer"][: settings.audio_buffer_bytes]
                start_time = session["next_chunk_start_time"]
                end_time = start_time + timedelta(
                    seconds=settings.audio_buffer_seconds
                )
                session["next_chunk_start_time"] = end_time
                queue_transcription(
                    meeting_id=meeting_id,
                    user_id=user_id,
                    audio_pcm=audio_to_transcribe,
                    start_time=start_time,
                    end_time=end_time,
                )
                transcription_batches_queued += 1

            await websocket.send_json(
                {
                    "type": "audio_ack",
                    "meeting_id": meeting_id,
                    "received_bytes": len(audio_chunk),
                    "buffered_bytes": len(session["audio_buffer"]),
                    "buffered_duration_ms": int(
                        len(session["audio_buffer"])
                        / (settings.audio_sample_rate * 2)
                        * 1000
                    ),
                    "transcription_batches_queued": transcription_batches_queued,
                }
            )
    finally:
        sessions.pop(session_id, None)
