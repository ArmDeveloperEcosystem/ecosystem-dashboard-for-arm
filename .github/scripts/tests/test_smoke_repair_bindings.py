"""Pure rebinding regressions, including the real Zlib/catalog payloads.

Anchor provenance below is explicitly synthetic test input, not an authenticated
commit or App observation. No commits are created and no workflows are executed.
Parent integration must prove the real anchor, its retained Git history, and the
final candidate. Full catalog validation here uses an isolated filesystem copy.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / ".github/scripts"))

import smoke_repair_bindings as bindings
import smoke_repair_policy as policy

validator = bindings.catalog_validator
WORKFLOW = ".github/workflows/test-zlib.yml"
PROVENANCE = {
    "source_commit": "a" * 40,
    "verified_by": "fixture-smoke-repair[bot]",
    "verified_at": "2026-09-23T00:00:00Z",
}


def canonical(value):
    return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def corpus_digest(catalog):
    return validator.calculate_corpus_sha256([
        pair for record in catalog["records"] for pair in (
            (record["content_path"], record["content_sha256"]),
            (record["workflow"]["path"], record["workflow"]["sha256"]),
        )
    ])


def sort_evidence(dimension):
    dimension["evidence"].sort(
        key=lambda item: json.dumps(item, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    )


def external_evidence():
    return {
        "source_kind": "frontmatter_url", "source_locator": "https://github.com/madler/zlib",
        "source_revision": "b" * 64, "evidence_sha256": "c" * 64,
        "verified_by": "historical-reviewer", "verified_at": "2026-09-03T16:16:13Z",
        "rationale": "Historical advisory source; preserve this observation unchanged.",
    }


def admitted_zlib_fixture(source):
    text = source.decode("utf-8")
    workflow = policy._workflow(text)
    (called_job, job), = workflow["jobs"].items()
    commands = []
    for step in job["steps"]:
        if step.get("id") != "install":
            continue
        for line in step.get("run", "").splitlines():
            installation = policy._installation(line)
            if installation and installation[0] == ("bash", ".github/actions/apt-bootstrap/bootstrap.sh", "--packages"):
                commands.append((step, line.strip(), installation))
    if len(commands) != 1:
        raise AssertionError("Zlib fixture requires one structured install-step apt-bootstrap command")
    step, old, (prefix, packages, _) = commands[0]
    present = {package.partition("=")[0] for package in packages}
    choices = ("libssl-dev", *sorted(policy.APT_BUILD_DEPENDENCIES - {"libssl-dev"}))
    dependency = next((item for item in choices if item not in present), None)
    if dependency is None:
        raise AssertionError("Zlib fixture has exhausted the existing approved dependency choices")
    new = shlex.join([*prefix, " ".join((*packages, dependency))])
    context = {"repository": "example/dashboard", "base_sha": "b" * 40,
               "orchestration_id": "orchestration-100-1", "package_slug": "zlib",
               "workflow_path": WORKFLOW, "called_job": called_job,
               "source_text": text, "failed_steps": [step["name"]]}
    proposal = {"diagnosis": "Add an approved prerequisite without modifying tests.",
                "edits": [{"path": WORKFLOW, "old": old, "new": new}],
                "unresolved_reason": ""}
    candidate = policy.validate_proposal(context, proposal)["candidate_source"].encode("utf-8")
    return context, proposal, candidate


def fixture_provenance(record):
    evidence = [item for dimension in record["registries"].values() for item in dimension["evidence"]
                if item["source_kind"] == "generated_workflow"]
    dates = [PROVENANCE["verified_at"], *(item["verified_at"] for item in evidence)]
    latest = max(datetime.fromisoformat(value.replace("Z", "+00:00")) for value in dates).astimezone(UTC)
    if latest.microsecond:
        latest = (latest + timedelta(seconds=1)).replace(microsecond=0)
    revisions = {item["source_revision"] for item in evidence}
    source_commit = next(character * 40 for character in "ade" if character * 40 not in revisions)
    return PROVENANCE | {"source_commit": source_commit, "verified_at": latest.isoformat().replace("+00:00", "Z")}


class BindingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.real_raw = (ROOT / validator.CATALOG_REPOSITORY_PATH).read_bytes()
        cls.real_catalog = json.loads(cls.real_raw)
        cls.original = (ROOT / WORKFLOW).read_bytes()
        cls.context, cls.proposal, cls.candidate = admitted_zlib_fixture(cls.original)
        target = next(record for record in cls.real_catalog["records"] if record["slug"] == "zlib")
        cls.provenance = fixture_provenance(target)

    def setUp(self):
        self.catalog = deepcopy(self.real_catalog)
        self.catalog["records"] = [record for record in self.catalog["records"]
                                   if record["slug"] in {"zlib", "zookeeper"}]
        self.catalog["corpus"]["entry_count"] = len(self.catalog["records"])
        self.catalog["corpus"]["corpus_sha256"] = corpus_digest(self.catalog)
        self.target = next(record for record in self.catalog["records"] if record["slug"] == "zlib")
        self.arguments = {"package_slug": "zlib", "workflow_path": WORKFLOW,
                          "original_source": self.original, "candidate_source": self.candidate}

    def validate(self, **kwargs):
        return bindings.validate_catalog_rebinding(canonical(self.catalog), **(self.arguments | kwargs))

    def rebind(self, **kwargs):
        return bindings.rebind_catalog(canonical(self.catalog), **(self.arguments | self.provenance | kwargs))

    def test_plan_is_immutable_and_binds_exact_bytes(self):
        plan = self.validate()
        self.assertEqual(plan.record_index, 0)
        self.assertEqual(plan.package_slug, "zlib")
        self.assertEqual(plan.workflow_path, WORKFLOW)
        self.assertEqual(plan.original_sha256, digest(self.original))
        self.assertEqual(plan.candidate_sha256, digest(self.candidate))
        self.assertEqual(plan.generated_evidence, (("pip", 0), ("npm", 0)))
        with self.assertRaises(FrozenInstanceError):
            plan.candidate_sha256 = "f" * 64

    def test_only_allowlisted_fields_change_including_mixed_evidence(self):
        for dimension in self.target["registries"].values():
            dimension["evidence"].append(external_evidence())
            sort_evidence(dimension)
        original = deepcopy(self.catalog)
        updated = json.loads(self.rebind())
        expected = deepcopy(original)
        expected["records"][0]["workflow"]["sha256"] = digest(self.candidate)
        for dimension in expected["records"][0]["registries"].values():
            for item in dimension["evidence"]:
                if item["source_kind"] == "generated_workflow":
                    item.update(source_revision=self.provenance["source_commit"],
                                evidence_sha256=digest(self.candidate),
                                verified_by=self.provenance["verified_by"],
                                verified_at=self.provenance["verified_at"],
                                rationale=bindings.AUTOMATED_ADVISORY_RATIONALE)
            sort_evidence(dimension)
        expected["corpus"]["corpus_sha256"] = corpus_digest(expected)
        self.assertEqual(updated, expected)
        self.assertEqual(self.catalog, original)
        self.assertEqual(updated["records"][1], original["records"][1])
        self.assertNotEqual(updated["corpus"]["corpus_sha256"], original["corpus"]["corpus_sha256"])

    def test_history_is_not_reasserted_as_current_evidence(self):
        previous = deepcopy(self.target)
        updated = json.loads(self.rebind())["records"][0]
        for kind in ("pip", "npm"):
            old, new = (record["registries"][kind]["evidence"][0] for record in (previous, updated))
            self.assertNotEqual(old["source_revision"], new["source_revision"])
            self.assertEqual(new["verified_by"], self.provenance["verified_by"])
            self.assertEqual(new["verified_at"], self.provenance["verified_at"])
            self.assertEqual(new["rationale"], bindings.AUTOMATED_ADVISORY_RATIONALE)
            self.assertEqual(set(old), set(new))
        self.assertEqual(self.target, previous)

    def test_deterministic_canonical_output_accepts_text_and_bytes(self):
        first = self.rebind()
        self.assertEqual(first, self.rebind())
        self.assertEqual(first, self.rebind(original_source=self.original.decode(), candidate_source=self.candidate.decode()))
        self.assertEqual(first, bindings.rebind_catalog(canonical(self.catalog).encode(), **self.arguments, **self.provenance))
        self.assertEqual(first, canonical(json.loads(first)))

    def test_no_filesystem_process_or_wall_clock_calls(self):
        with patch("builtins.open", side_effect=AssertionError("filesystem forbidden")), patch(
            "subprocess.run", side_effect=AssertionError("process forbidden")
        ), patch("subprocess.Popen", side_effect=AssertionError("process forbidden")), patch(
            "time.time", side_effect=AssertionError("clock forbidden")
        ), patch.object(validator, "_validate_timestamp", side_effect=AssertionError("clock validator forbidden")):
            self.assertEqual(json.loads(self.rebind())["records"][0]["workflow"]["sha256"], digest(self.candidate))

    def test_wrong_slug_path_and_unsafe_paths_fail_closed(self):
        for slug, path in (
            ("Zlib", WORKFLOW), ("other", WORKFLOW), ("zookeeper", WORKFLOW),
            ("absent", ".github/workflows/test-absent.yml"),
            ("zlib", "/.github/workflows/test-zlib.yml"),
            ("zlib", ".github/./workflows/test-zlib.yml"),
            ("zlib", ".github/workflows/../test-zlib.yml"),
            ("zlib", ".github\\workflows\\test-zlib.yml"),
            ("zlib", ".github//workflows/test-zlib.yml"),
            ("zlib", WORKFLOW + "\n"), ("../zlib", WORKFLOW),
            ("all-packages-batch1", ".github/workflows/test-all-packages-batch1.yml"),
            (None, WORKFLOW), ([], WORKFLOW), ("zlib", None),
        ):
            with self.subTest(slug=slug, path=path), self.assertRaises(bindings.CatalogRebindingError):
                self.validate(package_slug=slug, workflow_path=path)

    def test_another_real_slug_with_its_path_cannot_bind_zlib_source(self):
        with self.assertRaisesRegex(bindings.CatalogRebindingError, "does not bind original_source"):
            self.validate(package_slug="zookeeper", workflow_path=".github/workflows/test-zookeeper.yml")

    def test_wrong_original_digest_and_stale_catalog_digest_are_rejected(self):
        with self.assertRaisesRegex(bindings.CatalogRebindingError, "does not bind original_source"):
            self.validate(original_source=self.original + b"\n")
        self.target["workflow"]["sha256"] = "f" * 64
        with self.assertRaisesRegex(bindings.CatalogRebindingError, "original workflow"):
            self.validate()

    def test_stale_generated_evidence_is_not_laundered(self):
        for field, value in (("evidence_sha256", "f" * 64),
                             ("source_locator", ".github/workflows/test-other.yml")):
            with self.subTest(field=field):
                item = self.target["registries"]["pip"]["evidence"][0]
                before = item[field]
                item[field] = value
                with self.assertRaisesRegex(bindings.CatalogRebindingError, "original workflow"):
                    self.validate()
                item[field] = before

    def test_stale_corpus_is_not_repaired_as_a_side_effect(self):
        self.catalog["corpus"]["corpus_sha256"] = "f" * 64
        with self.assertRaisesRegex(bindings.CatalogRebindingError, "corpus digest is stale"):
            self.rebind()

    def test_duplicate_and_case_colliding_slugs_fail_closed(self):
        for identity in ("zlib", "ZLIB"):
            with self.subTest(identity=identity):
                self.catalog["records"][1]["slug"] = identity
                with self.assertRaisesRegex(bindings.CatalogRebindingError, "slugs must be unique"):
                    self.validate()

    def test_missing_target_and_unsorted_records_fail_closed(self):
        self.catalog["records"].reverse()
        with self.assertRaisesRegex(bindings.CatalogRebindingError, "sorted"):
            self.validate()

    def test_absent_target_is_not_created(self):
        self.target["workflow"].update(presence="absent", sha256=None)
        for dimension in self.target["registries"].values():
            dimension["evidence"] = [external_evidence()]
        self.catalog["corpus"]["corpus_sha256"] = corpus_digest(self.catalog)
        with self.assertRaisesRegex(bindings.CatalogRebindingError, "does not bind original_source"):
            self.validate()

    def test_malformed_and_duplicate_json_are_rejected(self):
        raw = canonical(self.catalog)
        variants = ["{", "null", "[]", "true", "1", "", "\ufeff" + raw,
                    raw.replace('"records":', '"records": [], "records":', 1),
                    raw.replace('"slug": "zlib"', '"slug": "other", "slug": "zlib"'),
                    raw.replace('"verified_by":', '"verified_by": "other", "verified_by":', 1),
                    raw.replace('"entry_count": 2', '"entry_count": NaN'),
                    raw.replace('"entry_count": 2', '"entry_count": Infinity'),
                    raw.replace('"entry_count": 2', '"entry_count": 1e999'),
                    '[' * 2000 + ']' * 2000, b"\xff", None, {}, bytearray(raw.encode())]
        for index, value in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(bindings.CatalogRebindingError):
                bindings.validate_catalog_rebinding(value, **self.arguments)

    def test_noncanonical_json_is_rejected(self):
        for raw in (json.dumps(self.catalog), canonical(self.catalog).rstrip(), canonical(self.catalog) + "\n"):
            with self.subTest(raw=raw[:20]), self.assertRaisesRegex(bindings.CatalogRebindingError, "canonical JSON"):
                bindings.validate_catalog_rebinding(raw, **self.arguments)

    def test_extra_mutation_fields_and_malformed_shapes_are_rejected(self):
        original = deepcopy(self.catalog)
        for path, field, value in (
            ((), "history", []), (("corpus",), "entry_count", True),
            (("records", 0), "aliases", ["other"]),
            (("records", 0, "workflow"), "extra", "mutation"),
            (("records", 0, "registries", "pip"), "exhaustive", 0),
            (("records", 0, "registries", "pip", "evidence", 0), "approved", True),
            (("records", 0, "registries", "pip", "evidence", 0), "source_kind", []),
            (("records", 0), "registries", []),
            ((), "schema_version", "2"), ((), "records", {}),
        ):
            self.catalog = deepcopy(original)
            target = self.catalog
            for part in path:
                target = target[part]
            target[field] = value
            with self.subTest(path=path, field=field), self.assertRaises(bindings.CatalogRebindingError):
                self.validate()

    def test_source_inputs_are_bounded_utf8_values_not_paths(self):
        for value in (b"", "", b"\xff", "\ud800", b"a\x00b", {}, None, Path(WORKFLOW), bytearray(b"source")):
            for key in ("original_source", "candidate_source"):
                with self.subTest(key=key, value=repr(value)), self.assertRaises(bindings.CatalogRebindingError):
                    self.validate(**{key: value})
        with self.assertRaisesRegex(bindings.CatalogRebindingError, "must change"):
            self.validate(candidate_source=self.original)
        with patch.object(validator, "MAX_WORKFLOW_BYTES", 1), self.assertRaises(bindings.CatalogRebindingError):
            self.validate()
        with patch.object(validator, "MAX_CATALOG_BYTES", 1), self.assertRaises(bindings.CatalogRebindingError):
            self.validate()

    def test_invalid_anchor_commit_inputs_are_rejected(self):
        old = self.target["registries"]["pip"]["evidence"][0]["source_revision"]
        for value in (None, 1, {}, [], "", "main", "HEAD", "0" * 40, "A" * 40, "a" * 64,
                      "a" * 39, "a" * 40 + "\n", old):
            with self.subTest(value=value), self.assertRaises(bindings.CatalogRebindingError):
                self.rebind(source_commit=value)

    def test_invalid_or_human_attribution_is_rejected(self):
        for value in (None, [], {}, "", "ranimandepudi", "fixture", "fixture[bot]\n", " fixture[bot]",
                      "fixture[bot] ", "fixture\n[bot]", "fixture\x00[bot]", "x" * 101 + "[bot]"):
            with self.subTest(value=value), self.assertRaises(bindings.CatalogRebindingError):
                self.rebind(verified_by=value)

    def test_malformed_and_backdated_timestamp_is_rejected(self):
        for value in (None, [], {}, "", "2026-09-23", "2026-09-23T00:00:00", "2026-09-23t00:00:00z",
                      "2026-02-30T00:00:00Z", "2026-09-23T25:00:00Z", "2026-09-23T00:00:00Z\n",
                      "2020-01-01T00:00:00Z", "2026-09-23T00:00:00+99:00",
                      "2026-09-23T00:00:00+00:00", "2026-09-23T00:00:00.000Z"):
            with self.subTest(value=value), self.assertRaises(bindings.CatalogRebindingError):
                self.rebind(verified_at=value)

    def test_clock_free_timestamp_validation_leaves_freshness_to_parent(self):
        result = json.loads(self.rebind(verified_at="2099-01-01T00:00:00Z"))
        self.assertEqual(result["records"][0]["registries"]["pip"]["evidence"][0]["verified_at"],
                         "2099-01-01T00:00:00Z")

    def test_historical_offset_timestamps_remain_accepted(self):
        self.target["registries"]["pip"]["evidence"][0]["verified_at"] = "2026-09-03T11:16:13-05:00"
        self.assertEqual(json.loads(self.rebind())["records"][0]["registries"]["pip"]["evidence"][0]["verified_at"],
                         self.provenance["verified_at"])

    def test_non_advisory_and_identity_asserting_generated_evidence_is_manual(self):
        dimension = self.target["registries"]["pip"]
        before = deepcopy(dimension)
        for status, identities in (("verified", ["zlib-fixture"]), ("ambiguous", [])):
            dimension.update(status=status, identities=identities)
            with self.subTest(status=status), self.assertRaises(bindings.ManualCatalogRebindingRequired):
                self.rebind()
        dimension.update(before)
        dimension["evidence"][0]["rationale"] = "A human approved this package identity."
        with self.assertRaises(bindings.ManualCatalogRebindingRequired):
            self.rebind()

    def test_multiple_generated_entries_are_not_collapsed(self):
        dimension = self.target["registries"]["pip"]
        other = deepcopy(dimension["evidence"][0])
        other["verified_by"] = "another-historical-reviewer"
        dimension["evidence"].append(other)
        sort_evidence(dimension)
        with self.assertRaises(bindings.ManualCatalogRebindingRequired):
            self.rebind()

    def test_external_only_identity_decisions_are_preserved(self):
        dimension = self.target["registries"]["pip"]
        dimension.update(status="verified", identities=["zlib-fixture"], evidence=[external_evidence()])
        before = deepcopy(dimension)
        result = json.loads(self.rebind())
        self.assertEqual(result["records"][0]["registries"]["pip"], before)
        self.assertEqual(self.validate().generated_evidence, (("npm", 0),))

    def test_no_generated_evidence_is_invented(self):
        for dimension in self.target["registries"].values():
            dimension["evidence"] = [external_evidence()]
        before = deepcopy(self.target["registries"])
        self.assertEqual(self.validate().generated_evidence, ())
        self.assertEqual(json.loads(self.rebind())["records"][0]["registries"], before)

    def test_repeated_repair_uses_new_anchor_without_historical_reattribution(self):
        self.catalog = json.loads(self.rebind())
        self.arguments.update(original_source=self.candidate, candidate_source=self.candidate + b"\n")
        provenance = fixture_provenance(self.catalog["records"][0])
        result = json.loads(self.rebind(**provenance))
        self.assertEqual(result["records"][0]["registries"]["pip"]["evidence"][0]["source_revision"],
                         provenance["source_commit"])

    def test_positive_fixture_supports_an_already_repaired_package_list(self):
        _, proposal, candidate = admitted_zlib_fixture(self.candidate)
        edit = proposal["edits"][0]
        _, existing, _ = policy._installation(edit["old"])
        _, changed, _ = policy._installation(edit["new"])
        self.assertIn("libssl-dev", {package.partition("=")[0] for package in existing})
        self.assertEqual(changed[:-1], existing)
        self.assertNotIn(changed[-1], {package.partition("=")[0] for package in existing})
        self.assertIn(changed[-1], policy.APT_BUILD_DEPENDENCIES)
        self.assertNotEqual(candidate, self.candidate)

    def test_fixture_provenance_tracks_refreshed_catalog_dates(self):
        target = deepcopy(self.target)
        for dimension in target["registries"].values():
            dimension["evidence"][0].update(source_revision="a" * 40, verified_at="2030-02-03T04:05:06Z")
        provenance = fixture_provenance(target)
        self.assertEqual(provenance["verified_at"], "2030-02-03T04:05:06Z")
        self.assertNotEqual(provenance["source_commit"], "a" * 40)

    def test_real_catalog_and_policy_admitted_zlib_plan(self):
        admitted = policy.validate_proposal(self.context, self.proposal)
        self.assertEqual(admitted["candidate_source"].encode(), self.candidate)
        plan = bindings.validate_catalog_rebinding(self.real_raw, **self.arguments)
        self.assertEqual(self.real_catalog["records"][plan.record_index]["slug"], "zlib")
        result = bindings.rebind_catalog(self.real_raw, **self.arguments, **self.provenance)
        updated = json.loads(result)
        self.assertEqual(updated["corpus"]["corpus_sha256"], corpus_digest(updated))
        for index, record in enumerate(self.real_catalog["records"]):
            if index != plan.record_index:
                self.assertEqual(record, updated["records"][index])
        self.assertEqual(json.loads(self.real_raw), self.real_catalog)

    def test_real_candidate_passes_existing_full_catalog_validator(self):
        result = bindings.rebind_catalog(self.real_raw, **self.arguments, **self.provenance)
        with tempfile.TemporaryDirectory(prefix="smoke-repair-binding-test-") as temporary:
            root = Path(temporary).resolve()
            shutil.copytree(ROOT / validator.CONTENT_ROOT, root / validator.CONTENT_ROOT, symlinks=True)
            shutil.copytree(ROOT / ".github/workflows", root / ".github/workflows", symlinks=True)
            catalog = root / validator.CATALOG_REPOSITORY_PATH
            catalog.write_bytes(self.real_raw)
            self.assertEqual(validator.validate_catalog(root), len(self.real_catalog["records"]))
            (root / WORKFLOW).write_bytes(self.candidate)
            with self.assertRaisesRegex(validator.CatalogValidationError, "workflow.sha256 is stale"):
                validator.validate_catalog(root)
            digest_only = deepcopy(self.real_catalog)
            target = next(record for record in digest_only["records"] if record["slug"] == "zlib")
            target["workflow"]["sha256"] = digest(self.candidate)
            catalog.write_text(canonical(digest_only), encoding="utf-8")
            with self.assertRaisesRegex(validator.CatalogValidationError, "must match the record workflow path and SHA-256"):
                validator.validate_catalog(root)
            stale_corpus = json.loads(result)
            stale_corpus["corpus"] = deepcopy(self.real_catalog["corpus"])
            catalog.write_text(canonical(stale_corpus), encoding="utf-8")
            with self.assertRaisesRegex(validator.CatalogValidationError, "corpus_sha256 is stale"):
                validator.validate_catalog(root)
            catalog.write_text(result, encoding="utf-8")
            self.assertEqual(validator.validate_catalog(root), len(self.real_catalog["records"]))


if __name__ == "__main__":
    unittest.main()
