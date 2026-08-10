from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.dataset import AnalysisPlan
from app.services.ai.base import AIProvider
from app.services.ai.structured import explanation_prompt, plan_prompt, validate_plan_json


class OllamaProvider(AIProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def _chat(self, prompt: str, structured: bool = False) -> str:
        payload: dict[str, Any] = {"model": self.settings.ollama_model, "messages": [{"role": "user", "content": prompt}], "stream": False}
        if structured: payload["format"] = "json"
        try:
            async with httpx.AsyncClient(timeout=self.settings.ai_timeout_seconds) as client:
                response = await client.post(f"{self.settings.ollama_base_url.rstrip('/')}/api/chat", json=payload)
                response.raise_for_status()
                return response.json()["message"]["content"]
        except httpx.TimeoutException as exc:
            raise AppError("The Ollama provider timed out.", "AI_PROVIDER_TIMEOUT", 504) from exc
        except (httpx.HTTPError, KeyError, TypeError) as exc:
            raise AppError("The Ollama provider is unavailable.", "AI_PROVIDER_UNAVAILABLE", 503) from exc

    async def create_analysis_plan(self, question: str, columns: list[dict[str, Any]]) -> AnalysisPlan:
        return validate_plan_json(await self._chat(plan_prompt(question, columns), True))

    async def explain_result(self, question: str, plan: AnalysisPlan, result: Any) -> str:
        return await self._chat(explanation_prompt(question, plan, result))
