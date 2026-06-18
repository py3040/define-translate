/** Shared constants for Define & Translate extension */

const ALLOWED_LANGUAGES = [
  { label: "Arabic", value: "ar" },
  { label: "Chinese (Simplified)", value: "zh-Hans" },
  { label: "Chinese (Traditional)", value: "zh-Hant" },
  { label: "Dutch", value: "nl" },
  { label: "English", value: "en" },
  { label: "French", value: "fr" },
  { label: "German", value: "de" },
  { label: "Hindi", value: "hi" },
  { label: "Italian", value: "it" },
  { label: "Japanese", value: "ja" },
  { label: "Korean", value: "ko" },
  { label: "Portuguese", value: "pt" },
  { label: "Russian", value: "ru" },
  { label: "Spanish", value: "es" },
];

const MAX_SELECTION_LENGTH = 300;
const UNSUPPORTED_URL_KEYWORDS = [
  "login", "log-in", "logon", "log-on",
  "signin", "sign-in", "signon", "sign-on",
  "payment", "checkout"
];

const API_BASE_URL = "https://define-translate.ai-builders.space";

if (typeof window !== "undefined") {
  window.DT_CONSTANTS = {
    ALLOWED_LANGUAGES,
    MAX_SELECTION_LENGTH,
    UNSUPPORTED_URL_KEYWORDS,
    API_BASE_URL,
  };
}
