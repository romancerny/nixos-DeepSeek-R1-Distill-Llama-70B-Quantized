# Operations guide

Running `agentic-ai` against real 70B/32B models on a single-GPU host.

## 1. Ollama service expectations

The orchestrator assumes an Ollama it can treat as (nearly) exclusive:

- `OLLAMA_NUM_PARALLEL=1` — one inference at a time. The client also serializes
  itself, but the server must not accept parallel requests from elsewhere.
- `OLLAMA_CONTEXT_LENGTH=16384` — matches `ollama.context_length` in the
  config; context compaction is tuned against this budget.
- The two required models pulled in advance:
  `ollama pull deepseek-r1:70b` and `ollama pull qwen2.5-coder:32b`.
- `dedicated_ollama: true` (default) means the residency manager may unload
  any resident model. Set it to `false` on a shared Ollama: the manager will
  then **refuse to run** while unknown external models are resident instead
  of unloading them.

Model load/unload of a 70B quantized model takes minutes, not seconds. The
defaults (`load_timeout_seconds: 1800`, `request_timeout_seconds: 3600`,
`keep_alive: "5m"`) reflect that. `keep_alive` keeps the resident model warm
across the short gaps between an agent's turns; explicit unload at switch
barriers uses `keep_alive: 0` and is always verified against `/api/ps`.

## 2. Preflight

```bash
agentic-ai doctor --config config.json --json
```

Checks, without loading any large model: config validity, state-dir
writability, `/api/tags` connectivity, presence of both required models, and
that every configured command's executable resolves. Fix whatever it reports
before starting a run — a run that discovers a missing model after a
40-minute load is an expensive lesson.

## 3. Running

```bash
agentic-ai run --config config.json --goal-file brief.md --stop-after-plan
agentic-ai resume <run-id> --config config.json
agentic-ai status <run-id> --json
agentic-ai report <run-id>
```

Strongly recommended: use `--stop-after-plan` for any non-trivial goal and
read `runs/<id>/plan.v0001.json` before resuming. Check that:

- acceptance criteria actually test your goal (not just "tasks completed");
- write scopes partition the workspace sensibly (QA owns `tests/`, coders own
  disjoint source areas);
- the DAG is small enough to finish within your patience budget — every model
  switch costs a full unload+load cycle of a very large model.

If the plan is wrong, delete the run directory (or just start a new run with a
refined brief) rather than editing the plan by hand; the planner responds
well to explicit constraints in the brief ("use unittest, not pytest";
"no web access needed"; "exactly three modules").

## 4. Deployment as the `ai-agent` account

The tools layer restricts paths, scopes, and commands, but generated tests
execute generated code: the OS account is the real sandbox. Recommended
shape (matches the neighbouring NixOS host configuration):

- a dedicated unprivileged user, e.g. `ai-agent`;
- the state directory owned by that user (`/var/lib/agentic-ai` or a project
  checkout), no sudo, no access to other users' data;
- network policy appropriate to your trust level — if web research is
  enabled, egress is needed only for HTTPS to allowlisted domains; if it is
  disabled (`web.enabled: false` plus removing it from researcher prompts is
  not required — the tool enforces it), the agent needs no network at all
  beyond loopback Ollama;
- run under a supervisor (systemd service or a tmux session) so a long
  multi-hour run survives your shell.

Example systemd unit sketch:

```ini
[Service]
User=ai-agent
WorkingDirectory=/var/lib/agentic-ai
ExecStart=/path/to/venv/bin/agentic-ai run --config config.json --goal-file brief.md
Restart=no
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/agentic-ai
PrivateTmp=true
```

## 5. Tuning

| Knob | Effect |
| --- | --- |
| `roles.<role>.num_predict` | Output cap per role. DeepSeek emits long reasoning; keep planner/reflector generous (≈6144) so the JSON answer is not truncated. |
| `roles.<role>.temperature` | 0.0–0.1 for reviewer/coder determinism; ≤0.2 elsewhere. |
| `roles.<role>.max_turns` | Per-task turn ceiling (1–32). Raise for genuinely iterative coding tasks. |
| `limits.max_repair_cycles` | DeepSeek→Qwen repair loops before the run fails. Each cycle costs at least two model switches. |
| `limits.max_waves` | Hard cap on scheduling waves. |
| `commands.<id>.timeout_seconds` | Per-command wall clock; process group is SIGTERM→SIGKILLed on expiry. |
| `commands.<id>.resume_policy` | `"rerun"` (default; replay after crash) or `"manual"` (fail the task — for non-idempotent commands). |
| `ollama.keep_alive` | How long the resident model stays warm between turns. Too short and cache-expiry reloads appear mid-wave (handled, but wasteful). |

## 6. What to watch during a run

- `runs/<id>/events.jsonl` — live audit trail (`tail -f`).
- `runs/<id>/waves/` and `switches/` — one file each per wave/switch, with
  full assignments and `/api/ps` before/after evidence.
- `runs/<id>/attempts/` — raw model I/O per turn when a task misbehaves.
- `ollama ps` — at any instant exactly zero or one of the two models should
  be listed. If you ever see both, something outside this system loaded a
  model; the run will refuse to proceed (or, with `dedicated_ollama`, will
  unload it at the next barrier).

## 7. Troubleshooting

- **Run is `interrupted` after a transport error.** Just `resume`. Inference
  interruptions are resumable by design; completed work is not repeated.
- **A task fails with protocol errors.** Read
  `attempts/<task>/attempt-*/turn-*/response.raw.txt`. Usually the model
  emitted prose around the JSON or truncated; the bounded feedback loop gives
  it `max_protocol_retries` chances, then fails the task. A failed plan task
  fails the whole run — the repair loop only handles acceptance/review
  failures after otherwise-successful execution.
- **Planner keeps returning invalid plans.** Simplify the brief, state the
  desired file layout explicitly, or reduce scope. All failed plan attempts
  are kept under `attempts/bootstrap-plan/`.
- **Model thrash (constant switching).** The scheduler already drains all
  ready same-model work before switching; remaining thrash means the DAG
  alternates roles at every rank. Group same-role work in the brief.
- **A completed task got requeued on resume.** Its recorded outputs changed
  or vanished (hash mismatch) — the run no longer trusts them.
- **`final_offload_failed` event.** A model stayed resident after exit; run
  `agentic-ai offload --config config.json` to force a verified unload.
