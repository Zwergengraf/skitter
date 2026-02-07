from __future__ import annotations

from pathlib import Path
from typing import List
import re

import hashlib
import json
import logging

from .config import settings

from ..data.db import SessionLocal
from ..data.repositories import Repository
from .embeddings import EmbeddingsClient


_HEADER_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")


def _split_markdown_sections(text: str) -> list[str]:
    lines = text.splitlines()
    if not lines:
        return []
    sections: list[str] = []
    current: list[str] = []
    for line in lines:
        if _HEADER_RE.match(line) and current:
            section = "\n".join(current).strip()
            if section:
                sections.append(section)
            current = [line]
        else:
            current.append(line)
    if current:
        section = "\n".join(current).strip()
        if section:
            sections.append(section)
    return sections


def _split_by_words(text: str, max_chars: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    current = ""
    for word in words:
        if len(word) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            # Single token larger than max: hard split is unavoidable.
            for i in range(0, len(word), max_chars):
                chunks.append(word[i : i + max_chars])
            continue
        candidate = f"{current} {word}".strip()
        if not current:
            current = word
        elif len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = word
    if current:
        chunks.append(current)
    return chunks


def _split_oversized(text: str, max_chars: int) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    if len(paragraphs) > 1:
        out: list[str] = []
        for paragraph in paragraphs:
            out.extend(_split_oversized(paragraph, max_chars))
        return out

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if len(lines) > 1:
        out = []
        for line in lines:
            out.extend(_split_oversized(line, max_chars))
        return out

    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]
    if len(sentences) > 1:
        out = []
        for sentence in sentences:
            out.extend(_split_oversized(sentence, max_chars))
        return out

    return _split_by_words(cleaned, max_chars)


def chunk_text(text: str, target_chars: int | None = None, max_chars: int | None = None) -> List[str]:
    raw = text.strip()
    if not raw:
        return []

    max_chars = max_chars or settings.embeddings_max_chunk_chars
    max_chars = max(100, int(max_chars))
    target_chars = target_chars or settings.embeddings_target_chunk_chars
    target_chars = max(80, min(int(target_chars), max_chars))

    sections = _split_markdown_sections(raw) or [raw]
    units: list[str] = []
    for section in sections:
        units.extend(_split_oversized(section, max_chars))

    chunks: list[str] = []
    current = ""
    for unit in units:
        if not current:
            current = unit
            continue
        candidate = f"{current}\n\n{unit}"
        if len(candidate) <= max_chars:
            current_distance = abs(len(current) - target_chars)
            candidate_distance = abs(len(candidate) - target_chars)
            # If we're already at/above target, split when adding would move us further away.
            if len(current) >= target_chars and candidate_distance >= current_distance:
                chunks.append(current)
                current = unit
            else:
                current = candidate
            continue
        chunks.append(current)
        current = unit
    if current:
        chunks.append(current)
    return chunks


class MemoryService:
    def __init__(self, embedder: EmbeddingsClient | None = None) -> None:
        self.embedder = embedder or EmbeddingsClient()
        self._logger = logging.getLogger(__name__)

    async def index_text(self, user_id: str, session_id: str | None, source: str, text: str) -> int:
        chunks = chunk_text(text)
        if not chunks:
            return 0
        try:
            embeddings = await self.embedder.embed_documents(chunks)
        except Exception as exc:  # pragma: no cover - network errors
            self._logger.exception("Embedding failed for %s: %s", source, exc)
            return 0
        tags = [f"file:{source}"]
        if session_id:
            tags.append(f"session:{session_id}")
        async with SessionLocal() as session:
            repo = Repository(session)
            for chunk, embedding in zip(chunks, embeddings):
                await repo.add_memory(user_id=user_id, summary=chunk, embedding=embedding, tags=tags)
        return len(chunks)

    def _split_sessions(self, text: str) -> List[tuple[str, str]]:
        pattern = re.compile(r"^# Session Summary \(([^)]+)\)", re.MULTILINE)
        matches = list(pattern.finditer(text))
        if not matches:
            return []
        sections: List[tuple[str, str]] = []
        for idx, match in enumerate(matches):
            session_id = match.group(1).strip()
            start = match.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            section_text = text[start:end].strip()
            if section_text.startswith("---"):
                section_text = section_text.lstrip("-").strip()
            sections.append((session_id, section_text))
        return sections

    def _is_hidden_or_internal(self, path: Path) -> bool:
        return path.name.startswith(".") or path.name == ".index.json"

    def _is_indexable_file(self, path: Path) -> bool:
        if self._is_hidden_or_internal(path):
            return False
        return path.suffix.lower() in {".md", ".txt"}

    async def index_file(self, user_id: str, session_id: str | None, path: Path, force: bool = False) -> bool:
        memory_root = path.parent
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.delete_memory_by_tag(user_id, f"file:{path.name}")

        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return False
        sections = self._split_sessions(text)
        indexed = 0
        if sections:
            for section_session_id, section_text in sections:
                indexed += await self.index_text(user_id, section_session_id, path.name, section_text)
        else:
            indexed = await self.index_text(user_id, session_id, path.name, text)
        if indexed > 0:
            index = self._load_index(memory_root)
            index[path.name] = self._hash_file(path)
            self._save_index(memory_root, index)
        return indexed > 0

    async def reindex_all(self, user_id: str, memory_root: Path) -> dict:
        memory_root.mkdir(parents=True, exist_ok=True)
        index = self._load_index(memory_root)
        current_files = {
            p.name: p
            for p in memory_root.iterdir()
            if p.is_file() and self._is_indexable_file(p)
        }

        indexed = 0
        skipped = 0
        removed = 0

        for name, path in current_files.items():
            changed = await self.index_file(user_id, session_id=None, path=path, force=True)
            if changed:
                indexed += 1
            else:
                skipped += 1

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
