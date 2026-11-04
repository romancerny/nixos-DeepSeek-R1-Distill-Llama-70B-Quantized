+++
classification = "private"
id = "memory-curation"
kind = "skill"
review_status = "curated"
schema_version = 1
summary = "Review and curate versioned memories without losing provenance or current updates"
tags = ["memory", "review", "provenance"]
title = "Memory curation procedure"
+++

1. Search before creating a memory; update an existing focused document when appropriate.
2. Verify actor, scope, classification, review status, and source provenance.
3. Read the current head and use its SHA-256 as the update precondition.
4. Keep one lesson per document, small enough to retrieve on demand.
5. Treat inbox content as unreviewed. Do not present it as organization policy.
6. On conflict, re-read and rebase; never overwrite a newer head to make an update succeed.
7. Run memory verification after mutation, export, rollback, or redaction.
