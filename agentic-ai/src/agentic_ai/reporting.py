from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .storage import RunStore, atomic_write_json, atomic_write_text, read_json, utc_now


def _read_all(directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    return [read_json(path) for path in sorted(directory.glob("*.json"))]


def generate_report(store: RunStore) -> dict[str, Any]:
    run = store.load_run()
    evaluations = _read_all(store.run_dir / "evaluations")
    waves = _read_all(store.run_dir / "waves")
    switches = _read_all(store.run_dir / "switches")
    latest = evaluations[-1] if evaluations else None
    artifacts: dict[str, dict[str, Any]] = {}
    for state in run.get("task_states", {}).values():
        for record in state.get("outputs", []):
            artifacts[record["path"]] = record
    report = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "run_id": store.run_id,
        "status": run["status"],
        "goal": run["goal"],
        "created_at": run["created_at"],
        "updated_at": run["updated_at"],
        "plan_revision": run.get("plan_revision", 0),
        "repair_cycle": run.get("repair_cycle", 0),
        "task_states": run.get("task_states", {}),
        "acceptance": latest,
        "evaluations": evaluations,
        "artifacts": sorted(artifacts.values(), key=lambda item: item["path"]),
        "waves": waves,
        "switches": switches,
        "metrics": run.get("metrics", {}),
        "error": run.get("error"),
    }
    atomic_write_json(store.run_dir / "report.json", report)

    lines = [
        f"# Agentic run {store.run_id}",
        "",
        f"- **Status:** {run['status']}",
        f"- **Plan revision:** {run.get('plan_revision', 0)}",
        f"- **Repair cycles:** {run.get('repair_cycle', 0)}",
        f"- **Model waves / verified switches:** {len(waves)} / {len(switches)}",
        "",
        "## Goal",
        "",
        run["goal"],
        "",
        "## Tasks",
        "",
        "| Task | Status | Attempt | Turns | Summary / error |",
        "|---|---|---:|---:|---|",
    ]
    for task_id, state in run.get("task_states", {}).items():
        detail = state.get("error") or state.get("summary") or ""
        detail = str(detail).replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{task_id}` | {state.get('status')} | {state.get('attempt', 0)} | "
            f"{state.get('turns', 0)} | {detail} |"
        )
    lines.extend(["", "## Latest acceptance evaluation", ""])
    if latest is None:
        lines.append("No acceptance evaluation completed.")
    else:
        lines.append(
            f"Evaluation {latest['evaluation_id']}: **{'PASS' if latest['passed'] else 'FAIL'}** "
            f"(plan revision {latest['plan_revision']})."
        )
        lines.extend(["", "| Criterion | Result | Evidence |", "|---|---|---|"])
        for result in latest["results"]:
            evidence = result.get("log_path") or result.get("evidence", {}).get("path") or result.get("error", "")
            lines.append(
                f"| `{result['id']}` | {'PASS' if result['passed'] else 'FAIL'} | {evidence} |"
            )
    lines.extend(["", "## Model coordination", ""])
    lines.append(
        "The resident-model limit is 1. `required_model_count` in each wave describes "
        "the distinct models in the plan, not simultaneous residency."
    )
    lines.extend(["", "| Wave | Active model | Steps | Assignments |", "|---:|---|---:|---|"])
    for wave in waves:
        assignments = ", ".join(
            f"{item['task_id']} ({item['role']})" for item in wave.get("assignments", [])
        )
        lines.append(
            f"| {wave['wave_id']} | `{wave['active_model']}` | {wave.get('steps', 0)} | {assignments} |"
        )
    lines.extend(["", "## Produced artifacts", ""])
    if artifacts:
        for record in sorted(artifacts.values(), key=lambda item: item["path"]):
            lines.append(f"- `{record['path']}` ({record['size_bytes']} bytes, SHA-256 `{record['sha256']}`)")
    else:
        lines.append("No verified task outputs recorded.")
    lines.extend(["", "## Metrics", "", "```json", json.dumps(run.get("metrics", {}), indent=2), "```", ""])
    if run.get("error"):
        lines.extend(["## Unresolved error", "", str(run["error"]), ""])
    atomic_write_text(store.run_dir / "report.md", "\n".join(lines))
    return report
