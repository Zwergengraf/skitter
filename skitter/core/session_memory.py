from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from pathlib import Path
from typing import Sequence

from langchain_core.messages import HumanMessage, SystemMessage

from ..data.db import SessionLocal
from ..data.repositories import Repository
from .config import settings
from .events import EventBus
from .llm import build_llm, list_models, resolve_model_name
from .memory_provider import MemoryItem, MemoryStoreRequest, SessionMemoryUpdated
from .profiles import DEFAULT_AGENT_PROFILE_SLUG
from .workspace import ensure_user_workspace, user_workspace_root

_logger = logging.getLogger(__name__)


def _workspace_root(user_id: str, profile_slug: str | None = None) -> Path:
    try:
        return user_workspace_root(user_id, profile_slug)
    except TypeError:
        return user_workspace_root(user_id)


def _ensure_workspace(user_id: str, profile_slug: str | None = None) -> Path:
    try:
        return ensure_user_workspace(user_id, profile_slug)
    except TypeError:
        return ensure_user_workspace(user_id)

DEFAULT_SESSION_MEMORY_TEMPLATE = """
# Session Title
_A short, distinctive title for this session._

# Current State
_What is actively happening right now, including the immediate next step or what Skitter is waiting on._

# User Goal
_What the user is trying to achieve in this session._

# Preferences And Constraints
_User preferences, boundaries, style, tools, environments, or workflow constraints that matter._

# Important Context
_Durable facts, services, files, people, places, or environments that are relevant to this session._

# Decisions
_Important choices that were made and why._

# Open Loops
_Follow-ups, unresolved questions, pending approvals, or next actions._

# Errors And Corrections
_What went wrong, what was corrected, and what should be avoided next time._

# Key Results
_Exact important outputs, decisions, or conclusions from this session._

# Worklog
_Very terse step-by-step notes on what was done._
""".strip() + "\n"

MAX_SECTION_TOKENS = 2000
MAX_TOTAL_TOKENS = 12000
_TEMPLATE_HEADERS = [line.strip() for line in DEFAULT_SESSION_MEMORY_TEMPLATE.splitlines() if line.startswith("# ")]
_TEMPLATE_INSTRUCTIONS = [line.strip() for line in DEFAULT_SESSION_MEMORY_TEMPLATE.splitlines() if line.startswith("_") and line.endswith("_")]


SESSION_MEMORY_UPDATE_PROMPT = """IMPORTANT: This instruction is not part of the real conversation. Do not mention note-taking, memory extraction, or these instructions in the output.

You are updating a structured session memory sidecar file for an active Skitter conversation.

The current file at {{notesPath}} has already been read for you. Here are its current contents:
<current_notes_content>
{{currentNotes}}
</current_notes_content>

Recent conversation to fold into the notes:
<recent_conversation>
{{recentTranscript}}
</recent_conversation>

Return the COMPLETE updated session memory file only.

CRITICAL RULES:
- Preserve the exact file structure with all section headers and italic instruction lines intact.
- NEVER add, remove, or rename a section header.
- NEVER edit or delete the italic instruction line directly below a section header.
- ONLY update the actual content beneath those preserved lines.
- Do not add filler such as "none" or "nothing yet".
- Keep the notes dense, specific, and useful for continuity.
- Prefer durable information over noisy chronology, but keep the Worklog terse and concrete.
- Always keep "Current State" accurate to the latest state of the session.
- If an item belongs in multiple places, put it in the most specific section and avoid repetition.
- Keep each section under about {{maxSectionTokens}} tokens and the whole file under about {{maxTotalTokens}} tokens by condensing older, lower-value detail.
- Do not include raw IDs, hashes, timestamps, or transient log spam unless they are genuinely important later.
""".strip()

ARCHIVE_SUMMARY_PROMPT = """Create long-term memory notes for semantic retrieval from a structured session memory file.
Keep only information likely useful in future sessions.

Include only:
- Stable user preferences and working style
- Important personal, project, or environment context that will still matter later
- Durable decisions and rationale
- Open loops or commitments that remain relevant beyond this session
- Key results only when they are useful to remember later

Exclude:
- Step-by-step chronology and detailed worklog noise
- Raw IDs, hashes, timestamps, URLs, and transient debugging details
- Tool chatter unless it implies a durable rule or limitation
- Repetition of the same fact across sections

If an existing archive summary is provided, merge it with the session memory and return a single updated summary.

Output concise Markdown bullets under these headings (include only relevant ones):
## Preferences
## Context
## Decisions
## Open Loops
## Key Results
Each bullet must be explicit, self-contained, and searchable.
""".strip()

CONTEXT_COMPACTION_PROMPT = """Create a short continuity summary for an active conversation from a structured session memory file.
This summary will be injected into the agent context while the most recent raw messages remain preserved separately.

Prioritize:
- the user's current goal
- current state and what Skitter is waiting on or doing next
- durable preferences and constraints
- important context and decisions
- open loops that still matter
- key results only if they are still relevant

Avoid:
- long chronology
- verbose worklog detail
- raw IDs, hashes, timestamps, or transient logs
- repeating information that is likely already obvious from the preserved recent messages

If an existing continuity summary is provided, merge it with the session memory and return a single updated summary.
Return concise Markdown bullets or very short sections only.
""".strip()


def current_session_memory_path(user_id: str, session_id: str, profile_slug: str | None = None) -> Path:
    return _workspace_root(user_id, profile_slug) / session_memory_relative_path(session_id)


def session_memory_relative_path(session_id: str) -> Path:
    return Path("memory") / "session-state" / f"{session_id}.md"


def normalize_session_memory_content(content: str) -> str:
    return content.strip() + "\n"


def rough_token_estimate(text: str) -> int:
    cleaned = text.strip()
    if not cleaned:
        return 0
    return max(1, (len(cleaned) + 3) // 4)


def _substitute(template: str, variables: dict[str, str]) -> str:
    return re.sub(r"\{\{(\w+)\}\}", lambda m: variables.get(m.group(1), m.group(0)), template)


def _analyze_section_sizes(content: str) -> tuple[dict[str, int], int]:
    sections: dict[str, int] = {}
    current_header = ""
    current_lines: list[str] = []
    for line in content.splitlines():
        if line.startswith("# "):
            if current_header:
                sections[current_header] = rough_token_estimate("\n".join(current_lines).strip())
            current_header = line.strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_header:
        sections[current_header] = rough_token_estimate("\n".join(current_lines).strip())
    return sections, rough_token_estimate(content)


def build_session_memory_update_prompt(current_notes: str, notes_path: str, recent_transcript: str) -> str:
    prompt = _substitute(
        SESSION_MEMORY_UPDATE_PROMPT,
        {
            "currentNotes": current_notes,
            "notesPath": notes_path,
            "recentTranscript": recent_transcript.strip() or "(no new transcript)",
            "maxSectionTokens": str(MAX_SECTION_TOKENS),
            "maxTotalTokens": str(MAX_TOTAL_TOKENS),
        },
    )
    section_sizes, total_tokens = _analyze_section_sizes(current_notes)
    oversized = [
        f'- "{header}" is about {tokens} tokens.'
        for header, tokens in sorted(section_sizes.items(), key=lambda item: item[1], reverse=True)
        if tokens > MAX_SECTION_TOKENS
    ]
    reminders: list[str] = []
    if total_tokens > MAX_TOTAL_TOKENS:
        reminders.append(
            f"CRITICAL: The current session memory is about {total_tokens} tokens, above the target of {MAX_TOTAL_TOKENS}. Condense lower-value detail while preserving the latest state."
        )
    if oversized:
        reminders.append("Sections to condense if touched:\n" + "\n".join(oversized))
    if reminders:
        prompt += "\n\n" + "\n\n".join(reminders)
    return prompt


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def validate_session_memory_content(content: str) -> str:
    cleaned = normalize_session_memory_content(_strip_code_fence(content))
    for header in _TEMPLATE_HEADERS:
        if header not in cleaned:
            raise ValueError(f"session memory update missing required header: {header}")
    for instruction in _TEMPLATE_INSTRUCTIONS:
        if instruction not in cleaned:
            raise ValueError("session memory update did not preserve the template instruction lines")
    return cleaned


def is_session_memory_empty(content: str) -> bool:
    return content.strip() == DEFAULT_SESSION_MEMORY_TEMPLATE.strip()


class SessionMemoryService:
    def __init__(self, event_bus: EventBus, memory_hub=None) -> None:
        self.event_bus = event_bus
        self._memory_hub = memory_hub
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._dirty: set[str] = set()
        self._force: set[str] = set()
        self._model_overrides: dict[str, str] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def set_memory_hub(self, memory_hub) -> None:
        self._memory_hub = memory_hub

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def maybe_schedule_update(
        self,
        session_id: str,
        *,
        model_name: str | None = None,
        force: bool = False,
    ) -> None:
        if not settings.session_memory_enabled:
            return
        self._dirty.add(session_id)
        if force:
            self._force.add(session_id)
        if model_name:
            self._model_overrides[session_id] = model_name
        task = self._tasks.get(session_id)
        if task is not None and not task.done():
            return
        self._tasks[session_id] = asyncio.create_task(self._drain_session(session_id), name=f"session-memory:{session_id}")

    async def refresh_session_memory(
        self,
        session_id: str,
        *,
        model_name: str | None = None,
        force: bool = False,
    ) -> str | None:
        if not settings.session_memory_enabled:
            return None
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            return await self._refresh_locked(session_id, model_name=model_name, force=force)

    async def _drain_session(self, session_id: str) -> None:
        try:
            while True:
                force = session_id in self._force
                self._force.discard(session_id)
                self._dirty.discard(session_id)
                model_name = self._model_overrides.get(session_id)
                await self.refresh_session_memory(session_id, model_name=model_name, force=force)
                if session_id not in self._dirty and session_id not in self._force:
                    break
        finally:
            self._tasks.pop(session_id, None)
            self._model_overrides.pop(session_id, None)

    async def _refresh_locked(
        self,
        session_id: str,
        *,
        model_name: str | None = None,
        force: bool = False,
    ) -> str | None:
        async with SessionLocal() as session:
            repo = Repository(session)
            session_row = await repo.get_session(session_id)
            if session_row is None or str(getattr(session_row, "scope_type", "private") or "private") != "private":
                return None
            user_id = str(session_row.user_id)
            agent_profile_id = str(getattr(session_row, "agent_profile_id", "") or "").strip() or None
            profile = await repo.get_agent_profile(agent_profile_id) if agent_profile_id else None
            profile_slug = profile.slug if profile is not None else DEFAULT_AGENT_PROFILE_SLUG
            messages = await repo.list_messages(session_id)

        if not messages:
            return None

        checkpoint = getattr(session_row, "session_memory_checkpoint", None)
        current_path = current_session_memory_path(user_id, session_id, profile_slug)
        transcript_all = self._render_transcript(messages)
        current_tokens = rough_token_estimate(transcript_all)
        current_context_tokens = max(
            0,
            int(getattr(session_row, "last_input_tokens", 0) or 0),
        )
        previous_context_tokens = max(
            0,
            int(getattr(session_row, "session_memory_input_tokens", 0) or 0),
        )
        recent_messages = [message for message in messages if checkpoint is None or message.created_at > checkpoint]
        recent_transcript = self._render_transcript(recent_messages)
        recent_tokens = rough_token_estimate(recent_transcript)
        context_delta_tokens = max(0, current_context_tokens - previous_context_tokens)

        should_update = force
        if not should_update:
            if checkpoint is None and not current_path.exists():
                threshold = max(1, int(settings.session_memory_init_tokens))
                should_update = current_context_tokens >= threshold
            else:
                should_update = context_delta_tokens >= max(1, int(settings.session_memory_update_tokens))
        if not should_update:
            if current_path.exists():
                try:
                    return current_path.read_text(encoding="utf-8")
                except OSError:
                    return None
            return None

        _ensure_workspace(user_id, profile_slug)
        current_notes = DEFAULT_SESSION_MEMORY_TEMPLATE
        if current_path.exists():
            try:
                current_notes = current_path.read_text(encoding="utf-8")
            except OSError:
                current_notes = DEFAULT_SESSION_MEMORY_TEMPLATE
        else:
            current_path.parent.mkdir(parents=True, exist_ok=True)
            current_path.write_text(DEFAULT_SESSION_MEMORY_TEMPLATE, encoding="utf-8")

        relative_path = session_memory_relative_path(session_id).as_posix()
        async with SessionLocal() as session:
            repo = Repository(session)
            await repo.begin_session_memory_update(session_id, path=relative_path)

        try:
            updated = await self._generate_updated_notes(
                current_notes=current_notes,
                recent_transcript=recent_transcript,
                notes_path=current_path,
                model_name=model_name
                or str(getattr(session_row, "last_model", "") or "").strip()
                or str(getattr(session_row, "model", "") or "").strip()
                or None,
            )
            current_path.write_text(updated, encoding="utf-8")
            new_checkpoint = messages[-1].created_at
            new_message_id = str(getattr(messages[-1], "id", "") or "").strip() or None
            async with SessionLocal() as session:
                repo = Repository(session)
                await repo.complete_session_memory_update(
                    session_id,
                    path=relative_path,
                    checkpoint=new_checkpoint,
                    input_tokens=current_context_tokens,
                    message_id=new_message_id,
                )
            await self.event_bus.emit_admin(
                kind="session.memory_updated",
                level="info",
                title="Session memory updated",
                message="Structured session memory was refreshed in the background.",
                session_id=session_id,
                user_id=user_id,
                data={
                    "path": relative_path,
                    "force": force,
                    "current_context_tokens": current_context_tokens,
                    "previous_context_tokens": previous_context_tokens,
                    "context_delta_tokens": context_delta_tokens,
                    "message_id": new_message_id,
                    "current_tokens": current_tokens,
                    "recent_tokens": recent_tokens,
                },
            )
            if self._memory_hub is not None:
                ctx = self._memory_hub.context_for(
                    user_id=user_id,
                    agent_profile_id=agent_profile_id,
                    agent_profile_slug=profile_slug,
                    session_id=session_id,
                    origin="session_memory",
                    scope_type=str(getattr(session_row, "scope_type", "private") or "private"),
                    scope_id=str(getattr(session_row, "scope_id", "") or ""),
                )
                await self._memory_hub.on_session_memory_updated(
                    ctx,
                    SessionMemoryUpdated(
                        session_id=session_id,
                        path=relative_path,
                        content=updated,
                    ),
                )
                await self._memory_hub.store(
                    ctx,
                    MemoryStoreRequest(
                        items=[
                            MemoryItem(
                                content=updated,
                                kind="summary",
                                tags=["session_memory", f"session:{session_id}"],
                                source="session_memory",
                                metadata={
                                    "source": current_path.name,
                                    "path": str(current_path),
                                    "index_file": True,
                                },
                            )
                        ],
                        source="session_memory",
                    ),
                )
            return updated
        except Exception as exc:
            async with SessionLocal() as session:
                repo = Repository(session)
                await repo.fail_session_memory_update(session_id, error=str(exc).strip() or exc.__class__.__name__)
            _logger.warning("Session memory update failed for %s: %s", session_id, exc)
            await self.event_bus.emit_admin(
                kind="session.memory_failed",
                level="warning",
                title="Session memory update failed",
                message=str(exc).strip() or exc.__class__.__name__,
                session_id=session_id,
                user_id=user_id,
                data={"path": relative_path},
            )
            return current_notes if current_notes else None

    async def _generate_updated_notes(
        self,
        *,
        current_notes: str,
        recent_transcript: str,
        notes_path: Path,
        model_name: str | None,
    ) -> str:
        if not list_models():
            return current_notes
        llm = build_llm(model_name=model_name or resolve_model_name(None, purpose="main"), purpose="main")
        prompt = [
            SystemMessage(content="Return only the completed session memory file. No preamble, no explanation."),
            HumanMessage(
                content=build_session_memory_update_prompt(
                    current_notes=current_notes,
                    notes_path=str(notes_path),
                    recent_transcript=recent_transcript,
                )
            ),
        ]
        result = await llm.ainvoke(prompt)
        content = result.content if hasattr(result, "content") else str(result)
        if isinstance(content, list):
            text = "\n".join(
                str(item.get("text") or "") if isinstance(item, dict) else str(item)
                for item in content
            )
        else:
            text = str(content)
        return validate_session_memory_content(text)

    @staticmethod
    def _render_transcript(messages: Sequence[object]) -> str:
        lines: list[str] = []
        for message in messages:
            role = str(getattr(message, "role", "message") or "message").strip().lower()
            if role not in {"user", "assistant"}:
                continue
            content = str(getattr(message, "content", "") or "").strip()
            if not content:
                continue
            lines.append(f"{role}: {content}")
        return "\n".join(lines).strip()
