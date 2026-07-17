# GEO IAS Backend Repository Instructions

These instructions apply to the `geo-whatsapp-webhook/` FastAPI repository. Read the workspace-root `AGENTS.md`, the product specification, and current planning documents before implementation.

## Git ownership

The user exclusively owns all source-control actions. Codex may inspect, create, modify, and delete approved files, but must not stage, commit, push, pull, merge, rebase, reset, stash, tag, create/delete branches, modify remotes, amend commits, alter Git history, or use checkout/restore to overwrite changes. Read-only Git inspection is allowed. Never discard or overwrite user changes. Suggested commit messages are informational only.

After every task, report every file created, modified, and deleted. These instructions apply even when this file is untracked; Codex must never stage or commit it.

## Framework, data, and infrastructure

- Preserve FastAPI, MongoDB, the separate backend repository, existing server/domains/deployment process, current environment-variable names, Meta configuration, and `/webhooks/whatsapp` URL.
- Production configuration must continue to come from the existing process/service environment. Do not create or expect a production `.env` file, and do not assume the environment-delivery mechanism without server evidence. `.env.example` is local/reference documentation only.
- Do not introduce microservices, Docker, a new database, a replacement backend framework, or a parallel legacy API.
- Never log or return secrets, access tokens, authorization headers, or complete successful provider payloads.
- Do not expose or commit secrets.
- Do not automatically run destructive production-database operations. Cleanup scripts must be manual, reviewable, dry-run-first, collection-specific, count-aware, suppression-preserving, and explicit about rollback limitations.

## Legacy classification and replacement

Classify relevant code as KEEP, REFACTOR, REMOVE, or VERIFY BEFORE REMOVAL using `docs/LEGACY_CODE_REMOVAL_PLAN.md`.

- Keep/refactor environment loading, MongoDB connectivity, Meta request construction, phone normalization, webhook verification, provider-message correlation, and useful extraction logic.
- Replace plaintext-password authentication, hard-coded JWT security, public business routes, template/campaign-specific APIs, duplicate send/process logic, raw-success payload persistence, and old campaign/message response structures.
- Remove empty/dead models, schemas, services, helpers, imports, test-only routes, and dependencies only after caller searches and replacement verification.
- Do not keep replaced files under `old_*`, `legacy_*`, `backup_*`, `unused_*`, or `*_v2` names.
- Remove obsolete application code after its replacement is connected and tested; never keep duplicate legacy and new implementations active in parallel.
- Preserve suppression behavior and the configured Meta webhook route until production usage and replacement behavior are verified.
- Never remove an endpoint while the frontend or an external caller still uses it unless every caller is updated in the same logical change batch.

## Verification and reporting

For applicable changes, run backend tests, authorization/duplicate/idempotency/index checks, and startup validation. Search router registrations, imports, services, schemas, collections, and both repositories for remaining references after removal. Report created/modified/deleted files, untouched user changes, model/index changes, environment additions, commands/tests/results, risks, removed endpoints, and suggested manual frontend/backend commit messages. Stop for user review without committing.
