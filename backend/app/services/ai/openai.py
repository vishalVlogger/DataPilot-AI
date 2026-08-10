from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.dataset import AnalysisPlan
from app.services.ai.base import AIProvider
from app.services.ai.structured import explanation_prompt, plan_prompt, validate_plan_json


class OpenAIProvider(AIProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise AppError("OPENAI_API_KEY is required for the OpenAI provider.", "AI_PROVIDER_UNAVAILABLE", 503)
        self.settings = settings

    async def _chat(self, prompt: str, structured: bool = False) -> str:
        payload: dict[str, Any] = {"model": self.settings.openai_model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}
        if structured: payload["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(timeout=self.settings.ai_timeout_seconds) as client:
                response = await client.post(f"{self.settings.openai_base_url.rstrip('/')}/chat/completions", headers={"Authorization": f"Bearer {self.settings.openai_api_key}"}, json=payload)
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]
        except httpx.TimeoutException as exc:
            raise AppError("The OpenAI provider timed out.", "AI_PROVIDER_TIMEOUT", 504) from exc
        except (httpx.HTTPError, KeyError, TypeError) as exc:
            raise AppError("The OpenAI provider is unavailable.", "AI_PROVIDER_UNAVAILABLE", 503) from exc

    async def create_analysis_plan(self, question: str, columns: list[dict[str, Any]]) -> AnalysisPlan:
        return validate_plan_json(await self._chat(plan_prompt(question, columns), True))

    async def explain_result(self, question: str, plan: AnalysisPlan, result: Any) -> str:
        return await self._chat(explanation_prompt(question, plan, result))
