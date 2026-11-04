from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigurationError


ROLE_NAMES = (
    "planner",
    "researcher",
    "architect",
    "coder",
    "qa",
    "reviewer",
    "reflector",
)
_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_NAMESPACE = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")


@dataclass(frozen=True)
class RoleConfig:
    model: str
    num_predict: int = 4096
    temperature: float = 0.2
    max_turns: int = 8


@dataclass(frozen=True)
class CommandConfig:
    argv: tuple[str, ...]
    timeout_seconds: int = 120
    resume_policy: str = "rerun"

    def resolved_argv(self) -> list[str]:
        return [part.replace("{python}", sys.executable) for part in self.argv]


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str = "http://127.0.0.1:11434"
    context_length: int = 16384
    keep_alive: str = "5m"
    load_timeout_seconds: int = 1800
    request_timeout_seconds: int = 3600
    dedicated_ollama: bool = False
    offload_on_exit: bool = True
    transport_retries: int = 2


LLAMACPP_DEFAULT_MODEL = "deepseek-r1-uncensored-v2:70b"
LLAMACPP_DEFAULT_MODEL_PATH = (
    "~/models/DeepSeek-R1-Distill-Llama-70B-Uncensored-v2-Unbiased-Reasoner.Q5_K_M.gguf"
)
KIMI_DEFAULT_MODEL = "k3.1-pro"


@dataclass(frozen=True)
class LlamaCppConfig:
    """A single GGUF model served by a managed llama.cpp subprocess."""

    enabled: bool = True
    model_name: str = LLAMACPP_DEFAULT_MODEL
    model_path: str = LLAMACPP_DEFAULT_MODEL_PATH
    server_binary: str = "llama-server"
    host: str = "127.0.0.1"
    port: int = 8085
    gpu_layers: int = 23
    context_length: int = 16384
    cache_type_k: str = "q8_0"
    cache_type_v: str = "q8_0"
    extra_args: tuple[str, ...] = ()
    startup_timeout_seconds: int = 1800
    request_timeout_seconds: int = 3600
    transport_retries: int = 2


@dataclass(frozen=True)
class KimiConfig:
    enabled: bool = False
    base_url: str = "https://api.kimi.ai/coding/v1"
    model_name: str = KIMI_DEFAULT_MODEL
    api_key_env: str = "KIMI_API_KEY"
    context_length: int = 262144
    request_timeout_seconds: int = 600
    transport_retries: int = 2
    max_response_bytes: int = 16_000_000
    offload_local: bool = True
    approved: bool = False
    allow_dreaming: bool = False


@dataclass(frozen=True)
class WebConfig:
    enabled: bool = False
    search_url: str = "https://html.duckduckgo.com/html/?q={query}"
    allowed_domains: tuple[str, ...] = ()
    timeout_seconds: int = 30
    max_bytes: int = 1_000_000
    max_results: int = 5


@dataclass(frozen=True)
class Limits:
    max_tasks: int = 64
    max_waves: int = 128
    max_repair_cycles: int = 2
    max_protocol_retries: int = 2
    max_file_bytes: int = 2_000_000
    max_command_output_bytes: int = 2_000_000
    max_tool_result_chars: int = 12_000
    max_list_entries: int = 500
    safety_reserve_tokens: int = 512


def _runtime_path(filename: str) -> str:
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return str(Path(base) / f"agentic-ai-{os.geteuid()}-{filename}")


@dataclass(frozen=True)
class ExecutionConfig:
    # One per-UID lock shared by every project, rather than a lock per run root.
    lock_path: str = field(default_factory=lambda: _runtime_path("executor.lock"))
    process_registry_path: str = field(default_factory=lambda: _runtime_path("llamacpp.json"))


@dataclass(frozen=True)
class MemoryConfig:
    enabled: bool = False
    root: str = "/var/lib/agentic-ai/memory"
    project_id: str = "default"
    classification: str = "private"
    dreaming_enabled: bool = False
    run_roots: tuple[str, ...] = ()
    transcript_retention_days: int = 30
    max_guidance_documents: int = 8
    max_search_results: int = 8


@dataclass(frozen=True)
class DreamConfig:
    subject_model: str = LLAMACPP_DEFAULT_MODEL
    curator_model: str = LLAMACPP_DEFAULT_MODEL
    allow_hosted: bool = False
    max_transcripts: int = 8
    max_transcript_bytes: int = 4_000_000
    max_shards: int = 8
    max_findings: int = 64
    max_proposals: int = 20
    min_distinct_runs: int = 2
    steering: str = (
        "Prefer repeated, evidence-backed lessons that improve reliability, "
        "deterministic verification, and the small business's recurring workflows."
    )


def _default_roles() -> dict[str, RoleConfig]:
    research = LLAMACPP_DEFAULT_MODEL
    coding = "qwen2.5-coder:32b"
    return {
        "planner": RoleConfig(research, num_predict=6144, temperature=0.1),
        "researcher": RoleConfig(research, num_predict=6144, temperature=0.2),
        "architect": RoleConfig(research, num_predict=6144, temperature=0.1),
        "coder": RoleConfig(coding, num_predict=4096, temperature=0.1),
        "qa": RoleConfig(coding, num_predict=4096, temperature=0.1),
        "reviewer": RoleConfig(research, num_predict=4096, temperature=0.0),
        "reflector": RoleConfig(research, num_predict=6144, temperature=0.1),
    }


def _default_commands() -> dict[str, CommandConfig]:
    return {
        "unit_tests": CommandConfig(
            ("{python}", "-m", "unittest", "discover", "-s", "tests", "-v")
        ),
        "pytest": CommandConfig(("{python}", "-m", "pytest", "-q")),
        "compile_all": CommandConfig(("{python}", "-m", "compileall", "-q", ".")),
    }


@dataclass(frozen=True)
class Config:
    roles: dict[str, RoleConfig] = field(default_factory=_default_roles)
    commands: dict[str, CommandConfig] = field(default_factory=_default_commands)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    llamacpp: LlamaCppConfig = field(default_factory=LlamaCppConfig)
    kimi: KimiConfig = field(default_factory=KimiConfig)
    web: WebConfig = field(default_factory=WebConfig)
    limits: Limits = field(default_factory=Limits)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    dream: DreamConfig = field(default_factory=DreamConfig)

    @classmethod
    def default(cls) -> "Config":
        return cls()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        if not isinstance(data, dict):
            raise ConfigurationError("Configuration root must be a JSON object")
        section_names = {
            "roles",
            "commands",
            "ollama",
            "llamacpp",
            "kimi",
            "web",
            "limits",
            "execution",
            "memory",
            "dream",
        }
        unknown = set(data) - section_names
        if unknown:
            raise ConfigurationError(f"Unknown configuration keys: {sorted(unknown)}")

        roles = _default_roles()
        raw_roles = data.get("roles", {})
        if not isinstance(raw_roles, dict):
            raise ConfigurationError("roles must be an object")
        for name, raw in raw_roles.items():
            if name not in ROLE_NAMES:
                raise ConfigurationError(f"Unknown role: {name}")
            if isinstance(raw, str):
                raw = {"model": raw}
            if not isinstance(raw, dict):
                raise ConfigurationError(f"Role {name} must be an object or model string")
            base = asdict(roles[name])
            unknown_role = set(raw) - set(base)
            if unknown_role:
                raise ConfigurationError(
                    f"Unknown settings for role {name}: {sorted(unknown_role)}"
                )
            base.update(raw)
            roles[name] = RoleConfig(**base)

        commands = _default_commands()
        raw_commands = data.get("commands", {})
        if not isinstance(raw_commands, dict):
            raise ConfigurationError("commands must be an object")
        for name, raw in raw_commands.items():
            if not _COMMAND_ID.fullmatch(name):
                raise ConfigurationError(f"Invalid command id: {name!r}")
            if not isinstance(raw, dict):
                raise ConfigurationError(f"Command {name} must be an object")
            if set(raw) - {"argv", "timeout_seconds", "resume_policy"}:
                raise ConfigurationError(f"Unknown settings for command {name}")
            argv = raw.get("argv")
            if not isinstance(argv, list) or not argv or not all(
                isinstance(part, str) and part for part in argv
            ):
                raise ConfigurationError(f"Command {name} requires a non-empty string argv")
            commands[name] = CommandConfig(
                tuple(argv),
                timeout_seconds=raw.get("timeout_seconds", 120),
                resume_policy=raw.get("resume_policy", "rerun"),
            )

        raw_sections = {}
        for name in section_names - {"roles", "commands"}:
            raw = data.get(name, {})
            if not isinstance(raw, dict):
                raise ConfigurationError(f"{name} must be an object")
            raw_sections[name] = raw

        def section(name: str, factory):
            defaults = asdict(factory())
            tuple_keys = {key for key, value in defaults.items() if isinstance(value, tuple)}
            unknown = set(raw_sections[name]) - set(defaults)
            if unknown:
                raise ConfigurationError(f"Unknown {name} settings: {sorted(unknown)}")
            defaults.update(raw_sections[name])
            for key in tuple_keys:
                defaults[key] = tuple(defaults[key])
            try:
                return factory(**defaults)
            except TypeError as exc:
                raise ConfigurationError(f"Invalid {name} configuration: {exc}") from exc

        config = cls(
            roles=roles,
            commands=commands,
            ollama=section("ollama", OllamaConfig),
            llamacpp=section("llamacpp", LlamaCppConfig),
            kimi=section("kimi", KimiConfig),
            web=section("web", WebConfig),
            limits=section("limits", Limits),
            execution=section("execution", ExecutionConfig),
            memory=section("memory", MemoryConfig),
            dream=section("dream", DreamConfig),
        )
        config.validate()
        return config

    def validate(self) -> None:
        for name in ROLE_NAMES:
            role = self.roles.get(name)
            if role is None:
                raise ConfigurationError(f"Missing role configuration: {name}")
            if not role.model or any(ch.isspace() for ch in role.model):
                raise ConfigurationError(f"Invalid model for role {name}")
            if role.num_predict <= 0 or role.max_turns <= 0:
                raise ConfigurationError(f"Role {name} limits must be positive")
            if not 0 <= role.temperature <= 2:
                raise ConfigurationError(f"Role {name} temperature must be between 0 and 2")
            if role.num_predict + self.limits.safety_reserve_tokens >= self.context_length_for_model(
                role.model
            ):
                raise ConfigurationError(f"Role {name} leaves no input context")
            if self.backend_for_model(role.model) == "kimi" and not self.kimi.enabled:
                raise ConfigurationError(f"Role {name} uses Kimi but kimi is disabled")
        if not self.ollama.base_url.startswith(("http://", "https://")):
            raise ConfigurationError("Ollama base_url must be HTTP(S)")
        for value in (
            self.ollama.context_length,
            self.ollama.load_timeout_seconds,
            self.ollama.request_timeout_seconds,
        ):
            if value <= 0:
                raise ConfigurationError("Ollama timeouts and context must be positive")
        if self.ollama.transport_retries < 0:
            raise ConfigurationError("transport_retries cannot be negative")
        llamacpp = self.llamacpp
        if llamacpp.enabled:
            if not llamacpp.model_name or any(ch.isspace() for ch in llamacpp.model_name):
                raise ConfigurationError("Invalid llamacpp.model_name")
            if not llamacpp.model_path:
                raise ConfigurationError("llamacpp.model_path cannot be empty")
            if not llamacpp.server_binary:
                raise ConfigurationError("llamacpp.server_binary cannot be empty")
            if not 0 < llamacpp.port < 65536:
                raise ConfigurationError("llamacpp.port must be a valid TCP port")
            for value in (
                llamacpp.context_length,
                llamacpp.startup_timeout_seconds,
                llamacpp.request_timeout_seconds,
            ):
                if value <= 0:
                    raise ConfigurationError("llama.cpp timeouts and context must be positive")
            if llamacpp.transport_retries < 0:
                raise ConfigurationError("llamacpp.transport_retries cannot be negative")
            if llamacpp.gpu_layers < 0:
                raise ConfigurationError("llamacpp.gpu_layers cannot be negative")
            if any(not isinstance(arg, str) or not arg for arg in llamacpp.extra_args):
                raise ConfigurationError("llamacpp.extra_args must be non-empty strings")
        else:
            for name in ROLE_NAMES:
                if self.roles[name].model == llamacpp.model_name:
                    raise ConfigurationError(
                        f"Role {name} uses {llamacpp.model_name} but llamacpp is disabled"
                    )
        if self.kimi.enabled:
            if not self.kimi.base_url.startswith("https://") and not self.kimi.base_url.startswith(
                ("http://127.0.0.1", "http://localhost")
            ):
                raise ConfigurationError("Kimi base_url must be HTTPS (loopback HTTP is test-only)")
            if not self.kimi.model_name or any(ch.isspace() for ch in self.kimi.model_name):
                raise ConfigurationError("Invalid kimi.model_name")
            if not _ENV_NAME.fullmatch(self.kimi.api_key_env):
                raise ConfigurationError("kimi.api_key_env must be an environment variable name")
            for value in (
                self.kimi.context_length,
                self.kimi.request_timeout_seconds,
                self.kimi.max_response_bytes,
            ):
                if value <= 0:
                    raise ConfigurationError("Kimi contexts, timeouts, and byte limits must be positive")
            if self.kimi.transport_retries < 0:
                raise ConfigurationError("kimi.transport_retries cannot be negative")
        for name, command in self.commands.items():
            if command.timeout_seconds <= 0:
                raise ConfigurationError(f"Command {name} timeout must be positive")
            if command.resume_policy not in {"rerun", "manual"}:
                raise ConfigurationError(f"Command {name} has invalid resume_policy")
        for name, value in asdict(self.limits).items():
            if not isinstance(value, int) or value < 0:
                raise ConfigurationError(f"Limit {name} must be a non-negative integer")
        if self.limits.max_tasks == 0 or self.limits.max_waves == 0:
            raise ConfigurationError("max_tasks and max_waves must be positive")
        if self.web.max_results <= 0 or self.web.max_bytes <= 0:
            raise ConfigurationError("Web result and byte limits must be positive")
        if "{query}" not in self.web.search_url:
            raise ConfigurationError("web.search_url must contain {query}")
        if not self.execution.lock_path or not self.execution.process_registry_path:
            raise ConfigurationError("Execution lock and process registry paths cannot be empty")
        if not self.memory.root:
            raise ConfigurationError("memory.root cannot be empty")
        if not _NAMESPACE.fullmatch(self.memory.project_id):
            raise ConfigurationError("Invalid memory.project_id")
        if self.memory.classification not in {"public", "shareable", "internal", "private"}:
            raise ConfigurationError("Invalid memory.classification")
        if self.memory.transcript_retention_days < 0:
            raise ConfigurationError("memory.transcript_retention_days cannot be negative")
        if self.memory.max_guidance_documents <= 0 or self.memory.max_search_results <= 0:
            raise ConfigurationError("Memory guidance/search limits must be positive")
        for model in (self.dream.subject_model, self.dream.curator_model):
            backend = self.backend_for_model(model)
            if backend == "llamacpp" and not self.llamacpp.enabled:
                raise ConfigurationError("Dream model requires llama.cpp but it is disabled")
            if backend == "kimi":
                if not self.kimi.enabled:
                    raise ConfigurationError("Dream model uses Kimi but kimi is disabled")
                if not (self.dream.allow_hosted and self.kimi.allow_dreaming):
                    raise ConfigurationError("Hosted dreaming requires dream and Kimi opt-ins")
        for name in (
            "max_transcripts",
            "max_transcript_bytes",
            "max_shards",
            "max_findings",
            "max_proposals",
            "min_distinct_runs",
        ):
            if getattr(self.dream, name) <= 0:
                raise ConfigurationError(f"dream.{name} must be positive")

    def backend_for_model(self, model: str) -> str:
        if model == self.kimi.model_name:
            return "kimi"
        if self.llamacpp.enabled and model == self.llamacpp.model_name:
            return "llamacpp"
        return "ollama"

    def context_length_for_model(self, model: str) -> int:
        backend = self.backend_for_model(model)
        if backend == "kimi":
            return self.kimi.context_length
        if backend == "llamacpp":
            return self.llamacpp.context_length
        return self.ollama.context_length

    def model_for_role(self, role: str) -> str:
        try:
            return self.roles[role].model
        except KeyError as exc:
            raise ConfigurationError(f"Unknown role: {role}") from exc

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_config(path: str | Path | None = None) -> Config:
    if path is None:
        return Config.default()
    config_path = Path(path)
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Cannot load configuration {config_path}: {exc}") from exc
    return Config.from_dict(data)
