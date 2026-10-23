from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Iterable

from .config import Config
from .errors import PlanValidationError


TASK_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
TASK_KINDS = {"research", "specification", "implement", "test", "review", "repair", "generic"}
TERMINAL_STATUSES = {"succeeded", "failed", "blocked", "skipped"}


def safe_relative_path(value: Any, *, allow_dot: bool = False) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise PlanValidationError(f"Invalid relative path: {value!r}")
    if value.startswith("/"):
        raise PlanValidationError(f"Absolute paths are forbidden: {value}")
    path = PurePosixPath(value)
    if ".." in path.parts:
        raise PlanValidationError(f"Parent traversal is forbidden: {value}")
    normalized = path.as_posix()
    if normalized == "." and not allow_dot:
        raise PlanValidationError("A file path is required")
    if normalized.startswith("~"):
        raise PlanValidationError(f"Home-relative paths are forbidden: {value}")
    return normalized


def safe_run_path(value: Any) -> str:
    normalized = safe_relative_path(value)
    if normalized.split("/", 1)[0] not in {"artifacts", "workspace"}:
        raise PlanValidationError(
            f"Run path must start with artifacts/ or workspace/: {value}"
        )
    return normalized


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PlanValidationError(f"{label} must be an array of strings")
    return value


@dataclass
class Acceptance:
    id: str
    description: str
    type: str
    required: bool = True
    command_id: str | None = None
    path: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], config: Config) -> "Acceptance":
        if not isinstance(data, dict):
            raise PlanValidationError("Acceptance entries must be objects")
        allowed = {"id", "description", "type", "required", "command_id", "path"}
        if set(data) - allowed:
            raise PlanValidationError(f"Unknown acceptance fields: {sorted(set(data) - allowed)}")
        acceptance = cls(
            id=data.get("id", ""),
            description=data.get("description", ""),
            type=data.get("type", ""),
            required=data.get("required", True),
            command_id=data.get("command_id"),
            path=data.get("path"),
        )
        if not TASK_ID.fullmatch(acceptance.id):
            raise PlanValidationError(f"Invalid acceptance id: {acceptance.id!r}")
        if not acceptance.description.strip():
            raise PlanValidationError(f"Acceptance {acceptance.id} needs a description")
        if not isinstance(acceptance.required, bool):
            raise PlanValidationError(f"Acceptance {acceptance.id} required must be boolean")
        if acceptance.type == "command":
            if acceptance.command_id not in config.commands:
                raise PlanValidationError(
                    f"Acceptance {acceptance.id} references unknown command {acceptance.command_id}"
                )
            if acceptance.path is not None:
                raise PlanValidationError(f"Command acceptance {acceptance.id} cannot have path")
        elif acceptance.type == "file":
            if acceptance.path is None:
                raise PlanValidationError(f"File acceptance {acceptance.id} needs path")
            acceptance.path = safe_run_path(acceptance.path)
            if acceptance.command_id is not None:
                raise PlanValidationError(f"File acceptance {acceptance.id} cannot have command_id")
        else:
            raise PlanValidationError(f"Acceptance {acceptance.id} has unsupported type")
        return acceptance

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.id,
            "description": self.description,
            "type": self.type,
            "required": self.required,
        }
        if self.command_id is not None:
            result["command_id"] = self.command_id
        if self.path is not None:
            result["path"] = self.path
        return result


@dataclass
class Task:
    id: str
    kind: str
    role: str
    instruction: str
    model: str
    depends_on: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    artifact_outputs: list[str] = field(default_factory=list)
    write_scope: list[str] = field(default_factory=list)
    max_turns: int = 8

    @classmethod
    def from_dict(cls, data: dict[str, Any], config: Config) -> "Task":
        if not isinstance(data, dict):
            raise PlanValidationError("Tasks must be objects")
        allowed = {
            "id",
            "kind",
            "role",
            "instruction",
            "model",
            "depends_on",
            "inputs",
            "artifact_outputs",
            "write_scope",
            "max_turns",
        }
        if set(data) - allowed:
            raise PlanValidationError(f"Unknown task fields: {sorted(set(data) - allowed)}")
        role = data.get("role", "")
        if role not in config.roles:
            raise PlanValidationError(f"Unknown task role: {role!r}")
        configured_model = config.model_for_role(role)
        if "model" in data and data["model"] != configured_model:
            raise PlanValidationError(
                f"Task {data.get('id')} cannot override role model {configured_model}"
            )
        task = cls(
            id=data.get("id", ""),
            kind=data.get("kind", ""),
            role=role,
            instruction=data.get("instruction", ""),
            model=configured_model,
            depends_on=_string_list(data.get("depends_on", []), "depends_on"),
            inputs=_string_list(data.get("inputs", []), "inputs"),
            artifact_outputs=_string_list(
                data.get("artifact_outputs", []), "artifact_outputs"
            ),
            write_scope=_string_list(data.get("write_scope", []), "write_scope"),
            max_turns=data.get("max_turns", config.roles[role].max_turns),
        )
        if not TASK_ID.fullmatch(task.id):
            raise PlanValidationError(f"Invalid task id: {task.id!r}")
        if task.kind not in TASK_KINDS:
            raise PlanValidationError(f"Task {task.id} has invalid kind {task.kind!r}")
        if not task.instruction.strip():
            raise PlanValidationError(f"Task {task.id} needs an instruction")
        if not isinstance(task.max_turns, int) or not 1 <= task.max_turns <= 32:
            raise PlanValidationError(f"Task {task.id} max_turns must be between 1 and 32")
        task.depends_on = list(dict.fromkeys(task.depends_on))
        task.inputs = [safe_run_path(path) for path in task.inputs]
        task.artifact_outputs = [
            safe_relative_path(path) for path in task.artifact_outputs
        ]
        for path in task.artifact_outputs:
            if path.split("/", 1)[0] in {"artifacts", "workspace"}:
                raise PlanValidationError(
                    f"Artifact output {path} must be relative to the artifacts directory"
                )
        task.write_scope = [_normalise_scope(path) for path in task.write_scope]
        return task

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "role": self.role,
            "model": self.model,
            "instruction": self.instruction,
            "depends_on": self.depends_on,
            "inputs": self.inputs,
            "artifact_outputs": self.artifact_outputs,
            "write_scope": self.write_scope,
            "max_turns": self.max_turns,
        }


def _normalise_scope(value: str) -> str:
    directory = value.endswith("/") or value in {".", "./"}
    normalized = safe_relative_path(value, allow_dot=True)
    if normalized == ".":
        return "./"
    return normalized + ("/" if directory else "")


def scopes_overlap(left: str, right: str) -> bool:
    if left == "./" or right == "./":
        return True
    left_dir = left.endswith("/")
    right_dir = right.endswith("/")
    left_clean = left.rstrip("/")
    right_clean = right.rstrip("/")
    if left_dir and right_dir:
        return left_clean == right_clean or left_clean.startswith(
            right_clean + "/"
        ) or right_clean.startswith(left_clean + "/")
    if left_dir:
        return right_clean == left_clean or right_clean.startswith(left_clean + "/")
    if right_dir:
        return left_clean == right_clean or left_clean.startswith(right_clean + "/")
    return left_clean == right_clean


@dataclass
class Plan:
    goal: str
    tasks: list[Task]
    acceptance: list[Acceptance]
    revision: int = 1
    schema_version: int = 1
    root_cause: str | None = None
    _ranks: dict[str, int] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._ranks = self._validate()

    @classmethod
    def from_dict(cls, data: dict[str, Any], config: Config) -> "Plan":
        if not isinstance(data, dict):
            raise PlanValidationError("Plan must be a JSON object")
        allowed = {"schema_version", "revision", "goal", "tasks", "acceptance", "root_cause"}
        if set(data) - allowed:
            raise PlanValidationError(f"Unknown plan fields: {sorted(set(data) - allowed)}")
        if data.get("schema_version", 1) != 1:
            raise PlanValidationError("Unsupported plan schema_version")
        raw_tasks = data.get("tasks")
        raw_acceptance = data.get("acceptance")
        if not isinstance(raw_tasks, list) or not isinstance(raw_acceptance, list):
            raise PlanValidationError("Plan tasks and acceptance must be arrays")
        if len(raw_tasks) > config.limits.max_tasks:
            raise PlanValidationError("Plan exceeds max_tasks")
        plan = cls(
            goal=data.get("goal", ""),
            tasks=[Task.from_dict(item, config) for item in raw_tasks],
            acceptance=[Acceptance.from_dict(item, config) for item in raw_acceptance],
            revision=data.get("revision", 1),
            schema_version=1,
            root_cause=data.get("root_cause"),
        )
        return plan

    def _validate(self) -> dict[str, int]:
        if not self.goal.strip():
            raise PlanValidationError("Plan goal cannot be empty")
        if not isinstance(self.revision, int) or self.revision < 1:
            raise PlanValidationError("Plan revision must be a positive integer")
        if not self.tasks:
            raise PlanValidationError("Plan must contain at least one task")
        if not self.acceptance:
            raise PlanValidationError("Plan must contain acceptance checks")
        ids = [task.id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise PlanValidationError("Task ids must be unique")
        task_map = {task.id: task for task in self.tasks}
        for task in self.tasks:
            for dependency in task.depends_on:
                if dependency not in task_map:
                    raise PlanValidationError(
                        f"Task {task.id} has unknown dependency {dependency}"
                    )
                if dependency == task.id:
                    raise PlanValidationError(f"Task {task.id} depends on itself")
        acceptance_ids = [item.id for item in self.acceptance]
        if len(acceptance_ids) != len(set(acceptance_ids)):
            raise PlanValidationError("Acceptance ids must be unique")
        owners: dict[str, str] = {}
        for task in self.tasks:
            for output in task.artifact_outputs:
                if output in owners:
                    raise PlanValidationError(
                        f"Artifact {output} has multiple owners: {owners[output]}, {task.id}"
                    )
                owners[output] = task.id
        ranks = self._topological_ranks(task_map)
        ancestors = {task_id: self._ancestors(task_id, task_map) for task_id in ids}
        for index, left in enumerate(self.tasks):
            for right in self.tasks[index + 1 :]:
                ordered = left.id in ancestors[right.id] or right.id in ancestors[left.id]
                if ordered:
                    continue
                for left_scope in left.write_scope:
                    for right_scope in right.write_scope:
                        if scopes_overlap(left_scope, right_scope):
                            raise PlanValidationError(
                                f"Concurrent tasks {left.id} and {right.id} have overlapping "
                                f"write scopes {left_scope} and {right_scope}; add a dependency"
                            )
        return ranks

    @staticmethod
    def _topological_ranks(task_map: dict[str, Task]) -> dict[str, int]:
        ranks: dict[str, int] = {}
        visiting: set[str] = set()

        def visit(task_id: str) -> int:
            if task_id in ranks:
                return ranks[task_id]
            if task_id in visiting:
                raise PlanValidationError(f"Dependency cycle includes {task_id}")
            visiting.add(task_id)
            task = task_map[task_id]
            rank = 0 if not task.depends_on else 1 + max(
                visit(dependency) for dependency in task.depends_on
            )
            visiting.remove(task_id)
            ranks[task_id] = rank
            return rank

        for task_id in task_map:
            visit(task_id)
        return ranks

    @staticmethod
    def _ancestors(task_id: str, task_map: dict[str, Task]) -> set[str]:
        result: set[str] = set()
        pending = list(task_map[task_id].depends_on)
        while pending:
            current = pending.pop()
            if current in result:
                continue
            result.add(current)
            pending.extend(task_map[current].depends_on)
        return result

    @property
    def ranks(self) -> dict[str, int]:
        return dict(self._ranks)

    @property
    def required_models(self) -> list[str]:
        return sorted({task.model for task in self.tasks})

    def task(self, task_id: str) -> Task:
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise KeyError(task_id)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": 1,
            "revision": self.revision,
            "goal": self.goal,
            "tasks": [task.to_dict() for task in self.tasks],
            "acceptance": [item.to_dict() for item in self.acceptance],
        }
        if self.root_cause is not None:
            result["root_cause"] = self.root_cause
        return result

    def with_repairs(
        self, patch: dict[str, Any], config: Config
    ) -> "Plan":
        if not isinstance(patch, dict) or set(patch) - {"root_cause", "tasks"}:
            raise PlanValidationError("Repair patch accepts only root_cause and tasks")
        root_cause = patch.get("root_cause")
        raw_tasks = patch.get("tasks")
        if not isinstance(root_cause, str) or not root_cause.strip():
            raise PlanValidationError("Repair patch needs root_cause")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise PlanValidationError("Repair patch needs at least one task")
        if len(self.tasks) + len(raw_tasks) > config.limits.max_tasks:
            raise PlanValidationError("Repair patch exceeds max_tasks")
        existing_ids = {task.id for task in self.tasks}
        for raw in raw_tasks:
            if isinstance(raw, dict) and raw.get("id") in existing_ids:
                raise PlanValidationError(f"Repair cannot rewrite completed task {raw.get('id')}")
        combined = self.to_dict()
        combined["revision"] = self.revision + 1
        combined["root_cause"] = root_cause
        combined["tasks"].extend(raw_tasks)
        return Plan.from_dict(combined, config)


def task_order(tasks: Iterable[Task], ranks: dict[str, int]) -> list[Task]:
    return sorted(tasks, key=lambda task: (ranks[task.id], task.id))
