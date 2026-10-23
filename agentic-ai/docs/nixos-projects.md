# Working across multiple projects on NixOS

How to install `agentic-ai` once and drive many projects with it, each in its
own nix environment. This is the exact-step runbook; background on the run
lifecycle itself is in [operations.md](operations.md).

## How the pieces fit together

- **One install of the tool.** This repo is the engine. It is built by
  `agentic-ai.nix` (exposed through the repo's `flake.nix`) and shared by every
  project.
- **Per project**: its own `flake.nix` (the nix env), its own `config.json`
  (test/build commands, role tuning), its own `brief.md` (the goal), and its
  own `.agentic-ai/` state directory holding all runs (`runs/<run-id>/...`).
- **State lives in the project, not the tool.** All commands default to
  `--state-dir .agentic-ai` relative to the current directory, so `cd` into a
  project and every command (`run`, `resume`, `status`, `report`) automatically
  operates on that project's runs.
- **One active run per machine.** The design assumes exclusive Ollama access
  with exactly one resident model. Never execute runs from two projects at the
  same time — they would fight over GPU residency. Pausing and switching
  projects is fully supported (below); concurrent execution is not.

Typical layout:

```
~/_/agentic-ai/            ← the tool, cloned once
~/projects/foo/
  ├── flake.nix            ← foo's nix env (from examples/project/flake.nix)
  ├── config.json          ← foo's test commands, roles, limits
  ├── brief.md             ← foo's goal
  └── .agentic-ai/runs/…   ← foo's run state (gitignored)
~/projects/bar/
  └── …same shape…
```

## Prerequisites (once per machine)

1. **Ollama as a NixOS system service.** The nix environments here do *not*
   include Ollama; the tool talks to the system service's HTTP API
   (`http://127.0.0.1:11434` by default). In your NixOS configuration:

   ```nix
   services.ollama = {
     enable = true;
     # acceleration = "cuda";  # or "rocm", per your GPU
   };
   ```

   Recommended alongside it (see [operations.md](operations.md) §1):
   `OLLAMA_NUM_PARALLEL=1` and a context length matching
   `ollama.context_length` in the config (16384).

2. **Models pulled in advance:**

   ```bash
   ollama pull deepseek-r1:70b
   ollama pull qwen2.5-coder:32b
   ```

   (Or edit `roles` in the project `config.json` to use different models.)

3. **The tool cloned once**, e.g. at `/home/roman/_/_/agentic-ai`. No build
   step is needed up front — each project's nix shell builds it on first use.

## New project: exact steps

1. **Create the project and its nix env.**

   ```bash
   mkdir -p ~/projects/my-project && cd ~/projects/my-project
   cp /home/roman/_/_/agentic-ai/examples/project/flake.nix ./flake.nix
   ```

   Edit `flake.nix`: set the project description and confirm the
   `agentic-ai.url = "path:…"` input points at your checkout of the tool.

2. **Enter the environment.** (First entry builds the tool; later entries are instant.)

   ```bash
   nix develop
   ```

3. **Add the project config and goal.**

   ```bash
   cp /home/roman/_/_/agentic-ai/config.example.json ./config.json
   $EDITOR config.json   # at minimum: review `commands` (test/build) and `roles`
   $EDITOR brief.md      # the goal; be explicit about layout and constraints
   ```

   Seed `brief.md` from `/home/roman/_/_/agentic-ai/examples/brief.md` if you
   want a starting shape.

4. **Gitignore the run state** (if the project is a git repo):

   ```bash
   echo '.agentic-ai/' >> .gitignore
   ```

5. **Preflight** — validates config, state dir, Ollama connectivity, model
   availability, command executables. Loads no large model:

   ```bash
   agentic-ai doctor --config config.json
   ```

6. **Plan, review the plan, then execute.**

   ```bash
   agentic-ai run --config config.json --goal-file brief.md --stop-after-plan
   # read .agentic-ai/runs/<run-id>/plan.v0001.json — criteria, write scopes, DAG size
   agentic-ai resume <run-id> --config config.json
   ```

   The run id is printed by `run` and is also the directory name under
   `.agentic-ai/runs/`. Note it down — you need it for `resume`/`status`/`report`.

7. **Inspect the outcome.**

   ```bash
   agentic-ai status <run-id> --json
   agentic-ai report <run-id>
   ```

## Pausing: switching away to another project

Interrupting is safe at any point — mid-inference, mid-tool, mid-switch. All
state is in atomic files under `.agentic-ai/`, and `resume` never repeats
completed work.

1. **Stop the run** (if one is executing): `Ctrl-C` the running command.
2. **Free the GPU** (recommended, so nothing stays resident while you're away):

   ```bash
   agentic-ai offload --config config.json
   ```

3. **Leave the environment and the project:**

   ```bash
   exit            # leave the nix develop shell
   cd ~/projects/other-project
   nix develop     # that project's own env, its own .agentic-ai/
   ```

That's it. There is no daemon and nothing in memory to lose — "pausing" is
just stopping the process.

## Resuming: coming back from another project

1. **Enter the project and its env:**

   ```bash
   cd ~/projects/my-project
   nix develop
   ```

2. **Check where the run stands** (run ids are per state dir, so run this from
   the project directory — otherwise pass `--state-dir` explicitly):

   ```bash
   agentic-ai status <run-id> --json
   ```

   If you've forgotten the run id: `ls .agentic-ai/runs/`.

3. **Resume.** Works whether the run was interrupted, crashed, or stopped
   after planning:

   ```bash
   agentic-ai resume <run-id> --config config.json
   ```

4. **When done, offload** so the next project starts from a clean GPU:

   ```bash
   agentic-ai offload --config config.json
   ```

## Updating the tool

Projects pin the tool by content hash (`path:` inputs are locked in each
project's `flake.lock`). After editing the agentic-ai repo itself, refresh each
project that should pick up the change:

```bash
cd ~/projects/my-project
nix flake update agentic-ai
nix develop
```

## Troubleshooting

- **`doctor` reports missing models / no connectivity** — check
  `systemctl status ollama` and `ollama list`; the nix env does not manage the
  Ollama service.
- **A run refuses to proceed because a foreign model is resident** — something
  outside the run loaded a model (e.g. an interactive `ollama run`). With the
  default `dedicated_ollama: true` the next barrier unloads it; otherwise run
  `agentic-ai offload --config config.json`.
- **Anything else mid-run** — see [operations.md](operations.md) §7; the short
  answer is almost always "just `resume`".
