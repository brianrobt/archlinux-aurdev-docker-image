---
title: Registry Tag Retention - Plan
type: feat
date: 2026-07-11
topic: registry-tag-retention
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
---

# Registry Tag Retention - Plan

## Goal Capsule

- **Objective:** Automatically delete stale version tags from Docker Hub and GHCR so both registries stay small without relying on Hub Active/Stale signals.
- **Product authority:** This Product Contract, then Planning Contract KTDs.
- **Execution profile:** `code` — CI workflow + stdlib Python cleanup script.
- **Stop conditions:** Cleanup must never delete `latest`/`master`/`main`; PR builds must not run cleanup; one registry failure must surface visibly.
- **Open blockers:** None.

## Product Contract

### Summary

Keep `latest`, `master`, and `main` by default (via configurable `PROTECTED_TAGS`).
Delete every other tag on Docker Hub and GHCR whose last push is older than 14 days.
Run cleanup from a **standalone** workflow on a weekly schedule and manual `workflow_dispatch` (not coupled to the image build).

### Problem Frame

Daily publishes have produced 270+ tags on Docker Hub.
Hub Image Management Active/Stale is not usable here: crawlers refresh `tag_last_pulled` for nearly every tag in seconds, so pull-based status stays Active even for unused pins.
AUR packages may still pin older tags, but an allowlist or AUR discovery pass is deferred; this first policy is push-age only and can be tightened later.

### Key Decisions

- **Push age, not pull/Active status.** Hub pull timestamps are polluted by bulk manifest crawls; retention must ignore them.
- **14-day window.** Aggressive cleanup; roughly two weeks of daily version tags remain at steady state.
- **Protected floating tags.** `latest`, `master`, and `main` are never deleted by age.
- **Both registries.** Docker Hub (`brianrobt/archlinux-aur-dev`) and GHCR (`ghcr.io/brianrobt/archlinux-aurdev-docker-image`) share the same policy.
- **Standalone cleanup workflow.** Cleanup lives in its own Actions workflow (weekly + manual), separate from build/publish, so publish failures and reusable-workflow permission coupling cannot block image builds.

### Requirements

**Retention rules**

- R1. A tag is eligible for deletion when its last-push timestamp is older than 14 days.
- R2. Tags named `latest`, `master`, or `main` are never deleted by this policy, regardless of age.
- R3. The same retention rules apply to Docker Hub and GHCR for this image.

**When cleanup runs**

- R4. A dedicated registry-cleanup workflow runs on a weekly schedule against both registries.
- R5. The same workflow can be triggered manually (`workflow_dispatch`), with an optional dry-run mode.
- R6. The image build/publish workflow does not invoke cleanup.

**Safety and observability**

- R7. Cleanup logs which tags it keeps and which it deletes (or would delete), per registry.
- R8. A missing or failed cleanup on one registry must not silently skip the other without a visible failure signal in the job summary or logs.
- R9. The retention window (14 days) and protected tag names are configurable without rewriting the policy intent, so the project can tighten or relax later.

### Key Flows

- F1. Manual dry-run or live cleanup
  - **Trigger:** `workflow_dispatch` on the registry-cleanup workflow.
  - **Steps:** List tags on Docker Hub and GHCR; apply R1–R3; delete eligible tags (or log would-delete when dry-run); report results.
  - **Outcome:** Operator can preview or apply retention without waiting for the weekly cron.
  - **Covered by:** R1–R3, R5, R7–R9

- F2. Weekly sweep
  - **Trigger:** Weekly schedule.
  - **Steps:** Same evaluation and deletion as F1 in live mode.
  - **Outcome:** Tags that aged past 14 days are pruned without coupling to publish.
  - **Covered by:** R1–R4, R7–R8

### Acceptance Examples

- AE1. Version tag older than 14 days
  - **Covers:** R1, R3
  - **Given:** `v1.4.100` was last pushed 20 days ago on Hub and GHCR
  - **When:** Cleanup runs
  - **Then:** Both registries delete `v1.4.100`

- AE2. Protected floating tag
  - **Covers:** R2
  - **Given:** `latest` and `master` exist and are older than 14 days by any metric
  - **When:** Cleanup runs
  - **Then:** Neither tag is deleted

- AE3. Recent version tag
  - **Covers:** R1
  - **Given:** `v1.4.325` was pushed yesterday
  - **When:** Cleanup runs
  - **Then:** `v1.4.325` is kept

- AE4. Image build workflow
  - **Covers:** R6
  - **Given:** The build/publish workflow runs (including on pull requests)
  - **When:** The workflow finishes
  - **Then:** No registry cleanup job is invoked from that workflow

### Scope Boundaries

**Deferred for later**

- Allowlisting tags still pinned by AUR packages
- Discovering `FROM brianrobt/archlinux-aur-dev:...` references from AUR sources
- Keeping a fixed “last N” count in addition to (or instead of) the 14-day window
- Using Docker Hub Active/Stale as a deletion signal

**Outside this change**

- Changing publish cadence or version-bump rules
- Removing GHCR publishing
- Cleaning unrelated Docker Hub or GHCR repositories

### Assumptions

- Age is measured from each tag’s last-push timestamp on that registry (not last-pulled).
- Weekly means once per calendar week on a fixed cron; exact UTC hour is a planning detail.
- The first successful cleanup may delete on the order of ~260 Hub version tags under current inventory.
- Tokens already used for publish (`DOCKERHUB_*`, `GITHUB_TOKEN`) are sufficient or can be extended with delete permission where required.

## Planning Contract

### Key Technical Decisions

- **KTD1. One stdlib Python script for both registries.** Prefer `scripts/cleanup_registry_tags.py` over composing Hub + GHCR marketplace actions so retention math, protected-tag rules, dry-run, and logging stay identical (R7–R9). No new pip dependencies.
- **KTD2. Docker Hub deletes by tag name.** Authenticate with Hub login JWT from `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN`; list via Hub tags API using `tag_last_pushed`; `DELETE /v2/repositories/{ns}/{repo}/tags/{tag}/`. Avoid blind digest GC that can break multi-arch indexes.
- **KTD3. GHCR deletes by package version id.** List `GET /user/packages/container/{package}/versions`; delete `DELETE .../versions/{id}`. Skip any version that still carries a protected tag. Age GHCR versions with `updated_at` (fallback `created_at`) as the push-age proxy — GHCR has no `tag_last_pushed`.
- **KTD4. Standalone cleanup workflow.** `.github/workflows/registry-cleanup.yml` only — weekly cron Sunday `05:00` UTC plus `workflow_dispatch` with `dry_run` (default true for manual). Do not call it from `docker-build.yml`.
- **KTD5. Dry-run is operator-controlled; schedule is live.** Manual runs default to dry-run; scheduled runs delete. Document Hub PAT **Delete** scope in `.github/WORKFLOW_SETUP.md`.

### High-level design

```text
[weekly cron | workflow_dispatch]
        |
        v
cleanup_registry_tags.py
  |-- Hub: login -> list tags -> filter -> DELETE tag (or dry-run log)
  |-- GHCR: list versions -> filter -> DELETE version id (or dry-run log)
  |-- exit non-zero if either registry hard-fails after partial work
  |-- write GITHUB_STEP_SUMMARY counts
```

Config via env (R9): `RETENTION_DAYS` (default 14), `PROTECTED_TAGS` (default `latest,master,main`), `DRY_RUN`, Hub credentials, `GITHUB_TOKEN`, image/package names.

### Assumptions (planning)

- Weekly cron: Sunday `05:00` UTC (after the existing daily build cron at `04:00`).
- Hub token must include Delete; if it only has Write today, first live run will fail Hub deletes until the secret is rotated — document that.
- `GITHUB_TOKEN` with `packages: write` can delete versions of packages this repo publishes; if not, surface clear 403 guidance.
- GHCR package name is `archlinux-aurdev-docker-image` under user `brianrobt`.

### Sequencing

1. U1 — cleanup script + unit tests (policy pure functions)
2. U2 — wire standalone GitHub Actions workflow (weekly + dry-run dispatch)
3. U3 — operator docs (token scopes, how to dry-run)

### Risks

- Shared digest on GHCR between a protected tag and a version tag: version must be kept if any protected tag is present (handled in KTD3).
- Hub token lacking Delete scope fails Hub half; job must fail visibly (R8) while still attempting GHCR (or fail after both attempts with combined status).

## Implementation Units

### U1. Retention cleanup script

- **Goal:** Implement configurable Hub + GHCR tag retention with dry-run and logging.
- **Requirements:** R1–R3, R7–R9
- **Files:** `scripts/cleanup_registry_tags.py`, `scripts/test_cleanup_registry_tags.py` (or `tests/test_cleanup_registry_tags.py` if adding a tests dir)
- **Approach:** Pure helpers for eligibility (`is_protected`, `is_older_than`, parse timestamps). Hub/GHCR clients using `urllib` + JSON. CLI/main driven by env vars. Non-zero exit if either registry reports API errors on list/delete (not on “nothing to delete”).
- **Test scenarios:**
  - Protected tag names never eligible even when older than retention.
  - Version tag older than retention is eligible; newer is not.
  - GHCR version with mixed protected + version tags is not deleted.
  - GHCR version with only old version tags is deleted.
  - Dry-run path records would-delete without invoking delete (mock HTTP or inject fake client).
- **Verification:** `python3 -m unittest` (or pytest if already present — prefer unittest/stdlib to avoid new deps) on the policy tests.
- **Dependencies:** None

### U2. GitHub Actions wiring

- **Goal:** Run cleanup weekly and on demand from a standalone workflow, never from the image build.
- **Requirements:** R4–R8
- **Files:** `.github/workflows/registry-cleanup.yml` (not `docker-build.yml`)
- **Approach:** Weekly cron + `workflow_dispatch` with `dry_run`. Permissions: `packages: write` and `contents: read`. Checkout repo for script. Fail the job if the script exits non-zero.
- **Test scenarios:**
  - Image build workflow has no cleanup job.
  - Manual dry-run input maps to `DRY_RUN=true`.
  - Schedule uses live deletes.
- **Verification:** YAML review + local dry-run of script against Hub/GHCR when credentials available.
- **Dependencies:** U1

### U3. Operator documentation

- **Goal:** Document retention policy, token Delete scope, dry-run, and weekly schedule.
- **Requirements:** R9 (operator configurability), Assumptions
- **Files:** `.github/WORKFLOW_SETUP.md`, brief note in `README.md` if it already documents publishing
- **Approach:** Extend existing workflow setup doc; do not invent a new top-level doc.
- **Test scenarios:** N/A (docs)
- **Verification:** Doc mentions Hub Delete scope, env knobs, and how to run dry-run via Actions UI or locally.
- **Dependencies:** U2

## Verification Contract

| Gate | Command / check | Applies to |
|------|-----------------|------------|
| Unit tests | `cd scripts && python3 -m unittest test_cleanup_registry_tags` | U1 |
| Workflow isolation | Confirm `docker-build.yml` does not call cleanup | U2 |
| Manual dry-run | Local script or Actions `dry_run: true` | U2, live registries |
| Live cleanup | First non-dry weekly/manual run deletes aged tags; protected tags remain | F1/F2 |

## Definition of Done

- [ ] U1 script merges with passing unit tests for protected/age/GHCR mixed-tag cases
- [ ] U2 standalone weekly + dispatch workflow (no build coupling)
- [ ] U3 documents Hub Delete token scope and dry-run
- [ ] R1–R9 satisfied; AE1–AE4 covered by tests and/or workflow conditions
- [ ] PR opened with summary of retention policy and expected first-run deletion volume
