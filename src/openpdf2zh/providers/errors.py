from __future__ import annotations

from typing import Any

from openai import APIStatusError, RateLimitError


def is_rate_limited_error(exc: Exception) -> bool:
    return isinstance(exc, RateLimitError) or (
        isinstance(exc, APIStatusError) and getattr(exc, "status_code", None) == 429
    )


def build_rate_limit_message(
    exc: Exception,
    *,
    route_name: str,
    model: str,
) -> str:
    body = getattr(exc, "body", None)
    error_body = body if isinstance(body, dict) else {}
    metadata = _metadata_from_error_body(error_body)
    upstream_provider = str(metadata.get("provider_name", "")).strip()
    raw_detail = str(metadata.get("raw", "")).strip()
    request_id = str(getattr(exc, "request_id", "") or "").strip()
    retry_after = _retry_after_hint(exc)

    route_label = route_name
    if upstream_provider:
        route_label = f"{route_name} → upstream {upstream_provider}"

    parts = [f"{route_label} rate-limited the model '{model}'."]
    if retry_after:
        parts.append(f"Retry after about {retry_after}.")
    else:
        parts.append("Please retry shortly.")
    if raw_detail:
        parts.append(f"Detail: {raw_detail}")
    if request_id:
        parts.append(f"Request ID: {request_id}")
    parts.append(
        "You can also switch to a different provider or model, or use your own provider key/integration limits if available."
    )
    return " ".join(parts)


def _metadata_from_error_body(error_body: dict[str, Any]) -> dict[str, Any]:
    metadata = error_body.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _retry_after_hint(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""

    retry_after = headers.get("retry-after") or headers.get("x-ratelimit-reset")
    return str(retry_after).strip() if retry_after else ""
