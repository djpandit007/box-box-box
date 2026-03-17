from __future__ import annotations

import logging

import httpx

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
        """Generate a 1536-dimension embedding vector for the given text."""
        resp = await self._client.post(
            "/embeddings",
            json={"model": self._model, "input": text},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["data"][0]["embedding"]

    async def close(self) -> None:
        await self._client.aclose()
