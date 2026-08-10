from app.core.config import Settings
from app.core.errors import AppError
from app.services.ai.base import AIProvider
from app.services.ai.mock import MockAIProvider


def get_ai_provider(settings: Settings) -> AIProvider:
    if settings.ai_provider == "mock":
        return MockAIProvider()
    if settings.ai_provider in {"openai", "ollama"}:
        raise AppError(f"Provider '{settings.ai_provider}' is configured but not enabled in this milestone.", "AI_PROVIDER_UNAVAILABLE", 503)
    raise AppError("Unknown AI provider configuration.", "AI_PROVIDER_INVALID", 500)
