from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

from .backends import ModelBackends
from .config import Config, load_config
from .documents import MemoryDocument
from .errors import AgenticError, ConfigurationError, StorageError
from .identity import (
    AGENT_OS_USER,
    HUMAN_OS_USER,
    Actor,
    MemoryScope,
    current_username,
    require_current_user,
)
from .memory import MemoryStore
from .reporting import generate_report
from .runner import ProjectRunner
from .storage import FileLock, RunStore, read_json


def _config_from_snapshot(store: RunStore) -> Config:
    return Config.from_dict(read_json(store.run_dir / "config.json"))


def _doctor(config: Config, state_dir: str) -> tuple[bool, dict]:
    checks = []
    try:
        state = Path(state_dir).expanduser().resolve()
        state.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=state):
            pass
        checks.append({"name": "state_directory", "ok": True, "path": str(state)})
    except OSError as exc:
        checks.append({"name": "state_directory", "ok": False, "error": str(exc)})
    backends = ModelBackends(config)
    available = set()
    try:
        tags = backends.tags()
        for model in tags.get("models", []):
            if isinstance(model, dict):
                available.add(model.get("name") or model.get("model"))
        available.discard(None)
        checks.append({"name": "ollama_api", "ok": True, "models": sorted(available)})
    except AgenticError as exc:
        checks.append({"name": "ollama_api", "ok": False, "error": str(exc)})
    if config.llamacpp.enabled:
        binary = config.llamacpp.server_binary
        binary_found = (
            Path(binary).is_file() if Path(binary).is_absolute() else shutil.which(binary)
        )
        checks.append(
            {
                "name": "llamacpp_binary",
                "ok": binary_found is not None and binary_found is not False,
                "executable": binary,
            }
        )
        model_path = backends.llamacpp.resolved_model_path()
        checks.append(
            {
                "name": "llamacpp_model_file",
                "ok": model_path.is_file(),
                "path": str(model_path),
            }
        )
        if model_path.is_file():
            available.add(config.llamacpp.model_name)
    if config.kimi.enabled:
        checks.append(
            {
                "name": "kimi_credentials",
                "ok": backends.kimi.credential_available(),
                "environment_variable": config.kimi.api_key_env,
                "approved": config.kimi.approved,
            }
        )
    required = sorted({role.model for role in config.roles.values()})
    missing = sorted(set(required) - available)
    checks.append(
        {
            "name": "required_models",
            "ok": not missing and bool(available),
            "required": required,
            "missing": missing,
        }
    )
    for command_id, command in config.commands.items():
        argv = command.resolved_argv()
        executable = argv[0]
        found = (
            Path(executable).is_file()
            if Path(executable).is_absolute()
            else shutil.which(executable) is not None
        )
        checks.append(
            {"name": f"command:{command_id}", "ok": found, "executable": executable}
        )
    ok = all(check["ok"] for check in checks)
    return ok, {"ok": ok, "checks": checks}


def _print_run_result(store: RunStore) -> None:
    run = store.load_run()
    print(f"Run {store.run_id}: {run['status']}")
    print(f"Report: {store.run_dir / 'report.md'}")
    print(f"Workspace: {store.workspace_dir}")


def _memory_scope(arguments) -> MemoryScope:
    namespace = arguments.namespace or (
        "global" if arguments.scope in {"org", "skills"} else "default"
    )
    if arguments.scope == "scratch" and not arguments.namespace:
        namespace = "cli"
    return MemoryScope(arguments.scope, namespace)


def _read_actor(arguments) -> Actor:
    username = current_username()
    if username == HUMAN_OS_USER:
        return Actor(kind="human", os_user=HUMAN_OS_USER, display_name=arguments.actor_name)
    if username == AGENT_OS_USER:
        agent_id = arguments.agent_id or "cli"
        projects = tuple(arguments.project or [])
        if arguments.scope in {"curated", "inbox"}:
            projects = tuple(dict.fromkeys((*projects, _memory_scope(arguments).namespace)))
        if arguments.scope == "scratch":
            agent_id = _memory_scope(arguments).namespace
        return Actor(
            kind="agent",
            os_user=AGENT_OS_USER,
            agent_id=agent_id,
            projects=projects,
        )
    raise ConfigurationError(f"Unsupported OS user for agentic-ai: {username}")


def _human_actor(arguments) -> Actor:
    return Actor.human(display_name=arguments.actor_name)


def _handle_memory(arguments) -> int:
    store = MemoryStore(arguments.root)
    action = arguments.memory_action
    if action == "init":
        print(json.dumps({"initialized": store.initialize(_human_actor(arguments))}, indent=2))
        return 0
    if action == "put":
        document = MemoryDocument.from_text(
            Path(arguments.file).read_text(encoding="utf-8")
        )
        record = store.put(
            _memory_scope(arguments),
            document,
            _human_actor(arguments),
            expected_sha256=arguments.expected_sha256,
            operation=arguments.operation,
            mutation_id=arguments.mutation_id,
        )
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0
    if action == "search":
        actor = _read_actor(arguments)
        scope = _memory_scope(arguments) if arguments.scope else None
        results = store.search(
            actor,
            arguments.query or "",
            scope=scope,
            kind=arguments.kind,
            tags=arguments.tag or [],
            limit=arguments.limit,
        )
        print(json.dumps(results, indent=2, sort_keys=True))
        return 0
    if action == "read":
        document, version = store.read(
            _memory_scope(arguments), arguments.document_id, _read_actor(arguments)
        )
        if arguments.json:
            print(json.dumps({"document": document.to_bytes().decode(), "version": version}, indent=2))
        else:
            print(document.to_bytes().decode(), end="")
        return 0
    if action == "history":
        print(json.dumps(store.history(_memory_scope(arguments), arguments.document_id, _read_actor(arguments)), indent=2))
        return 0
    if action == "diff":
        print(
            store.diff(
                _memory_scope(arguments),
                arguments.document_id,
                _read_actor(arguments),
                from_version=arguments.from_version,
                to_version=arguments.to_version,
            ),
            end="",
        )
        return 0
    if action == "rollback":
        record = store.rollback(
            _memory_scope(arguments),
            arguments.document_id,
            arguments.version_id,
            _human_actor(arguments),
            expected_sha256=arguments.expected_sha256,
            reason=arguments.reason,
        )
        print(json.dumps(record, indent=2))
        return 0
    if action == "delete":
        record = store.delete(
            _memory_scope(arguments),
            arguments.document_id,
            _human_actor(arguments),
            expected_sha256=arguments.expected_sha256,
            reason=arguments.reason,
        )
        print(json.dumps(record, indent=2))
        return 0
    if action == "redact":
        marker = store.redact(
            _memory_scope(arguments),
            arguments.document_id,
            _human_actor(arguments),
            reason=arguments.reason,
        )
        print(json.dumps(marker, indent=2))
        return 0
    if action == "verify":
        errors = store.verify(raise_on_error=False)
        print(json.dumps({"ok": not errors, "errors": errors}, indent=2))
        return 0 if not errors else 1
    if action == "reindex":
        results = store.search(_read_actor(arguments), limit=1)
        print(json.dumps({"ok": True, "indexed_sample": len(results)}))
        return 0
    if action == "export":
        manifest = store.export(_human_actor(arguments), arguments.destination)
        print(json.dumps(manifest, indent=2))
        return 0
    if action == "import":
        expected = {}
        if arguments.expected:
            expected = json.loads(Path(arguments.expected).read_text(encoding="utf-8"))
        versions = store.import_(_human_actor(arguments), arguments.source, expected=expected)
        print(json.dumps(versions, indent=2))
        return 0
    raise ConfigurationError(f"Unknown memory action: {action}")


def _offload(config: Config, state_dir: str) -> int:
    lock_path = Path(config.execution.lock_path).expanduser()
    client = ModelBackends(config)
    owned = {role.model for role in config.roles.values()}
    with FileLock(lock_path):
        names = client.model_names()
        unexpected = [name for name in names if name not in owned]
        if unexpected and not config.ollama.dedicated_ollama:
            raise ConfigurationError(
                "Refusing to offload external models without dedicated_ollama=true: "
                + ", ".join(unexpected)
            )
        for name in names:
            print(f"Unloading {name}")
            client.unload_model(name)
            deadline = time.monotonic() + config.ollama.load_timeout_seconds
            while name in client.model_names():
                if time.monotonic() >= deadline:
                    raise AgenticError(f"Timed out unloading {name}")
                time.sleep(0.2)
        print(f"Resident models: {client.model_names()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentic-ai",
        description="Autonomous file-backed multi-agent projects with one resident Ollama model",
    )
    subparsers = parser.add_subparsers(dest="command")

    def config_option(subparser, required=True):
        subparser.add_argument("--config", required=required, help="JSON configuration")

    def state_option(subparser):
        subparser.add_argument("--state-dir", default=".agentic-ai")

    doctor = subparsers.add_parser("doctor", help="Check runtime without loading large models")
    config_option(doctor)
    state_option(doctor)
    doctor.add_argument("--json", action="store_true")

    run = subparsers.add_parser("run", help="Start a complete autonomous project")
    config_option(run)
    state_option(run)
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--goal-file")
    source.add_argument("--goal")
    run.add_argument("--run-id", help="Optional deterministic run id")
    run.add_argument("--stop-after-plan", action="store_true")
    run.add_argument("--approve-hosted", action="store_true")

    resume = subparsers.add_parser("resume", help="Resume an interrupted or paused run")
    resume.add_argument("run_id")
    config_option(resume, required=False)
    state_option(resume)
    resume.add_argument("--approve-hosted", action="store_true")

    status = subparsers.add_parser("status", help="Read canonical run state")
    status.add_argument("run_id")
    state_option(status)
    status.add_argument("--json", action="store_true")

    report = subparsers.add_parser("report", help="Print or regenerate a run report")
    report.add_argument("run_id")
    state_option(report)

    offload = subparsers.add_parser("offload", help="Explicitly unload local models under the executor lock")
    config_option(offload)
    state_option(offload)

    memory = subparsers.add_parser("memory", help="Versioned human/agent memory and skills")
    memory_commands = memory.add_subparsers(dest="memory_action", required=True)

    def memory_command(name, *, scoped=True):
        command = memory_commands.add_parser(name)
        command.add_argument("--root", required=True)
        command.add_argument("--scope", choices=["org", "skills", "curated", "inbox", "scratch"], required=scoped)
        command.add_argument("--namespace")
        command.add_argument("--actor-name")
        command.add_argument("--agent-id")
        command.add_argument("--project", action="append")
        return command

    memory_command("init", scoped=False)
    put = memory_command("put")
    put.add_argument("--file", required=True)
    put.add_argument("--expected-sha256")
    put.add_argument("--operation", choices=["created", "modified", "imported"], default="modified")
    put.add_argument("--mutation-id")
    search = memory_command("search", scoped=False)
    search.add_argument("--query")
    search.add_argument("--kind")
    search.add_argument("--tag", action="append")
    search.add_argument("--limit", type=int, default=20)
    read = memory_command("read")
    read.add_argument("document_id")
    read.add_argument("--json", action="store_true")
    history = memory_command("history")
    history.add_argument("document_id")
    diff = memory_command("diff")
    diff.add_argument("document_id")
    diff.add_argument("--from-version", required=True)
    diff.add_argument("--to-version")
    rollback = memory_command("rollback")
    rollback.add_argument("document_id")
    rollback.add_argument("version_id")
    rollback.add_argument("--expected-sha256", required=True)
    rollback.add_argument("--reason", default="")
    delete = memory_command("delete")
    delete.add_argument("document_id")
    delete.add_argument("--expected-sha256", required=True)
    delete.add_argument("--reason", default="")
    redact = memory_command("redact")
    redact.add_argument("document_id")
    redact.add_argument("--reason", required=True)
    memory_command("verify", scoped=False)
    memory_command("reindex", scoped=False)
    export = memory_command("export", scoped=False)
    export.add_argument("--destination", required=True)
    import_command = memory_command("import", scoped=False)
    import_command.add_argument("--source", required=True)
    import_command.add_argument("--expected")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if not arguments.command:
        parser.print_help()
        return 2
    try:
        if arguments.command == "doctor":
            config = load_config(arguments.config)
            ok, result = _doctor(config, arguments.state_dir)
            if arguments.json:
                print(json.dumps(result, indent=2))
            else:
                for check in result["checks"]:
                    detail = check.get("error") or check.get("missing") or check.get("path") or check.get("executable") or ""
                    print(f"{'OK' if check['ok'] else 'FAIL'} {check['name']} {detail}")
            return 0 if ok else 1
        if arguments.command == "run":
            require_current_user(AGENT_OS_USER)
            config = load_config(arguments.config)
            if arguments.goal_file:
                brief = Path(arguments.goal_file).read_text(encoding="utf-8")
            else:
                brief = arguments.goal
            if not brief.strip():
                raise ConfigurationError("Project goal cannot be empty")
            store = RunStore.create(
                arguments.state_dir, brief, config.to_dict(), arguments.run_id
            )
            print(f"Run ID: {store.run_id}", flush=True)
            result = ProjectRunner(
                store, config, approve_hosted=arguments.approve_hosted
            ).execute(
                stop_after_plan=arguments.stop_after_plan
            )
            _print_run_result(store)
            return 0 if result["status"] in {"succeeded", "paused_after_plan"} else 1
        if arguments.command == "resume":
            require_current_user(AGENT_OS_USER)
            store = RunStore.open(arguments.state_dir, arguments.run_id)
            config = (
                load_config(arguments.config)
                if arguments.config
                else _config_from_snapshot(store)
            )
            result = ProjectRunner(
                store, config, approve_hosted=arguments.approve_hosted
            ).execute()
            _print_run_result(store)
            return 0 if result["status"] == "succeeded" else 1
        if arguments.command == "status":
            store = RunStore.open(arguments.state_dir, arguments.run_id)
            run = store.load_run()
            if arguments.json:
                print(json.dumps(run, indent=2, sort_keys=True))
            else:
                print(f"Run {run['run_id']}: {run['status']}")
                print(f"Plan revision: {run.get('plan_revision', 0)}; repair cycle: {run.get('repair_cycle', 0)}")
                for task_id, state in run.get("task_states", {}).items():
                    print(f"  {task_id}: {state.get('status')}")
            return 0
        if arguments.command == "report":
            store = RunStore.open(arguments.state_dir, arguments.run_id)
            if not (store.run_dir / "report.md").is_file():
                generate_report(store)
            print((store.run_dir / "report.md").read_text(encoding="utf-8"))
            return 0
        if arguments.command == "offload":
            require_current_user(AGENT_OS_USER)
            return _offload(load_config(arguments.config), arguments.state_dir)
        if arguments.command == "memory":
            return _handle_memory(arguments)
        parser.error(f"Unknown command {arguments.command}")
        return 2
    except (AgenticError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
