# v0.2.0 development log

## 2026-11-04 — preservation and research

- Confirmed clean `Sway-Waybar` baseline at `a8e4d1d`.
- Created local `release/v0.1.0-local-model-swap-dag-agents` and annotated tag
  `agentic-ai-v0.1.0-local-model-swap-dag-agents`; did not push.
- Ran the complete baseline suite: **44 tests passed** in 10.653 seconds.
- Located and read the original Lamis Mukta talk transcript rather than relying
  on the X repost. Recorded requirement mapping in
  `presentation-traceability.md`.
- Reviewed the current `verbisept-l1-only` implementation and the neighbouring
  project's historical evolution. Recorded transferable patterns and known
  limitations in `verbisept-transfer.md`.
- Established the v0.2.0 architecture, privacy model, and human-approval
  boundary in `memory-dreaming-architecture.md` and `security-model.md`.

Implementation and verification results are appended below as they are
completed. No real GPU inference, live Kimi request, Nix rebuild, or remote
push was performed during preservation/research.

## 2026-11-04 — implementation

- Bumped the package to v0.2.0 and committed the architecture/release lineage.
- Implemented canonical Markdown/TOML memories and skills, per-scope catalogs,
  immutable versions, provenance, locked SHA-256 CAS, hash-chained audits,
  recovery journals, redaction, disposable SQLite indexes, and safe portable
  export/import.
- Added in-band memory tools, run guidance snapshots, canonical transcripts,
  Kimi K3.1 Pro routing with privacy taint, global execution locking, command
  output caps, effective-UID CLI gates, and verified llama.cpp orphan recovery.
- Implemented resumable dream subject/curator workflows with deterministic
  evidence/prevalence validation, staged diffs, human-only atomic promotion,
  transcript revocation, and observed run-metric comparisons.
- Added NixOS package installation, a locked `ai-agent` system identity,
  group-aware memory roots, a hardened optional service, and a disabled timer.
- Reviewed the memory core for same-UID and crash edge cases and added
  regression coverage for every concrete finding. Strengthened dream resume,
  input/artifact integrity, privacy snapshots, and approval/redaction races.
- Updated operator, architecture, traceability, file protocol, and verification
  documentation. Current offline result: **89 tests passed** in 19.853 seconds.
  Real GPU, live Kimi, Nix evaluation/activation, and two-UID workstation gates
  remain explicitly open in `verification.md`.
