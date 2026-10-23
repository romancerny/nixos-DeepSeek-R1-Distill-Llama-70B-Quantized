from __future__ import annotations

import json
import re
import sys
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


def _default_roles() -> dict[str, RoleConfig]:
    research = "deepseek-r1:70b"
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
    web: WebConfig = field(default_factory=WebConfig)
    limits: Limits = field(default_factory=Limits)

    @classmethod
    def default(cls) -> "Config":
        return cls()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        if not isinstance(data, dict):
            raise ConfigurationError("Configuration root must be a JSON object")
        unknown = set(data) - {"roles", "commands", "ollama", "web", "limits"}
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

        ollama_raw = data.get("ollama", {})
        web_raw = data.get("web", {})
        limits_raw = data.get("limits", {})
        for label, raw in (("ollama", ollama_raw), ("web", web_raw), ("limits", limits_raw)):
            if not isinstance(raw, dict):
                raise ConfigurationError(f"{label} must be an object")
        try:
            ollama_defaults = asdict(OllamaConfig())
            if set(ollama_raw) - set(ollama_defaults):
                raise ConfigurationError("Unknown Ollama settings")
            ollama_defaults.update(ollama_raw)
            ollama = OllamaConfig(**ollama_defaults)

            web_defaults = asdict(WebConfig())
            if set(web_raw) - set(web_defaults):
                raise ConfigurationError("Unknown web settings")
            web_defaults.update(web_raw)
            if "allowed_domains" in web_defaults:
                web_defaults["allowed_domains"] = tuple(web_defaults["allowed_domains"])
            web = WebConfig(**web_defaults)

            limits_defaults = asdict(Limits())
            if set(limits_raw) - set(limits_defaults):
                raise ConfigurationError("Unknown limit settings")
            limits_defaults.update(limits_raw)
            limits = Limits(**limits_defaults)
        except TypeError as exc:
            raise ConfigurationError(str(exc)) from exc

        config = cls(roles, commands, ollama, web, limits)
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
            if role.num_predict + self.limits.safety_reserve_tokens >= self.ollama.context_length:
                raise ConfigurationError(f"Role {name} leaves no input context")
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
