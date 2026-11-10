import json
import time
from typing import Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel

from app.config import settings
from app.core.logging import log_event
from app.core.metrics import get_metrics_collector


T = TypeVar("T", bound=BaseModel)


class LLMClient:
    def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
    ) -> T:
        raise NotImplementedError


class NVIDIAClient(LLMClient):

    def __init__(self):
        if not settings.nvidia_api_key:
            raise ValueError(
                "NVIDIA_API_KEY is not configured."
            )

        self.client = OpenAI(
            api_key=settings.nvidia_api_key,
            base_url=settings.nvidia_base_url,
        )

        self.model = settings.nvidia_model

    def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
    ) -> T:

        start_time = time.perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an evidence-based hiring "
                            "analysis assistant. "
                            "Return ONLY valid JSON."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=0,
                extra_body={
                    "chat_template_kwargs": {
                        "enable_thinking": False,
                    },
                },
            )

            content = response.choices[0].message.content

            if not content:
                raise ValueError("LLM returned an empty response.")

            parsed = self._parse_response(
                content,
                response_model,
            )
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            log_event(
                event="llm_completed",
                model=self.model,
                duration_ms=duration_ms,
            )
            get_metrics_collector().record_llm(success=True, latency_ms=duration_ms)
            return parsed
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            get_metrics_collector().record_llm(success=False, latency_ms=duration_ms)
            raise

    @staticmethod
    def _parse_response(
        content: str,
        response_model: Type[T],
    ) -> T:

        content = content.strip()

        # Handle accidental markdown JSON fences.
        if content.startswith("```"):
            lines = content.splitlines()

            if lines[0].startswith("```"):
                lines = lines[1:]

            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]

            content = "\n".join(lines).strip()

        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"LLM returned invalid JSON:\n{content}"
            ) from exc

        return response_model.model_validate(data)
