from __future__ import annotations

import os
import pwd
from dataclasses import dataclass
from typing import Any

from .errors import IdentityError


AGENT_OS_USER = "ai-agent"
HUMAN_OS_USER = "roman"


def current_username() -> str:
    return pwd.getpwuid(os.geteuid()).pw_name


def require_current_user(expected: str) -> None:
    actual = current_username()
    if actual != expected:
        raise IdentityError(f"This operation must run as {expected}, not {actual}")


@dataclass(frozen=True)
class Actor:
    kind: str
    os_user: str
    agent_id: str | None = None
    projects: tuple[str, ...] = ()
    display_name: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"human", "agent"}:
            raise IdentityError(f"Unknown actor kind: {self.kind}")
        expected = HUMAN_OS_USER if self.kind == "human" else AGENT_OS_USER
        if self.os_user != expected:
            raise IdentityError(f"{self.kind} actor must use OS user {expected}")
        if self.kind == "agent" and not self.agent_id:
            raise IdentityError("Agent actors require agent_id")

    @classmethod
    def human(cls, display_name: str | None = None) -> "Actor":
        require_current_user(HUMAN_OS_USER)
        return cls(kind="human", os_user=HUMAN_OS_USER, display_name=display_name)

    @classmethod
    def agent(
        cls, agent_id: str, *, projects: tuple[str, ...] = ()
    ) -> "Actor":
        require_current_user(AGENT_OS_USER)
        return cls(kind="agent", os_user=AGENT_OS_USER, agent_id=agent_id, projects=projects)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": self.kind, "os_user": self.os_user}
        if self.agent_id:
            result["agent_id"] = self.agent_id
        if self.projects:
            result["projects"] = list(self.projects)
        if self.display_name:
            result["display_name"] = self.display_name
        return result


@dataclass(frozen=True)
class MemoryScope:
    kind: str
    namespace: str = "global"

    def __post_init__(self) -> None:
        if self.kind not in {"org", "skills", "curated", "inbox", "scratch"}:
            raise IdentityError(f"Unknown memory scope: {self.kind}")

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "namespace": self.namespace}


class MemoryPolicy:
    @staticmethod
    def can_read(actor: Actor, scope: MemoryScope) -> bool:
        if actor.kind == "human":
            return True
        if scope.kind in {"org", "skills"}:
            return True
        if scope.kind in {"curated", "inbox"}:
            return scope.namespace in actor.projects
        return scope.kind == "scratch" and scope.namespace == actor.agent_id

    @staticmethod
    def can_write(actor: Actor, scope: MemoryScope) -> bool:
        if actor.kind == "human":
            return True
        if scope.kind == "inbox":
            return scope.namespace in actor.projects
        return scope.kind == "scratch" and scope.namespace == actor.agent_id

    @classmethod
    def require_read(cls, actor: Actor, scope: MemoryScope) -> None:
        if not cls.can_read(actor, scope):
            raise IdentityError(
                f"{actor.kind} {actor.agent_id or actor.os_user} cannot read "
                f"{scope.kind}/{scope.namespace}"
            )

    @classmethod
    def require_write(cls, actor: Actor, scope: MemoryScope) -> None:
        if not cls.can_write(actor, scope):
            raise IdentityError(
                f"{actor.kind} {actor.agent_id or actor.os_user} cannot write "
                f"{scope.kind}/{scope.namespace}"
            )

    @staticmethod
    def require_human(actor: Actor, operation: str) -> None:
        if actor.kind != "human":
            raise IdentityError(f"{operation} requires the roman human actor")
