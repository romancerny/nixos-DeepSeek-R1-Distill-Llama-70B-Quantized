from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

from .config import Config, load_config
from .errors import AgenticError, ConfigurationError, StorageError
from .ollama import OllamaClient
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
    client = OllamaClient(config.ollama)
    available = set()
    try:
        tags = client.tags()
        for model in tags.get("models", []):
            if isinstance(model, dict):
                available.add(model.get("name") or model.get("model"))
        available.discard(None)
        checks.append({"name": "ollama_api", "ok": True, "models": sorted(available)})
    except AgenticError as exc:
        checks.append({"name": "ollama_api", "ok": False, "error": str(exc)})
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


def _offload(config: Config, state_dir: str) -> int:
    lock_path = Path(state_dir).expanduser().resolve() / "executor.lock"
    client = OllamaClient(config.ollama)
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

    resume = subparsers.add_parser("resume", help="Resume an interrupted or paused run")
    resume.add_argument("run_id")
    config_option(resume, required=False)
    state_option(resume)

    status = subparsers.add_parser("status", help="Read canonical run state")
    status.add_argument("run_id")
    state_option(status)
    status.add_argument("--json", action="store_true")

    report = subparsers.add_parser("report", help="Print or regenerate a run report")
    report.add_argument("run_id")
    state_option(report)

    offload = subparsers.add_parser("offload", help="Explicitly unload Ollama models under the executor lock")
    config_option(offload)
    state_option(offload)
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
            result = ProjectRunner(store, config).execute(
                stop_after_plan=arguments.stop_after_plan
            )
            _print_run_result(store)
            return 0 if result["status"] in {"succeeded", "paused_after_plan"} else 1
        if arguments.command == "resume":
            store = RunStore.open(arguments.state_dir, arguments.run_id)
            config = (
                load_config(arguments.config)
                if arguments.config
                else _config_from_snapshot(store)
            )
            result = ProjectRunner(store, config).execute()
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
            return _offload(load_config(arguments.config), arguments.state_dir)
        parser.error(f"Unknown command {arguments.command}")
        return 2
    except (AgenticError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
