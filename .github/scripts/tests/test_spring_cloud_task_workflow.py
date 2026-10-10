"""Exercise Task's actual workflow scripts; fixtures are not native Arm proof."""

import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-spring_cloud_task.yml"
CLASS = "smoke.TaskSmokeTest"
METHOD = "startsTaskEnabledApplication"
REPORT = f"TEST-{CLASS}.xml"
VERIFIED = f"Verified {CLASS}#{METHOD}: tests=1 failures=0 errors=0 skipped=0"
SOURCE = '''package smoke;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.ApplicationContext;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(args = "--spring.cloud.task.name=arm64-smoke")
class TaskSmokeTest {
  @Autowired
  ApplicationContext context;

  @Test
  void startsTaskEnabledApplication() {
    assertThat(context.getBean(TaskSmokeApplication.class)).isNotNull();
    assertThat(TaskSmokeApplication.RAN.get()).isTrue();
  }
}
'''
APPLICATION = '''package smoke;

import java.util.concurrent.atomic.AtomicBoolean;
import org.springframework.boot.CommandLineRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.task.configuration.EnableTask;

@EnableTask
@SpringBootApplication
public class TaskSmokeApplication implements CommandLineRunner {
  static final AtomicBoolean RAN = new AtomicBoolean(false);

  public static void main(String[] args) {
    SpringApplication.run(TaskSmokeApplication.class, args);
  }

  @Override
  public void run(String... args) {
    RAN.set(true);
    System.out.println("task-ok");
  }
}
'''


def report_tree():
    suite = ET.Element("testsuite", name=CLASS, tests="1", failures="0", errors="0", skipped="0")
    properties = ET.SubElement(suite, "properties")
    ET.SubElement(properties, "property", name="java.version", value="17")
    case = ET.SubElement(suite, "testcase", classname=CLASS, name=METHOD, time="0.1")
    ET.SubElement(case, "system-out").text = "Spring fixture output"
    return suite


class SpringCloudTaskWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="task-workflow-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "baseline"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "python3").symlink_to(sys.executable)
        self.job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["test-spring_cloud_task"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.env = dict(os.environ, **self.job["env"], TMPDIR=str(self.root),
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        GITHUB_OUTPUT=str(self.root / "output"),
                        MAVEN_LOG=str(self.root / "maven.jsonl"), MAVEN_EXIT="0",
                        REPORT_MODE="fresh", REPORT_NAME=REPORT,
                        REPORT_XML=ET.tostring(report_tree(), encoding="unicode"))
        self.values = {"steps.version.outputs.version": self.job["env"]["SPRING_CLOUD_TASK_VERSION"]}
        self.values.update({f"steps.test{i}.{key}": value for i in range(1, 7)
                            for key, value in (("outputs.status", "passed"),
                                               ("outcome", "success"), ("outputs.duration", "1"))})
        stub = self.bin / "mvn"
        stub.write_text(f"#!{sys.executable}\n" + r'''
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

if sys.argv[1:] == ["-B", "-q", "dependency:resolve", "-DincludeArtifactIds=spring-cloud-starter-task"]:
    sys.exit(0)

ns = {"m": "http://maven.apache.org/POM/4.0.0"}
pom = ET.parse("pom.xml")
dependencies = {item.find("m:artifactId", ns).text: item.findtext("m:version", namespaces=ns)
                for item in pom.findall("m:dependencies/m:dependency", ns)}
boot_version = pom.findtext("m:properties/m:spring-boot.version", namespaces=ns)
for argument in sys.argv[1:]:
    if argument.startswith("-Dspring-boot.version="):
        boot_version = argument.split("=", 1)[1]
with open(os.environ["MAVEN_LOG"], "a") as log:
    log.write(json.dumps({"args": sys.argv[1:], "project": str(Path.cwd()),
                          "target_exists": Path("target").exists(),
                          "version": dependencies["spring-cloud-starter-task"],
                          "boot_version": boot_version,
                          "source": Path("src/test/java/smoke/TaskSmokeTest.java").read_text()}) + "\n")
# Deliberately ignore Maven's clean goal: the workflow must remove stale output.
mode = os.environ["REPORT_MODE"]
if mode != "missing":
    report = Path("target/surefire-reports") / os.environ["REPORT_NAME"]
    report.parent.mkdir(parents=True, exist_ok=True)
    if mode == "symlink":
        original = Path(os.environ["TMPDIR"]) / "external-report.xml"
        original.write_text(os.environ["REPORT_XML"])
        report.symlink_to(original)
    else:
        report.write_text(os.environ["REPORT_XML"])
    if mode == "stale":
        os.utime(report, (1, 1))
    if mode == "extra":
        report.with_name("TEST-other.xml").write_text(os.environ["REPORT_XML"])
sys.exit(int(os.environ["MAVEN_EXIT"]))
''')
        stub.chmod(0o755)
        bootstrap = self.root / ".github/actions/apt-bootstrap/bootstrap.sh"
        bootstrap.parent.mkdir(parents=True)
        bootstrap.write_text("exit 0\n")
        result, output = self.run_step("install")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("success", output["install_status"])

    def run_step(self, step_id, **environment):
        def expression(match):
            for term in match[1].split("||"):
                term = term.strip()
                if term.startswith("'") and term.endswith("'"):
                    return term[1:-1]
                if term.isdigit():
                    return term
                if self.values.get(term):
                    return self.values[term]
            return ""

        script = re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, self.steps[step_id]["run"])
        script = script.replace("/tmp/spring-task-smoke", str(self.project))
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
            cwd=self.root, env=dict(self.env, **environment), capture_output=True,
            text=True, timeout=15,
        )
        pairs = [line.split("=", 1) for line in output.read_text().splitlines()]
        self.assertEqual(len(pairs), len(dict(pairs)), "Outputs must be emitted exactly once")
        return result, dict(pairs)

    def assert_lane(self, lane, passed, **environment):
        result, output = self.run_step(lane, **environment)
        self.assertEqual(passed, result.returncode == 0, result.stdout + result.stderr)
        self.assertEqual("passed" if passed else "failed", output.get("status"))
        self.assertRegex(output.get("duration", ""), r"^[0-9]+$")
        self.assertEqual(1 if passed else 0, result.stdout.count(VERIFIED))
        if lane == "test6":
            self.assertEqual("next_install_validated" if passed else "next_install_failed",
                             output["decision"])
            self.assertEqual("5.0.1" if passed else "install_failed", output["next_installed_version"])
        return result, output

    def test_preserves_runner_versions_and_full_functional_test_with_junit5_plugin(self):
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        self.assertEqual({"SPRING_CLOUD_TASK_VERSION": "3.0.0", "SPRING_CLOUD_TASK_NEXT_VERSION": "5.0.1"}, self.job["env"])
        self.assertEqual(SOURCE, (self.project / "src/test/java/smoke/TaskSmokeTest.java").read_text())
        self.assertEqual(APPLICATION, (self.project / "src/main/java/smoke/TaskSmokeApplication.java").read_text())
        ns = {"m": "http://maven.apache.org/POM/4.0.0"}
        pom = ET.parse(self.project / "pom.xml")
        self.assertEqual("3.0.13", pom.find("m:properties/m:spring-boot.version", ns).text)
        plugins = {item.find("m:artifactId", ns).text: item
                   for item in pom.findall("m:build/m:plugins/m:plugin", ns)}
        surefire = plugins["maven-surefire-plugin"]
        self.assertEqual("3.2.5", surefire.find("m:version", ns).text)
        self.assertEqual("true", surefire.find("m:configuration/m:failIfNoTests", ns).text)
        self.assertNotIn("continue-on-error", self.steps["test6"])

    def test_both_versions_run_same_named_test_and_report_positive_execution(self):
        for lane, version, boot_version in (("test5", "3.0.0", "3.0.13"),
                                            ("test6", "5.0.1", "4.0.2")):
            with self.subTest(lane=lane):
                self.assert_lane(lane, True)
                invocation = json.loads(Path(self.env["MAVEN_LOG"]).read_text().splitlines()[-1])
                expected_args = ["-B", "-q", "clean", "test", f"-Dtest={CLASS}#{METHOD}"]
                if lane == "test6":
                    expected_args.append("-Dspring-boot.version=4.0.2")
                self.assertEqual(expected_args, invocation["args"])
                self.assertFalse(invocation["target_exists"])
                self.assertEqual(version, invocation["version"])
                self.assertEqual(boot_version, invocation["boot_version"])
                self.assertEqual(SOURCE, invocation["source"])
                self.assertEqual(APPLICATION, (Path(invocation["project"]) / "src/main/java/smoke/TaskSmokeApplication.java").read_text())
                self.assertEqual(lane == "test5", Path(invocation["project"]) == self.project)
                self.assertEqual((self.project / "run-smoke.py").read_text(),
                                 (Path(invocation["project"]) / "run-smoke.py").read_text())
        self.assertIn("<version>3.0.0</version>", (self.project / "pom.xml").read_text())
        self.assertTrue((self.project / "target/surefire-reports" / REPORT).is_file())

    def test_rejects_missing_stale_symlink_wrong_or_extra_reports_in_both_lanes(self):
        for lane in ("test5", "test6"):
            for mode in ("missing", "stale", "symlink", "extra"):
                with self.subTest(lane=lane, mode=mode):
                    self.assert_lane(lane, False, REPORT_MODE=mode)
            with self.subTest(lane=lane, mode="wrong_filename"):
                self.assert_lane(lane, False, REPORT_NAME="TEST-other.xml")

    def test_stubborn_noop_maven_cannot_reuse_baseline_reports_or_compiled_classes(self):
        for lane in ("test5", "test6"):
            with self.subTest(lane=lane):
                stale = self.project / "target/surefire-reports" / REPORT
                stale.parent.mkdir(parents=True, exist_ok=True)
                stale.write_text(self.env["REPORT_XML"])
                compiled = self.project / "target/test-classes/smoke/TaskSmokeTest.class"
                compiled.parent.mkdir(parents=True, exist_ok=True)
                compiled.write_bytes(b"old compiled fixture")
                self.assert_lane(lane, False, REPORT_MODE="missing")
                invocation = json.loads(Path(self.env["MAVEN_LOG"]).read_text().splitlines()[-1])
                self.assertFalse(invocation["target_exists"])
                self.assertEqual(lane == "test6", stale.exists())
                self.assertEqual(lane == "test6", compiled.exists())

    def test_maven_failure_cannot_be_masked_by_a_valid_report_in_either_lane(self):
        for lane in ("test5", "test6"):
            for mode in ("fresh", "missing"):
                with self.subTest(lane=lane, mode=mode):
                    self.assert_lane(lane, False, MAVEN_EXIT="7", REPORT_MODE=mode)

    def test_xml_must_prove_exactly_one_successful_named_test_in_both_lanes(self):
        fixtures = [("empty", ""), ("malformed", "<testsuite")]

        def add(label, tree):
            fixtures.append((label, ET.tostring(tree, encoding="unicode")))

        for key in ("tests", "failures", "errors", "skipped"):
            for value in (None, "invalid", "-1", "0" if key == "tests" else "1", "2"):
                tree = report_tree()
                if value is None:
                    del tree.attrib[key]
                else:
                    tree.set(key, value)
                add(f"{key}={value}", tree)
        for location, key, value in (("suite", "name", "other.Suite"),
                                      ("case", "classname", "other.Suite"),
                                      ("case", "name", "unrelatedTest"),
                                      ("case", "name", METHOD + "()")):
            tree = report_tree()
            node = tree if location == "suite" else tree.find("testcase")
            node.set(key, value)
            add(f"wrong_{location}_{key}_{value}", tree)
        for tag in ("failure", "error", "skipped", "flakyFailure", "flakyError",
                    "rerunFailure", "rerunError"):
            tree = report_tree()
            ET.SubElement(tree.find("testcase"), tag)
            add(tag + "_despite_zero_counter", tree)
        tree = report_tree()
        tree.remove(tree.find("testcase"))
        add("no_testcase", tree)
        tree = report_tree()
        tree.append(copy.deepcopy(tree.find("testcase")))
        add("duplicate_testcase", tree)
        tree = report_tree()
        tree.find("properties").append(copy.deepcopy(tree.find("testcase")))
        add("nested_duplicate_testcase", tree)
        tree = report_tree()
        ET.SubElement(tree, "testsuite", name="other.Suite")
        add("nested_cross_suite", tree)
        wrapper = ET.Element("testsuites")
        wrapper.append(report_tree())
        add("wrong_root", wrapper)
        tree = report_tree()
        other = ET.SubElement(tree, "testsuite", name="other.Suite")
        other.append(tree.find("testcase"))
        tree.remove(tree.find("testcase"))
        add("cross_suite_case", tree)
        for lane in ("test5", "test6"):
            for label, xml in fixtures:
                with self.subTest(lane=lane, report=label):
                    self.assert_lane(lane, False, REPORT_XML=xml)

    def test_lane_failures_propagate_to_overall_summary_and_keep_core_badge_semantics(self):
        for lane in ("test5", "test6"):
            with self.subTest(lane=lane):
                _, output = self.assert_lane(lane, False, REPORT_MODE="missing")
                self.values[f"steps.{lane}.outputs.status"] = output["status"]
                self.values[f"steps.{lane}.outcome"] = "failure"
                result, summary = self.run_step("summary")
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(("5", "1", "0", "failure"),
                                 tuple(summary[key] for key in ("passed", "failed", "skipped", "overall_status")))
                self.assertEqual("1" if lane == "test5" else "0", summary["core_failed"])
                self.assertEqual("failing" if lane == "test5" else "passing", summary["badge_status"])
                self.values[f"steps.{lane}.outputs.status"] = "passed"
                self.values[f"steps.{lane}.outcome"] = "success"

    def test_actual_sequential_lanes_propagate_all_pass_failure_combinations(self):
        for baseline_passed in (True, False):
            for candidate_passed in (True, False):
                with self.subTest(baseline=baseline_passed, candidate=candidate_passed):
                    for lane, passed in (("test5", baseline_passed), ("test6", candidate_passed)):
                        _, output = self.assert_lane(lane, passed,
                                                     REPORT_MODE="fresh" if passed else "missing")
                        self.values[f"steps.{lane}.outputs.status"] = output["status"]
                        self.values[f"steps.{lane}.outcome"] = "success" if passed else "failure"
                    result, summary = self.run_step("summary")
                    self.assertEqual(baseline_passed and candidate_passed, result.returncode == 0)
                    failures = int(not baseline_passed) + int(not candidate_passed)
                    self.assertEqual(str(failures), summary["failed"])
                    self.assertEqual(str(6 - failures), summary["passed"])
                    self.assertEqual(str(int(not baseline_passed)), summary["core_failed"])
                    self.assertEqual("failure" if failures else "success", summary["overall_status"])

    def test_summary_requires_both_lanes_successfully_completed(self):
        result, summary = self.run_step("summary")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(("6", "0", "0", "0", "6", "success", "passing"),
                         tuple(summary[key] for key in ("passed", "failed", "skipped", "core_failed",
                                                        "duration", "overall_status", "badge_status")))
        for lane in ("test5", "test6"):
            for status, outcome in (("", ""), ("", "success"), ("skipped", "skipped"),
                                    ("failed", "success"), ("passed", ""),
                                    ("passed", "failure"), ("passed", "cancelled"), ("passed", "skipped")):
                with self.subTest(lane=lane, status=status, outcome=outcome):
                    self.values[f"steps.{lane}.outputs.status"] = status
                    self.values[f"steps.{lane}.outcome"] = outcome
                    result, summary = self.run_step("summary")
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual("failure", summary["overall_status"])
            self.values[f"steps.{lane}.outputs.status"] = "passed"
            self.values[f"steps.{lane}.outcome"] = "success"


if __name__ == "__main__":
    unittest.main()
