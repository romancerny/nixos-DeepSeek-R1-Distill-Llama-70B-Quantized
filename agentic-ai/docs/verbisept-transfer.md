# Verbisept research and engineering transfer

## Scope and evidence discipline

The neighbouring `/home/roman/_/_/verbisept` project and its current
`verbisept-l1-only` direction were reviewed, including historical architecture,
implementation audits, recovery code, and acceptance records. They implement
Bitcoin/RGB wallet and reward systems, not LLM memory or multi-agent learning.
No source files in that project were changed.

Historical documents are treated as decisions or proposals, not proof of
implementation. The latest L1-only direction supersedes older Lightning/Nostr
architecture where they conflict. Current reference points include:

- `verbisept-l1-only/docs/00-decisions.md` — current fixed scope and invariants.
- `verbisept-l1-only/crates/reward-service/src/wallet.rs` — single-writer actor.
- `verbisept-l1-only/crates/reward-service/src/store.rs` — transacted snapshots.
- `verbisept-l1-only/crates/rgb-l1/src/backup.rs` — staged backup/restore.
- `docs/16-progress-log.md`, `docs/17-implementation-audit.md`, and
  `docs/19-local-ci.md` — historical implementation evidence and limitations.

## Patterns adopted

| Verbisept pattern | Application to agentic-ai v0.2.0 |
| --- | --- |
| Pure checked state transitions | Memory operations and dream phases have explicit validated states; models do not define the transition rules. |
| Single-writer actor / one FIFO owner | One locked catalog owns visibility for each scope/project; one global execution lock owns local model switching. |
| Pending record before external side effect | Memory mutations and dream phases persist pending state before visible changes or inference. |
| Terminal tombstones and idempotent transitions | Delete/redact markers, mutation IDs, proposal decisions, and completed dream artifacts suppress duplicate effects. |
| Reconcile unknown outcomes instead of blind retry | Recovery inspects catalogs/journals and ambiguous provider outcomes rather than assuming failure means “not happened.” |
| Conservative checkpoint merge vs explicit replacement | Import/rollback require explicit preconditions and create attributable versions; newer heads never disappear through ordinary restore. |
| Backend/mode-bound snapshots | Run/dream manifests bind config, model/provider identity, memory versions, and transcript hashes. |
| Stable provider adapters with common acceptance | Ollama, llama.cpp, Kimi, and fakes expose one backend surface with offline conformance tests. |
| Independent fail-closed check before irreversible action | Human approval repeats ACL, evidence, redaction, and base-hash checks even if the curator already claims they pass. |
| Exact operation identity | Canonical mutation/proposal/transcript IDs and body hashes prevent accidental replay and lost updates. |
| Restrictive modes and safe archive paths | Memory/export paths are normalized and size bounded; human/agent roots have distinct Unix owners and modes. |
| Evidence-layered local QA | Deterministic tests, races/fault injection, end-to-end fake models, then explicit real GPU/Nix/Kimi gates with no inflated claims. |

## Important limitations not copied

- Verbisept's actor and atomic rename do not by themselves exclude multiple
  processes. Agentic-ai uses actual cross-process catalog/executor locks and
  compare-and-swap.
- A backup containing both ciphertext and its password is not separate-secret
  protection. Agentic-ai does not reproduce that construction or invent new
  cryptography; exports are documented plaintext and require encrypted storage.
- Secret-bearing files need explicit restrictive modes. Every new memory,
  proposal, manifest, and export path sets its mode rather than relying only on
  a process umask.
- In-memory prepared operations can disappear on restart. Dream and memory
  side effects have durable pending/terminal records and stable IDs.
- Simulation and recorded smoke results are not production acceptance. The
  final verification report lists real model, NixOS, and live hosted checks
  independently and leaves unexecuted gates open.
- Documentation drift in historical wallet trees is a warning: this project's
  architecture document points to actual code/tests and the development log
  records implementation status.

## New engineering not supplied by Verbisept

Markdown semantic/procedural memories, full-text retrieval, skill progressive
disclosure, memory provenance and content CAS, transcript manifests, privacy
taint, dream subject/curator prompts, cross-run prevalence, and review-gated
memory consolidation are new agent-system work. They are inspired by the
presentation and implemented against this repository's Python orchestrator,
not copied from wallet code.

## Historical evolution considered

The earlier Lightning/Nostr work contributed persistent ordered outboxes,
encrypted operation journals, acknowledged operations, replay suppression,
and the distinction between ordinary checkpoint merge and explicit archive
replacement. The L1-only rewrite contributes a narrower current protocol,
checked accounting, mockable single-writer actors, and two-layer fail-closed
checks. The older custom marketplace and third-party alternatives do not
change this agent architecture; they are context, not dependencies.
