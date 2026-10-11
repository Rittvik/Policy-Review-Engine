"""Opt-in Gemini transport for advisory extraction; imported without SDK or key."""

import json
import os
import random
import re
import time

from .llm import AdapterUnavailable, ModelCall


MODEL = "gemini-3.5-flash-lite"
MAX_REQUEST_BYTES = 65_536
MAX_RESPONSE_BYTES = 65_536
# Only transient provider conditions are retried. Validation failures, blocked or
# incomplete responses and client errors (400/401/403/404) are never retried.
TRANSIENT_REASONS = frozenset({"gemini_rate_limited", "gemini_server_error",
                               "gemini_timeout", "gemini_connection_failed"})
DEFAULT_MAX_RETRIES = 3
DEFAULT_MAX_RETRY_WAIT_SECONDS = 90.0


class _Transient(Exception):
    def __init__(self, reason, delay=None):
        super().__init__(reason)
        self.reason, self.delay = reason, delay


def _env_number(name, default, cast):
    try:
        return max(0, cast(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _retry_delay(exc):
    """Provider-suggested wait from google.rpc.RetryInfo or Retry-After, if any."""
    try:
        details = exc.details.get("error", exc.details) if isinstance(exc.details, dict) else {}
        for item in details.get("details") or ():
            if isinstance(item, dict) and str(item.get("@type", "")).endswith("RetryInfo"):
                match = re.fullmatch(r"(\d+(?:\.\d+)?)s", str(item.get("retryDelay", "")))
                if match:
                    return float(match[1])
        header = exc.response.headers.get("retry-after") if exc.response is not None else None
        return float(header) if header else None
    except Exception:
        return None


class GeminiAdapter:
    """One logical request per extraction, with no tools.

    Transient provider failures (rate limit, 5xx, timeout, connection) are retried
    a bounded number of times, honouring the provider's suggested delay, within a
    capped total wait. Configure with GEMINI_MAX_RETRIES (default 3, 0 disables)
    and GEMINI_MAX_RETRY_WAIT_SECONDS (default 90). Construction does not read
    credentials or create a client. Only an explicit generate call reads
    GEMINI_API_KEY. extract_candidates sanitizes failures and applies the shared
    schema/provenance checks to the returned JSON; invalid output is not retried.
    """

    adapter_id = "gemini:" + MODEL

    def __init__(self, *, max_retries=None, max_retry_wait=None, sleep=time.sleep):
        self._max_retries = max_retries
        self._max_retry_wait = max_retry_wait
        self._sleep = sleep

    def generate(self, call: ModelCall) -> str:
        if sum(len(value.encode("utf-8")) for value in (
            call.instruction, call.payload_json, call.response_schema_json
        )) > MAX_REQUEST_BYTES:
            raise AdapterUnavailable("request_too_large")
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise AdapterUnavailable("missing_gemini_key")
        try:
            from google import genai
            from google.genai import types
            from google.genai import errors
            import httpx
        except ImportError:
            raise AdapterUnavailable("gemini_extra_not_installed") from None

        retries = self._max_retries if self._max_retries is not None else _env_number(
            "GEMINI_MAX_RETRIES", DEFAULT_MAX_RETRIES, int)
        budget = self._max_retry_wait if self._max_retry_wait is not None else _env_number(
            "GEMINI_MAX_RETRY_WAIT_SECONDS", DEFAULT_MAX_RETRY_WAIT_SECONDS, float)
        waited = 0.0
        for attempt in range(retries + 1):
            try:
                return self._attempt(call, api_key, genai, types, errors, httpx)
            except _Transient as failure:
                backoff = failure.delay if failure.delay is not None else 2.0 * 2 ** attempt
                delay = backoff + random.uniform(0, 1)
                # A long provider delay (e.g. exhausted daily quota) will not clear here.
                if attempt == retries or delay > 60.0 or waited + delay > budget:
                    raise AdapterUnavailable(failure.reason) from None
                self._sleep(delay)
                waited += delay
        raise AdapterUnavailable("gemini_request_failed")  # pragma: no cover

    def _attempt(self, call, api_key, genai, types, errors, httpx) -> str:
        try:
            # Explicit provider, endpoint, and key avoid SDK environment defaults
            # selecting Vertex AI, another key, or a custom base URL.
            with genai.Client(
                api_key=api_key, vertexai=False,
                http_options=types.HttpOptions(
                    api_version="v1beta",
                    base_url="https://generativelanguage.googleapis.com",
                    timeout=60_000,
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            ) as client:
                response = client.models.generate_content(
                    model=MODEL,
                    contents=call.payload_json,
                    config=types.GenerateContentConfig(
                        system_instruction=call.instruction,
                        response_mime_type="application/json",
                        response_json_schema=json.loads(call.response_schema_json),
                        candidate_count=1,
                        max_output_tokens=4096,
                        thinking_config=types.ThinkingConfig(thinking_level="LOW", include_thoughts=False),
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    ),
                )
            feedback = response.prompt_feedback
            if feedback and feedback.block_reason and feedback.block_reason.value != "BLOCK_REASON_UNSPECIFIED":
                raise AdapterUnavailable("blocked_response")
            candidates = response.candidates or []
            if len(candidates) != 1 or candidates[0].finish_reason != types.FinishReason.STOP:
                raise AdapterUnavailable("incomplete_response")
            content = candidates[0].content
            parts = content.parts if content else None
            if not parts:
                raise AdapterUnavailable("empty_response")
            texts = []
            for part in parts:
                # Do not silently discard tool calls, thoughts, or other output.
                fields = part.model_dump(exclude_none=True)
                # A thought signature is opaque provider metadata, not a finding.
                # Do not return or persist it. Tool/nontext/thought output still fails.
                if fields.keys() - {"text", "thought", "thought_signature"} or part.thought or not part.text:
                    raise AdapterUnavailable("unexpected_response_part")
                texts.append(part.text)
            raw = "".join(texts)
            if not raw.strip() or len(raw.encode("utf-8")) > MAX_RESPONSE_BYTES:
                raise AdapterUnavailable("empty_or_oversized_response")
            return raw
        except AdapterUnavailable:
            raise
        except errors.APIError as exc:
            code = {
                400: "gemini_invalid_request", 401: "gemini_authentication_failed",
                403: "gemini_permission_denied", 404: "gemini_model_not_found",
                429: "gemini_rate_limited",
            }.get(exc.code, "gemini_server_error" if isinstance(exc.code, int) and exc.code >= 500 else "gemini_request_failed")
            if code in TRANSIENT_REASONS:
                raise _Transient(code, _retry_delay(exc)) from None
            raise AdapterUnavailable(code) from None
        except httpx.TimeoutException:
            raise _Transient("gemini_timeout") from None
        except httpx.RequestError:
            raise _Transient("gemini_connection_failed") from None
        except Exception:
            # Provider errors can contain request bodies or credential details.
            raise AdapterUnavailable("gemini_request_failed") from None
