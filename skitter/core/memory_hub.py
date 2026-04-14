from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..data.db import SessionLocal
from ..data.repositories import Repository
from .memory_provider import (
    BaseMemoryProvider,
    ContextContribution,
    MemoryContext,
    MemoryContextRequest,
    MemoryContextResult,
    ConversationTurn,
    MemoryForgetRequest,
    MemoryForgetResult,
    MemoryForgetSelector,
    MemoryHealth,
    MemoryHit,
    MemoryItem,
    MemoryProvider,
    MemoryRecallRequest,
    MemoryRecallResult,
    MemoryStoreRequest,
    MemoryStoreResult,
    MemorySystemContext,
    SessionArchived,
    SessionMemoryUpdated,
)
from .memory_service import MemoryService
from .plugins.hooks import HookBus
from .plugins.transforms import merge_filters, normalized_int, normalized_string_set, patches_from_results
from .workspace import user_workspace_root

_logger = logging.getLogger(__name__)


class BuiltInMemoryProvider(BaseMemoryProvider):
    id = "builtin"
    name = "Skitter Built-in Memory"
    capabilities = {"health", "recall", "store", "forget"}

    def __init__(self, memory_service: MemoryService | None = None) -> None:
        self.memory_service = memory_service or MemoryService()

    async def recall(
        self,
        ctx: MemoryContext,
        request: MemoryRecallRequest,
    ) -> MemoryRecallResult:
        rows = await self.memory_service.search(
            ctx.user_id,
            request.query,
            request.top_k,
            agent_profile_id=ctx.agent_profile_id or None,
        )
        hits: list[MemoryHit] = []
        for idx, row in enumerate(rows):
            source = str(row.get("source") or "(unknown)")
            hits.append(
                MemoryHit(
                    id=f"{self.id}:{source}:{idx}",
                    provider_id=self.id,
                    content=str(row.get("summary") or ""),
                    score=float(row.get("score") or 0.0),
                    tags=[str(tag) for tag in (row.get("tags") or [])],
                    source=source,
                    created_at=str(row.get("created_at") or ""),
                )
            )
        return MemoryRecallResult(hits=hits)

    async def store(
        self,
        ctx: MemoryContext,
        request: MemoryStoreRequest,
    ) -> MemoryStoreResult:
        stored = 0
        for idx, item in enumerate(request.items):
            source = str(item.metadata.get("source") or item.source or f"memory-{idx}")
            if bool(item.metadata.get("replace_source")):
                async with SessionLocal() as session:
                    repo = Repository(session)
                    await repo.delete_memory_by_tag(
                        ctx.user_id,
                        f"file:{source}",
                        agent_profile_id=ctx.agent_profile_id or None,
                    )
            if bool(item.metadata.get("index_file")):
                path = Path(str(item.metadata.get("path") or ""))
                if path.exists() and path.is_file():
                    indexed = await self.memory_service.index_file(
                        ctx.user_id,
                        ctx.session_id,
                        path,
                        force=True,
                        agent_profile_id=ctx.agent_profile_id or None,
                    )
                    stored += 1 if indexed else 0
                continue
            stored += await self.memory_service.index_text(
                ctx.user_id,
                ctx.session_id,
                source,
                item.content,
                agent_profile_id=ctx.agent_profile_id or None,
            )
        return MemoryStoreResult(stored=stored)

    async def forget(
        self,
        ctx: MemoryContext,
        request: MemoryForgetRequest,
    ) -> MemoryForgetResult:
        selector = request.selector
        if not selector.all_for_profile:
            return MemoryForgetResult(unsupported=True)
        async with SessionLocal() as session:
            repo = Repository(session)
            deleted = await repo.delete_memory(
                selector.user_id or ctx.user_id,
                agent_profile_id=selector.agent_profile_id or ctx.agent_profile_id,
            )
        return MemoryForgetResult(deleted=deleted)


class MemoryHub:
    def __init__(
        self,
        *,
        hook_bus: HookBus | None = None,
        built_in_provider: BuiltInMemoryProvider | None = None,
        external_provider_id: str | None = None,
        context_timeout_seconds: float = 0.75,
        recall_timeout_seconds: float = 5.0,
        store_timeout_seconds: float = 5.0,
    ) -> None:
        self.hook_bus = hook_bus or HookBus()
        self.built_in_provider = built_in_provider or BuiltInMemoryProvider()
        self.external_provider_id = str(external_provider_id or "").strip()
        self.context_timeout_seconds = float(context_timeout_seconds)
        self.recall_timeout_seconds = float(recall_timeout_seconds)
        self.store_timeout_seconds = float(store_timeout_seconds)
        self._external_providers: dict[str, BaseMemoryProvider] = {}
        self._last_errors: dict[str, str] = {}
        self._observe_chains: dict[str, asyncio.Task[None]] = {}
        self._started = False

    def add_external_provider(
        self,
        plugin_id: str,
        provider: MemoryProvider | type[MemoryProvider],
    ) -> None:
        instance = self._instantiate_provider(provider)
        provider_id = str(getattr(instance, "id", "") or "").strip()
        if not provider_id:
            raise ValueError(f"memory provider from plugin {plugin_id} has no id")
        if self.external_provider_id and provider_id != self.external_provider_id:
            return
        if provider_id == self.built_in_provider.id:
            raise ValueError("external memory provider id conflicts with built-in provider")
        self._external_providers[provider_id] = instance

    async def startup(self) -> None:
        if self._started:
            return
        self._started = True
        await self._startup_provider("builtin", self.built_in_provider)
        for provider_id, provider in self._external_providers.items():
            await self._startup_provider(provider_id, provider)

    async def shutdown(self) -> None:
        observe_tasks = list(self._observe_chains.values())
        if observe_tasks:
            done, pending = await asyncio.wait(
                observe_tasks,
                timeout=max(0.1, self.store_timeout_seconds),
            )
            _ = done
            for task in pending:
                task.cancel()
            self._observe_chains.clear()
        providers = self._providers()
        for provider_id, provider in providers:
            try:
                await self.hook_bus.emit("memory.provider.shutdown", {"provider_id": provider_id})
                await provider.shutdown(MemorySystemContext(plugin_id=provider_id))
            except Exception as exc:
                self._last_errors[provider_id] = str(exc) or exc.__class__.__name__
                _logger.warning("Memory provider shutdown failed: provider=%s error=%s", provider_id, exc)
        self._started = False

    async def status(self, ctx: MemoryContext | None = None) -> dict[str, Any]:
        context = ctx or self._empty_context()
        providers: list[dict[str, Any]] = []
        for provider_id, provider in self._providers():
            try:
                await self.hook_bus.emit("memory.health.check", {"provider_id": provider_id})
                health = await asyncio.wait_for(provider.health(context), timeout=2.0)
            except Exception as exc:
                health = MemoryHealth(status="error", message=str(exc) or exc.__class__.__name__)
            providers.append(
                {
                    "id": provider_id,
                    "name": getattr(provider, "name", provider_id),
                    "capabilities": sorted(getattr(provider, "capabilities", set()) or []),
                    "health": {
                        "status": health.status,
                        "message": health.message,
                        "metadata": health.metadata,
                    },
                    "last_error": self._last_errors.get(provider_id),
                }
            )
        return {
            "providers": providers,
            "external_provider_id": self.external_provider_id or None,
            "started": self._started,
            "background": {
                "observe_queue_count": len(self._observe_chains),
                "observe_session_keys": sorted(self._observe_chains),
            },
            "last_errors": dict(self._last_errors),
        }

    async def build_context(
        self,
        ctx: MemoryContext,
        request: MemoryContextRequest,
    ) -> MemoryContextResult:
        before_results = await self.hook_bus.emit("memory.context.before_build", {"ctx": ctx, "request": request})
        request, disabled_providers = self._apply_context_request_patches(
            request,
            patches_from_results(before_results),
        )
        tasks = [
            self._call_provider_build_context(provider_id, provider, ctx, request)
            for provider_id, provider in self._providers()
            if provider_id not in disabled_providers
            if "build_context" in (getattr(provider, "capabilities", set()) or set())
        ]
        contributions = []
        if tasks:
            for result in await asyncio.gather(*tasks):
                contributions.extend(result.contributions)
        contributions.sort(key=lambda item: (item.priority, item.provider_id, item.title))
        merged = MemoryContextResult(contributions=contributions)
        after_results = await self.hook_bus.emit("memory.context.after_build", {"ctx": ctx, "request": request, "result": merged})
        merged = self._apply_context_result_patches(merged, patches_from_results(after_results))
        return merged

    async def recall(
        self,
        ctx: MemoryContext,
        request: MemoryRecallRequest,
    ) -> MemoryRecallResult:
        before_results = await self.hook_bus.emit("memory.recall.before", {"ctx": ctx, "request": request})
        request, disabled_providers = self._apply_recall_request_patches(
            request,
            patches_from_results(before_results),
        )
        tasks = [
            self._call_provider_recall(provider_id, provider, ctx, request)
            for provider_id, provider in self._providers()
            if provider_id not in disabled_providers
            if "recall" in (getattr(provider, "capabilities", set()) or set())
        ]
        merged = MemoryRecallResult()
        if tasks:
            for result in await asyncio.gather(*tasks):
                merged.hits.extend(result.hits)
                merged.errors.update(result.errors)
        merged.hits = self._dedupe_hits(merged.hits)
        merged.hits.sort(key=lambda hit: (hit.score is None, -(hit.score or 0.0), hit.provider_id))
        merged.hits = merged.hits[: max(1, int(request.top_k))]
        after_results = await self.hook_bus.emit("memory.recall.after", {"ctx": ctx, "request": request, "result": merged})
        merged = self._apply_recall_result_patches(merged, patches_from_results(after_results), top_k=request.top_k)
        return merged

    async def search(
        self,
        user_id: str,
        query: str,
        top_k: int = 5,
        *,
        agent_profile_id: str | None = None,
        agent_profile_slug: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
        origin: str = "tool",
        transport_account_key: str | None = None,
        scope_type: str = "private",
        scope_id: str = "",
        source: str = "tool",
    ) -> list[dict[str, Any]]:
        ctx = self.context_for(
            user_id=user_id,
            agent_profile_id=agent_profile_id,
            agent_profile_slug=agent_profile_slug,
            session_id=session_id,
            run_id=run_id,
            origin=origin,
            transport_account_key=transport_account_key,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        result = await self.recall(
            ctx,
            MemoryRecallRequest(query=query, top_k=top_k, source=source),  # type: ignore[arg-type]
        )
        return [hit.to_legacy_dict() for hit in result.hits]

    async def store(
        self,
        ctx: MemoryContext,
        request: MemoryStoreRequest,
    ) -> MemoryStoreResult:
        before_results = await self.hook_bus.emit("memory.store.before", {"ctx": ctx, "request": request})
        request, disabled_providers, rejection = self._apply_store_request_patches(
            request,
            patches_from_results(before_results),
        )
        merged = MemoryStoreResult()
        if rejection:
            merged.errors["hook"] = rejection
            after_results = await self.hook_bus.emit("memory.store.after", {"ctx": ctx, "request": request, "result": merged})
            return self._apply_store_result_patches(merged, patches_from_results(after_results))
        tasks = [
            self._call_provider_store(provider_id, provider, ctx, request)
            for provider_id, provider in self._providers()
            if provider_id not in disabled_providers
            if "store" in (getattr(provider, "capabilities", set()) or set())
        ]
        if tasks:
            for result in await asyncio.gather(*tasks):
                merged.stored += result.stored
                merged.errors.update(result.errors)
        after_results = await self.hook_bus.emit("memory.store.after", {"ctx": ctx, "request": request, "result": merged})
        return self._apply_store_result_patches(merged, patches_from_results(after_results))

    async def forget(
        self,
        ctx: MemoryContext,
        request: MemoryForgetRequest,
    ) -> MemoryForgetResult:
        await self.hook_bus.emit("memory.forget.before", {"ctx": ctx, "request": request})
        merged = MemoryForgetResult()
        for provider_id, provider in self._providers():
            if not request.include_builtin and provider_id == self.built_in_provider.id:
                continue
            if request.selector.provider_id and provider_id != request.selector.provider_id:
                continue
            if "forget" not in (getattr(provider, "capabilities", set()) or set()):
                merged.errors[provider_id] = "unsupported"
                continue
            result = await self._call_provider_forget(provider_id, provider, ctx, request)
            merged.deleted += result.deleted
            merged.unsupported = merged.unsupported or result.unsupported
            merged.errors.update(result.errors)
        await self.hook_bus.emit("memory.forget.after", {"ctx": ctx, "request": request, "result": merged})
        return merged

    async def on_session_memory_updated(
        self,
        ctx: MemoryContext,
        event: SessionMemoryUpdated,
    ) -> None:
        tasks = [
            self._call_provider_session_memory_updated(provider_id, provider, ctx, event)
            for provider_id, provider in self._providers()
            if "session_memory_updated" in (getattr(provider, "capabilities", set()) or set())
        ]
        if tasks:
            await asyncio.gather(*tasks)
        await self.hook_bus.emit("memory.session_memory.updated", {"ctx": ctx, "event": event})

    async def on_session_archived(
        self,
        ctx: MemoryContext,
        event: SessionArchived,
    ) -> None:
        tasks = [
            self._call_provider_session_archived(provider_id, provider, ctx, event)
            for provider_id, provider in self._providers()
            if "session_archived" in (getattr(provider, "capabilities", set()) or set())
        ]
        if tasks:
            await asyncio.gather(*tasks)
        await self.hook_bus.emit("memory.session.archived", {"ctx": ctx, "event": event})

    async def before_session_archive(self, ctx: MemoryContext, session_id: str) -> None:
        await self.hook_bus.emit("memory.session.archiving", {"ctx": ctx, "session_id": session_id})

    def queue_observe_turn(self, ctx: MemoryContext, turn: ConversationTurn) -> None:
        providers = [
            (provider_id, provider)
            for provider_id, provider in self._providers()
            if "observe_turn" in (getattr(provider, "capabilities", set()) or set())
        ]
        if not providers:
            return
        key = ctx.session_id or ctx.scope_id or ctx.user_id or "default"
        previous = self._observe_chains.get(key)
        task = asyncio.create_task(
            self._observe_turn_after(previous, providers, ctx, turn),
            name=f"memory-observe-turn:{key}",
        )
        self._observe_chains[key] = task

        def _cleanup(done: asyncio.Task[None], *, expected: asyncio.Task[None] = task, chain_key: str = key) -> None:
            if self._observe_chains.get(chain_key) is expected:
                self._observe_chains.pop(chain_key, None)
            try:
                done.result()
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                self._last_errors["observe_turn"] = str(exc) or exc.__class__.__name__

        task.add_done_callback(_cleanup)

    def context_for(
        self,
        *,
        user_id: str,
        agent_profile_id: str | None = None,
        agent_profile_slug: str | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
        origin: str = "",
        transport_account_key: str | None = None,
        scope_type: str = "private",
        scope_id: str = "",
    ) -> MemoryContext:
        slug = str(agent_profile_slug or "").strip()
        workspace_root: Path | None = None
        if user_id:
            try:
                workspace_root = user_workspace_root(user_id, slug or None)
            except Exception:
                workspace_root = None
        return MemoryContext(
            user_id=user_id,
            agent_profile_id=str(agent_profile_id or "").strip(),
            agent_profile_slug=slug,
            session_id=session_id,
            run_id=run_id,
            origin=origin,
            transport_account_key=transport_account_key,
            scope_type=scope_type,
            scope_id=scope_id,
            workspace_root=workspace_root,
        )

    def _apply_context_request_patches(
        self,
        request: MemoryContextRequest,
        patches: list[dict[str, Any]],
    ) -> tuple[MemoryContextRequest, set[str]]:
        updated = replace(request, filters=dict(request.filters or {}))
        disabled_providers: set[str] = set()
        for patch in patches:
            if isinstance(patch.get("query"), str):
                updated.query = patch["query"]
            if "max_tokens" in patch:
                updated.max_tokens = max(1, normalized_int(patch.get("max_tokens"), updated.max_tokens))
            if "filters" in patch:
                updated.filters = merge_filters(updated.filters, patch.get("filters"))
            disabled_providers.update(normalized_string_set(patch.get("disabled_providers")))
        return updated, disabled_providers

    def _apply_recall_request_patches(
        self,
        request: MemoryRecallRequest,
        patches: list[dict[str, Any]],
    ) -> tuple[MemoryRecallRequest, set[str]]:
        updated = replace(request, filters=dict(request.filters or {}))
        disabled_providers: set[str] = set()
        for patch in patches:
            if isinstance(patch.get("query"), str):
                updated.query = patch["query"]
            if "top_k" in patch:
                updated.top_k = max(1, normalized_int(patch.get("top_k"), updated.top_k))
            if "max_tokens" in patch:
                updated.max_tokens = max(1, normalized_int(patch.get("max_tokens"), updated.max_tokens or 1))
            if "filters" in patch:
                updated.filters = merge_filters(updated.filters, patch.get("filters"))
            disabled_providers.update(normalized_string_set(patch.get("disabled_providers")))
        return updated, disabled_providers

    def _apply_store_request_patches(
        self,
        request: MemoryStoreRequest,
        patches: list[dict[str, Any]],
    ) -> tuple[MemoryStoreRequest, set[str], str | None]:
        updated = replace(request, items=list(request.items))
        disabled_providers: set[str] = set()
        rejection: str | None = None
        for patch in patches:
            if patch.get("reject") is True:
                rejection = str(patch.get("reason") or "store rejected by hook")
            elif isinstance(patch.get("reject"), str) and patch.get("reject"):
                rejection = str(patch["reject"])
            if isinstance(patch.get("source"), str):
                updated.source = patch["source"]  # type: ignore[assignment]
            if isinstance(patch.get("items"), list):
                updated.items = [item for item in (self._coerce_memory_item(value) for value in patch["items"]) if item]
            if isinstance(patch.get("add_items"), list):
                updated.items.extend(
                    item for item in (self._coerce_memory_item(value) for value in patch["add_items"]) if item
                )
            drop_indexes = {
                normalized_int(value, -1)
                for value in (patch.get("drop_indexes") or [])
                if normalized_int(value, -1) >= 0
            }
            if drop_indexes:
                updated.items = [item for idx, item in enumerate(updated.items) if idx not in drop_indexes]
            drop_tags = normalized_string_set(patch.get("drop_tags"))
            if drop_tags:
                updated.items = [item for item in updated.items if not drop_tags.intersection(item.tags)]
            disabled_providers.update(normalized_string_set(patch.get("disabled_providers")))
        return updated, disabled_providers, rejection

    def _apply_context_result_patches(
        self,
        result: MemoryContextResult,
        patches: list[dict[str, Any]],
    ) -> MemoryContextResult:
        updated = MemoryContextResult(contributions=list(result.contributions))
        for patch in patches:
            if isinstance(patch.get("contributions"), list):
                updated.contributions = [
                    item for item in (self._coerce_context_contribution(value) for value in patch["contributions"]) if item
                ]
            if isinstance(patch.get("add_contributions"), list):
                updated.contributions.extend(
                    item for item in (self._coerce_context_contribution(value) for value in patch["add_contributions"]) if item
                )
            drop_provider_ids = normalized_string_set(patch.get("drop_provider_ids"))
            drop_titles = normalized_string_set(patch.get("drop_titles"))
            for item in patch.get("drop_contributions") or []:
                if isinstance(item, dict):
                    drop_provider_ids.update(normalized_string_set(item.get("provider_id")))
                    drop_titles.update(normalized_string_set(item.get("title")))
                elif isinstance(item, str) and ":" in item:
                    provider_id, title = item.split(":", 1)
                    drop_provider_ids.update(normalized_string_set(provider_id))
                    drop_titles.update(normalized_string_set(title))
            if drop_provider_ids:
                updated.contributions = [item for item in updated.contributions if item.provider_id not in drop_provider_ids]
            if drop_titles:
                updated.contributions = [item for item in updated.contributions if item.title not in drop_titles]
            self._apply_contribution_redactions(updated, patch.get("redactions"))
            if "max_tokens" in patch:
                updated.contributions = self._trim_contributions(
                    updated.contributions,
                    max(1, normalized_int(patch.get("max_tokens"), 1)),
                )
        updated.contributions.sort(key=lambda item: (item.priority, item.provider_id, item.title))
        return updated

    def _apply_recall_result_patches(
        self,
        result: MemoryRecallResult,
        patches: list[dict[str, Any]],
        *,
        top_k: int,
    ) -> MemoryRecallResult:
        updated = MemoryRecallResult(hits=list(result.hits), errors=dict(result.errors))
        limit = max(1, int(top_k))
        for patch in patches:
            if isinstance(patch.get("hits"), list):
                updated.hits = [hit for hit in (self._coerce_memory_hit(value) for value in patch["hits"]) if hit]
            if isinstance(patch.get("add_hits"), list):
                updated.hits.extend(hit for hit in (self._coerce_memory_hit(value) for value in patch["add_hits"]) if hit)
            drop_ids = normalized_string_set(patch.get("drop_hit_ids") or patch.get("drop_ids"))
            drop_provider_ids = normalized_string_set(patch.get("drop_provider_ids"))
            if drop_ids:
                updated.hits = [hit for hit in updated.hits if hit.id not in drop_ids]
            if drop_provider_ids:
                updated.hits = [hit for hit in updated.hits if hit.provider_id not in drop_provider_ids]
            self._apply_hit_redactions(updated, patch.get("redactions"))
            if isinstance(patch.get("errors"), dict):
                updated.errors.update({str(key): str(value) for key, value in patch["errors"].items()})
            if "top_k" in patch:
                limit = max(1, normalized_int(patch.get("top_k"), limit))
        updated.hits = self._dedupe_hits(updated.hits)
        updated.hits = updated.hits[:limit]
        return updated

    @staticmethod
    def _apply_store_result_patches(
        result: MemoryStoreResult,
        patches: list[dict[str, Any]],
    ) -> MemoryStoreResult:
        updated = MemoryStoreResult(
            stored=result.stored,
            errors=dict(result.errors),
            metadata=dict(result.metadata),
        )
        for patch in patches:
            if "stored" in patch:
                updated.stored = max(0, normalized_int(patch.get("stored"), updated.stored))
            if "stored_delta" in patch:
                updated.stored = max(0, updated.stored + normalized_int(patch.get("stored_delta"), 0))
            if isinstance(patch.get("errors"), dict):
                updated.errors.update({str(key): str(value) for key, value in patch["errors"].items()})
            if isinstance(patch.get("metadata"), dict):
                updated.metadata.update(patch["metadata"])
        return updated

    @staticmethod
    def _coerce_context_contribution(value: Any) -> ContextContribution | None:
        if isinstance(value, ContextContribution):
            return value
        if not isinstance(value, dict):
            return None
        content = str(value.get("content") or "").strip()
        if not content:
            return None
        return ContextContribution(
            provider_id=str(value.get("provider_id") or "hook"),
            title=str(value.get("title") or "Hook Context"),
            content=content,
            priority=normalized_int(value.get("priority"), 100),
            token_estimate=value.get("token_estimate"),
            metadata=dict(value.get("metadata") or {}),
        )

    @staticmethod
    def _coerce_memory_hit(value: Any) -> MemoryHit | None:
        if isinstance(value, MemoryHit):
            return value
        if not isinstance(value, dict):
            return None
        content = str(value.get("content") or value.get("summary") or "").strip()
        if not content:
            return None
        return MemoryHit(
            id=str(value.get("id") or f"hook:{hash(content)}"),
            provider_id=str(value.get("provider_id") or "hook"),
            content=content,
            score=value.get("score"),
            kind=value.get("kind"),
            tags=[str(tag) for tag in (value.get("tags") or [])],
            source=value.get("source"),
            created_at=value.get("created_at"),
            metadata=dict(value.get("metadata") or {}),
        )

    @staticmethod
    def _coerce_memory_item(value: Any) -> MemoryItem | None:
        if isinstance(value, MemoryItem):
            return value
        if not isinstance(value, dict):
            return None
        content = str(value.get("content") or "").strip()
        if not content:
            return None
        return MemoryItem(
            content=content,
            kind=str(value.get("kind") or "fact"),
            importance=value.get("importance"),
            confidence=value.get("confidence"),
            tags=[str(tag) for tag in (value.get("tags") or [])],
            source=value.get("source") or "api",
            metadata=dict(value.get("metadata") or {}),
        )

    @staticmethod
    def _apply_contribution_redactions(result: MemoryContextResult, redactions: Any) -> None:
        if not isinstance(redactions, list):
            return
        for redaction in redactions:
            if not isinstance(redaction, dict):
                continue
            provider_id = str(redaction.get("provider_id") or "")
            title = str(redaction.get("title") or "")
            content = redaction.get("content")
            if content is None:
                continue
            for item in result.contributions:
                if provider_id and item.provider_id != provider_id:
                    continue
                if title and item.title != title:
                    continue
                item.content = str(content)

    @staticmethod
    def _apply_hit_redactions(result: MemoryRecallResult, redactions: Any) -> None:
        if not isinstance(redactions, list):
            return
        for redaction in redactions:
            if not isinstance(redaction, dict):
                continue
            hit_id = str(redaction.get("id") or "")
            provider_id = str(redaction.get("provider_id") or "")
            content = redaction.get("content")
            if content is None:
                continue
            for hit in result.hits:
                if hit_id and hit.id != hit_id:
                    continue
                if provider_id and hit.provider_id != provider_id:
                    continue
                hit.content = str(content)

    @staticmethod
    def _trim_contributions(contributions: list[ContextContribution], max_tokens: int) -> list[ContextContribution]:
        out: list[ContextContribution] = []
        used = 0
        for item in contributions:
            estimate = item.token_estimate
            if estimate is None:
                estimate = max(1, (len(item.content.strip()) + 3) // 4)
            if used + int(estimate) > max_tokens and out:
                continue
            out.append(item)
            used += max(1, int(estimate))
            if used >= max_tokens:
                break
        return out

    def _providers(self) -> list[tuple[str, BaseMemoryProvider]]:
        return [(self.built_in_provider.id, self.built_in_provider), *sorted(self._external_providers.items())]

    async def _startup_provider(self, provider_id: str, provider: BaseMemoryProvider) -> None:
        try:
            await self.hook_bus.emit("memory.provider.startup", {"provider_id": provider_id})
            await provider.startup(MemorySystemContext(plugin_id=provider_id))
        except Exception as exc:
            self._last_errors[provider_id] = str(exc) or exc.__class__.__name__
            _logger.warning("Memory provider startup failed: provider=%s error=%s", provider_id, exc)

    async def _call_provider_build_context(
        self,
        provider_id: str,
        provider: BaseMemoryProvider,
        ctx: MemoryContext,
        request: MemoryContextRequest,
    ) -> MemoryContextResult:
        try:
            return await asyncio.wait_for(
                provider.build_context(ctx, request),
                timeout=max(0.1, self.context_timeout_seconds),
            )
        except Exception as exc:
            self._last_errors[provider_id] = str(exc) or exc.__class__.__name__
            return MemoryContextResult()

    async def _call_provider_recall(
        self,
        provider_id: str,
        provider: BaseMemoryProvider,
        ctx: MemoryContext,
        request: MemoryRecallRequest,
    ) -> MemoryRecallResult:
        try:
            return await asyncio.wait_for(
                provider.recall(ctx, request),
                timeout=max(0.1, self.recall_timeout_seconds),
            )
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            self._last_errors[provider_id] = message
            return MemoryRecallResult(errors={provider_id: message})

    async def _call_provider_store(
        self,
        provider_id: str,
        provider: BaseMemoryProvider,
        ctx: MemoryContext,
        request: MemoryStoreRequest,
    ) -> MemoryStoreResult:
        try:
            return await asyncio.wait_for(
                provider.store(ctx, request),
                timeout=max(0.1, self.store_timeout_seconds),
            )
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            self._last_errors[provider_id] = message
            return MemoryStoreResult(errors={provider_id: message})

    async def _call_provider_forget(
        self,
        provider_id: str,
        provider: BaseMemoryProvider,
        ctx: MemoryContext,
        request: MemoryForgetRequest,
    ) -> MemoryForgetResult:
        try:
            return await asyncio.wait_for(
                provider.forget(ctx, request),
                timeout=max(0.1, self.store_timeout_seconds),
            )
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            self._last_errors[provider_id] = message
            return MemoryForgetResult(errors={provider_id: message})

    async def _call_provider_session_memory_updated(
        self,
        provider_id: str,
        provider: BaseMemoryProvider,
        ctx: MemoryContext,
        event: SessionMemoryUpdated,
    ) -> None:
        try:
            await asyncio.wait_for(
                provider.on_session_memory_updated(ctx, event),
                timeout=max(0.1, self.store_timeout_seconds),
            )
        except Exception as exc:
            self._last_errors[provider_id] = str(exc) or exc.__class__.__name__

    async def _call_provider_session_archived(
        self,
        provider_id: str,
        provider: BaseMemoryProvider,
        ctx: MemoryContext,
        event: SessionArchived,
    ) -> None:
        try:
            await asyncio.wait_for(
                provider.on_session_archived(ctx, event),
                timeout=max(0.1, self.store_timeout_seconds),
            )
        except Exception as exc:
            self._last_errors[provider_id] = str(exc) or exc.__class__.__name__

    async def _observe_turn_after(
        self,
        previous: asyncio.Task[None] | None,
        providers: list[tuple[str, BaseMemoryProvider]],
        ctx: MemoryContext,
        turn: ConversationTurn,
    ) -> None:
        if previous is not None:
            try:
                await previous
            except Exception:
                pass
        errors: dict[str, str] = {}
        for provider_id, provider in providers:
            try:
                await asyncio.wait_for(
                    provider.observe_turn(ctx, turn),
                    timeout=max(0.1, self.store_timeout_seconds),
                )
            except Exception as exc:
                message = str(exc) or exc.__class__.__name__
                self._last_errors[provider_id] = message
                errors[provider_id] = message
        await self.hook_bus.emit(
            "memory.turn.observed",
            {
                "ctx": ctx,
                "turn": turn,
                "errors": errors,
            },
        )

    @staticmethod
    def _instantiate_provider(provider: MemoryProvider | type[MemoryProvider]) -> BaseMemoryProvider:
        if isinstance(provider, BaseMemoryProvider):
            return provider
        if isinstance(provider, type):
            instance = provider()
            if isinstance(instance, BaseMemoryProvider):
                return instance
            return instance  # type: ignore[return-value]
        return provider  # type: ignore[return-value]

    @staticmethod
    def _dedupe_hits(hits: list[MemoryHit]) -> list[MemoryHit]:
        seen: set[tuple[str, str]] = set()
        out: list[MemoryHit] = []
        for hit in hits:
            key = (hit.provider_id, hit.content.strip())
            if key in seen:
                continue
            seen.add(key)
            out.append(hit)
        return out

    @staticmethod
    def _empty_context() -> MemoryContext:
        return MemoryContext(user_id="", agent_profile_id="", agent_profile_slug="")


def forget_all_for_profile(user_id: str, agent_profile_id: str) -> MemoryForgetRequest:
    return MemoryForgetRequest(
        selector=MemoryForgetSelector(
            user_id=user_id,
            agent_profile_id=agent_profile_id,
            all_for_profile=True,
        )
    )
