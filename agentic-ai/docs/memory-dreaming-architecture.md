# Memory and dreaming architecture

Status: v0.2.0 target architecture. `development-log.md` and
`verification.md` distinguish implemented/tested behavior from deployment
checks that still require the operator.

## 1. Goals and scale

The system adds continual, inspectable learning to the existing durable DAG
orchestrator without changing its hardware contract. Two local model families
(DeepSeek research and Qwen coding) share one GPU residency slot; Kimi K3.1 Pro
is an optional hosted provider. Agent roles are logical workers, not extra OS
users or extra resident models.

The design serves one to three people on one workstation. It deliberately uses
portable files, one shared state root, one execution lock, and an optional
oneshot dream timer. It does not require a database server, vector database,
distributed queue, always-on API daemon, model fine-tuning, or enterprise IAM.

## 2. Authority and identities

| Action | Required OS identity |
| --- | --- |
| Inference, normal agent tools, model load/unload, dream analysis/curation | `ai-agent` |
| Curated organization/project/skill writes | `roman` |
| Dream review, approval, rejection, rollback, redaction, export/import | `roman` |
| Read-only status/report/search | Either, subject to filesystem and scope policy |

The application checks the effective UID through `pwd`, in addition to Unix
ownership and modes. A model cannot supply an actor identity. One to three
people may use `roman` with a display name for attribution; those names are
self-attribution, not cryptographically separate users.

Agents can read curated knowledge but write only their own scratch namespace
and a project's low-trust inbox. Dream workers write proposals, never shared
heads. Human approval is a separate operation as `roman`.

## 3. Canonical data model

Markdown with TOML front matter is the portable document format. JSON holds
catalogs, immutable provenance, operation journals, manifests, and proposals.
SQLite is only a per-reader, rebuildable full-text index. It is never the
source of truth and can be deleted without losing memory.

A typical root is `/var/lib/agentic-ai/memory`:

```text
org/                         human-curated organization knowledge
skills/<skill-id>/SKILL.md    human-curated procedural workflows
projects/<id>/curated/       approved project knowledge
projects/<id>/inbox/         unreviewed in-band agent lessons
agents/<agent-id>/scratch/   agent-local working memory
dreams/                      jobs, findings, proposals, diffs
catalogs/                    atomic current-head maps per scope/project
objects/                     content-addressed Markdown payloads
versions/                    immutable version/provenance records
operations/                  pending/terminal mutation records
audit/                       per-scope hash-chained metadata events
redactions/                  content-free redaction markers
locks/                       catalog and review locks
```

A memory key includes scope, project/namespace, and document ID. Front matter
contains a stable ID, title, kind, summary, tags, classification, and review
status. Bodies stay small; many focused documents are preferable to one large
`CLAUDE.md`. Secrets, API keys, tokens, and credentials are forbidden memory
content.

### Catalogs and atomic batches

Each scope/project has one catalog mapping document IDs to current version IDs
and body hashes. The catalog is the atomic visibility boundary. Writers lock
the catalog, compare preconditions, stage immutable objects and records, then
replace the catalog atomically. Readers never observe half of a multi-document
commit within a catalog. A dream proposal targets exactly one catalog so its
acceptance cannot partially apply across scopes.

### Versions and provenance

Every create/update/delete/rollback/import records:

- operation and mutation IDs, parent/current body SHA-256, and timestamps;
- actor kind and OS identity, plus optional human display name;
- run, task, attempt, turn, tool call, and dream job/proposal where applicable;
- evidence transcript and tool-event IDs/hashes;
- source version for rollback or imported manifest for portability.

Deleting writes a tombstone. Rollback creates a new version referencing the
selected historical version; it does not erase later history. Redaction is the
explicit exception to payload immutability: affected payloads become
inaccessible, non-content provenance remains, and future readers/proposals see
a redaction marker. Filesystem deletion cannot guarantee erasure from SSDs,
old exports, or external backups.

## 4. Mutation and recovery protocol

1. Authenticate the OS actor and authorize the target scope.
2. Validate paths, front matter, size/count limits, classification, and review
   state. Never accept a caller-supplied human actor.
3. Acquire the target catalog lock and read the current catalog.
4. Require the expected body hash for an existing document (or absence for a
   create). A mismatch is a conflict, not an overwrite.
5. Persist a pending operation with a unique mutation ID before changing the
   visible state. Repeating the same mutation ID reconciles the existing
   operation.
6. Stage the content-addressed object and immutable version record.
7. Re-read the head under the same lock, recheck all hashes, and atomically
   replace the catalog. This locked compare-and-swap closes the TOCTOU window
   between a model's read/draft and its write.
8. Append a metadata-only event to the scope's hash-chained audit log and mark
   the operation terminal. Startup/resume reconciles a crash from the journal
   and catalog rather than blindly repeating a completed mutation.

Hash chains reveal accidental inconsistency and casual edits. They are not a
defense against an attacker who already controls the same UID and can rewrite
both records and audit files. Human-owned curated roots and approval decisions
therefore have different Unix ownership from agent-writable state.

## 5. Search, guidance, and progressive disclosure

The deterministic API supports list, search, read, history, diff, write,
rollback, redact, verify, reindex, export, and import. Search filters by actor,
scope, project, tags, kind, and classification before returning small metadata
matches. Full bodies load only when requested. Index hashes are checked against
catalogs; stale indexes are rebuilt.

At run creation, a bounded snapshot injects only relevant curated guidance and
skill names/descriptions. Exact source versions and hashes are recorded. This
keeps a run reproducible and prevents a concurrent memory edit from silently
changing its system prompt. Skills expose front matter first and their full
`SKILL.md` body only through `skill_read`.

In-band tools are `memory_search`, `memory_read`, `memory_write`,
`skill_search`, and `skill_read`. The harness attaches run provenance and
enforces permissions. Agent-written inbox lessons remain marked unreviewed and
are not promoted into organizational guidance merely because they exist.

## 6. Privacy and hosted inference

Classifications are `public`, `shareable`, `internal`, and `private`.
Local-only is the default for internal/private data. Hosted calls require an
explicit public/shareable run and hosted approval. Classification is tracked
as taint across the complete context: reading one private artifact or memory
prevents a later hosted call in that context, even if the next prompt looks
harmless. Web and model outputs are data, never authority.

Kimi uses `k3.1-pro` through the configured OpenAI-compatible coding endpoint.
Only the environment variable **name** for the key is stored in configuration;
the secret never enters run snapshots, memory, command environments, or logs.
The client identifies itself truthfully as `agentic-ai`. A Kimi Code
membership and the separately metered Kimi Platform are not assumed to be the
same product or billing arrangement.

## 7. Dreaming pipeline

Dreaming is a durable out-of-band batch workflow with its own configured model,
time, transcript, byte, turn, and token budgets. It shares the machine-wide
execution lock so it cannot unload a model beneath an ordinary run.

1. **Select.** Use only explicitly configured run roots and terminal runs with
   dreaming consent. Verify canonical transcript manifests, request/response
   and tool-event hashes, ACL, classification, retention, and redaction state.
2. **Snapshot.** Copy the authorized transcripts and matching memory versions
   into the dream run with hashes. Selection and memory target must have the
   same permission scope; private inputs cannot be sent to hosted models.
3. **Analyze.** Shard complete transcripts/events within budget. Logical dream
   subjects use the existing scheduler and run serially when the local model
   requires it. Every finding must cite real transcript and tool-event IDs.
4. **Curate.** A curator receives validated findings and the memory snapshot,
   looking for repeated mistakes, missing or stale guidance, contradictions,
   tool configuration failures, and reusable procedural skills. Business
   steering controls which patterns matter.
5. **Validate.** The harness—not the model—computes prevalence from evidence.
   The default threshold is two distinct source runs. It validates operations,
   targets, evidence, review status, and expected base hashes. Unsupported
   proposals are rejected with reasons.
6. **Review.** Only staged proposals and unified diffs are produced. A human
   inspects evidence and accepts or rejects as `roman`. Approval repeats every
   check and commits one catalog atomically with proposal provenance. Stale
   proposals require a new dream/rebase; repeated approval is idempotent.
7. **Resume/report.** Pending/terminal records and phases make interruption
   recoverable. Token, latency, model-switch, acceptance, and subsequent task
   metrics are reported. No accuracy, speed, or cost improvement is asserted
   without repeated-task evidence.

Dreaming changes files, not model weights. It cannot rewrite its own authority,
system prompts, acceptance criteria, or historical audit records.

## 8. Model and process residency

The existing residency manager remains the only local model switching path.
Hosted calls are not locally resident models. Local-to-hosted transitions obey
the configured offload policy, and all local projects plus dreams use the same
per-UID execution lock.

A durable llama.cpp process registry stores PID, UID, executable/model/port,
and Linux process start time. Recovery adopts or stops only a verified owned
process. PID reuse or identity mismatch fails closed instead of killing an
unrelated process.

## 9. Portability and verification

Export is a bounded, normalized directory with a manifest and hashes, written
with restrictive modes. Import validates every entry in staging, rejects
absolute/traversal/symlink paths and excessive sizes/counts, and merges only
with explicit current-head preconditions. Ordinary merge never silently
replaces newer local state. Exports contain sensitive plaintext and belong in
encrypted external storage; the project does not invent its own cryptography.

Offline acceptance uses fake model providers, multiprocessing race tests,
crash injection, ACL/prompt-injection cases, and complete memory-to-dream-to-
approval workflows. Real GPU model switching, NixOS evaluation/activation, and
live Kimi calls are separate operator gates and must be reported separately.
