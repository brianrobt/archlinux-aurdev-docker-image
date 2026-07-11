#!/usr/bin/env python3
"""Delete stale container tags from Docker Hub and GHCR by push age.

Environment:
  RETENTION_DAYS   Days to keep non-protected tags (default: 14)
  PROTECTED_TAGS   Comma-separated forever tags (default: latest,master,main)
  DRY_RUN          If true/1/yes, log actions without deleting
  DOCKERHUB_USERNAME / DOCKERHUB_TOKEN
  DOCKERHUB_NAMESPACE / DOCKERHUB_REPOSITORY  (default: brianrobt / archlinux-aur-dev)
  GITHUB_TOKEN
  GHCR_PACKAGE     (default: archlinux-aurdev-docker-image)
  GHCR_OWNER       Optional; defaults to authenticated user package API
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable


DEFAULT_RETENTION_DAYS = 14
DEFAULT_PROTECTED = ("latest", "master", "main")
HUB_API = "https://hub.docker.com/v2"
GITHUB_API = "https://api.github.com"


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def parse_protected_tags(raw: str | None) -> frozenset[str]:
    if raw is None or not raw.strip():
        return frozenset(DEFAULT_PROTECTED)
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # Hub/GitHub may emit >6 fractional digits; fromisoformat accepts up to microseconds.
    if "." in text:
        head, rest = text.split(".", 1)
        digits = ""
        tz = ""
        for index, char in enumerate(rest):
            if char.isdigit():
                digits += char
            else:
                tz = rest[index:]
                break
        text = f"{head}.{digits[:6]}{tz}"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_protected(tag: str, protected: frozenset[str]) -> bool:
    return tag in protected


def is_older_than(pushed_at: datetime | None, cutoff: datetime) -> bool:
    if pushed_at is None:
        return False
    return pushed_at < cutoff


def hub_tag_eligible(
    name: str,
    tag_last_pushed: str | None,
    *,
    protected: frozenset[str],
    cutoff: datetime,
) -> bool:
    if is_protected(name, protected):
        return False
    return is_older_than(parse_timestamp(tag_last_pushed), cutoff)


def ghcr_version_eligible(
    tags: Iterable[str],
    timestamp: str | None,
    *,
    protected: frozenset[str],
    cutoff: datetime,
) -> bool:
    tag_list = list(tags)
    if not tag_list:
        return False
    if any(is_protected(tag, protected) for tag in tag_list):
        return False
    return is_older_than(parse_timestamp(timestamp), cutoff)


@dataclass
class RegistryResult:
    name: str
    kept: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    would_delete: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class HttpError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    expect_json: bool = True,
) -> Any:
    data = None
    req_headers = {"Accept": "application/json", "User-Agent": "archlinux-aurdev-cleanup"}
    if headers:
        req_headers.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            if not expect_json or response.status == 204 or not raw:
                return None
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HttpError(f"{method} {url} failed: HTTP {exc.code} {detail}", status=exc.code) from exc
    except urllib.error.URLError as exc:
        raise HttpError(f"{method} {url} failed: {exc}") from exc


def hub_login(username: str, token: str) -> str:
    payload = http_json(
        "POST",
        f"{HUB_API}/users/login/",
        body={"username": username, "password": token},
    )
    jwt = payload.get("token") if isinstance(payload, dict) else None
    if not jwt:
        raise HttpError("Docker Hub login did not return a token")
    return jwt


def hub_list_tags(namespace: str, repository: str, jwt: str) -> list[dict[str, Any]]:
    url: str | None = (
        f"{HUB_API}/repositories/{namespace}/{repository}/tags"
        f"?page_size=100&ordering=last_updated"
    )
    tags: list[dict[str, Any]] = []
    while url:
        page = http_json("GET", url, headers={"Authorization": f"Bearer {jwt}"})
        tags.extend(page.get("results") or [])
        url = page.get("next")
    return tags


def hub_delete_tag(namespace: str, repository: str, tag: str, jwt: str) -> None:
    encoded = urllib.parse.quote(tag, safe="")
    http_json(
        "DELETE",
        f"{HUB_API}/repositories/{namespace}/{repository}/tags/{encoded}/",
        headers={"Authorization": f"Bearer {jwt}"},
        expect_json=False,
    )


def cleanup_dockerhub(
    *,
    username: str,
    token: str,
    namespace: str,
    repository: str,
    protected: frozenset[str],
    cutoff: datetime,
    dry_run: bool,
    login: Callable[[str, str], str] = hub_login,
    list_tags: Callable[[str, str, str], list[dict[str, Any]]] = hub_list_tags,
    delete_tag: Callable[[str, str, str, str], None] = hub_delete_tag,
) -> RegistryResult:
    result = RegistryResult(name="dockerhub")
    try:
        jwt = login(username, token)
        tags = list_tags(namespace, repository, jwt)
    except HttpError as exc:
        result.errors.append(str(exc))
        return result

    for tag in tags:
        name = tag.get("name") or ""
        pushed = tag.get("tag_last_pushed") or tag.get("last_updated")
        if hub_tag_eligible(name, pushed, protected=protected, cutoff=cutoff):
            label = f"{namespace}/{repository}:{name}"
            if dry_run:
                result.would_delete.append(label)
            else:
                try:
                    delete_tag(namespace, repository, name, jwt)
                    result.deleted.append(label)
                except HttpError as exc:
                    result.errors.append(f"delete {label}: {exc}")
        else:
            result.kept.append(name)
    return result


def ghcr_list_versions(package: str, token: str, owner: str | None = None) -> list[dict[str, Any]]:
    if owner:
        base = f"{GITHUB_API}/users/{urllib.parse.quote(owner)}/packages/container/{urllib.parse.quote(package)}/versions"
    else:
        base = f"{GITHUB_API}/user/packages/container/{urllib.parse.quote(package)}/versions"
    versions: list[dict[str, Any]] = []
    page = 1
    while True:
        url = f"{base}?per_page=100&page={page}"
        batch = http_json(
            "GET",
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if not isinstance(batch, list) or not batch:
            break
        versions.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return versions


def ghcr_delete_version(package: str, version_id: int, token: str, owner: str | None = None) -> None:
    if owner:
        url = (
            f"{GITHUB_API}/users/{urllib.parse.quote(owner)}/packages/container/"
            f"{urllib.parse.quote(package)}/versions/{version_id}"
        )
    else:
        url = f"{GITHUB_API}/user/packages/container/{urllib.parse.quote(package)}/versions/{version_id}"
    http_json(
        "DELETE",
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        expect_json=False,
    )


def cleanup_ghcr(
    *,
    token: str,
    package: str,
    owner: str | None,
    protected: frozenset[str],
    cutoff: datetime,
    dry_run: bool,
    list_versions: Callable[..., list[dict[str, Any]]] = ghcr_list_versions,
    delete_version: Callable[..., None] = ghcr_delete_version,
) -> RegistryResult:
    result = RegistryResult(name="ghcr")
    try:
        versions = list_versions(package, token, owner)
    except HttpError as exc:
        result.errors.append(str(exc))
        return result

    for version in versions:
        version_id = version.get("id")
        meta = (version.get("metadata") or {}).get("container") or {}
        tags = list(meta.get("tags") or [])
        timestamp = version.get("updated_at") or version.get("created_at")
        label = f"ghcr:{package}@{version_id} tags={tags or ['<untagged>']}"
        if ghcr_version_eligible(tags, timestamp, protected=protected, cutoff=cutoff):
            if dry_run:
                result.would_delete.append(label)
            else:
                try:
                    delete_version(package, int(version_id), token, owner)
                    result.deleted.append(label)
                except HttpError as exc:
                    result.errors.append(f"delete {label}: {exc}")
        else:
            result.kept.extend(tags or [f"untagged:{version_id}"])
    return result


def write_summary(results: list[RegistryResult], dry_run: bool) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    lines = [
        "## Registry tag retention",
        "",
        f"**Mode:** {'dry-run' if dry_run else 'live'}",
        "",
    ]
    for result in results:
        lines.append(f"### {result.name}")
        lines.append(f"- Kept: {len(result.kept)}")
        lines.append(f"- Deleted: {len(result.deleted)}")
        lines.append(f"- Would delete: {len(result.would_delete)}")
        if result.errors:
            lines.append(f"- Errors: {len(result.errors)}")
            for err in result.errors:
                lines.append(f"  - {err}")
        lines.append("")
    text = "\n".join(lines)
    print(text)
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")


def log_actions(result: RegistryResult) -> None:
    for name in result.kept:
        print(f"[{result.name}] keep {name}")
    for name in result.would_delete:
        print(f"[{result.name}] would-delete {name}")
    for name in result.deleted:
        print(f"[{result.name}] deleted {name}")
    for err in result.errors:
        print(f"[{result.name}] ERROR {err}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    _ = argv
    retention_days = int(os.environ.get("RETENTION_DAYS", str(DEFAULT_RETENTION_DAYS)))
    protected = parse_protected_tags(os.environ.get("PROTECTED_TAGS"))
    dry_run = env_bool("DRY_RUN", False)
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    print(
        f"Retention={retention_days}d cutoff={cutoff.isoformat()} "
        f"protected={sorted(protected)} dry_run={dry_run}"
    )

    results: list[RegistryResult] = []

    hub_user = os.environ.get("DOCKERHUB_USERNAME", "")
    hub_token = os.environ.get("DOCKERHUB_TOKEN", "")
    if hub_user and hub_token:
        results.append(
            cleanup_dockerhub(
                username=hub_user,
                token=hub_token,
                namespace=os.environ.get("DOCKERHUB_NAMESPACE", hub_user),
                repository=os.environ.get("DOCKERHUB_REPOSITORY", "archlinux-aur-dev"),
                protected=protected,
                cutoff=cutoff,
                dry_run=dry_run,
            )
        )
    else:
        results.append(
            RegistryResult(
                name="dockerhub",
                errors=["DOCKERHUB_USERNAME/DOCKERHUB_TOKEN not set"],
            )
        )

    gh_token = os.environ.get("GITHUB_TOKEN", "")
    if gh_token:
        results.append(
            cleanup_ghcr(
                token=gh_token,
                package=os.environ.get("GHCR_PACKAGE", "archlinux-aurdev-docker-image"),
                owner=os.environ.get("GHCR_OWNER") or None,
                protected=protected,
                cutoff=cutoff,
                dry_run=dry_run,
            )
        )
    else:
        results.append(RegistryResult(name="ghcr", errors=["GITHUB_TOKEN not set"]))

    for result in results:
        log_actions(result)
    write_summary(results, dry_run)

    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
