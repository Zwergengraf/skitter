from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..memory_provider import BaseMemoryProvider, MemoryProvider
from .hooks import HookBus, HookHandler

_logger = logging.getLogger(__name__)


class PluginCapabilities(BaseModel):
    hooks: list[str] = Field(default_factory=list)
    memory_provider: str | None = None

    model_config = ConfigDict(extra="ignore")


class PluginManifest(BaseModel):
    id: str
    enabled: bool = Field(default=False)
    required: bool = Field(default=False)
    version: str = Field(default="0.0.0")
    description: str = Field(default="")
    entrypoint: str = Field(default="")
    capabilities: PluginCapabilities = Field(default_factory=PluginCapabilities)
    config: dict[str, Any] = Field(default_factory=dict)
    config_schema: dict[str, Any] = Field(default_factory=dict)
    required_secrets: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")

    @field_validator("id", "entrypoint", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("required_secrets", mode="before")
    @classmethod
    def _normalize_required_secrets(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    @field_validator("config", mode="before")
    @classmethod
    def _normalize_config(cls, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}


@dataclass
class PluginDiagnostic:
    plugin_id: str
    level: str
    message: str
    detail: str | None = None


@dataclass
class RegisteredPlugin:
    manifest: PluginManifest
    path: Path | None
    config: dict[str, Any] = field(default_factory=dict)
    module: ModuleType | None = None


class PluginContext:
    def __init__(
        self,
        *,
        plugin_id: str,
        config: dict[str, Any],
        hook_bus: HookBus,
        registry: "PluginRegistry",
    ) -> None:
        self.plugin_id = plugin_id
        self.config = dict(config)
        self._hook_bus = hook_bus
        self._registry = registry

    def register_hook(
        self,
        hook_name: str,
        handler: HookHandler,
        *,
        priority: int = 100,
        timeout_seconds: float | None = None,
    ) -> None:
        self._hook_bus.register(
            hook_name,
            handler,
            plugin_id=self.plugin_id,
            priority=priority,
            timeout_seconds=timeout_seconds,
        )

    def register_memory_provider(self, provider: MemoryProvider | type[MemoryProvider]) -> None:
        self._registry.register_memory_provider(self.plugin_id, provider)


class PluginRegistry:
    def __init__(
        self,
        *,
        hook_bus: HookBus | None = None,
        plugin_root: str | Path = "plugins",
    ) -> None:
        self.hook_bus = hook_bus or HookBus()
        self.plugin_root = Path(plugin_root).expanduser()
        self.plugins: dict[str, RegisteredPlugin] = {}
        self.diagnostics: list[PluginDiagnostic] = []
        self._memory_providers: list[tuple[str, MemoryProvider | type[MemoryProvider]]] = []
        self._loaded = False

    @property
    def memory_providers(self) -> list[tuple[str, MemoryProvider | type[MemoryProvider]]]:
        return list(self._memory_providers)

    async def load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        for path in self._discover_plugin_paths():
            await self._load_one(path)

    def register_memory_provider(
        self,
        plugin_id: str,
        provider: MemoryProvider | type[MemoryProvider],
    ) -> None:
        self._memory_providers.append((plugin_id, provider))

    def snapshot(self) -> dict[str, Any]:
        return {
            "plugins": [
                {
                    "id": plugin.manifest.id,
                    "version": plugin.manifest.version,
                    "description": plugin.manifest.description,
                    "path": str(plugin.path) if plugin.path else None,
                    "required": plugin.manifest.required,
                    "enabled": plugin.manifest.enabled,
                    "capabilities": plugin.manifest.capabilities.model_dump(),
                }
                for plugin in sorted(self.plugins.values(), key=lambda item: item.manifest.id)
            ],
            "hooks": self.hook_bus.snapshot(),
            "memory_providers": [
                {"plugin_id": plugin_id, "provider_id": self._provider_id(provider)}
                for plugin_id, provider in self._memory_providers
            ],
            "diagnostics": [
                {
                    "plugin_id": item.plugin_id,
                    "level": item.level,
                    "message": item.message,
                    "detail": item.detail,
                }
                for item in self.diagnostics
            ],
            "plugin_root": str(self.plugin_root),
        }

    async def _load_one(self, path: Path) -> None:
        plugin_id = path.name
        try:
            manifest = self._load_manifest(path)
            plugin_id = manifest.id
            if manifest.id in self.plugins:
                raise ValueError(f"duplicate plugin id: {manifest.id}")
            if not manifest.enabled:
                self.plugins[manifest.id] = RegisteredPlugin(
                    manifest=manifest,
                    path=path,
                    config=dict(manifest.config),
                )
                return
            self._validate_plugin_config(manifest)
            module = self._import_entrypoint_module(manifest.entrypoint, path)
            register = self._resolve_register(module, manifest.entrypoint)
            plugin = RegisteredPlugin(
                manifest=manifest,
                path=path,
                config=dict(manifest.config),
                module=module,
            )
            self.plugins[manifest.id] = plugin
            ctx = PluginContext(
                plugin_id=manifest.id,
                config=manifest.config,
                hook_bus=self.hook_bus,
                registry=self,
            )
            result = register(ctx)
            if hasattr(result, "__await__"):
                await result
        except Exception as exc:
            self._record(plugin_id, "error", "Plugin registration failed", str(exc))
            _logger.warning("Plugin registration failed for %s: %s", plugin_id, exc)
            if self._manifest_required(path):
                raise

    def _discover_plugin_paths(self) -> list[Path]:
        root = self.plugin_root
        try:
            root = root.resolve()
        except OSError:
            root = root.absolute()
        if not root.exists():
            return []
        if not root.is_dir():
            self._record(str(root), "error", "Plugin root is not a directory")
            return []
        paths: list[Path] = []
        for child in sorted(root.iterdir(), key=lambda item: item.name):
            if not child.is_dir():
                continue
            if self._find_manifest(child) is None:
                continue
            paths.append(child)
        return paths

    def _load_manifest(self, path: Path) -> PluginManifest:
        if not path.exists():
            raise FileNotFoundError(f"plugin path does not exist: {path}")
        manifest_path = self._find_manifest(path)
        if manifest_path is None:
            raise FileNotFoundError(f"plugin manifest not found: {path}")
        data = self._read_manifest(manifest_path)
        manifest = PluginManifest.model_validate(data)
        if manifest.enabled and not manifest.entrypoint:
            raise ValueError(f"plugin {manifest.id} is missing an entrypoint")
        return manifest

    def _validate_plugin_config(self, manifest: PluginManifest) -> None:
        schema = manifest.config_schema or {}
        if not schema:
            return
        if str(schema.get("type") or "object").strip().lower() != "object":
            raise ValueError(f"plugin {manifest.id} config_schema must describe an object")
        config = manifest.config or {}
        required = schema.get("required") or []
        if isinstance(required, list):
            for key in required:
                name = str(key).strip()
                if name and name not in config:
                    raise ValueError(f"plugin {manifest.id} config missing required field: {name}")
        properties = schema.get("properties") or {}
        if not isinstance(properties, dict):
            return
        for key, spec in properties.items():
            if key not in config or not isinstance(spec, dict):
                continue
            expected_type = str(spec.get("type") or "").strip().lower()
            if not expected_type:
                continue
            value = config[key]
            if not self._matches_schema_type(value, expected_type):
                raise ValueError(
                    f"plugin {manifest.id} config field {key} must be {expected_type}"
                )

    @staticmethod
    def _matches_schema_type(value: Any, expected_type: str) -> bool:
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected_type == "boolean":
            return isinstance(value, bool)
        if expected_type == "object":
            return isinstance(value, dict)
        if expected_type == "array":
            return isinstance(value, list)
        if expected_type == "null":
            return value is None
        return True

    def _manifest_required(self, path: Path) -> bool:
        manifest_path = self._find_manifest(path)
        if manifest_path is None:
            return False
        try:
            manifest = PluginManifest.model_validate(self._read_manifest(manifest_path))
        except Exception:
            return False
        return bool(manifest.required)

    @staticmethod
    def _find_manifest(path: Path) -> Path | None:
        if path.is_file():
            return path
        for name in ("plugin.yaml", "plugin.yml", "plugin.json"):
            candidate = path / name
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        raw = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            data = json.loads(raw)
        else:
            data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            raise ValueError(f"plugin manifest must be an object: {path}")
        return data

    @staticmethod
    def _import_entrypoint_module(entrypoint: str, path: Path | None) -> ModuleType:
        module_name, _sep, _func_name = entrypoint.partition(":")
        module_name = module_name.strip()
        if not module_name:
            raise ValueError("plugin entrypoint is missing a module name")
        if path is not None and path.is_dir():
            path_text = str(path)
            if path_text not in sys.path:
                sys.path.insert(0, path_text)
        if path is not None and path.is_file() and path.suffix == ".py":
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise ImportError(f"failed to import plugin module from {path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return module
        return importlib.import_module(module_name)

    @staticmethod
    def _resolve_register(module: ModuleType, entrypoint: str) -> Callable[[PluginContext], Any]:
        _module_name, _sep, func_name = entrypoint.partition(":")
        target = func_name.strip() or "register"
        register = getattr(module, target, None)
        if not callable(register):
            raise AttributeError(f"plugin entrypoint function not found: {target}")
        return register

    def _record(self, plugin_id: str, level: str, message: str, detail: str | None = None) -> None:
        self.diagnostics.append(
            PluginDiagnostic(
                plugin_id=plugin_id,
                level=level,
                message=message,
                detail=detail,
            )
        )

    @staticmethod
    def _provider_id(provider: MemoryProvider | type[MemoryProvider]) -> str:
        if isinstance(provider, type):
            return str(getattr(provider, "id", provider.__name__))
        if isinstance(provider, BaseMemoryProvider):
            return provider.id
        return str(getattr(provider, "id", provider.__class__.__name__))
