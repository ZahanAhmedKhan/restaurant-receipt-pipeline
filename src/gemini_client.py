"""One place that calls the Gemini API, used by the OCR option and the chatbot.

Gemini models are sometimes overloaded (errors 503 / 504 / 429). Instead of
waiting forever, each call:
    - waits at most TIMEOUT_MS for an answer, with no hidden retries
    - tries the models in GEMINI_MODELS order and uses the first that answers
"""

import logging

from src import config

logger = logging.getLogger(__name__)

TIMEOUT_MS = 10_000      # give up on a busy model after 10 s and try the next one
# Error codes that mean "busy, try another model", not "your request is wrong"
BUSY_CODES = {429, 500, 503, 504}


class GeminiUnavailable(Exception):
    """Every model in the list was busy or failed."""


def model_list():
    """GEMINI_MODEL first, then the fallbacks (no duplicates)."""
    models = [config.GEMINI_MODEL] + list(config.GEMINI_FALLBACK_MODELS)
    unique = []
    for model in models:
        if model and model not in unique:
            unique.append(model)
    return unique


def _client():
    from google import genai
    from google.genai import types
    return genai.Client(
        api_key=config.GEMINI_API_KEY,
        http_options=types.HttpOptions(timeout=TIMEOUT_MS,
                                       retry_options=types.HttpRetryOptions(attempts=1)),
    )


def is_busy_error(error):
    code = getattr(error, "code", None)
    return code in BUSY_CODES or "deadline" in str(error).lower() or "timed out" in str(error).lower()


def generate(contents, generation_config=None, client=None):
    """Return the answer text from the first model that responds."""
    client = client or _client()
    last_error = None
    for model in model_list():
        try:
            response = client.models.generate_content(model=model, contents=contents,
                                                      config=generation_config)
            return response.text
        except Exception as error:
            if not is_busy_error(error) and getattr(error, "code", None) != 404:
                raise                      # a real problem (e.g. bad key): don't hide it
            logger.warning("Gemini model %s unavailable (%s); trying the next one",
                           model, type(error).__name__)
            last_error = error
    raise GeminiUnavailable("all Gemini models are busy right now") from last_error
