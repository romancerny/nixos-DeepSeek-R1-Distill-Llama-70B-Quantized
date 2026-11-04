# Security model

## Security objectives

The memory system must not turn one agent's mistake, malicious source, or
prompt injection into organization-wide authority. The design favors bounded
writes, attributable versions, deterministic concurrency controls, local-only
private processing, and human promotion.

## Trust boundaries

1. **Model output is untrusted.** Plans, findings, proposed memories, and
   curated text are parsed and validated by the harness. A model never grants
   itself a scope, actor, approval, or evidence ID.
2. **Retrieved content is untrusted data.** Web pages, repository files,
   transcripts, and prior memories cannot override system/tool rules.
   Agent-written inbox memories remain unreviewed even if they claim to be
   approved or contain instruction-like text.
3. **The OS is the primary execution boundary.** Tool scopes are
   defense-in-depth, not a sandbox for generated commands. Normal commands run
   as `ai-agent`; they must not run as `roman` or root.
4. **Curated ownership is separate from agent ownership.** `roman` owns
   organization/project/skill heads and human decisions. `ai-agent` can read
   them but cannot write them through Unix permissions.
5. **Hosted inference is an egress boundary.** Private/internal content and
   credentials must not leave the host unless a human deliberately configures
   a shareable/public workflow and approves hosted use.

## Identity and filesystem controls

The CLI verifies effective usernames rather than trusting environment
variables. Agent execution, inference, offload, and dream jobs require
`ai-agent`; human mutation, approval, rollback, redaction, and portability
operations require `roman`. NixOS tmpfiles and systemd settings provide the
corresponding ownership and modes.

Catalogs and proposals use normalized relative paths, symlink containment,
atomic replacement, restrictive file creation modes, and explicit locks.
`ai-agent` cannot become a human actor by passing `--actor roman` or editing
JSON through a memory tool. A person using `roman` may supply a display name,
but names do not provide independent authentication for the 1–3-person team.

## Memory poisoning and stale knowledge

- Curated guidance is human-controlled; agents write only scratch/inbox.
- Inbox content is marked unreviewed and is not silently injected as
  organization guidance.
- Every version links actor, session/task, and evidence hashes.
- Dream proposals need real evidence and prevalence across distinct runs.
- Approval rechecks evidence, target scope, redaction state, and current base
  hashes. A stale proposal cannot overwrite a newer human/agent version.
- Rollback is a new attributable version, not history destruction.
- Run guidance snapshots bind source hashes so concurrent edits do not mutate
  an active run invisibly.

A human still needs to review semantic correctness. Hashes prove which bytes
changed, not that those bytes are true or safe.

## Concurrency and integrity

One catalog lock serializes each scope/project. Expected body SHA-256 values
are rechecked after drafting and before atomic catalog replacement. A conflict
requires re-read/rebase. One machine-wide execution lock serializes GPU users
across every project state directory and dream worker.

Audit logs are hash chained and append oriented, and operations have durable
pending/terminal states. These mechanisms support recovery and detection, not
Byzantine fault tolerance. An attacker controlling the owning UID can rewrite
files and recompute a chain. Human-owned decisions are consequently not stored
in agent-writable locations.

## Prompts, transcripts, and logs

Run prompts and raw model responses can contain proprietary code, personal
information, or accidental secrets. They receive the run's classification and
are eligible for dreams only when consent, ACL, retention, and redaction state
permit it. Dream subjects receive complete authorized evidence, including tool
metadata, but no unrelated scopes.

Never put credentials in memory, briefs, configuration, or transcripts. Kimi
configuration stores only a key environment variable name. Generated command
environments exclude provider credentials. Error logs redact authorization
values and bound remote response bodies.

Redaction prevents future reads and dream selection and removes affected
canonical payloads. It cannot recall data already sent to a provider, erase
all backups, or guarantee physical deletion. A secret exposure still requires
credential rotation and provider-specific remediation.

## Hosted provider safeguards

- HTTPS and configured host validation; no credential-forwarding redirects.
- Truthful `agentic-ai/<version>` User-Agent and configurable `k3.1-pro` model.
- Explicit hosted approval and public/shareable context classification.
- Context-wide privacy taint: one private input blocks subsequent hosted use.
- Bounded output, time, retries, and response sizes.
- Authentication/client errors do not retry. Rate limits and safe pre-response
  transport failures have bounded backoff. Ambiguous outcomes are recorded for
  reconciliation rather than blindly repeated.
- No hosted fallback from a failed local call and no hosted dream timer by
  default. No live provider call is part of the offline test suite.

## Commands and network

Commands remain fixed configured argv with `shell=False`, minimal environment,
workspace cwd, timeouts, process-group termination, and capped output. They
can still perform anything the `ai-agent` OS account can do; declared write
scopes do not confine a malicious test binary at the kernel level. Use the
hardened systemd service and restrictive project permissions for unattended
execution.

The old example's wildcard web allowlist is not a safe production default.
New configuration starts with web disabled or explicit domains. The existing
NixOS firewall blocks common private/LAN destinations for `ai-sandbox` but
allows public egress; it is not a per-domain TLS proxy.

## Dreaming safeguards

Dream jobs can create only proposals. Human decisions live under `roman`, and
approval is the sole shared-memory promotion path. Evidence IDs and prevalence
are computed by deterministic code. Each proposal targets one catalog for
atomic acceptance. Rejection, approval, and stale outcomes are terminal and
idempotent; a repeated request cannot apply a change twice.

## Availability and resource limits

Memory documents, search results, transcript batches, remote responses,
command output, plan tasks, model turns, dream shards, and repair cycles all
have limits. Imports reject unsafe paths and excessive entries/bytes. Local
inference is serial because the GPU is constrained; logical subject fan-out
must not be represented as parallel 70B execution.

## Known limitations

- The same `ai-agent` UID hosts multiple logical agents; per-agent scratch
  isolation is application policy, not a kernel boundary between agents.
- Generated commands can modify other agent-writable state if deliberately
  malicious. Curated human-owned memory remains outside that write authority.
- Hashing is not a signature, and audit logs are not remote immutable storage.
- Portable exports are plaintext unless the operator encrypts the destination.
- No claim is made that memory/dreaming improves quality or cost until measured
  on repeated real tasks.
