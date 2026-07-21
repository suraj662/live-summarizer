"""Generate structured meeting summaries with a local Ollama model."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from functools import lru_cache
from typing import Any, Mapping

import httpx
import ollama

from app.config import settings
from app.database import get_transcripts_between


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_ollama_client() -> ollama.Client:
    """Reuse one locally configured Ollama HTTP client."""
    return ollama.Client(
        host=settings.ollama_base_url,
        timeout=settings.ollama_request_timeout_seconds,
    )


def _response_content(response: Any) -> str:
    """Read chat text from both mapping and typed ollama-python responses."""
    if isinstance(response, Mapping):
        message = response.get("message")
        if isinstance(message, Mapping):
            content = message.get("content")
            return content if isinstance(content, str) else ""

    message = getattr(response, "message", None)
    content = getattr(message, "content", None)
    return content if isinstance(content, str) else ""


def _validated_summary(content: str) -> dict[str, Any] | None:
    if not content.strip():
        return None

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict) or not isinstance(data.get("summary"), str):
        return None
    if not isinstance(data.get("key_points"), list) or not isinstance(
        data.get("action_items"), list
    ):
        return None

    key_points = [item.strip() for item in data["key_points"] if isinstance(item, str)]
    action_items = [item.strip() for item in data["action_items"] if isinstance(item, str)]
    if len(key_points) != len(data["key_points"]) or len(action_items) != len(
        data["action_items"]
    ):
        return None

    return {
        "summary": data["summary"].strip(),
        "key_points": key_points,
        "action_items": action_items,
    }


def generate_summary(
    meeting_id: str,
    start_time: datetime,
    end_time: datetime,
    duration_minutes: float,
) -> dict[str, Any] | None:
    """Return a structured local-LLM summary, or ``None`` when unavailable."""
    try:
        chunks = get_transcripts_between(meeting_id, start_time, end_time)
        transcript = "\n".join(chunk.strip() for chunk in chunks if chunk.strip())
        if not transcript:
            return None

        prompt = f"""Summarize this meeting segment.

Meeting ID: {meeting_id}
Time range: {start_time.isoformat()} to {end_time.isoformat()}
Duration: {duration_minutes:g} minutes

Transcript:
---
{transcript}
---

Return only one valid JSON object with exactly these keys:
{{
  \"summary\": \"concise meeting summary\",
  \"key_points\": [\"key decision or discussion point\"],
  \"action_items\": [\"action item, including an owner when stated\"]
}}
Use empty arrays when there are no key points or action items. Do not add markdown."""

        response = get_ollama_client().chat(
            model=settings.ollama_model,
            messages=[
                {
                    "role": "system",
                    "content": "You create accurate, concise structured meeting summaries.",
                },
                {"role": "user", "content": prompt},
            ],
            format="json",
            options={"temperature": 0},
            stream=False,
        )
        summary = _validated_summary(_response_content(response))
        if summary is None:
            logger.warning("Ollama returned an empty or invalid summary for %s", meeting_id)
        return summary
    except (ollama.ResponseError, httpx.HTTPError, TimeoutError, ValueError) as exc:
        logger.warning("Unable to generate summary for %s: %s", meeting_id, exc)
        return None
    except Exception:
        logger.exception("Unexpected summary generation failure for %s", meeting_id)
        return None
