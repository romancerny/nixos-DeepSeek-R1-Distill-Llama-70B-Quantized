# v0.2.0 verification evidence

## Executed locally

### Baseline before edits

```text
Ran 44 tests in 10.653s
OK
```

The baseline was captured before creating v0.2.0 source changes. The original
commit is preserved by `release/v0.1.0-local-model-swap-dag-agents` and
`agentic-ai-v0.1.0-local-model-swap-dag-agents`.

### Current offline suite

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=agentic-ai/src \
  python3 -m unittest discover -s agentic-ai/tests -q

Ran 89 tests in 19.853s
OK
```

The suite uses temporary directories, real multiprocessing locks, local fake
HTTP inference services, and scripted model responses. No external model or
service is contacted.

## What the tests demonstrate

- Original DAG planning, scoped tools, residency, evaluation, reflection,
  repair, CLI, and resume behavior remains green.
- TOML/Markdown round trips, secret rejection in bodies/front matter, and
  normalized IDs.
- Human/agent scope policy and effective-UID enforcement, including forged
  human actor rejection and other-agent scratch denial.
- Immutable versions and provenance, rollback/tombstones, redaction,
  hash-chain verification, torn-audit repair, and crash reconciliation.
- Locked SHA-256 compare-and-swap: competing updates have one winner; a reused
  mutation ID with different content also has exactly one winner.
- Crash recovery after a visible catalog update, including audit completion by
  a later writer and idempotent mutation replay.
- Group-compatible file/lock modes, bounded/race-safe import, explicit stale
  head preconditions, symlink rejection, and imports exceeding 100 documents.
- Disposable index search, human/agent memory CLI, low-trust inbox memories,
  progressive-disclosure skills, and provenance-idempotent in-band writes.
- Canonical transcript hashes, source-file integrity, dream eligibility,
  redaction/revocation, and confidential-to-hosted denial through context
  taint.
- Bounded command output without subprocess pipe deadlock.
- Kimi streaming/SSE, usage accounting, missing credentials, bounded rate-limit
  retry, no authentication retry, truthful User-Agent, and local→hosted→local
  residency transitions. These tests use a loopback fake only.
- Verified llama.cpp orphan adoption/stop and PID-identity mismatch behavior
  using an actual harmless subprocess.
- Dream subject/curator execution, evidence and distinct-run prevalence,
  review diffs, human promotion, stale rejection, repeated approval,
  approval-after-crash recovery, interrupted curator resume, changed-artifact
  requeue, evidence tamper rejection, and no matching transcript fail-fast.
- Transcript revocation blocks both execution and approval; private documents
  are excluded from public snapshots.
- NixOS example configuration is valid and local/private by default.

## Review-driven fixes

A dedicated memory-core review identified same-UID blind spots. The final
suite includes regressions for its concrete findings: forged actors, mutation
ID races, redaction crash/resurrection windows, privileged redacted operations,
history traversal, intermediate import symlinks, implicit stale imports,
missing audit events after later writes, torn audit tails, front-matter
secrets, cross-UID modes, implicit all-scope search, and >100-document imports.

The dream path was then hardened to revalidate source eligibility and copied
input hashes on execute/resume/approval and before each scheduled step, compare
configured task graphs, requeue changed completed artifacts, recompute proposal
statistics/evidence, and share a review lock between approval and transcript
redaction.

## Not executed — remaining operator gates

The following are **not** claimed as verified:

1. Real DeepSeek/Qwen GPU loading, generation, switching, and memory use.
2. A real llama.cpp server crash/orphan (the lifecycle registry is tested with
   a harmless real subprocess instead).
3. Live Kimi authentication, quota, response semantics, or billing.
4. `nix`, `nix flake check`, `nixos-rebuild`, systemd service activation, or
   timer activation. No `nix` executable was available in this environment.
5. Two-UID integration on the actual NixOS host (permissions are declared and
   modes are unit-tested, but the workstation was not reconfigured).
6. Quality, accuracy, latency, token, or cost improvement on real recurring
   business tasks. Use `agentic-ai metrics` for observed comparisons without
   assuming causation.

## Recommended operator acceptance sequence

```bash
# Validate the Nix configuration on a Nix-enabled host.
nix flake check
sudo nixos-rebuild test --flake .#beast-kf

# Check local models and configured paths without loading large weights.
sudo -u ai-agent agentic-ai doctor --config /etc/agentic-ai/config.json --json

# Initialize curated memory as roman and run one small real local project.
agentic-ai memory init --root /var/lib/agentic-ai/memory
sudo -u ai-agent agentic-ai run \
  --config /etc/agentic-ai/config.json \
  --state-dir /var/lib/agentic-ai/runs \
  --goal-file /var/lib/agentic-ai/brief.md --stop-after-plan

# After two consenting terminal runs, stage and review one local dream.
sudo -u ai-agent agentic-ai dream run --config /etc/agentic-ai/config.json
agentic-ai dream review --config /etc/agentic-ai/config.json
agentic-ai memory verify --root /var/lib/agentic-ai/memory

# Only after local acceptance, opt into the disabled timer if desired.
sudo systemctl enable --now agentic-ai-dream.timer
```

A live hosted test must be a separate, explicit public/shareable request with
`--approve-hosted`, a valid Kimi Code credential, and operator approval of any
quota implications. The implementation test suite never makes that request.
