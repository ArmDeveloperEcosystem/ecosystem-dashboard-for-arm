"""Render Chef's measured source scope without relabeling historical results."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser


ROOT = Path(__file__).resolve().parents[3]
HUGO = os.environ.get("PACKAGE_CATALOG_HUGO_BINARY") or shutil.which("hugo")
SCOPED_NAME = "Chef Infra (source file-resource API only)"
SCOPE = "Source file-resource API only"
EXCLUSION = "Vendor CLI and .deb installation not tested"
JOB_URL = "https://example.com/actions/runs/123/job/456"


class RenderedRow(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                 "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.nodes = []
        self.stack = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "ancestors": tuple(self.stack)}
        self.nodes.append(node)
        if tag not in self.VOID_TAGS:
            self.stack.append(len(self.nodes) - 1)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.nodes[self.stack[index]]["tag"] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        text = " ".join(data.split())
        if text:
            self.text.append((text, tuple(self.stack)))

    def occurrences(self, text):
        return [ancestors for value, ancestors in self.text if value == text]


@unittest.skipUnless(HUGO, "Hugo is required for rendered Chef scope checks")
class ChefSourceScopeRenderTests(unittest.TestCase):
    def render(self, *, slug="chef-infra", name=SCOPED_NAME, passed=6, failed=0,
               details=True, result=True):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(
                ROOT / "themes/arm-design-system-hugo-theme/layouts/partials",
                root / "layouts/partials",
            )
            (root / "hugo.toml").write_text('baseURL = "https://example.com/"\n')
            content = root / "content/linux/opensource_packages"
            content.mkdir(parents=True)
            metadata = {
                "name": "Chef Infra" if slug == "chef-infra" else "Redis",
                "category": "Miscellaneous",
                "works_on_arm": True,
                "supported_minimum_version": {
                    "version_number": "1.0", "release_date": "2020/01/01",
                },
                "optional_info": {
                    "getting_started_resources": {},
                    "arm_recommended_minimum_version": {},
                },
            }
            (content / f"{slug}.md").write_text(json.dumps(metadata) + "\n")
            package = {"version": "18.8.54"}
            if name is not None:
                package["name"] = name
            payload = {
                "package": package,
                "run": {
                    "url": JOB_URL, "timestamp": "2026-10-27T12:00:00Z",
                    "runner": {"os": "ubuntu-24.04", "arch": "arm64"},
                },
                "metadata": {"badge_status": "failing" if failed else "passing"},
                "tests": {
                    "passed": passed, "failed": failed, "skipped": 0,
                    "duration_seconds": 6,
                    "details": [
                        {"name": f"Test {ordinal} - Fixture",
                         "status": "passed" if ordinal <= passed else "failed",
                         "duration_seconds": 1}
                        for ordinal in range(1, 7)
                    ] if details else [],
                },
            }
            (root / "data").mkdir()
            (root / "data/category_data.json").write_text(
                '{"subcategory_mapping": {}}'
            )
            (root / "data/test-results-index.json").write_text(
                json.dumps({slug: payload} if result else {})
            )
            (root / "layouts/index.html").write_text(
                '{{ range .Site.RegularPages }}<table><tbody>'
                '{{ partial "package-display/row-sub.html" '
                '(dict "metadata" . "os" "Linux" "dashboard_page_path" "/linux/") }}'
                '</tbody></table>{{ end }}'
            )
            process = subprocess.run(
                [str(HUGO), "--source", str(root), "--quiet"],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            row = RenderedRow()
            row.feed((root / "public/index.html").read_text())
            return row

    def assert_badge(self, row, text, color):
        badges = [node for node in row.nodes if node["tag"] == "span"
                  and "background-color:" in node["attrs"].get("style", "")]
        self.assertEqual(len(badges), 1)
        badge = badges[0]
        self.assertIn(f"background-color: {color};", badge["attrs"]["style"])
        badge_index = row.nodes.index(badge)
        badge_text = " ".join(value for value, ancestors in row.text
                              if badge_index in ancestors)
        self.assertTrue(badge_text.endswith(text), badge_text)
        anchor = row.nodes[badge["ancestors"][-1]]
        self.assertEqual(anchor["tag"], "a")
        self.assertEqual(anchor["attrs"]["href"], JOB_URL)
        return anchor["ancestors"][-1]

    def assert_scope_adjacent(self, row, badge_container):
        for text in (SCOPE, EXCLUSION):
            occurrences = row.occurrences(text)
            self.assertEqual(len(occurrences), 1, text)
            ancestors = occurrences[0]
            self.assertIn(badge_container, ancestors, text)
            self.assertNotIn("details", [row.nodes[index]["tag"]
                                         for index in ancestors], text)

    def assert_unscoped(self, row):
        self.assertEqual(row.occurrences(SCOPE), [])
        self.assertEqual(row.occurrences(EXCLUSION), [])

    def test_scoped_success_is_adjacent_and_outside_closed_details(self):
        row = self.render()
        container = self.assert_badge(row, "6/6 passing", "#28a745")
        self.assert_scope_adjacent(row, container)
        details = [node for node in row.nodes if node["tag"] == "details"]
        self.assertEqual(len(details), 1)
        self.assertNotIn("open", details[0]["attrs"])
        self.assertEqual(len(row.occurrences("View test details")), 1)

    def test_scoped_failures_retain_red_badge_and_actual_counts(self):
        for passed, failed, text in ((5, 1, "5/6 passing"), (0, 6, "0 passing")):
            with self.subTest(passed=passed, failed=failed):
                row = self.render(passed=passed, failed=failed)
                container = self.assert_badge(row, text, "#dc3545")
                self.assert_scope_adjacent(row, container)

    def test_historical_chef_and_inexact_names_are_not_relabelled(self):
        for name in ("Chef Infra", "Chef Infra (source API only)",
                     SCOPED_NAME + " ", None):
            with self.subTest(name=name):
                row = self.render(name=name)
                self.assert_unscoped(row)
                self.assert_badge(row, "6/6 passing", "#28a745")

    def test_other_package_is_not_scoped_even_with_exact_chef_name(self):
        for name in ("Redis", SCOPED_NAME):
            with self.subTest(name=name):
                row = self.render(slug="redis", name=name)
                self.assert_unscoped(row)
                self.assert_badge(row, "6/6 passing", "#28a745")

    def test_scope_does_not_depend_on_detail_records(self):
        row = self.render(details=False)
        container = self.assert_badge(row, "6/6 passing", "#28a745")
        self.assert_scope_adjacent(row, container)
        self.assertFalse(any(node["tag"] == "details" for node in row.nodes))

    def test_no_result_has_no_scope_or_badge(self):
        row = self.render(result=False)
        self.assert_unscoped(row)
        self.assertFalse(any("background-color:" in node["attrs"].get("style", "")
                             for node in row.nodes))


if __name__ == "__main__":
    unittest.main()
