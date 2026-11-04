# Release v0.1.0 — local model-swap DAG agents

## Preservation

- Baseline commit: `a8e4d1d9386663ad8945549fefaf4f6fb283c9d1`.
- Local branch: `release/v0.1.0-local-model-swap-dag-agents`.
- Local annotated tag: `agentic-ai-v0.1.0-local-model-swap-dag-agents`.
- Development continues on `Sway-Waybar`. No release ref was pushed.

The release contains the complete `Sway-Waybar` tree as it existed before the
memory/dreaming work, including the NixOS workstation configuration. To inspect
or run this exact state later:

```bash
git switch release/v0.1.0-local-model-swap-dag-agents
```

Do not commit new v0.2.0 work onto that branch. Start a separate topic branch
from it if a maintenance fix is ever needed.

## Functionality captured

- Durable, typed DAG planning and bounded reflection/repair.
- Research/reasoning and coding/QA role families.
- DeepSeek GGUF via managed llama.cpp and Qwen via Ollama, with explicit
  unload/load transitions and one locally resident model.
- File-backed run state, attempt logs, scoped tools, deterministic acceptance,
  reports, and crash recovery.
- Separate `ai-agent` and `roman` NixOS accounts and the workstation setup from
  the baseline commit.

This release has no cross-run semantic memory, procedural skill store, dream
worker, or Kimi provider. The baseline executor lock is per state directory;
the documentation's machine-wide wording is therefore aspirational for this
release, not a guarantee.

## Verified baseline

On 2026-11-04, before any v0.2.0 source edit:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.../agentic-ai/src \
  python3 -m unittest discover -s .../agentic-ai/tests -v
Ran 44 tests in 10.653s
OK
```

These are offline tests with fake inference services. Real GPU models, NixOS
rebuild/activation, and hosted providers were not exercised by the baseline.
