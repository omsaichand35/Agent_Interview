from typing import Type, TypeVar

from pydantic import BaseModel

from app.llm.client import LLMClient


T = TypeVar("T", bound=BaseModel)


class ReliableLLMClient:

    def __init__(
        self,
        client: LLMClient,
        max_retries: int = 1,
    ):
        self.client = client
        self.max_retries = max_retries

    def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
    ) -> T:

        last_error = None

        for attempt in range(self.max_retries + 1):

            try:
                return self.client.generate_structured(
                    prompt=prompt,
                    response_model=response_model,
                )

            except Exception as exc:
                last_error = exc

                if attempt >= self.max_retries:
                    raise

        raise RuntimeError(
            f"LLM request failed: {last_error}"
        )