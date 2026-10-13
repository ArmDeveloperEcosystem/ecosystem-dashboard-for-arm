"""Render the real package partial to check opt-in inline support caveats."""

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
NOTE = "Arm-specific limit: see the [support matrix](https://example.com/support)."


class Sections(HTMLParser):
    def __init__(self):
        super().__init__()
        self.articles = {}
        self.article = None
        self.section = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "article":
            self.article = self.articles.setdefault(attrs["id"], [])
        elif tag == "section":
            self.section = {"text": [], "links": []}
        elif tag == "a" and self.section is not None:
            self.section["links"].append(attrs.get("href"))

    def handle_data(self, data):
        if self.section is not None:
            self.section["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "section":
            self.section["text"] = " ".join("".join(self.section["text"]).split())
            self.article.append(self.section)
            self.section = None
        elif tag == "article":
            self.article = None


@unittest.skipUnless(HUGO, "Hugo is required for rendered support-caveat checks")
class InlineSupportCaveatsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        root = Path(cls.temporary.name)
        shutil.copytree(
            ROOT / "themes/arm-design-system-hugo-theme/layouts/partials",
            root / "layouts/partials",
        )
        (root / "hugo.toml").write_text('baseURL = "https://example.com/"\n')
        content = root / "content"
        content.mkdir()
        (root / "data").mkdir()
        (root / "data/category_data.json").write_text('{"subcategory_mapping": {}}')
        fixtures = {
            "inline": {"support_caveats_inline": True, "support_caveats": NOTE},
            "default": {"support_caveats": NOTE},
            "explicit-false": {"support_caveats_inline": False, "support_caveats": NOTE},
            "empty": {"support_caveats_inline": True, "support_caveats": None},
            "absent": {},
        }
        for slug, optional in fixtures.items():
            optional["getting_started_resources"] = {}
            optional["arm_recommended_minimum_version"] = {}
            metadata = {
                "name": slug,
                "category": "Miscellaneous",
                "works_on_arm": True,
                "supported_minimum_version": {
                    "version_number": "1.0",
                    "release_date": "2020/01/01",
                },
                "optional_info": optional,
            }
            (content / f"{slug}.md").write_text(json.dumps(metadata) + "\n")
        for slug in ("xen-hypervisor", "dot-net"):
            shutil.copyfile(
                ROOT / f"content/linux/opensource_packages/{slug}.md",
                content / f"{slug}.md",
            )
        (root / "layouts/index.html").write_text(
            '{{ range .Site.RegularPages }}<article id="{{ .File.ContentBaseName }}">'
            '{{ partial "package-display/row-sub.html" '
            '(dict "metadata" . "os" "Linux" "dashboard_page_path" "/linux/") }}'
            '</article>{{ end }}'
        )
        result = subprocess.run(
            [str(HUGO), "--source", str(root), "--quiet"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        parser = Sections()
        parser.feed((root / "public/index.html").read_text())
        cls.articles = parser.articles

    def works(self, slug):
        return next(section for section in self.articles[slug]
                    if section["text"].startswith("Works on"))

    def support_notes(self, slug):
        return [section for section in self.articles[slug]
                if section["text"].startswith("Support Notes")]

    def test_inline_caveat_renders_once_inside_works_row_with_link(self):
        self.assertIn("Arm-specific limit:", self.works("inline")["text"])
        self.assertEqual(self.works("inline")["links"], ["https://example.com/support"])
        self.assertEqual(self.support_notes("inline"), [])

    def test_default_and_false_keep_existing_separate_row(self):
        for slug in ("default", "explicit-false"):
            with self.subTest(slug=slug):
                self.assertNotIn("Arm-specific limit:", self.works(slug)["text"])
                notes = self.support_notes(slug)
                self.assertEqual(len(notes), 1)
                self.assertIn("Arm-specific limit:", notes[0]["text"])

    def test_missing_or_empty_caveats_create_no_notes_row(self):
        for slug in ("empty", "absent"):
            with self.subTest(slug=slug):
                self.assertEqual(self.support_notes(slug), [])
                self.assertNotIn("Arm-specific limit:", self.works(slug)["text"])

    def test_xen_keeps_ticket_requirements_in_works_row_only(self):
        works = self.works("xen-hypervisor")
        for text in ("version 4.4.0", "March 2014", "Xen 4.22 Arm64",
                     "Supported features may have security exceptions",
                     "Experimental/Tech Preview", "excludes XAPI and XCP-ng"):
            self.assertIn(text, works["text"])
        self.assertIn("https://xenbits.xen.org/docs/unstable/support-matrix.html", works["links"])
        self.assertEqual(self.support_notes("xen-hypervisor"), [])

    def test_dotnet_recommendation_is_unchanged(self):
        self.assertIn("For best performance Arm recommends", self.works("dot-net")["text"])
        self.assertEqual(self.support_notes("dot-net"), [])


if __name__ == "__main__":
    unittest.main()
