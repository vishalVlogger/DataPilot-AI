from contextvars import ContextVar
from typing import Any

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


def current_request_id() -> str | None:
    return request_id_context.get()


def initialize_sentry(dsn: str | None, environment: str) -> bool:
    if not dsn: return False
    try:
        import sentry_sdk
        def scrub(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
            request = event.get("request", {})
            request.pop("data", None); request.pop("cookies", None)
            if "headers" in request:
                request["headers"] = {key: value for key, value in request["headers"].items() if key.casefold() not in {"authorization", "cookie"}}
            return event
        sentry_sdk.init(dsn=dsn, environment=environment, send_default_pii=False, before_send=scrub)
        return True
    except ImportError:
        return False
