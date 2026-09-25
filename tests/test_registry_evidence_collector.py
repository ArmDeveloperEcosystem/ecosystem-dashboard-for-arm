"""Focused tests for the bounded registry evidence collector."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_PATH = ROOT / "build_steps/collect_registry_evidence.py"
SPEC = importlib.util.spec_from_file_location("registry_evidence_collector", COLLECTOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load registry evidence collector")
collector = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)


def _csv_bytes(columns: tuple[str, ...], rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


class RegistryEvidenceCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.worksheet = self.root / "worksheet"
        self.worksheet.mkdir()
        self.output = self.root / "collected"
        self.commit = "a" * 40
        inventory = {column: "" for column in collector.INVENTORY_COLUMNS}
        inventory.update({"base_commit": self.commit, "slug": "alpha"})
        decisions = []
        for registry, hints in (("pip", ["alpha-pkg"]), ("npm", ["@scope/alpha"])):
            row = {column: "" for column in collector.DECISION_COLUMNS}
            row.update({
                "base_commit": self.commit,
                "decision_id": f"alpha:{registry}",
                "slug": "alpha",
                "registry": registry,
                "candidate_identity_hints": json.dumps(hints, separators=(",", ":")),
                "normalized_candidate_identity_hints": json.dumps(hints, separators=(",", ":")),
                "invalid_candidate_identity_hints": "[]",
                "candidate_source_fields": "[]",
                "candidate_source_urls": (
                    '["https://pypi.org/project/alpha-pkg/1.2.3/#files"]'
                    if registry == "pip"
                    else "[]"
                ),
                "decision_status": "unknown",
                "exhaustive": "false",
                "review_state": "pending",
            })
            decisions.append(row)
        payloads = {
            "corpus-inventory.csv": _csv_bytes(collector.INVENTORY_COLUMNS, [inventory]),
            "registry-decisions.csv": _csv_bytes(collector.DECISION_COLUMNS, decisions),
            "evidence-ledger.csv": _csv_bytes(collector.EVIDENCE_COLUMNS, []),
        }
        for name, payload in payloads.items():
            (self.worksheet / name).write_bytes(payload)
        manifest = {
            "schema_version": "1.0",
            "purpose": "advisory_package_identity_review",
            "base_commit": self.commit,
            "files": {
                name: {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
                for name, payload in payloads.items()
            },
            "counts": {
                "package_pages": 1,
                "registry_decisions": 2,
                "evidence_rows": 0,
            },
            "safety": {
                "advisory_only": True,
                "hints_are_evidence": False,
                "approved_identities_prefilled": False,
            },
        }
        (self.worksheet / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True), encoding="utf-8"
        )

    @staticmethod
    def fetch(url: str, timeout: float) -> bytes:
        if url == "https://pypi.org/pypi/alpha-pkg/json":
            return b'{"urls":[],"info":{"version":"1.0","name":"Alpha_Pkg"}}'
        if url == "https://pypi.org/pypi/alpha-pkg/1.2.3/json":
            return b'{"urls":[],"info":{"version":"1.2.3","name":"Alpha_Pkg"}}'
        if url == "https://registry.npmjs.org/%40scope%2Falpha/latest":
            return b'{"version":"2.0","name":"@scope/alpha"}'
        raise AssertionError((url, timeout))

    def test_collects_canonical_snapshots_and_only_unknown_proposals(self) -> None:
        manifest = collector.collect(
            self.worksheet,
            self.output,
            ["alpha:npm=@scope/alpha", "alpha:pip=alpha-pkg"],
            fetcher=self.fetch,
        )

        with (self.output / "collected-evidence.csv").open(encoding="utf-8", newline="") as source:
            evidence = list(csv.DictReader(source))
        with (self.output / "proposed-decisions.csv").open(encoding="utf-8", newline="") as source:
            proposals = list(csv.DictReader(source))
        self.assertEqual([row["decision_id"] for row in evidence], ["alpha:npm", "alpha:pip"])
        self.assertTrue(all(row["source_revision"] == row["evidence_sha256"] for row in evidence))
        self.assertTrue(all(row["verified_by"] == row["verified_at"] == "" for row in evidence))
        self.assertTrue(all(row["proposed_status"] == "unknown" for row in proposals))
        self.assertTrue(all(row["proposed_exhaustive"] == "false" for row in proposals))
        self.assertTrue(all(row["proposed_approved_identities"] == "" for row in proposals))
        self.assertEqual(manifest["safety"]["not_applicable_inferred"], False)
        for snapshot in manifest["snapshots"]:
            payload = (self.output / snapshot["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), snapshot["sha256"])
            self.assertTrue(payload.endswith(b"\n"))

    def test_output_is_deterministic_for_equivalent_registry_json(self) -> None:
        collector.collect(
            self.worksheet,
            self.output,
            ["alpha:pip=alpha-pkg"],
            fetcher=lambda _url, _timeout: b'{"info":{"name":"Alpha_Pkg"},"urls":[]}',
        )
        second = self.root / "second"
        collector.collect(
            self.worksheet,
            second,
            ["alpha:pip=alpha-pkg"],
            fetcher=lambda _url, _timeout: b'{ "urls" : [], "info" : {"name":"Alpha_Pkg"} }',
        )
        first_snapshot = next((self.output / "snapshots").iterdir()).read_bytes()
        second_snapshot = next((second / "snapshots").iterdir()).read_bytes()
        self.assertEqual(first_snapshot, second_snapshot)
        self.assertEqual(
            (self.output / "collected-evidence.csv").read_bytes(),
            (second / "collected-evidence.csv").read_bytes(),
        )

    def test_rejects_candidates_not_explicitly_present_in_worksheet(self) -> None:
        with self.assertRaisesRegex(collector.EvidenceCollectionError, "not an explicit"):
            collector.collect(
                self.worksheet,
                self.output,
                ["alpha:pip=other"],
                fetcher=self.fetch,
            )

    def test_collects_release_bound_by_same_decision_source_url(self) -> None:
        manifest = collector.collect(
            self.worksheet,
            self.output,
            ["alpha:pip=alpha-pkg"],
            pypi_release_specs=["alpha:pip=1.2.3"],
            fetcher=self.fetch,
        )

        self.assertEqual(
            manifest["snapshots"][0]["source_locator"],
            "https://pypi.org/pypi/alpha-pkg/1.2.3/json",
        )
        with (self.output / "collected-evidence.csv").open(encoding="utf-8", newline="") as source:
            evidence = list(csv.DictReader(source))
        self.assertEqual(evidence[0]["source_kind"], "pypi_api")
        self.assertEqual(evidence[0]["source_revision"], evidence[0]["evidence_sha256"])

    def test_rejects_arbitrary_or_unbound_pypi_release(self) -> None:
        cases = (
            (["alpha:pip=alpha-pkg"], "alpha:pip=9.9.9", "not bound"),
            (["alpha:npm=@scope/alpha"], "alpha:npm=1.2.3", "non-pip"),
        )
        for candidates, release, message in cases:
            with self.subTest(release=release):
                with self.assertRaisesRegex(collector.EvidenceCollectionError, message):
                    collector.collect(
                        self.worksheet,
                        self.output,
                        candidates,
                        pypi_release_specs=[release],
                        fetcher=self.fetch,
                    )
                self.assertFalse(self.output.exists())

    def test_rejects_release_bound_only_to_another_decision(self) -> None:
        decisions = collector.load_worksheet(self.worksheet)[1]
        alpha = decisions["alpha:pip"]
        other = dict(alpha)
        other.update({
            "decision_id": "other:pip",
            "slug": "other",
            "candidate_source_urls": '["https://pypi.org/project/alpha-pkg/9.9.9/#files"]',
        })

        with self.assertRaisesRegex(collector.EvidenceCollectionError, "not bound"):
            collector.parse_pypi_release_specs(
                ["alpha:pip=9.9.9"],
                [(alpha, "alpha-pkg"), (other, "alpha-pkg")],
            )

    def test_rejects_release_response_with_wrong_version(self) -> None:
        with self.assertRaisesRegex(collector.EvidenceCollectionError, "bound release"):
            collector.collect(
                self.worksheet,
                self.output,
                ["alpha:pip=alpha-pkg"],
                pypi_release_specs=["alpha:pip=1.2.3"],
                fetcher=lambda _url, _timeout: (
                    b'{"urls":[],"info":{"version":"9.9.9","name":"Alpha_Pkg"}}'
                ),
            )
        self.assertFalse(self.output.exists())

    def test_rejects_tampered_worksheet_file(self) -> None:
        with (self.worksheet / "registry-decisions.csv").open("ab") as target:
            target.write(b"tampered\n")
        with self.assertRaisesRegex(collector.EvidenceCollectionError, "does not match manifest"):
            collector.collect(
                self.worksheet,
                self.output,
                ["alpha:pip=alpha-pkg"],
                fetcher=self.fetch,
            )

    def test_rejects_registry_identity_mismatch_and_leaves_no_output(self) -> None:
        with self.assertRaisesRegex(collector.EvidenceCollectionError, "does not match"):
            collector.collect(
                self.worksheet,
                self.output,
                ["alpha:pip=alpha-pkg"],
                fetcher=lambda _url, _timeout: b'{"info":{"name":"different"}}',
            )
        self.assertFalse(self.output.exists())

    def test_rejects_numeric_overflow_before_json_serialization(self) -> None:
        payload = b'{"info":{"name":"alpha-pkg"},"overflow":1e999}'

        with self.assertRaisesRegex(
            collector.EvidenceCollectionError,
            "non-finite number",
        ):
            collector._canonical_snapshot(payload, "pip", "alpha-pkg")

    def test_endpoint_allowlist_rejects_credentials_redirect_targets_and_http(self) -> None:
        invalid = (
            "http://pypi.org/pypi/alpha/json",
            "https://user@pypi.org/pypi/alpha/json",
            "https://pypi.org.evil.example/pypi/alpha/json",
            "https://registry.npmjs.org/alpha",
            "https://pypi.org/pypi/alpha/1.2.3/extra/json",
        )
        for url in invalid:
            with self.subTest(url=url):
                with self.assertRaisesRegex(collector.EvidenceCollectionError, "allowlist"):
                    collector.fetch_registry_json(url)

    def test_http_client_disables_proxies_and_redirects(self) -> None:
        class Headers:
            @staticmethod
            def get_content_type() -> str:
                return "application/json"

            @staticmethod
            def get(name: str, default: str | None = None) -> str | None:
                return default

        class Response:
            status = 200
            headers = Headers()

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            @staticmethod
            def geturl() -> str:
                return "https://pypi.org/pypi/alpha/json"

            @staticmethod
            def read(_maximum: int) -> bytes:
                return b'{"info":{"name":"alpha"}}'

        class Opener:
            @staticmethod
            def open(_request: object, timeout: float) -> Response:
                self.assertEqual(timeout, 3.0)
                return Response()

        captured: tuple[object, ...] = ()

        def build_opener(*handlers: object) -> Opener:
            nonlocal captured
            captured = handlers
            return Opener()

        with patch.object(collector.urllib.request, "build_opener", build_opener):
            collector.fetch_registry_json("https://pypi.org/pypi/alpha/json", 3.0)
        proxy = next(item for item in captured if isinstance(item, collector.urllib.request.ProxyHandler))
        self.assertEqual(proxy.proxies, {})
        self.assertTrue(any(isinstance(item, collector._NoRedirect) for item in captured))

    def test_bounds_candidates_timeout_json_and_existing_output(self) -> None:
        cases = (
            ([], "at least one explicit"),
            (["alpha:pip=Alpha-Pkg"], "not a normalized"),
            (["alpha:pip=alpha-pkg", "alpha:pip=alpha-pkg"], "duplicate candidate"),
        )
        decisions = collector.load_worksheet(self.worksheet)[1]
        for specifications, message in cases:
            with self.subTest(specifications=specifications):
                with self.assertRaisesRegex(collector.EvidenceCollectionError, message):
                    collector.parse_candidate_specs(specifications, decisions)
        selected = collector.parse_candidate_specs(["alpha:pip=alpha-pkg"], decisions)
        with self.assertRaisesRegex(collector.EvidenceCollectionError, "invalid PyPI release"):
            collector.parse_pypi_release_specs(["missing:pip=1.2.3"], selected)
        with self.assertRaisesRegex(collector.EvidenceCollectionError, "complexity"):
            collector._canonical_snapshot(
                (b'{"info":{"name":"alpha-pkg","nested":' + b"[" * 40 + b"0" + b"]" * 40 + b"}}"),
                "pip",
                "alpha-pkg",
            )
        self.output.mkdir()
        with self.assertRaisesRegex(collector.EvidenceCollectionError, "must not already exist"):
            collector.collect(
                self.worksheet,
                self.output,
                ["alpha:pip=alpha-pkg"],
                fetcher=self.fetch,
            )


if __name__ == "__main__":
    unittest.main()
