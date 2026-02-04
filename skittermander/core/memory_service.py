from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

import hashlib
import json
import logging

from .config import settings

from ..data.db import SessionLocal
from ..data.repositories import Repository
from .embeddings import EmbeddingsClient


def chunk_text(text: str, chunk_size: int | None = None, overlap: int = 100) -> List[str]:
    chunk_size = chunk_size or settings.embeddings_max_chunk_chars
    cleaned = text.strip()
    if not cleaned:
        return []
    chunks: List[str] = []
    start = 0
    length = len(cleaned)
    while start < length:
        end = min(start + chunk_size, length)
        chunks.append(cleaned[start:end])
        if end == length:
            break
        start = max(0, end - overlap)
    return chunks


class MemoryService:
    def __init__(self, embedder: EmbeddingsClient | None = None) -> None:
        self.embedder = embedder or EmbeddingsClient()
        self._logger = logging.getLogger(__name__)

    async def index_text(self, user_id: str, session_id: str, source: str, text: str) -> int:
        chunks = chunk_text(text)
        if not chunks:
            return 0
        try:
            embeddings = await self.embedder.embed_documents(chunks)
        except Exception as exc:  # pragma: no cover - network errors
            self._logger.exception("Embedding failed for %s: %s", source, exc)
            return 0
        tags = [f"file:{source}", f"session:{session_id}"]
        async with SessionLocal() as session:
            repo = Repository(session)
            for chunk, embedding in zip(chunks, embeddings):
                await repo.add_memory(user_id=user_id, summary=chunk, embedding=embedding, tags=tags)
        return len(chunks)

    async def index_file(self, user_id: str, session_id: str, path: Path, force: bool = False) -> bool:
        memory_root = path.parent
        index = self._load_index(memory_root)
        digest = self._hash_file(path)
        if not force and index.get(path.name) == digest:
            return False

        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.delete_memory_by_tag(user_id, f"file:{path.name}")

        text = path.read_text(encoding="utf-8")
        indexed = await self.index_text(user_id, session_id, path.name, text)
        if indexed > 0:
            index[path.name] = digest
            self._save_index(memory_root, index)
        return indexed > 0

    async def reindex_all(self, user_id: str, memory_root: Path) -> dict:
        memory_root.mkdir(parents=True, exist_ok=True)
        index = self._load_index(memory_root)
        current_files = {p.name: p for p in memory_root.glob("*.md")}

        indexed = 0
        skipped = 0
        removed = 0

        for name, path in current_files.items():
            digest = self._hash_file(path)
            if index.get(name) == digest:
                skipped += 1
                continue
            changed = await self.index_file(user_id, session_id=name, path=path, force=True)
            if changed:
                indexed += 1

        removed_files = [name for name in index.keys() if name not in current_files]
        if removed_files:
            async with SessionLocal() as session:
                repo = Repository(session)
                for name in removed_files:
                    await repo.delete_memory_by_tag(user_id, f"file:{name}")
                    removed += 1
                    index.pop(name, None)
            self._save_index(memory_root, index)

        return {"indexed": indexed, "skipped": skipped, "removed": removed}

    def _hash_file(self, path: Path) -> str:
        data = path.read_bytes()
        return hashlib.sha256(data).hexdigest()

    def _load_index(self, memory_root: Path) -> dict:
        index_path = memory_root / ".index.json"
        if not index_path.exists():
            return {}
        try:
            return json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save_index(self, memory_root: Path, index: dict) -> None:
        index_path = memory_root / ".index.json"
        index_path.write_text(json.dumps(index, indent=2, ensure_ascii=True), encoding="utf-8")
