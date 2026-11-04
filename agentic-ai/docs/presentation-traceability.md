# Presentation traceability and feasibility

Source of truth: Lamis Mukta, **Learning while you sleep: Beyond memory to
dreaming**, AI Native DevCon, June 2026,
<https://www.youtube.com/watch?v=tTcxVv8HHNw>. The supplied X post republishes
this talk. Requirements below come from the original talk transcript, not the
post's claims about Anthropic employment practices or an “Opus 5.5” model.

## Feasibility for this system

The concepts are feasible without changing the one-local-model constraint.
Memory writes and search are deterministic file operations. Dream subjects are
logical tasks in the existing same-model scheduler, so their apparent fan-out
does not require two 70B models simultaneously. Kimi is optional and introduces
a privacy/egress policy rather than replacing local models.

The main new engineering is trustworthy state management: immutable versions,
locked compare-and-swap, scoped authority, transcript manifests, resumable
batches, and human-gated promotion. It is not a training or weight-update
project.

## Concept-to-implementation matrix

| Talk concept (approximate transcript location) | Existing foundation | v0.2.0 implementation and boundary |
| --- | --- | --- |
| Simple Markdown guidance, `CLAUDE.md` lesson (03:42–05:02) | Human-readable run brief/artifacts | Bounded curated Markdown guidance with version/hash snapshots; avoid one ever-growing file. |
| In-band autonomous memory read/write (05:02–05:50) | Durable tool protocol | `memory_search`, `memory_read`, `memory_write` through `ToolRuntime`; only scratch/inbox writes. |
| Procedural skills and progressive disclosure (05:50–07:35) | Role prompts and scoped file reads | Human-curated `SKILL.md`; index name/description first, full body only through `skill_read`. |
| Filesystem as memory; Markdown, search/index, agent autonomy (07:35–08:55) | Atomic file storage and SHA-256 utilities | Canonical Markdown/TOML plus JSON metadata and disposable SQLite FTS index. No mandatory vector store. |
| Many agents and long-lived production problems (08:55–10:29) | Logical waves and durable runs | Cross-run memory, scoped permissions, low-trust inbox, stale/redaction handling. Local inference remains serial. |
| Versioning, transcript provenance, actor attribution, rollback (10:42–11:17) | Attempt/run history and file hashes | Immutable version records with actor/run/task/attempt/evidence; rollback creates a new head. |
| Hash before/after drafting; retry on mismatch (11:17–12:09) | SHA-256 and `flock` | Locked catalog CAS rechecks expected body hashes immediately before atomic visibility. Conflicts require re-read/rebase. |
| Organization read-only vs agent scratch read-write (12:09–13:08) | Tool role checks and separate OS users | `roman` owns curated/skills; `ai-agent` owns scratch/inbox/proposals. Both application and Unix checks. |
| Portable memory with a clean API (13:08–13:51) | File-based protocol | Public Python store API plus bounded manifest export/import; no vendor-specific database required. |
| Better accuracy, latency, and cost (14:07–15:23) | Run metrics and acceptance reports | Measure repeated-task success, tokens, tool failures, latency, and switches. No unmeasured improvement claim. |
| Limits of in-band memory: split focus and session-only visibility (15:23–17:14) | Per-run contexts and review/reflection | Separate dream budget and cross-run transcript selection; ordinary task context stays bounded. |
| Stale-memory pass and dreaming as asynchronous second-order curation (18:00–19:55) | Atomic run snapshots | Durable dream jobs consolidate, prune, contradict, and propose updates against a fixed memory snapshot. |
| Learn from tool calls and metadata, not only chat (19:55–21:24) | Durable tool calls/results and events | Canonical transcripts include request/response and tool metadata with hashes and ACLs. |
| Organization-specific steering (21:45–22:58) | Role prompts and config | Dream steering config identifies important business processes, failure patterns, and exclusions. |
| Subject fleet, orchestrator aggregation, prevalence/evidence (22:58–23:35) | DAG scheduler, round-robin waves, reports | Subject findings feed curator; deterministic code validates citations and computes distinct-run prevalence. |
| Human accept/reject of proposed memory changes (23:35–23:52) | Human-readable artifacts | Staged proposals and unified diffs; only `roman` can approve/reject/promote. |
| In-band and out-of-band processes run together (23:52–25:14) | Durable run state and model locks | Independent dream worker/timer with dedicated budgets and the same global execution lock; no GPU overlap. |
| Consolidate, remove stale, add missing, reorganize (26:30–27:17) | Versioned file storage | Create/update/tombstone/rollback proposals with review status and provenance; no auto-promotion. |
| Dream transcript permissions must match memory permissions (29:11–30:16) | Scoped run/tool access | Selection filters ACL/classification/namespace and excludes redacted/unconsented runs before copying or inference. |
| Hashing/versioning belongs deterministically in the harness (30:33–31:41) | `RunStore`, `FileLock`, atomic rename | Model proposes content; `MemoryStore` owns versions, hashes, CAS, catalogs, audit, and recovery. |

## Deliberate adaptations for 1–3 people

- One workstation and shared state root rather than thousands of agents.
- Two distinct source runs as the default prevalence threshold, configurable
  for a genuinely one-off high-severity human review.
- No always-on service is required; manual dreams and an optional oneshot
  systemd timer use the same code.
- SQLite is only a local index, Markdown/JSON remain portable.
- Human approval is intentionally mandatory for shared memory. This is
  stricter than unrestricted autonomous writes and appropriate for a small
  business whose organizational context affects every agent.

## Non-goals

Model fine-tuning/weight updates, autonomous modification of system authority,
automatic promotion from one persuasive transcript, hidden hosted processing
of private transcripts, distributed multi-tenant IAM, and claims of continual
learning without evaluation evidence.
