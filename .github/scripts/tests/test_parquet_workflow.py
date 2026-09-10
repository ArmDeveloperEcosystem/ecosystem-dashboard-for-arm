"""Execute Parquet workflow identity guards, failure paths and six-test accounting.

CLI fixtures exercise shell behavior; real Java/schema/data corruption is verified
separately on native Arm, not simulated by these fixtures.
"""

import copy
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/test-parquet.yml"
ARTIFACTS = ("parquet-hadoop", "parquet-column", "parquet-common", "parquet-encoding",
             "parquet-format-structures", "parquet-jackson")


def render(source, values):
    def expression(match):
        for term in match[1].split("||"):
            term = term.strip()
            if term.startswith("'") and term.endswith("'"):
                return term[1:-1]
            if term.isdigit():
                return term
            if values.get(term):
                return str(values[term])
        return ""
    return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", expression, source)


class ParquetWorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="parquet-workflow-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.workflow = yaml.safe_load(WORKFLOW.read_text())
        self.job = self.workflow["jobs"]["test-parquet"]
        self.steps = {step["id"]: step for step in self.job["steps"] if "id" in step}
        self.work = self.root / "parquet-java.fixture"
        self.work.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("date", "cat", "mkdir", "rm"):
            (self.bin / name).symlink_to(shutil.which(name))
        (self.bin / "python3").symlink_to(sys.executable)
        self.stub("timeout", "import os, sys\nos.execvp(sys.argv[2], sys.argv[2:])\n")
        self.stub("uname", 'import os\nprint(os.environ.get("HOST_ARCH", "aarch64"))\n')
        self.stub("javac", 'import os, sys\nsys.exit(int(os.environ.get("JAVAC_RC", "0")))\n')
        self.stub("java", r'''
import os
from pathlib import Path
import sys
mode = sys.argv[sys.argv.index("ParquetSmoke") + 1]
with open(os.environ["JAVA_LOG"], "a") as log:
    log.write(mode + "\n")
if mode == "write":
    (Path(os.environ["WORK"]) / "rows.parquet").write_bytes(b"PAR1fixturePAR1")
if os.environ.get("MUTATE_DURING_READ") and mode in ("read", "metadata"):
    (Path(os.environ["WORK"]) / "rows.parquet").write_bytes(b"changed during read")
sys.exit(int(os.environ.get("JAVA_RC", "0")))
''')
        self.stub("sha256sum", r'''
import hashlib
import os
from pathlib import Path
import sys
if sys.argv[1] == "--check":
    digest, filename = Path(sys.argv[2]).read_text().strip().split("  ", 1)
    if hashlib.sha256(Path(filename).read_bytes()).hexdigest() != digest:
        sys.exit(1)
else:
    file = Path(sys.argv[1])
    print(hashlib.sha256(file.read_bytes()).hexdigest() + "  " + str(file))
sys.exit(int(os.environ.get("HASH_RC", "0")))
''')
        self.env = dict(os.environ, PATH=str(self.bin), PYTHONDONTWRITEBYTECODE="1",
                        GITHUB_OUTPUT=str(self.root / "output"), RUNNER_TEMP=str(self.root),
                        JAVA_LOG=str(self.root / "java.log"))
        self.create_artifacts()

    def stub(self, name, source):
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n{source}")
        path.chmod(0o755)

    def artifact(self, name, release="1.15.0"):
        return self.work / "repository/org/apache/parquet" / name / release / f"{name}-{release}.jar"

    def create_artifacts(self, release="1.15.0", artifacts=ARTIFACTS):
        paths = []
        for name in artifacts:
            jar = self.artifact(name, release)
            jar.parent.mkdir(parents=True, exist_ok=True)
            paths.append(str(jar))
            jar.with_suffix(".pom").write_text(
                '<project xmlns="http://maven.apache.org/POM/4.0.0">'
                f"<parent><groupId>org.apache.parquet</groupId><artifactId>parquet</artifactId>"
                f"<version>{release}</version></parent><artifactId>{name}</artifactId></project>")
            self.jar_properties(name, f"groupId=org.apache.parquet\nartifactId={name}\nversion={release}\n", release)
        (self.work / "classpath").write_text(os.pathsep.join(paths))

    def jar_properties(self, name, properties, release="1.15.0"):
        with zipfile.ZipFile(self.artifact(name, release), "w") as jar:
            jar.writestr(f"META-INF/maven/org.apache.parquet/{name}/pom.properties", properties)

    def values(self):
        return {"steps.install.outputs.work_dir": str(self.work),
                "steps.version.outputs.status": "passed", "steps.version.outputs.version": "1.15.0",
                "steps.test3.outputs.status": "passed", "steps.test3.outcome": "success"}

    def run_step(self, name, values=None, source=None, **environment):
        values = self.values() if values is None else values
        step = self.steps[name]
        step_env = {key: render(value, values) for key, value in step.get("env", {}).items()}
        output = Path(self.env["GITHUB_OUTPUT"])
        output.write_text("")
        result = subprocess.run(["/bin/bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c",
                                 render(source or step["run"], values)],
                                cwd=self.root, env={**self.env, **step_env, **environment},
                                capture_output=True, text=True, timeout=15)
        pairs = [line.split("=", 1) for line in output.read_text().splitlines()]
        self.assertTrue(all(len(pair) == 2 for pair in pairs), pairs)
        self.assertEqual(len(pairs), len(dict(pairs)), "Outputs must be emitted exactly once")
        return result, dict(pairs)

    def assert_result(self, name, passed=True, **kwargs):
        result, outputs = self.run_step(name, **kwargs)
        self.assertEqual(result.returncode == 0, passed, result.stdout + result.stderr)
        self.assertEqual(outputs.get("status"), "passed" if passed else "failed")
        self.assertRegex(outputs.get("duration", ""), r"^[0-9]+$")
        if name == "version" and not passed:
            self.assertNotIn("version", outputs)
        return result, outputs

    def test_release_is_read_from_resolved_pom_and_jar(self):
        _, outputs = self.assert_result("version")
        self.assertEqual("1.15.0", outputs["version"])

    def test_direct_pom_coordinates_are_supported(self):
        pom = self.artifact("parquet-hadoop").with_suffix(".pom")
        pom.write_text('<project xmlns="http://maven.apache.org/POM/4.0.0">'
                       "<groupId>org.apache.parquet</groupId><artifactId>parquet-hadoop</artifactId>"
                       "<version>1.15.0</version></project>")
        self.assert_result("version")

    def test_wrong_group_artifact_or_release_in_pom_fails(self):
        pom = self.artifact("parquet-hadoop").with_suffix(".pom")
        original = pom.read_text()
        for old, new in (("org.apache.parquet", "python.parquet_tools"),
                         ("parquet-hadoop", "parquet-tools"), ("1.15.0", "1.12.0")):
            with self.subTest(new=new):
                pom.write_text(original.replace(old, new))
                self.assert_result("version", False)

    def test_jar_identity_mismatch_duplicate_or_missing_properties_fails(self):
        valid = "groupId=org.apache.parquet\nartifactId=parquet-hadoop\nversion=1.15.0\n"
        for properties in (valid.replace("1.15.0", "1.14.0"),
                           valid.replace("org.apache.parquet", "python"),
                           valid.replace("parquet-hadoop", "parquet-tools"),
                           valid + "version=1.15.0\n", valid.replace("version=1.15.0\n", ""), "malformed"):
            with self.subTest(properties=properties):
                self.jar_properties("parquet-hadoop", properties)
                self.assert_result("version", False)

    def test_missing_corrupt_or_unidentified_jar_fails(self):
        jar = self.artifact("parquet-hadoop")
        jar.unlink()
        self.assert_result("version", False)
        jar.write_bytes(b"not a jar")
        self.assert_result("version", False)
        with zipfile.ZipFile(jar, "w") as archive:
            archive.writestr("some-other-package", "1.15.0")
        self.assert_result("version", False)

    def test_malformed_or_missing_pom_fails(self):
        pom = self.artifact("parquet-column").with_suffix(".pom")
        pom.write_text("<project>")
        self.assert_result("version", False)
        pom.unlink()
        self.assert_result("version", False)

    def test_wrong_consistent_release_cannot_be_relabelled(self):
        for release in ("1.12.0", "1.15.1", "1.15.0-SNAPSHOT", "1.15.0-rc1"):
            with self.subTest(release=release):
                self.create_artifacts(release)
                self.assert_result("version", False)

    def test_missing_unexpected_or_mixed_parquet_dependencies_fail(self):
        for artifacts in (ARTIFACTS[:-1], ARTIFACTS + ("parquet-tools",)):
            with self.subTest(artifacts=artifacts):
                self.create_artifacts(artifacts=artifacts)
                self.assert_result("version", False)
        self.create_artifacts()
        self.create_artifacts("1.14.0", ("parquet-column",))
        classpath = [str(self.artifact(name, "1.14.0" if name == "parquet-column" else "1.15.0"))
                     for name in ARTIFACTS]
        (self.work / "classpath").write_text(os.pathsep.join(classpath))
        self.assert_result("version", False)

    def test_empty_duplicate_or_external_classpath_fails(self):
        path = self.work / "classpath"
        valid = path.read_text()
        external = self.root / "unowned.jar"
        external.write_bytes(b"unowned")
        for value in ("", valid + os.pathsep + valid.split(os.pathsep)[0], valid + os.pathsep + str(external)):
            with self.subTest(value=value):
                path.write_text(value)
                self.assert_result("version", False)

    def test_symlink_escape_fails(self):
        jar = self.artifact("parquet-common")
        outside = self.root / jar.name
        jar.rename(outside)
        jar.symlink_to(outside)
        self.assert_result("version", False)

    def test_all_core_success_paths_emit_once(self):
        for name in ("test1", "test2", "test3", "test4", "test5"):
            with self.subTest(name=name):
                self.assert_result(name)
        self.assertEqual(["identity", "architecture", "write", "metadata", "read"],
                         (self.root / "java.log").read_text().splitlines())

    def test_failed_version_blocks_compilation(self):
        values = self.values()
        values["steps.version.outputs.status"] = "failed"
        self.assert_result("test1", False, values=values)
        self.assertFalse((self.work / "ParquetSmoke.java").exists())

    def test_compilation_failure_is_not_a_pass(self):
        result, _ = self.assert_result("test1", False, JAVAC_RC="23")
        self.assertEqual(23, result.returncode)
        self.assertFalse((self.root / "java.log").exists())

    def test_non_arm_host_fails(self):
        self.assert_result("test2", False, HOST_ARCH="x86_64")
        self.assertFalse((self.root / "java.log").exists())

    def test_every_java_failure_propagates_including_timeout(self):
        self.assert_result("test3")
        for name in ("test1", "test2", "test3", "test4", "test5"):
            for rc in (1, 23, 124, 137):
                with self.subTest(name=name, rc=rc):
                    result, _ = self.assert_result(name, False, JAVA_RC=str(rc))
                    self.assertEqual(rc, result.returncode)

    def test_missing_work_directory_fails_all_guards(self):
        values = self.values()
        values["steps.install.outputs.work_dir"] = str(self.root / "missing")
        for name in ("version", "test1", "test2", "test3", "test4", "test5"):
            with self.subTest(name=name):
                self.assert_result(name, False, values=values)

    def test_failed_or_skipped_writer_blocks_reads(self):
        for key in ("steps.test3.outputs.status", "steps.test3.outcome"):
            for value in ("", "failed", "failure", "skipped", "cancelled"):
                values = self.values()
                values[key] = value
                for name in ("test4", "test5"):
                    with self.subTest(name=name, key=key, value=value):
                        self.assert_result(name, False, values=values)

    def test_modified_fixture_fails_before_java_reads(self):
        self.assert_result("test3")
        (self.root / "java.log").unlink()
        (self.work / "rows.parquet").write_bytes(b"truncated")
        for name in ("test4", "test5"):
            self.assert_result(name, False)
        self.assertFalse((self.root / "java.log").exists())

    def test_hash_failure_is_a_failure(self):
        self.assert_result("test3")
        for name in ("test3", "test4", "test5"):
            with self.subTest(name=name):
                self.assert_result(name, False, HASH_RC="1")

    def test_successful_java_cannot_mutate_the_read_fixture(self):
        for name in ("test4", "test5"):
            with self.subTest(name=name):
                self.assert_result("test3")
                self.assert_result(name, False, MUTATE_DURING_READ="1")

    def summary_values(self):
        values = {}
        for i in range(1, 7):
            values[f"steps.test{i}.outcome"] = "success"
            values[f"steps.test{i}.outputs.status"] = "passed" if i < 6 else "skipped"
            values[f"steps.test{i}.outputs.duration"] = str(i)
        values["steps.test6.outputs.decision"] = "not_applicable_package_manager"
        return values

    def test_summary_counts_five_passes_and_explicit_skip(self):
        result, outputs = self.run_step("summary", self.summary_values())
        self.assertEqual(0, result.returncode)
        self.assertEqual({"passed": "5", "failed": "0", "core_failed": "0", "skipped": "1",
                          "duration": "21", "overall_status": "success", "badge_status": "passing"}, outputs)

    def test_summary_rejects_every_bad_core_status_and_outcome(self):
        for i in range(1, 6):
            for field, bad in (("outcome", ("failure", "skipped", "cancelled", "")),
                               ("outputs.status", ("failed", "skipped", "unknown", ""))):
                for value in bad:
                    with self.subTest(test=i, field=field, value=value):
                        values = self.summary_values()
                        values[f"steps.test{i}.{field}"] = value
                        result, outputs = self.run_step("summary", values)
                        self.assertNotEqual(0, result.returncode)
                        self.assertEqual(("4", "1", "1", "1", "failure", "failing"),
                                         tuple(outputs[k] for k in
                                               ("passed", "failed", "core_failed", "skipped", "overall_status", "badge_status")))

    def test_regression_skip_requires_correct_status_outcome_and_decision(self):
        for field, bad in (("outcome", ("failure", "skipped", "cancelled", "")),
                           ("outputs.status", ("passed", "failed", "")),
                           ("outputs.decision", ("not_configured", "baseline_failed", ""))):
            for value in bad:
                with self.subTest(field=field, value=value):
                    values = self.summary_values()
                    values[f"steps.test6.{field}"] = value
                    result, outputs = self.run_step("summary", values)
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual(("5", "1", "0", "0"), tuple(outputs[k] for k in
                                                               ("passed", "failed", "core_failed", "skipped")))

    def test_missing_steps_count_as_failures(self):
        result, outputs = self.run_step("summary", {})
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(("0", "6", "5", "0", "0"), tuple(outputs[k] for k in
                                                        ("passed", "failed", "core_failed", "skipped", "duration")))

    def test_maven_regression_is_explicitly_skipped(self):
        result, outputs = self.run_step("test6")
        self.assertEqual(0, result.returncode)
        self.assertEqual("skipped", outputs["status"])
        self.assertEqual("not_applicable_package_manager", outputs["decision"])
        self.assertEqual("1.15.0", outputs["current_version"])
        self.assertEqual("not_applicable", outputs["latest_version"])
        self.assertEqual("not_applicable", outputs["next_installed_version"])
        self.assertEqual("0", outputs["duration"])
        self.assertIn("Maven", outputs["regression_result"])

    def test_install_uses_official_pinned_maven_dependency(self):
        script = self.steps["install"]["run"]
        pom = ET.fromstring(re.search(r"<<'XML'\n(.*?)\nXML", script, re.S)[1])
        ns = {"m": "http://maven.apache.org/POM/4.0.0"}
        dependencies = [tuple(dep.findtext(f"m:{field}", namespaces=ns)
                              for field in ("groupId", "artifactId", "version"))
                        for dep in pom.findall("m:dependencies/m:dependency", ns)]
        self.assertIn(("org.apache.parquet", "parquet-hadoop", "1.15.0"), dependencies)
        self.assertIn("timeout 600s mvn -B -ntp -C", script)
        self.assertIn('bash .github/actions/apt-bootstrap/bootstrap.sh --packages "maven openjdk-17-jdk-headless"', script)
        self.assertIn("export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-arm64", script)
        self.assertIn('export PATH="$JAVA_HOME/bin:$PATH"', script)
        self.assertIn('echo "JAVA_HOME=$JAVA_HOME" >> "$GITHUB_ENV"', script)
        self.assertIn('echo "$JAVA_HOME/bin" >> "$GITHUB_PATH"', script)
        self.assertNotRegex(script, r"\bpip[0-9]*\s+install\b")
        self.assertNotIn("parquet-tools", script)

    def test_bootstrap_binds_java17_and_persists_the_runner_environment(self):
        bootstrap = self.root / ".github/actions/apt-bootstrap/bootstrap.sh"
        bootstrap.parent.mkdir(parents=True)
        bootstrap.write_text('test "$1" = --packages\n'
                             'test "$2" = "maven openjdk-17-jdk-headless"\n'
                             'exit "${BOOTSTRAP_RC:-0}"\n')
        (self.bin / "bash").symlink_to("/bin/bash")
        java_home = self.root / "java-17-openjdk-arm64"
        (java_home / "bin").mkdir(parents=True)
        for name in ("java", "javac"):
            executable = java_home / "bin" / name
            executable.write_text(f"#!{sys.executable}\n" +
                                  'import os, sys\nfrom pathlib import Path\n'
                                  'assert sys.argv[1:] == ["-version"]\n'
                                  'assert Path(os.environ["JAVA_HOME"]) == Path(__file__).parent.parent\n'
                                  'with open(os.environ["BINDING_LOG"], "a") as log:\n'
                                  '    log.write(str(Path(__file__)) + "\\n")\n')
            executable.chmod(0o755)
        source = self.steps["install"]["run"].split("WORK=$(mktemp", 1)[0]
        source = source.replace("/usr/lib/jvm/java-17-openjdk-arm64", str(java_home))
        environment = {"JAVA_HOME": str(self.root / "wrong-jdk"),
                       "GITHUB_ENV": str(self.root / "runner-env"),
                       "GITHUB_PATH": str(self.root / "runner-path"),
                       "BINDING_LOG": str(self.root / "binding-log")}
        result, _ = self.run_step("install", source=source, **environment)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(f"JAVA_HOME={java_home}\n", Path(environment["GITHUB_ENV"]).read_text())
        self.assertEqual(f"{java_home}/bin\n", Path(environment["GITHUB_PATH"]).read_text())
        self.assertEqual([str(java_home / "bin/java"), str(java_home / "bin/javac")],
                         Path(environment["BINDING_LOG"]).read_text().splitlines())
        for key in ("GITHUB_ENV", "GITHUB_PATH", "BINDING_LOG"):
            Path(environment[key]).unlink()
        result, outputs = self.run_step("install", source=source, BOOTSTRAP_RC="23", **environment)
        self.assertEqual(23, result.returncode)
        self.assertNotIn("install_status", outputs)
        self.assertFalse(Path(environment["GITHUB_ENV"]).exists())
        self.assertFalse(Path(environment["GITHUB_PATH"]).exists())
        self.assertFalse(Path(environment["BINDING_LOG"]).exists())

    def test_contract_security_pins_and_summary_detail_ids(self):
        self.assertEqual({"contents": "read"}, self.workflow["permissions"])
        self.assertEqual("ubuntu-24.04-arm", self.job["runs-on"])
        uses = [step["uses"] for step in self.job["steps"] if "uses" in step]
        self.assertEqual(["actions/checkout@11d5960a326750d5838078e36cf38b85af677262"], uses)
        self.assertFalse(self.job["steps"][0]["with"]["persist-credentials"])
        interface = (self.workflow.get("on") or self.workflow[True])["workflow_call"]["outputs"]
        self.assertEqual(set(interface), set(self.job["outputs"]))
        self.assertEqual("2.0", self.job["outputs"]["contract_version"])
        self.assertEqual("always()", self.steps["summary"]["if"])
        details = self.job["steps"][-1]["run"]
        for i in range(1, 7):
            self.assertIn(f"steps.test{i}.outputs.status", details)

    def test_unchanged_migration_auditor_recognizes_real_outputs(self):
        sys.path.insert(0, str(ROOT / ".github/scripts"))
        import package_observation_migration_audit as audit
        for name in ("test1", "test2", "test3", "test4", "test5", "test6"):
            for field in ("status", "duration"):
                with self.subTest(name=name, field=field):
                    self.assertTrue(audit._step_emits_output(ROOT, self.steps[name], field))
        for field in ("passed", "failed", "core_failed", "skipped", "duration", "overall_status", "badge_status"):
            self.assertTrue(audit._step_emits_output(ROOT, self.steps["summary"], field))
        self.assertEqual(("not_applicable_package_manager",),
                         audit._step_literal_outputs(ROOT, self.steps["test6"], "decision"))
        unreachable = copy.deepcopy(self.steps["test1"])
        unreachable["run"] = unreachable["run"].replace("finish 0", "")
        self.assertFalse(audit._step_emits_output(ROOT, unreachable, "status"))

    def test_repository_auditor_has_no_parquet_output_or_accounting_gaps(self):
        sys.path.insert(0, str(ROOT / ".github/scripts"))
        import package_observation_migration_audit as audit
        remediation = audit.audit_repository(ROOT)["remediation"]
        fields = ("missing_test_steps", "missing_test_status", "missing_test_duration",
                  "missing_summary_outputs", "missing_summary_step", "invalid_test_names",
                  "baseline_literal_skip", "baseline_dynamic_skip", "no_literal_decision",
                  "summary_missing_duration_reference", "package_manager_missing_decision",
                  "package_manager_missing_explicit_skip_counter", "package_manager_non_skipped_status",
                  "package_manager_summary_omits_test6", "literal_pair_contradictions")

        def contains_parquet(value):
            if isinstance(value, dict):
                return any(contains_parquet(item) for item in value.values())
            if isinstance(value, list):
                return any(contains_parquet(item) for item in value)
            return value == "parquet"

        for field in fields:
            with self.subTest(field=field):
                self.assertFalse(contains_parquet(remediation[field]), remediation[field])


if __name__ == "__main__":
    unittest.main()
