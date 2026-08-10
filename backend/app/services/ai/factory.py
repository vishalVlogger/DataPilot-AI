from app.core.config import Settings
from app.core.errors import AppError
from app.services.ai.base import AIProvider
from app.services.ai.mock import MockAIProvider
from app.services.ai.ollama import OllamaProvider
from app.services.ai.openai import OpenAIProvider


def get_ai_provider(settings: Settings) -> AIProvider:
    if settings.ai_provider == "mock":
        return MockAIProvider()
    if settings.ai_provider == "openai":
        return OpenAIProvider(settings)
    if settings.ai_provider == "ollama":
        return OllamaProvider(settings)
    raise AppError("Unknown AI provider configuration.", "AI_PROVIDER_INVALID", 500)
