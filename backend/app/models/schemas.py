"""Pydantic request/response models."""

from pydantic import BaseModel, Field, field_validator, model_validator
import re

ALLOWED_LANGUAGES = {
    "ar", "zh-Hans", "zh-Hant", "nl", "en", "fr", "de", "hi",
    "it", "ja", "ko", "pt", "ru", "es"
}

UNSUPPORTED_URL_KEYWORDS = [
    "login", "log-in", "logon", "log-on",
    "signin", "sign-in", "signon", "sign-on",
    "payment", "checkout"
]

UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE
)


def is_valid_uuid(u: str) -> bool:
    return bool(UUID_PATTERN.match(u)) if u else False


class LookupRequest(BaseModel):
    client_request_id: str
    install_id: str
    selected_text: str
    full_context: str | None = None
    target_language: str | None = None
    mode: str
    page_url: str
    extension_version: str

    @field_validator("client_request_id")
    @classmethod
    def validate_client_request_id(cls, v: str) -> str:
        if not v or not is_valid_uuid(v):
            raise ValueError("client_request_id must be a valid UUID v4")
        return v

    @field_validator("install_id")
    @classmethod
    def validate_install_id(cls, v: str) -> str:
        if not v or not is_valid_uuid(v):
            raise ValueError("install_id must be a valid UUID v4")
        return v

    @field_validator("selected_text")
    @classmethod
    def validate_selected_text(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("selected_text cannot be empty")
        if len(v) > 300:
            raise ValueError("selected_text exceeds 300 chars")
        return v

    @field_validator("full_context")
    @classmethod
    def validate_full_context(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 300:
            raise ValueError("full_context exceeds 300 chars")
        return v

    @model_validator(mode="after")
    def full_context_contains_selected_text(self):
        if self.full_context and self.full_context.strip() and self.selected_text not in self.full_context:
            raise ValueError("full_context must contain selected_text when non-empty")
        return self

    @field_validator("target_language")
    @classmethod
    def validate_target_language(cls, v: str | None) -> str | None:
        if v is not None and v.strip():
            v_norm = v.strip()
            if v_norm not in ALLOWED_LANGUAGES:
                raise ValueError("target_language not in allowed set")
            return v_norm
        return None

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        if v not in ("meaning_only", "translation_only", "meaning_and_translation"):
            raise ValueError("mode must be one of meaning_only, translation_only, meaning_and_translation")
        return v

    @field_validator("page_url")
    @classmethod
    def validate_page_url(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("page_url cannot be empty")
        if not v.lower().startswith("https://"):
            raise ValueError("page_url must be HTTPS")
        v_lower = v.lower()
        for kw in UNSUPPORTED_URL_KEYWORDS:
            if kw in v_lower:
                raise ValueError("page_url contains unsupported keyword")
        return v

    @field_validator("extension_version")
    @classmethod
    def validate_extension_version(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("extension_version cannot be empty")
        return v


class LookupSuccessResponse(BaseModel):
    meaning: str | None = None
    translation: str | None = None
    server_request_id: str


class LookupErrorResponse(BaseModel):
    error_code: str
    error_message: str
    server_request_id: str
