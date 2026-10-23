# agentic-ai

A fully local, autonomous, multi-agent project system built around one hard
hardware constraint: **only one large model can be resident in GPU memory at a
time.** DeepSeek-R1 70B plans, researches, reviews, and reflects;
Qwen2.5-Coder 32B implements and tests. Because the two models can never run
simultaneously, all collaboration happens through a durable, auditable
file-storage protocol, and the orchestrator explicitly unloads one model and
loads the other — back and forth, as many times as the project requires.

The architecture applies the workflow patterns taught in DeepLearning.AI's
*Agentic AI* course (see [Course mapping](#course-mapping) and its caveat).

## Properties

- **One resident model, verified.** Every inference passes through a residency
  manager that inspects `/api/ps`, explicitly unloads non-target models with
  `keep_alive: 0`, preloads the target, and verifies that exactly one model is
  resident before any agent runs. It never relies on implicit Ollama eviction.
- **Logically concurrent agents on a shared model.** Multiple researchers can
  share the DeepSeek wave, and multiple coders plus QA can share the Qwen
  wave. They advance round-robin within the wave; inference itself is serial,
  which is the honest behaviour of this hardware.
- **Durable file protocol between model loads.** Plans, per-agent contexts,
  tool results, artifacts, wave/switch records, evaluations, and the canonical
  `run.json` snapshot are all atomic, hash-recorded files. Nothing lives only
  in memory, so a crash or a model switch never loses state.
- **Executable plans, not vibes.** The planner must return a validated JSON
  DAG: typed tasks, dependencies, role→model assignments, artifact ownership,
  disjoint write scopes for concurrent tasks, and deterministic acceptance
  checks (files that must exist, configured test commands that must pass).
- **Bounded autonomy.** Limits on tasks, waves, turns per task, protocol
  retries, and repair cycles. Every malformed model response becomes bounded
  feedback, not silent best-effort parsing.
- **Reflection and repair across the model boundary.** Acceptance evidence and
  a DeepSeek review feed a DeepSeek reflector that emits validated repair
  tasks; Qwen then implements the fixes; DeepSeek reviews again. Criteria can
  never be weakened by a replan.
- **Crash-safe resume.** Interrupt at any point — mid-inference, mid-tool,
  mid-switch — and `resume` continues without repeating completed work.

## Requirements

- Python 3.11+ (standard library only — no pip dependencies), or the Nix
  package (`nix build` — see [Nix / multiple projects](#nix--multiple-projects)).
- [Ollama](https://ollama.com) serving `deepseek-r1:70b` and
  `qwen2.5-coder:32b` (or edit `roles` in the config for other models). On
  NixOS this is typically the `services.ollama` system service.
- Hardware where one such model fits comfortably and two do not — the entire
  design exists for exactly that situation.

## Nix / multiple projects

The tool is installed **once** and driven from any number of projects. Each
project keeps its own nix env (`flake.nix` + `nix develop`), its own
`config.json` and goal brief, and its own `.agentic-ai/` state directory —
`--state-dir` defaults to the current directory, so commands always operate on
the project you're standing in. Runs are serial per machine (one resident
model), but pausing one project and resuming another is fully supported and
crash-safe.

- `agentic-ai.nix` — the package derivation (`pkgs.callPackage`).
- `flake.nix` — exposes `packages.agentic-ai` and a dev shell for this repo.
- `examples/project/flake.nix` — template for a project's own nix env.

The exact per-project lifecycle — setup, activating the env, starting,
pausing to work on another project, and resuming — is documented step by step
in [docs/nixos-projects.md](docs/nixos-projects.md).

## Quickstart

```bash
cd agentic-ai
cp config.example.json config.json   # adjust models/commands if needed

# 1. Preflight: config, state dir, Ollama connectivity, model availability.
#    Does NOT load any large model.
PYTHONPATH=src python3 -m agentic_ai doctor --config config.json

# 2. Inspect the generated plan before any code is written.
PYTHONPATH=src python3 -m agentic_ai run \
    --config config.json --goal-file examples/brief.md --stop-after-plan

# 3. Review .agentic-ai/runs/<run-id>/plan.v0001.json, then execute.
PYTHONPATH=src python3 -m agentic_ai resume <run-id> --config config.json

# 4. Inspect the outcome.
PYTHONPATH=src python3 -m agentic_ai status <run-id> --json
PYTHONPATH=src python3 -m agentic_ai report <run-id>
```

Or install the console script (`pip install .`) and use `agentic-ai …`
instead of `PYTHONPATH=src python3 -m agentic_ai …`.

## CLI

| Command | Purpose |
| --- | --- |
| `doctor --config C [--json]` | Validate config, state dir, Ollama API, required models, command executables. Never loads a large model. |
| `run --config C (--goal G \| --goal-file F) [--run-id ID] [--stop-after-plan]` | Bootstrap a plan and execute the full autonomous workflow. |
| `resume RUN_ID --config C` | Continue a paused, interrupted, or crashed run without repeating completed work. |
| `status RUN_ID [--json]` | Print the canonical run snapshot. |
| `report RUN_ID` | Print (and regenerate) the JSON/Markdown report. |
| `offload --config C` | Unload every managed model under the executor lock. |

All commands take `--state-dir` (default `.agentic-ai`).

## How a run proceeds

1. **Plan (DeepSeek).** The planner model receives the goal and must return a
   valid executable DAG. Invalid JSON or schema violations are fed back, with
   bounded retries. The plan is persisted as `plan.v0001.json`.
2. **Waves.** The scheduler picks the ready set for one model, records a wave
   file with the full assignment list and required-model count, switches
   residency if needed, then advances each agent in the wave round-robin.
   Newly unblocked same-model tasks join the active wave; nothing switches
   mid-step.
3. **Switch (unload → verify → load → verify).** When the resident model's
   ready set is drained, the orchestrator explicitly unloads it, verifies
   `/api/ps` is empty, loads the next model, verifies exclusivity, and writes
   a switch record (from/to, before/after `/api/ps` snapshots, assignments).
   This repeats as often as the DAG requires.
4. **Evaluate (no model).** At quiescent barriers, deterministic acceptance
   checks run: required files must exist and configured commands (unit tests,
   compilation) must pass. Model claims are never trusted as evidence.
5. **Review (DeepSeek).** The reviewer compares goal, criteria, artifacts, and
   runtime evidence and returns `pass`/`fail`.
6. **Reflect & repair (DeepSeek → Qwen → DeepSeek).** On failure, the
   reflector diagnoses the root cause and emits a validated patch of new
   repair tasks (acceptance criteria immutable). The loop is bounded by
   `max_repair_cycles`.
7. **Report.** `report.json` / `report.md` capture status, task states,
   acceptance evidence, artifacts, waves, switches, metrics, and errors.

A typical successful run with one repair switches models five or more times:
plan (DS) → research/architect (DS) → implement/test (QW) → review (DS) →
reflect (DS) → repair (QW) → re-review (DS), with explicit offload at exit.

## The write-scope rule

Tasks that can be active in the same wave must declare **disjoint write
scopes** (e.g. coder A owns `src/billing/`, coder B owns `src/reporting/`, QA
owns `tests/`). Two unordered tasks with overlapping scopes are rejected at
plan validation; if two tasks must write the same file, one must depend on the
other. Scope prefixes require a trailing slash, so `src/` cannot match
`src2/x.py`. Symlink escapes out of the run directory are rejected.

## Security model

This system executes code written by a local model. The tools layer is
defence-in-depth, **not a sandbox**:

- Commands are restricted to fixed `command_id` entries from the config,
  executed with `shell=False`, fixed argv, the workspace as cwd, a minimal
  environment, process-group termination, timeouts, and bounded output.
- File tools are confined to the run directory with path/symlink containment,
  per-task write scopes, and size caps.
- Web access (researcher only) is HTTPS-only, domain-allowlisted, and
  size/time bounded; retrieved content is treated as untrusted data.
- **The real security boundary is the operating system.** Run the service as
  an unprivileged, network-restricted `ai-agent` account — generated tests do
  execute generated code. See [docs/operations.md](docs/operations.md).

## Recovery

Every state transition is persisted atomically (temp file + `fsync` +
`os.replace`). On `resume`:

- completed tasks whose recorded output hashes still match are never repeated;
- a task interrupted mid-inference gets recovery feedback and retries;
- a task interrupted mid-tool replays the idempotent tool (writes are atomic;
  commands default to `resume_policy: "rerun"`, or fail loudly with
  `"manual"` for non-idempotent commands);
- a torn final line in `events.jsonl` is repaired;
- SIGINT/SIGTERM stop at safe step boundaries and offload models only when
  quiescent.

Two machine-wide and per-run `flock` locks prevent competing executors from
unloading each other's models.

## Course mapping

Built from the public syllabus of
[DeepLearning.AI's Agentic AI](https://www.coursera.org/learn/dlai-agentic-ai):

| Course pattern | Where it lives |
| --- | --- |
| Workflow decomposition & planning | `planner.py` executable DAG, `plan.py` validation |
| Tool use | `tools.py` scoped files/artifacts, fixed commands, web |
| Reflection with external feedback | `evaluation.py` deterministic checks + reviewer/reflector repair loop in `runner.py` |
| Traces & evaluations | `attempts/` raw requests/responses, `events.jsonl`, `evaluations/`, `reporting.py` |
| Component & end-to-end testing | `tests/` fake stateful Ollama + full workflow tests |
| Specialised multi-agent coordination | role system prompts, round-robin waves in `scheduler.py` |
| Bounded autonomy | `limits` config enforced throughout |

**Caveat:** the course's videos, labs, and quizzes are login-gated and were
not accessed. The mapping above follows the publicly visible syllabus and
descriptions, not the gated lesson content. If you have authorized access to
transcripts/labs and want lesson-level fidelity, provide them and the
prompts/exercises can be aligned more precisely.

## Documentation

- [docs/file-protocol.md](docs/file-protocol.md) — run layout and every
  durable schema (`run.json`, plan, contexts, waves, switches, evaluations,
  events).
- [docs/operations.md](docs/operations.md) — real Ollama/NixOS operation,
  `ai-agent` deployment, tuning, troubleshooting.

## Development

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The suite uses a stateful fake Ollama server that enforces the one-resident-
model rule, so the full multi-switch workflow is tested without loading real
70B/32B weights.
