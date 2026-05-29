"""AI Builder Space client - POST /v1/chat/completions."""

import json
import re
import httpx
from app.config import Settings

MAX_COMPLETION_TOKENS = 250  # Requested from API; models may exceed this
MAX_CONTENT_CHARS = 500  # Max chars per meaning/translation; validates actual content

# Language label map for prompts (target_language is BCP-47, we need display name for prompt)
LANGUAGE_LABELS = {
    "ar": "Arabic",
    "zh-Hans": "Chinese (Simplified)",
    "zh-Hant": "Chinese (Traditional)",
    "nl": "Dutch",
    "en": "English",
    "fr": "French",
    "de": "German",
    "hi": "Hindi",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "pt": "Portuguese",
    "ru": "Russian",
    "es": "Spanish",
}


def _build_prompt(
    mode: str,
    selected_text_norm: str,
    full_context_norm: str | None,
    target_language_norm: str | None,
) -> str:
    """Build mode-specific prompt per TR-1.02-04c."""
    # Only add context when it differs from selection and adds useful info
    has_context = bool(
        full_context_norm
        and full_context_norm.strip()
        and full_context_norm.strip() != selected_text_norm.strip()
        and len(selected_text_norm) < 300
    )
    context_part = f" (surrounding context: {full_context_norm})" if has_context else ""
    lang_label = LANGUAGE_LABELS.get(
        target_language_norm or "", target_language_norm or ""
    )

    # Explicit instruction to treat selection as a whole, not substrings
    prefix = "The user selected the following text. Treat it as a single unit. "
    if mode == "meaning_only":
        return f"{prefix}Explain its meaning in plain English (<=80 tokens){context_part}.\n\nSelected text: {selected_text_norm}."

    if mode == "translation_only":
        return f"{prefix}Translate it to {lang_label} (<=80 tokens){context_part}.\n\nSelected text: {selected_text_norm}."

    if mode == "meaning_and_translation":
        return f"{prefix}Explain its meaning in plain English (<=80 tokens) and translate to {lang_label} (<=80 tokens){context_part}.\n\nSelected text: {selected_text_norm}."

    raise ValueError(f"Unknown mode: {mode}")


def _build_messages(mode: str, prompt: str) -> list[dict]:
    """Build messages array with system + user."""
    schema_hint = ""
    if mode == "meaning_only":
        schema_hint = ' Return a JSON object with a single key "meaning" (string).'
    elif mode == "translation_only":
        schema_hint = ' Return a JSON object with a single key "translation" (string).'
    else:
        schema_hint = ' Return a JSON object with keys "meaning" (string) and "translation" (string).'

    system = (
        "Return ONLY valid JSON as your response. No preamble, no explanation, no markdown, no code fences. "
        f"Start your response with {{ and end with }}.{schema_hint}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]


def _extract_json(content: str) -> str:
    """Extract JSON object from content that may have markdown fences or surrounding text."""
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    # If content has text before JSON, try to extract {...}
    if not content.startswith("{"):
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            content = match.group(0)
    return content


def _parse_response(mode: str, content: str) -> dict:
    """Parse and validate AI response JSON per TR-1.03-04."""
    content = _extract_json(content)
    parsed = json.loads(content)

    result = {"meaning": None, "translation": None}
    if mode == "meaning_only":
        if "meaning" not in parsed or not isinstance(parsed["meaning"], str):
            raise ValueError("missing or invalid meaning")
        result["meaning"] = parsed["meaning"]
    elif mode == "translation_only":
        if "translation" not in parsed or not isinstance(parsed["translation"], str):
            raise ValueError("missing or invalid translation")
        result["translation"] = parsed["translation"]
    else:
        if "meaning" not in parsed or not isinstance(parsed["meaning"], str):
            raise ValueError("missing or invalid meaning")
        if "translation" not in parsed or not isinstance(parsed["translation"], str):
            raise ValueError("missing or invalid translation")
        result["meaning"] = parsed["meaning"]
        result["translation"] = parsed["translation"]
    return result


async def call_ai_builder_space(
    settings: Settings,
    selected_text_norm: str,
    full_context_norm: str | None,
    target_language_norm: str | None,
    mode: str,
    server_request_id: str,
) -> tuple[dict, float]:
    """
    Call AI Builder Space /v1/chat/completions.
    Returns (payload, elapsed_seconds). Payload has meaning, translation, server_request_id.
    Raises on error - caller maps to appropriate HTTP error response.
    """
    base_url = settings.ai_builder_base_url.rstrip("/")
    if "/v1" not in base_url:
        base_url = f"{base_url}/v1"
    url = f"{base_url}/chat/completions"

    prompt = _build_prompt(
        mode, selected_text_norm, full_context_norm, target_language_norm
    )
    messages = _build_messages(mode, prompt)

    payload = {
        "model": "deepseek",
        "messages": messages,
        "max_tokens": MAX_COMPLETION_TOKENS,
        "temperature": 0.2,
        "stream": False,
        "tool_choice": "none",
        "user": server_request_id,
    }

    async with httpx.AsyncClient(timeout=settings.ai_builder_timeout_sec) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.ai_builder_token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    ai_builder_elapsed_sec = response.elapsed.total_seconds()

    if response.status_code == 401 or response.status_code == 403:
        raise UpstreamAuthError(response.status_code, upstream_body=response.text[:200])
    if response.status_code == 429:
        raise UpstreamRateLimitedError(response.status_code, upstream_body=response.text[:200])
    if response.status_code == 504:
        raise UpstreamTimeoutError(response.status_code, upstream_body=response.text[:200])
    if 500 <= response.status_code < 600:
        raise UpstreamError(response.status_code, upstream_body=response.text[:200])
    if response.status_code in (400, 422):
        raise UpstreamRequestFailedError(response.status_code, upstream_body=response.text[:200])
    if 400 <= response.status_code < 500:
        raise UpstreamClientError(response.status_code, upstream_body=response.text[:200])
    if response.status_code != 200:
        raise UpstreamError(response.status_code, upstream_body=response.text[:200])

    data = response.json()
    usage = data.get("usage", {})
    choices = data.get("choices", [])
    if not choices:
        raise UpstreamResponseInvalidError(
            response.status_code,
            upstream_body=json.dumps(data, ensure_ascii=False)[:500],
        )
    content = choices[0].get("message", {}).get("content")
    if not content:
        raise UpstreamResponseInvalidError(
            response.status_code,
            upstream_body=str(choices[0])[:200],
        )

    try:
        parsed = _parse_response(mode, content)
    except (json.JSONDecodeError, ValueError) as e:
        raise UpstreamResponseInvalidError(
            response.status_code,
            upstream_body=f"parse_error: {type(e).__name__}: {e}",
        ) from e

    # Validate content length (models may exceed max_tokens; we validate actual output)
    for key in ("meaning", "translation"):
        val = parsed.get(key)
        if val is not None and len(val) > MAX_CONTENT_CHARS:
            raise UpstreamResponseTooLongError()

    payload = {
        "meaning": parsed.get("meaning"),
        "translation": parsed.get("translation"),
        "server_request_id": server_request_id,
    }
    return (payload, ai_builder_elapsed_sec)


class _UpstreamBase(Exception):
    """Base for all upstream errors.  Carries the HTTP status and raw
    response body returned by AI Builder Space so callers can include
    them in the structured error log."""

    def __init__(self, status_code: int | None = None, upstream_body: str | None = None) -> None:
        super().__init__()
        self.status_code = status_code
        self.upstream_body = upstream_body


class UpstreamAuthError(_UpstreamBase):
    pass


class UpstreamRateLimitedError(_UpstreamBase):
    pass


class UpstreamTimeoutError(_UpstreamBase):
    pass


class UpstreamError(_UpstreamBase):
    pass


class UpstreamRequestFailedError(_UpstreamBase):
    pass


class UpstreamClientError(_UpstreamBase):
    pass


class UpstreamResponseInvalidError(_UpstreamBase):
    pass


class UpstreamResponseTooLongError(_UpstreamBase):
    pass
