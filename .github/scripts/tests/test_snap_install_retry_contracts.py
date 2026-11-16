"""Regression contracts for production-safe Snap-backed package installs."""

from pathlib import Path
import re
import shlex
import unittest


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
WORKFLOWS = {
    "snapcraft": "test-snapcraft.yml",
    "librepcb": "test-librepcb.yml",
    "lxd": "test-lxd.yml",
    "multipass": "test-multipass.yml",
    "chromium": "test-chromium.yml",
}

STEP_START = re.compile(r"^ {6}- name:\s*(?P<name>.+?)\s*$", re.MULTILINE)
STEP_ID = re.compile(r"^\s+id:\s*(?P<id>[A-Za-z0-9_-]+)\s*$", re.MULTILINE)
SNAP_OPERATION = re.compile(
    r"\b(?:sudo\s+)?snap\s+"
    r"(?:abort|change|changes|info|install|list|remove|version|wait|watch)\b"
)
DESTRUCTIVE_OR_INSTALL = re.compile(
    r"\b(?:sudo\s+)?snap\s+(?:install|remove)\b"
)
SNAP_LIST = re.compile(r"\b(?:sudo\s+)?snap\s+list\b")


def parse_steps(workflow_text):
    """Return workflow job steps keyed by id using stable YAML indentation."""
    matches = list(STEP_START.finditer(workflow_text))
    steps = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(workflow_text)
        block = workflow_text[match.start():end]
        id_match = STEP_ID.search(block)
        if id_match:
            steps[id_match.group("id")] = {
                "name": match.group("name").strip("'\""),
                "text": block,
            }
    return steps


def executable_snap_lines(workflow_text):
    """Yield line numbers and shell lines that invoke a Snap operation."""
    for line_number, line in enumerate(workflow_text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("echo "):
            continue
        match = SNAP_OPERATION.search(line)
        if match:
            yield line_number, line, match


def package_change_resolver(install_text, package_name):
    """Locate the shell function that detects this package's in-flight changes."""
    lines = install_text.splitlines()
    change_indexes = [
        index for index, line in enumerate(lines)
        if re.search(r"\bsnap\s+changes\b", line)
    ]
    if not change_indexes:
        return None, lines, None

    change_index = change_indexes[0]
    declaration = None
    for index in range(change_index, -1, -1):
        match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\(\)\s*\{\s*$", lines[index])
        if match:
            declaration = (match.group(1), index)
            break
    if declaration is None:
        return None, lines, change_index

    function_name, declaration_index = declaration
    function_end = None
    for index in range(change_index + 1, len(lines)):
        if lines[index].strip() == "}":
            function_end = index
            break
    if function_end is None:
        return None, lines, change_index

    return (function_name, declaration_index, function_end), lines, change_index


class SnapInstallRetryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflows = {}
        cls.steps = {}
        for package, filename in WORKFLOWS.items():
            path = WORKFLOW_DIR / filename
            text = path.read_text(encoding="utf-8")
            cls.workflows[package] = text
            cls.steps[package] = parse_steps(text)

    def test_expected_install_and_baseline_steps_are_present(self):
        for package, steps in self.steps.items():
            with self.subTest(package=package):
                self.assertIn("install", steps)
                for test_number in range(1, 6):
                    self.assertIn(f"test{test_number}", steps)

    def test_every_snap_operation_is_timeout_bounded(self):
        for package, text in self.workflows.items():
            with self.subTest(package=package):
                unbounded = []
                for line_number, line, match in executable_snap_lines(text):
                    command_prefix = line[:match.start()]
                    if not re.search(r"\btimeout\b", command_prefix):
                        unbounded.append(f"line {line_number}: {line.strip()}")
                self.assertEqual(
                    [],
                    unbounded,
                    f"{package} has unbounded Snap operations: {unbounded}",
                )

    def test_install_detects_and_resolves_package_specific_inflight_changes(self):
        for package, steps in self.steps.items():
            with self.subTest(package=package):
                install_text = steps["install"]["text"]
                resolver, lines, change_index = package_change_resolver(
                    install_text, package
                )
                self.assertIsNotNone(
                    change_index,
                    f"{package} does not inspect `snap changes` before retrying",
                )
                change_line = lines[change_index]
                package_selector = re.compile(
                    rf"(?:\b{re.escape(package)}\b|\$\{{?SNAP_NAME\}}?)",
                    re.IGNORECASE,
                )
                self.assertRegex(
                    change_line,
                    package_selector,
                    f"{package} in-flight change detection is not package-specific",
                )
                self.assertIsNotNone(
                    resolver,
                    f"{package} in-flight change handling must be a reusable resolver",
                )
                _, declaration_index, function_end = resolver
                resolver_text = "\n".join(lines[declaration_index:function_end + 1])
                self.assertRegex(resolver_text, r"\bsnap\s+watch\b")
                self.assertRegex(resolver_text, r"\bsnap\s+abort\b")

    def test_install_rechecks_snap_list_after_each_resolution(self):
        for package, steps in self.steps.items():
            with self.subTest(package=package):
                install_text = steps["install"]["text"]
                resolver, lines, _ = package_change_resolver(install_text, package)
                self.assertIsNotNone(
                    resolver,
                    f"{package} has no in-flight change resolver to validate",
                )
                function_name, _, function_end = resolver
                invocation = re.compile(
                    rf"^\s*(?:if\s+!?\s*)?{re.escape(function_name)}(?:\s|;|$)"
                )
                call_indexes = [
                    index for index in range(function_end + 1, len(lines))
                    if invocation.search(lines[index])
                ]
                self.assertGreater(
                    len(call_indexes),
                    0,
                    f"{package} defines but never invokes {function_name}",
                )

                for call_index in call_indexes:
                    next_call = next(
                        (index for index in call_indexes if index > call_index),
                        len(lines),
                    )
                    recheck_index = next(
                        (
                            index
                            for index in range(call_index + 1, next_call)
                            if SNAP_LIST.search(lines[index])
                        ),
                        None,
                    )
                    retry_or_cleanup_index = next(
                        (
                            index
                            for index in range(call_index + 1, next_call)
                            if DESTRUCTIVE_OR_INSTALL.search(lines[index])
                        ),
                        None,
                    )
                    self.assertIsNotNone(
                        recheck_index,
                        f"{package} must run `snap list` immediately after "
                        f"{function_name} before retry or cleanup",
                    )
                    if retry_or_cleanup_index is not None:
                        self.assertLess(
                            recheck_index,
                            retry_or_cleanup_index,
                            f"{package} retries or cleans up before rechecking installation",
                        )

    def test_install_failure_is_reported_honestly(self):
        for package, steps in self.steps.items():
            with self.subTest(package=package):
                install_text = steps["install"]["text"]
                for status in ("failed", "success"):
                    self.assertRegex(
                        install_text,
                        rf"echo\s+[\"']install_status={status}[\"']",
                        f"{package} does not emit install_status={status}",
                    )
                self.assertRegex(
                    install_text,
                    r">>\s*[\"']?\$GITHUB_OUTPUT",
                    f"{package} does not publish its install status",
                )

    def test_tests_one_through_five_do_not_continue_on_error(self):
        for package, steps in self.steps.items():
            for test_number in range(1, 6):
                with self.subTest(package=package, test=test_number):
                    step = steps[f"test{test_number}"]
                    self.assertNotRegex(
                        step["text"],
                        re.compile(
                            r"^\s+continue-on-error:\s*true\s*$",
                            re.MULTILINE,
                        ),
                        f"{package} Test {test_number} may not mask a real failure",
                    )

    def test_chromium_uses_direct_snap_install_with_minimal_apt_bootstrap(self):
        install_text = self.steps["chromium"]["install"]["text"]
        self.assertRegex(
            install_text,
            r"\btimeout\b[^\n]*\bsudo\s+snap\s+install\s+chromium\b",
            "Chromium must be installed directly with a bounded `snap install chromium`",
        )

        package_match = re.search(
            r"--packages\s+(?P<value>\"[^\"]*\"|'[^']*'|\S+)",
            install_text,
        )
        self.assertIsNotNone(
            package_match,
            "Chromium apt bootstrap must declare its support-only package set",
        )
        package_arguments = shlex.split(package_match.group("value"))
        self.assertEqual(
            1,
            len(package_arguments),
            "Chromium apt bootstrap must pass one explicit support-package value",
        )
        packages = shlex.split(package_arguments[0])
        self.assertEqual(
            ["python3", "binutils"],
            packages,
            "Chromium apt bootstrap may only install python3 and binutils",
        )
        self.assertNotRegex(
            package_match.group("value"),
            r"\bchromium(?:-browser)?\b",
            "The transitional Chromium apt package must not be installed",
        )


if __name__ == "__main__":
    unittest.main()
