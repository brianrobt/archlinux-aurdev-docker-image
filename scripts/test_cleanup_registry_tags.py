#!/usr/bin/env python3
"""Unit tests for registry tag retention policy helpers."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from cleanup_registry_tags import (
    cleanup_dockerhub,
    cleanup_ghcr,
    ghcr_version_eligible,
    hub_tag_eligible,
    parse_protected_tags,
    parse_timestamp,
)


class PolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.protected = parse_protected_tags("latest,master,main")
        self.now = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
        self.cutoff = self.now - timedelta(days=14)

    def test_protected_never_eligible(self) -> None:
        old = (self.cutoff - timedelta(days=30)).isoformat().replace("+00:00", "Z")
        for name in ("latest", "master", "main"):
            self.assertFalse(
                hub_tag_eligible(name, old, protected=self.protected, cutoff=self.cutoff)
            )

    def test_old_version_eligible(self) -> None:
        old = (self.cutoff - timedelta(days=1)).isoformat().replace("+00:00", "Z")
        self.assertTrue(
            hub_tag_eligible("v1.4.100", old, protected=self.protected, cutoff=self.cutoff)
        )

    def test_recent_version_kept(self) -> None:
        recent = (self.cutoff + timedelta(days=1)).isoformat().replace("+00:00", "Z")
        self.assertFalse(
            hub_tag_eligible("v1.4.325", recent, protected=self.protected, cutoff=self.cutoff)
        )

    def test_ghcr_mixed_protected_kept(self) -> None:
        old = (self.cutoff - timedelta(days=40)).isoformat().replace("+00:00", "Z")
        self.assertFalse(
            ghcr_version_eligible(
                ["latest", "v1.4.325"],
                old,
                protected=self.protected,
                cutoff=self.cutoff,
            )
        )

    def test_ghcr_old_version_only_eligible(self) -> None:
        old = (self.cutoff - timedelta(days=40)).isoformat().replace("+00:00", "Z")
        self.assertTrue(
            ghcr_version_eligible(
                ["v1.4.100"],
                old,
                protected=self.protected,
                cutoff=self.cutoff,
            )
        )

    def test_parse_timestamp_fractional(self) -> None:
        dt = parse_timestamp("2026-07-10T22:52:31.696215341Z")
        self.assertIsNotNone(dt)
        assert dt is not None
        self.assertEqual(dt.tzinfo, timezone.utc)


class CleanupDryRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.protected = frozenset({"latest", "master", "main"})
        self.cutoff = datetime(2026, 7, 1, tzinfo=timezone.utc)

    def test_hub_dry_run_does_not_delete(self) -> None:
        delete = mock.Mock()
        tags = [
            {"name": "latest", "tag_last_pushed": "2026-06-01T00:00:00Z"},
            {"name": "v1.4.1", "tag_last_pushed": "2026-06-01T00:00:00Z"},
            {"name": "v1.4.2", "tag_last_pushed": "2026-07-10T00:00:00Z"},
        ]
        result = cleanup_dockerhub(
            username="u",
            token="t",
            namespace="u",
            repository="repo",
            protected=self.protected,
            cutoff=self.cutoff,
            dry_run=True,
            login=lambda *_: "jwt",
            list_tags=lambda *_: tags,
            delete_tag=delete,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.would_delete, ["u/repo:v1.4.1"])
        self.assertIn("latest", result.kept)
        self.assertIn("v1.4.2", result.kept)
        delete.assert_not_called()

    def test_ghcr_dry_run_skips_protected_versions(self) -> None:
        delete = mock.Mock()
        versions = [
            {
                "id": 1,
                "updated_at": "2026-06-01T00:00:00Z",
                "metadata": {"container": {"tags": ["latest", "v1.4.9"]}},
            },
            {
                "id": 2,
                "updated_at": "2026-06-01T00:00:00Z",
                "metadata": {"container": {"tags": ["v1.4.1"]}},
            },
        ]
        result = cleanup_ghcr(
            token="t",
            package="pkg",
            owner=None,
            protected=self.protected,
            cutoff=self.cutoff,
            dry_run=True,
            list_versions=lambda *_args, **_kwargs: versions,
            delete_version=delete,
        )
        self.assertTrue(result.ok)
        self.assertEqual(len(result.would_delete), 1)
        self.assertIn("tags=['v1.4.1']", result.would_delete[0])
        delete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
