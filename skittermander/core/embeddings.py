from __future__ import annotations

from typing import List

import httpx

from .config import settings


class EmbeddingsClient:
    def __init__(self) -> None:
        self.base_url = settings.embeddings_api_base.rstrip("/")
        self.api_key = settings.embeddings_api_key
        self.model = settings.embeddings_model

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self.model, "input": texts}
        data = await self._post(payload)
        return [item["embedding"] for item in data]

    async def embed_query(self, text: str) -> list[float]:
        payload = {"model": self.model, "input": text}
        data = await self._post(payload)
        return data[0]["embedding"] if data else []

    async def _post(self, payload: dict) -> List[dict]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(f"{self.base_url}/embeddings", json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()
            return body.get("data", [])
