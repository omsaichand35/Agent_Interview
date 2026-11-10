from app.config import settings

from app.llm.client import LLMClient, NVIDIAClient
from app.llm.reliable_client import ReliableLLMClient


def get_llm_client() -> LLMClient:

    if settings.llm_provider == "nvidia":

        client = NVIDIAClient()

        return ReliableLLMClient(
            client=client,
            max_retries=1,
        )

    raise ValueError(
        f"Unsupported LLM provider: {settings.llm_provider}"
    )