# File-storage communication protocol

Because only one model can be resident at a time, agents never talk to each
other directly. Everything one model's agents need from another model's
agents — assignments, research, specifications, feedback, evidence — passes
through the durable files described here. All JSON files are written
atomically: same-directory temporary file, `fsync`, `os.replace`, directory
`fsync`. File payloads are recorded with SHA-256 and size.

## Layout

```
<state-dir>/                            (default .agentic-ai)
  executor.lock                         # machine-wide flock: one active executor
  runs/<run-id>/
    run.lock                            # per-run flock
    run.json                            # canonical recovery snapshot (source of truth)
    events.jsonl                        # append-only audit log (repaired on resume)
    brief.md                            # the original user goal
    plan.v0001.json, plan.v0002.json    # plan revisions (repairs create new revisions)
    contexts/<task-id>.json             # durable per-agent conversation state
    waves/0001.json                     # one file per scheduling wave
    switches/0001.json                  # one file per verified model switch
    attempts/<task-id>/attempt-<N>/turn-<M>/
      request.json                      # exact messages sent to the model
      response.raw.txt                  # raw streamed model output (pre-parsing)
      result.json                       # parsed outcome / error for that turn
      tool.started.json                 # tool call accepted before execution
    artifacts/                          # cross-model handoffs (research, specs)
    workspace/                          # the generated project itself
    logs/                               # command output logs
    evaluations/evaluation-0001.json    # deterministic acceptance evidence
    report.json, report.md              # final (or interim) report
```

Agents address files only as run-relative paths rooted at `artifacts/` or
`workspace/`; the store rejects anything else, including symlink escapes.

## `run.json` — canonical snapshot

The single source of truth for recovery. Small, always rewritten atomically.

```json
{
  "run_id": "20261019-033000-a1b2c3d4",
  "status": "created|planning|planned|running|paused_after_plan|interrupted|succeeded|failed",
  "goal": "the original user brief",
  "created_at": "…", "updated_at": "…",
  "plan_revision": 1,
  "current_wave": 4,
  "current_switch": 3,
  "repair_cycle": 1,
  "evaluation_count": 2,
  "stop_after_plan": false,
  "task_states": {
    "research-billing": {
      "status": "pending|running|succeeded|failed|blocked",
      "attempt": 1,
      "turns": 3,
      "summary": "…",
      "outputs": [{"path": "artifacts/research.md", "sha256": "…", "size_bytes": 1234}],
      "error": null,
      "final": {"type": "final", "summary": "…", "outputs": ["artifacts/research.md"]}
    }
  },
  "metrics": {
    "model_calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
    "model_loads": 0, "model_unloads": 0, "model_switches": 0,
    "tool_calls": 0
  },
  "error": null
}
```

Status semantics for `resume`:

- `paused_after_plan` — plan exists, waiting for human go-ahead.
- `interrupted` — signal or transient Ollama/residency/OS error; safe to resume.
- `failed` / `succeeded` — terminal; `run`/`resume` return the snapshot as-is.

On resume, succeeded tasks whose recorded output hashes no longer match are
requeued automatically.

## `plan.vNNNN.json` — executable DAG

Produced by the planner (revision 1) or by validated reflector repair patches
(revision ≥ 2). Validated before persistence: unique ids, known roles,
dependency existence and acyclicity, artifact single-ownership, safe paths,
and disjoint write scopes for unordered tasks.

```json
{
  "schema_version": 1,
  "revision": 1,
  "goal": "verbatim user goal",
  "root_cause": "only on repair revisions",
  "tasks": [{
    "id": "implement-billing",
    "kind": "research|specification|implement|test|repair|generic",
    "role": "researcher|architect|coder|qa",
    "model": "resolved from role; tasks cannot override it",
    "instruction": "self-contained assignment",
    "depends_on": ["research-billing"],
    "inputs": ["artifacts/spec.md"],
    "artifact_outputs": ["spec.md"],
    "write_scope": ["src/billing/", "README.md"],
    "max_turns": 8
  }],
  "acceptance": [
    {"id": "tests-pass", "description": "…", "type": "command",
     "command_id": "unit_tests", "required": true},
    {"id": "readme-exists", "description": "…", "type": "file",
     "path": "workspace/README.md", "required": true}
  ]
}
```

- `artifact_outputs` are relative to `artifacts/` and may have exactly one
  owning task.
- `write_scope` entries are workspace-relative files or `dir/` prefixes;
  `./` means the whole workspace and therefore conflicts with everything.
- Two tasks with overlapping scopes must be ordered by `depends_on`.
- Repair patches can only *add* tasks and set `root_cause`; acceptance
  criteria and existing tasks are immutable.

## `contexts/<task-id>.json` — durable agent memory

Rewritten after every turn, so a crash mid-turn loses at most that turn.

```json
{
  "schema_version": 1,
  "task_id": "implement-billing",
  "status": "running|completed|failed",
  "attempt": 1,
  "turn": 3,
  "task": {"…": "task snapshot from the plan"},
  "goal": "…", "acceptance": ["…"],
  "dependency_summaries": {"research-billing": {"status": "succeeded", "summary": "…"}},
  "history": [
    {"turn": 1, "kind": "assistant_tool_call", "content": "…", "compact": "…"},
    {"turn": 1, "kind": "tool_result", "content": "…", "compact": "…"},
    {"turn": 2, "kind": "protocol_feedback|external_feedback|recovery_feedback", "…": "…"}
  ],
  "called_ids": ["write-1"],
  "written_outputs": ["workspace/src/billing/core.py"],
  "pending_tool": {"call": {"…": "…"}, "attempt_dir": "…"},
  "protocol_errors": 0,
  "final": null,
  "outputs": [],
  "error": null
}
```

`pending_tool` is the crash-recovery hinge: a tool call is persisted before
execution, so on resume an interrupted idempotent tool replays without another
inference. History is compacted deterministically to fit `context_length`
while retaining the assignment and recent failures.

## `waves/NNNN.json` — one model's working session

```json
{
  "schema_version": 1,
  "wave_id": 3,
  "status": "opening|active|closed|interrupted",
  "opened_at": "…", "closed_at": "…",
  "active_model": "qwen2.5-coder:32b",
  "required_models": ["deepseek-r1-uncensored-v2:70b", "qwen2.5-coder:32b"],
  "required_model_count": 2,
  "resident_model_limit": 1,
  "assignments": [
    {"task_id": "implement-core", "role": "coder", "model": "qwen2.5-coder:32b", "attempt": 1},
    {"task_id": "write-tests", "role": "qa", "model": "qwen2.5-coder:32b", "attempt": 1}
  ],
  "steps": 17,
  "close_reason": "resident-model ready set drained"
}
```

`assignments` grows if newly unblocked same-model tasks join the wave.
`required_model_count` is the number of distinct models the whole plan needs
(not how many are resident — that is always ≤ 1).

## `switches/NNNN.json` — verified unload → load

Written only for real model transitions (same-model cache-expiry reloads and
already-resident fast paths are logged as events instead).

```json
{
  "schema_version": 1,
  "switch_id": 2,
  "timestamp": "…",
  "reason": "topological ready-set scheduling",
  "quiescent_wave_id": 3,
  "from_model": "deepseek-r1-uncensored-v2:70b",
  "to_model": "qwen2.5-coder:32b",
  "active_model": "qwen2.5-coder:32b",
  "required_models": ["deepseek-r1-uncensored-v2:70b", "qwen2.5-coder:32b"],
  "required_model_count": 2,
  "resident_model_limit": 1,
  "assignments": ["…next wave assignments…"],
  "before_ps": {"models": [{"name": "deepseek-r1-uncensored-v2:70b", "…": "…"}]},
  "after_ps": {"models": [{"name": "qwen2.5-coder:32b", "…": "…"}]},
  "unload_verification": [{"model": "deepseek-r1-uncensored-v2:70b", "resident_models": []}],
  "load_verification": {"model": "qwen2.5-coder:32b",
                        "resident_models": ["qwen2.5-coder:32b"], "verified": true}
}
```

Switches only happen at quiescent barriers: no inference or tool execution is
in flight. An unexpected residency change mid-wave aborts the run as
`interrupted` rather than silently continuing on the wrong model. If
`dedicated_ollama` is false, unknown external resident models are never
unloaded — the run refuses to proceed instead.

## `evaluations/evaluation-NNNN.json` — deterministic evidence

Model claims are never accepted as proof. At each quiescent evaluation
barrier the orchestrator itself checks every acceptance criterion.

```json
{
  "schema_version": 1,
  "evaluation_id": 1,
  "timestamp": "…",
  "plan_revision": 1,
  "execution_passed": true,
  "passed": false,
  "results": [
    {"id": "tests-pass", "type": "command", "required": true,
     "command_id": "unit_tests", "argv": ["…"], "return_code": 1,
     "timed_out": false, "ok": false, "passed": false,
     "log_path": "logs/acceptance-1-tests-pass.log", "output_tail": "…"},
    {"id": "readme-exists", "type": "file", "required": true,
     "passed": true, "evidence": {"path": "workspace/README.md",
     "sha256": "…", "size_bytes": 812}}
  ]
}
```

`passed = execution_passed AND every required criterion passed`. This file is
the primary input to the reviewer and, on failure, to the reflector.

## `events.jsonl` — audit log

One JSON object per line: `{timestamp, type, payload}`. Event types include
`run_created`, `plan_created`, `task_started`, `protocol_feedback`,
`tool_completed`, `task_completed`, `task_failed`, `task_recovered`,
`model_loaded`, `model_unloaded`, `model_switch_verified`,
`model_reloaded_after_cache_expiry`, `wave_closed`, `acceptance_evaluated`,
`repair_plan_created`, `repair_patch_rejected`, `run_succeeded`,
`run_operational_interruption`, `final_offload`, and
`final_offload_failed`. The log is audit material, not a recovery source — a
torn final line is truncated by `repair_event_log()` on resume.

## `attempts/` — full inference trace

Every model call keeps its exact request messages, the raw streamed response
(before reasoning-tag stripping or JSON parsing), and the parsed result or
structured error. Use these to debug protocol failures, prompt regressions,
or model behaviour; nothing is overwritten across attempts or turns.
