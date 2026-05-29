"""Request fingerprint for cache key per TR-1.01-12."""

import base64
import hmac
import hashlib
import json


def compute_fingerprint(
    selected_text_norm: str,
    full_context_norm: str | None,
    target_language_norm: str | None,
    mode: str,
    fingerprint_secret: str,
) -> str:
    """
    Base64URL(HMAC-SHA256) over canonical JSON.
    Key order: selected_text_norm, full_context_norm, target_language_norm, mode.
    Mode is included so translation_only and meaning_and_translation cache entries
    do not collide (translation_only returns no meaning).
    """
    payload = {
        "selected_text_norm": selected_text_norm,
        "full_context_norm": full_context_norm,
        "target_language_norm": target_language_norm,
        "mode": mode,
    }
    canonical_json = json.dumps(payload, separators=(",", ":"), sort_keys=False)
    canonical_bytes = canonical_json.encode("utf-8")
    sig = hmac.new(
        fingerprint_secret.encode("utf-8"),
        canonical_bytes,
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")
