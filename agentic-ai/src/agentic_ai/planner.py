from __future__ import annotations

import json
import os
from typing import Any

from .config import Config
from .errors import PlanValidationError, ProtocolError
from .parsing import parse_json_object
from .plan import Plan
from .residency import ResidencyManager
from .storage import RunStore, atomic_write_json


PLANNER_INSTRUCTION = """You are the manager-planning agent for an autonomous local multi-model project system.
Decompose the user's real objective into an executable JSON DAG for specialist agents. Return only one JSON object, without Markdown or prose.

Schema:
{
  "schema_version": 1,
  "revision": 1,
  "goal": "repeat the goal",
  "tasks": [{
    "id": "lower-case-unique-id",
    "kind": "research|specification|implement|test|repair|generic",
    "role": "researcher|architect|coder|qa",
    "instruction": "specific, self-contained assignment",
    "depends_on": ["other-task-id"],
    "inputs": ["artifacts/input.md", "workspace/optional/file.py"],
    "artifact_outputs": ["artifact-relative-output.md"],
    "write_scope": ["workspace-relative-file.py", "workspace-relative-directory/"],
    "max_turns": 8
  }],
  "acceptance": [
    {"id":"tests-pass","description":"...","type":"command","command_id":"unit_tests","required":true},
    {"id":"required-file","description":"...","type":"file","path":"workspace/src/file.py","required":true}
  ]
}

Planning requirements:
- For a software project, include independent research as useful, one consolidating architecture specification, implementation, and QA. Do not create planner, reviewer, or reflector tasks; the orchestrator adds those stages.
- Give researchers/architects declared artifact_outputs. Give coders/QA precise workspace write_scope. Artifact output paths do not include an artifacts/ prefix.
- Independent tasks that may share a model wave must have disjoint write scopes. If two tasks write the same file, make one depend on the other. QA normally owns tests/ while coders own source files.
- Use dependencies to pass durable artifacts and summaries. Prefer small tasks with clear ownership over one enormous task.
- Use only configured command_id values for acceptance. Include file acceptance for critical deliverables. Acceptance must test the user's actual goal, not merely task completion.
- For quantitative trading/time-series requests, require explicit mathematical definitions, lookahead/survivorship/leakage analysis, non-stationarity handling, realistic spread/fees/latency, purged and embargoed validation with regime analysis where appropriate, and Sortino, maximum drawdown and duration, and Profit Factor metrics. Distinguish research hypotheses from validated results.
- Keep the DAG finite and within the configured task limit. Do not invent model names; role mapping is enforced by the orchestrator.
"""


class Planner:
    def __init__(self, store: RunStore, config: Config, residency: ResidencyManager):
        self.store = store
        self.config = config
        self.residency = residency

    def create_plan(self, brief: str) -> Plan:
        role = self.config.roles["planner"]
        model = role.model
        command_ids = sorted(self.config.commands)
        messages = [
            {"role": "system", "content": PLANNER_INSTRUCTION},
            {
                "role": "user",
                "content": (
                    f"Create revision 1 of the project plan. Available acceptance commands: "
                    f"{json.dumps(command_ids)}. Maximum tasks: {self.config.limits.max_tasks}.\n\n"
                    f"USER GOAL:\n{brief}"
                ),
            },
        ]
        last_error = ""
        for turn in range(1, self.config.limits.max_protocol_retries + 3):
            if turn > 1:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The previous planning response was invalid: "
                            + last_error
                            + " Return a corrected complete plan JSON object. Preserve the original goal and acceptance rigour."
                        ),
                    }
                )
            attempt_dir = self.store.attempt_dir("bootstrap-plan", 1, turn)
            atomic_write_json(
                attempt_dir / "request.json", {"model": model, "messages": messages}
            )
            raw_path = attempt_dir / "response.raw.txt"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            with raw_path.open("wb") as raw:
                def on_text(text: str) -> None:
                    raw.write(text.encode("utf-8"))
                    raw.flush()

                generation = self.residency.chat(
                    model, messages, role, on_text=on_text
                )
                os.fsync(raw.fileno())
            try:
                raw_plan = parse_json_object(
                    generation.text, done_reason=generation.done_reason
                )
                raw_plan["goal"] = brief
                raw_plan["revision"] = 1
                plan = Plan.from_dict(raw_plan, self.config)
            except (ProtocolError, PlanValidationError) as exc:
                last_error = str(exc)
                atomic_write_json(
                    attempt_dir / "result.json",
                    {"ok": False, "error_type": "plan_validation", "error": last_error},
                )
                continue
            atomic_write_json(self.store.plan_path(1), plan.to_dict())
            atomic_write_json(
                attempt_dir / "result.json", {"ok": True, "plan_revision": 1}
            )
            run = self.store.load_run()
            run["plan_revision"] = 1
            run["status"] = "planned"
            states = run.setdefault("task_states", {})
            for task in plan.tasks:
                states[task.id] = {
                    "status": "pending",
                    "attempt": 0,
                    "turns": 0,
                    "summary": None,
                    "outputs": [],
                    "error": None,
                }
            self.store.save_run(run)
            self.store.append_event(
                "plan_created", revision=1, tasks=[task.id for task in plan.tasks]
            )
            return plan
        raise ProtocolError(f"Planner exhausted protocol retries: {last_error}")
