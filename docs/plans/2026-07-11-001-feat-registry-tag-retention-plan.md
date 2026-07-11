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

Keep `latest`, `master`, and `main` indefinitely.
Delete every other tag on Docker Hub and GHCR whose last push is older than 14 days.
Run that cleanup after every successful publish and on a weekly schedule.

### Problem Frame

Daily publishes have produced 270+ tags on Docker Hub.
Hub Image Management Active/Stale is not usable here: crawlers refresh `tag_last_pulled` for nearly every tag in seconds, so pull-based status stays Active even for unused pins.
AUR packages may still pin older tags, but an allowlist or AUR discovery pass is deferred; this first policy is push-age only and can be tightened later.

### Key Decisions

- **Push age, not pull/Active status.** Hub pull timestamps are polluted by bulk manifest crawls; retention must ignore them.
- **14-day window.** Aggressive cleanup; roughly two weeks of daily version tags remain at steady state.
- **Protected floating tags.** `latest`, `master`, and `main` are never deleted by age.
- **Both registries.** Docker Hub (`brianrobt/archlinux-aur-dev`) and GHCR (`ghcr.io/brianrobt/archlinux-aurdev-docker-image`) share the same policy.
- **Publish + weekly.** Cleanup runs after each successful non-PR publish and on a weekly sweep so missed runs still prune.

### Requirements

**Retention rules**

- R1. A tag is eligible for deletion when its last-push timestamp is older than 14 days.
- R2. Tags named `latest`, `master`, or `main` are never deleted by this policy, regardless of age.
- R3. The same retention rules apply to Docker Hub and GHCR for this image.

**When cleanup runs**

- R4. After every successful publish on the default branch (when new tags are pushed), cleanup runs against both registries.
- R5. A weekly scheduled job also runs the same cleanup against both registries.
- R6. Pull requests and failed publishes do not run cleanup.

**Safety and observability**

- R7. Cleanup logs which tags it keeps and which it deletes (or would delete), per registry.
- R8. A missing or failed cleanup on one registry must not silently skip the other without a visible failure signal in the job summary or logs.
- R9. The retention window (14 days) and protected tag names are configurable without rewriting the policy intent, so the project can tighten or relax later.

### Key Flows

- F1. Post-publish cleanup
  - **Trigger:** Successful default-branch publish of version + floating tags.
  - **Steps:** List tags on Docker Hub and GHCR; apply R1–R3; delete eligible tags; report results.
  - **Outcome:** Registries retain protected tags plus version tags pushed within 14 days.
  - **Covered by:** R1–R4, R6–R8

- F2. Weekly sweep
  - **Trigger:** Weekly schedule.
  - **Steps:** Same evaluation and deletion as F1, independent of a new publish.
  - **Outcome:** Tags that aged past 14 days since the last publish are still pruned.
  - **Covered by:** R1–R3, R5, R7–R8

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

- AE4. PR build
  - **Covers:** R6
  - **Given:** A pull request triggers the build workflow
  - **When:** The workflow finishes
  - **Then:** No registry cleanup runs

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
- **KTD4. Shared cleanup job, two triggers.** Reusable job/workflow path: (1) `needs: build` after successful non-PR publish in `.github/workflows/docker-build.yml`; (2) weekly cron Sunday `05:00` UTC plus `workflow_dispatch` with optional `dry_run` input. Separate small workflow that calls the same script is acceptable if wiring `needs` is awkward — same script and env contract either way.
- **KTD5. Dry-run is operator-controlled, live by default.** `DRY_RUN=true` / `workflow_dispatch` input prints keep/delete sets without calling delete APIs. Scheduled and post-publish runs default to live deletes (product accepted the first ~260-tag purge). Document Hub PAT **Delete** scope in `.github/WORKFLOW_SETUP.md`.

### High-level design

```text
[build success | weekly cron | workflow_dispatch]
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
2. U2 — wire GitHub Actions (post-publish + weekly + dry-run)
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

- **Goal:** Run cleanup after successful publishes and weekly, never on PRs.
- **Requirements:** R4–R8
- **Files:** `.github/workflows/docker-build.yml` and/or `.github/workflows/registry-cleanup.yml`
- **Approach:** After `build` succeeds on non-PR default-branch pushes/schedules that published, run cleanup job with secrets. Add weekly-only trigger path. Expose `dry_run` boolean on `workflow_dispatch`. Permissions: `packages: write` (and `contents: read` if checkout needed). Checkout repo for script. Fail the job if the script exits non-zero.
- **Test scenarios:**
  - Workflow YAML conditions exclude `pull_request`.
  - Manual dry-run input maps to `DRY_RUN=true`.
  - Post-publish job `needs: build` and skips when build skipped/failed.
- **Verification:** YAML review + local dry-run of script against Hub list (read-only) if credentials available; otherwise unittest coverage of condition helpers and workflow condition comments in PR.
- **Dependencies:** U1

### U3. Operator documentation

- **Goal:** Document retention policy, token Delete scope, dry-run, and weekly schedule.
- **Requirements:** R9 (operator configurability), Assumptions
- **Files:** `.github/WORKFLOW_SETUP.md`, brief note in `README.md` if it already documents publishing
- **Approach:** Extend existing workflow setup doc; do not invent a new top-level doc.
- **Test scenarios:** N/A (docs)
- **Verification:** Doc mentions Hub Delete scope, env knobs, and how to run dry-run via Actions UI.
- **Dependencies:** U2

## Verification Contract

| Gate | Command / check | Applies to |
|------|-----------------|------------|
| Unit tests | `python3 -m unittest scripts.test_cleanup_registry_tags` (adjust path to match U1 layout) | U1 |
| Workflow conditions | Confirm cleanup jobs gated off `pull_request` | U2 |
| Manual dry-run | `workflow_dispatch` with `dry_run: true` after merge (operator) | U2, live registries |
| Live cleanup | First non-dry scheduled/post-publish run deletes aged tags; protected tags remain | F1/F2 |

## Definition of Done

- [ ] U1 script merges with passing unit tests for protected/age/GHCR mixed-tag cases
- [ ] U2 runs cleanup after successful non-PR publish and on weekly cron
- [ ] U3 documents Hub Delete token scope and dry-run
- [ ] R1–R9 satisfied; AE1–AE4 covered by tests and/or workflow conditions
- [ ] PR opened with summary of retention policy and expected first-run deletion volume
