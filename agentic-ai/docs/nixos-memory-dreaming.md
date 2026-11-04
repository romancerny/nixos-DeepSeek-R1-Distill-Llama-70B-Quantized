# NixOS memory and dreaming operations

## 1. Apply the declarative configuration

The root configuration installs `agentic-ai`, the `ai-agent` system identity,
shared state directories, and an optional dream service/timer. Review and apply
it through the normal NixOS administration process as `roman`/root:

```bash
sudo nixos-rebuild test --flake .#beast-kf
```

This document does not claim that a rebuild or activation was executed during
development. Real GPU models and the NixOS configuration are separate
acceptance gates from the offline Python tests.

`ai-agent` is deliberately a locked, non-login system account. Run commands
with an explicit executable as root; do not attempt an interactive login:

```bash
sudo -u ai-agent agentic-ai doctor --config /etc/agentic-ai/config.json --json
```

`roman` remains the human administrator and the only identity allowed to
curate/promote/redact/export shared memory. The `ai-sandbox` supplementary
group provides group-read review access, not `wheel` or sudo privileges.

## 2. Initialize configuration and memory

An example is installed at `/etc/agentic-ai/config.example.json`. Copy it as
root and review every path, model, command, and privacy setting:

```bash
sudo cp /etc/agentic-ai/config.example.json /etc/agentic-ai/config.json
sudo -u ai-agent agentic-ai doctor --config /etc/agentic-ai/config.json --json
agentic-ai memory init --root /var/lib/agentic-ai/memory --actor-name "Roman"
```

The example is local-only: Kimi and web research are disabled. Its configured
run root is `/var/lib/agentic-ai/runs` and its memory project is `default`.
Runs use the ordinary `RunStore` layout below that root (`runs/<run-id>`).

Add a human-curated Markdown/TOML memory with `memory put`. Do not store
credentials, API keys, bearer tokens, or private keys in memory.

```bash
agentic-ai memory put \
  --root /var/lib/agentic-ai/memory --scope org \
  --file ./operating-principles.md --operation created --actor-name "Roman"
```

The source checkout includes `seeds/operating-principles.md`,
`seeds/memory-curation.md`, and `seeds/dream-review.md`. They are examples,
not automatic replacements for human judgment; import them only after review.
The two skill examples belong in `--scope skills`.

Curated files use `roman:ai-sandbox` ownership with group-read modes. Agent
inbox/proposal state is owned by `ai-agent`; locks are group-writable (`0660`)
so human redaction/approval and agent mutation cannot race. Search indexes are
per-UID disposable files in the group-writable index directory.

## 3. Normal run lifecycle as `ai-agent`

Create project state under the configured run root, or use a project-specific
state directory and add that root to `memory.run_roots`:

```bash
sudo -u ai-agent agentic-ai run \
  --config /etc/agentic-ai/config.json \
  --state-dir /var/lib/agentic-ai/runs \
  --goal-file /var/lib/agentic-ai/brief.md --stop-after-plan

sudo -u ai-agent agentic-ai resume RUN_ID \
  --config /etc/agentic-ai/config.json --state-dir /var/lib/agentic-ai/runs
```

Only terminal runs whose configuration has `memory.dreaming_enabled: true`
produce eligible transcript manifests. The run classification and project ID
must match the dream selection policy. Transcripts contain prompts, code, and
tool metadata; protect and retain them accordingly.

## 4. Manual dream and human review

Run the worker as `ai-agent`. It selects transcripts, snapshots memory,
executes subject/curator tasks under the same global executor lock as normal
runs, and writes proposals only:

```bash
sudo -u ai-agent agentic-ai dream run --config /etc/agentic-ai/config.json
```

Inspect jobs and proposals as `roman` (read-only commands also work for
`ai-agent` where filesystem scopes allow):

```bash
agentic-ai dream list --config /etc/agentic-ai/config.json
agentic-ai dream review --config /etc/agentic-ai/config.json
agentic-ai dream show PROPOSAL_ID --config /etc/agentic-ai/config.json
agentic-ai dream status JOB_ID --config /etc/agentic-ai/config.json
```

Review the actual diff, prevalence, and source evidence. Then make one human
decision:

```bash
agentic-ai dream approve PROPOSAL_ID \
  --config /etc/agentic-ai/config.json --actor-name "Roman"
agentic-ai dream reject PROPOSAL_ID \
  --config /etc/agentic-ai/config.json --actor-name "Roman" \
  --reason "Insufficiently general for curated memory"
```

Approval rechecks evidence eligibility, prevalence, current base hashes,
permissions, and redaction state before one atomic catalog commit. A stale
proposal requires a new dream. Repeating an approval is idempotent. Dream
workers cannot promote their own output.

If a dream is interrupted:

```bash
sudo -u ai-agent agentic-ai dream resume JOB_ID \
  --config /etc/agentic-ai/config.json
```

## 5. Optional nightly timer

The timer is installed **disabled**. It has no effect until both conditions
are true: `/etc/agentic-ai/config.json` exists and a human explicitly enables
it. Confirm hosted inference and `dream.allow_hosted` are disabled before
unattended use, then run one manual dream successfully.

```bash
sudo systemctl enable --now agentic-ai-dream.timer
systemctl list-timers agentic-ai-dream.timer
sudo systemctl start agentic-ai-dream.service   # manual oneshot invocation
systemctl status agentic-ai-dream.service
```

Disable it at any time:

```bash
sudo systemctl disable --now agentic-ai-dream.timer
```

The service uses `User=ai-agent`, `Group=ai-sandbox`, `NoNewPrivileges`, a
private temporary directory, strict system protection, read-only home paths,
explicit writable state/cache paths, no capabilities, and a 24-hour ceiling.
The timer runs at 03:17 with persistent catch-up and a randomized delay.

## 6. Memory maintenance

```bash
agentic-ai memory search --root /var/lib/agentic-ai/memory --query "testing"
agentic-ai memory history --root /var/lib/agentic-ai/memory --scope curated \
  --namespace default DOCUMENT_ID
agentic-ai memory diff --root /var/lib/agentic-ai/memory --scope curated \
  --namespace default DOCUMENT_ID --from-version v000001
agentic-ai memory verify --root /var/lib/agentic-ai/memory
agentic-ai memory reindex --root /var/lib/agentic-ai/memory
agentic-ai memory export --root /var/lib/agentic-ai/memory \
  --destination /var/lib/agentic-ai/exports/memory-YYYYMMDD
```

Exports contain sensitive plaintext despite restrictive modes. Put them in
encrypted backups with tested restore procedures. Import requires explicit
expected hashes for every existing destination document.

Rollback/delete/redact require `roman`. Redaction blocks future reads and dream
selection immediately and cleans payloads afterward. It cannot erase external
backups or data already sent to a provider.

Revoke one source transcript:

```bash
agentic-ai transcript redact RUN_ID \
  --state-dir /var/lib/agentic-ai/runs --reason "Contains sensitive content" \
  --actor-name "Roman"
```

The original restricted attempt files may remain for forensic retention; the
canonical dream payload is removed and its manifest becomes ineligible.
Rotate any exposed credential separately.

## 7. Optional public/shareable Kimi workflow

Do not edit the unattended local example into a hosted dream configuration.
Use a separate configuration for deliberately public/shareable work. Set the
Kimi API key in the `ai-agent` environment without writing it to Nix, memory,
briefs, or shell history (a secret-aware service credential is preferable).
The configuration stores only `KIMI_API_KEY` as the variable name.

Hosted calls require all of the following:

- `kimi.enabled: true`, `kimi.approved: true`, and a valid credential;
- an explicit `--approve-hosted` command/run flag;
- `public` or `shareable` classification for the complete context;
- for dreams, both `dream.allow_hosted` and `kimi.allow_dreaming`.

Private/internal memory or tool output taints the context and blocks later
hosted inference. The offline suite never calls Kimi. Test a single public
request deliberately and review the Kimi Code plan's quota terms before use.
The Kimi Code membership and separately metered Kimi Platform are not treated
as interchangeable products.

## 8. Verification and limitations

Run the offline suite from the source checkout:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=agentic-ai/src \
  python3 -m unittest discover -s agentic-ai/tests -v
```

Then verify on the actual host, as separate gates:

1. `agentic-ai doctor` as `ai-agent`.
2. One small real local run and explicit model-switch/offload inspection.
3. One manual local dream over two consenting terminal runs.
4. Human proposal review/promotion and `memory verify`.
5. NixOS service start/timer status, if unattended operation is desired.
6. Only then an explicitly approved public Kimi request.

Generated commands are not a complete kernel sandbox when run interactively.
Logical agent scratch scopes share one OS UID; their isolation is application
policy, while curated human roots remain a separate Unix ownership boundary.
