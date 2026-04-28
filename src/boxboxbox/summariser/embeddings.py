from __future__ import annotations

import logging

import httpx

from boxboxbox.observability import tracer

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """Generate text embeddings via the OpenRouter API (OpenAI-compatible endpoint)."""

    def __init__(self, api_key: str, model: str = "openai/text-embedding-3-small"):
        self._client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )
        self._model = model

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for the given text."""
        with tracer.start_as_current_span("embed_text") as span:
            span.set_attribute("input.value", text[:500])
            span.set_attribute("embedding.model_name", self._model)
            resp = await self._client.post(
                "/embeddings",
                json={"model": self._model, "input": text},
            )
            resp.raise_for_status()
            data = resp.json()
            return data["data"][0]["embedding"]

    async def close(self) -> None:
        await self._client.aclose()
