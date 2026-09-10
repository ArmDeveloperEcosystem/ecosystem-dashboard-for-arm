"""Exercise libjpeg-turbo identity binding and real workflow failure accounting."""

from pathlib import Path
import unittest

from test_notary_workflow import ContractChecks, WorkflowHarness


WORKFLOW = Path(__file__).resolve().parents[2] / "workflows/test-libjpeg.yml"
VERSION = "2.1.5"
REVISION = "2.1.5-2ubuntu2"


class LibjpegWorkflowTests(WorkflowHarness, ContractChecks, unittest.TestCase):
    workflow = WORKFLOW

    def setUp(self):
        super().setUp()
        self.headers = self.root / "include"
        self.headers.mkdir()
        for name in ("jpeglib.h", "jconfig.h"):
            (self.headers / name).write_text("/* Controlled package header fixture. */\n")
        self.library = self.root / "libjpeg.so.8.2.2"
        self.library.write_bytes(b"controlled library identity fixture")
        self.values.update({"steps.version.outputs.version": VERSION,
                            "steps.version.outputs.package_version": REVISION})
        self.env.update(
            PM_DEV=self.package_row("libjpeg-turbo8-dev"),
            PM_RUNTIME=self.package_row("libjpeg-turbo8"),
            PM_RC="0", FILES_RC="0", CC_RC="0", PROBE_RC="0",
            PM_HEADERS=str(self.headers / "jpeglib.h") + "\n" + str(self.headers / "jconfig.h") + "\n",
            PM_LIBRARIES=str(self.library) + "\n",
            PROBE_STDOUT=f"libjpeg-turbo\t{VERSION}\t{self.library}\n",
            PROBE_STDERR="", ROUNDTRIP_STDOUT="libjpeg-roundtrip-ok\n", ROUNDTRIP_RC="0",
        )
        self.tool("dpkg-query", r'''
case "$1" in
  -W)
    test "$#" = 3; test "$2" = "$PM_FORMAT"
    case "$3" in
      libjpeg-turbo8-dev) printf '%s' "$PM_DEV" ;;
      libjpeg-turbo8) printf '%s' "$PM_RUNTIME" ;;
      *) exit 99 ;;
    esac
    exit "$PM_RC" ;;
  -L)
    test "$#" = 2
    case "$2" in
      libjpeg-turbo8-dev) printf '%s' "$PM_HEADERS" ;;
      libjpeg-turbo8) printf '%s' "$PM_LIBRARIES" ;;
      *) exit 99 ;;
    esac
    exit "$FILES_RC" ;;
  *) exit 99 ;;
esac
''')
        self.tool("cc", r'''
if [ "$CC_RC" != 0 ]; then exit "$CC_RC"; fi
for argument in "$@"; do
  case "$argument" in
    *.c) source="$argument" ;;
  esac
done
while [ "$1" != -o ]; do shift; done
output="$2"
cp "$source" "$RUNNER_TEMP/compiled.c"
if [ "$(basename "$source")" = identity.c ]; then
  printf '%s\n' '#!/bin/bash' 'printf "%s" "$PROBE_STDOUT"' 'printf "%s" "$PROBE_STDERR" >&2' 'exit "$PROBE_RC"' > "$output"
else
  printf '%s\n' '#!/bin/bash' 'printf "%s" "$ROUNDTRIP_STDOUT"' 'exit "$ROUNDTRIP_RC"' > "$output"
fi
chmod +x "$output"
''')

    def package_row(self, name, version=VERSION, revision=REVISION):
        return f"{name}\tinstall ok installed\t{revision}\tarm64\tlibjpeg-turbo\t{version}\n"

    def test_version_and_test2_bind_header_and_loaded_library_to_arm_packages(self):
        for step in ("version", "test2"):
            result, outputs = self.run_step(step)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(VERSION, outputs["version"])
            self.assertEqual(REVISION, outputs["package_version"])
            self.assertEqual(VERSION, outputs["source_upstream_version"])
            self.assertEqual("native_header_and_dpkg", outputs["version_source"])
            self.assertEqual("passed", outputs["status"])

    def test_epoch_and_revision_do_not_change_upstream_version(self):
        revision = "2:2.1.5-7ubuntu1"
        result, outputs = self.run_step(
            "version", PM_DEV=self.package_row("libjpeg-turbo8-dev", revision=revision),
            PM_RUNTIME=self.package_row("libjpeg-turbo8", revision=revision))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(VERSION, outputs["version"])
        self.assertEqual(revision, outputs["package_version"])

    def test_metapackage_abi_wrong_product_and_malformed_native_versions_fail(self):
        for version in ("8c", "80", "unknown", "1.x.3", "", "9.9.9"):
            for step in ("version", "test2"):
                with self.subTest(step=step, version=version):
                    self.rejected(step, PROBE_STDOUT=f"libjpeg-turbo\t{version}\t{self.library}\n")
        for banner in ("", self.env["PROBE_STDOUT"] * 2,
                       self.env["PROBE_STDOUT"] + "\n",
                       self.env["PROBE_STDOUT"].replace("libjpeg-turbo", "libjpeg"),
                       "prefix " + self.env["PROBE_STDOUT"]):
            self.rejected(PROBE_STDOUT=banner)

    def test_failed_native_probe_compiler_or_query_cannot_publish_version(self):
        for step in ("version", "test2"):
            for variable in ("PM_RC", "FILES_RC", "CC_RC", "PROBE_RC"):
                with self.subTest(step=step, variable=variable):
                    self.rejected(step, **{variable: "1"})
            self.rejected(step, PROBE_STDERR="native error\n")

    def test_wrong_missing_duplicate_uninstalled_or_non_arm_package_fails(self):
        for variable, name in (("PM_DEV", "libjpeg-turbo8-dev"), ("PM_RUNTIME", "libjpeg-turbo8")):
            row = self.package_row(name)
            for package in ("", row + row, row.replace(name + "\t", "libjpeg-dev\t", 1),
                            row.replace("\tlibjpeg-turbo\t", "\tlibjpeg\t"),
                            row.replace("install ok installed", "deinstall ok config-files"),
                            row.replace("arm64", "amd64"), row.replace(REVISION, "unknown"),
                            row.replace("\t2.1.5\n", "\t8c\n"),
                            row.replace(REVISION, "2.1.6-2ubuntu2")):
                for step in ("version", "test2"):
                    with self.subTest(step=step, variable=variable, package=package):
                        self.rejected(step, **{variable: package})

    def test_development_and_runtime_revisions_must_match(self):
        self.rejected(PM_RUNTIME=self.package_row("libjpeg-turbo8", revision="2.1.5-3ubuntu1"))
        self.rejected(PM_RUNTIME=self.package_row("libjpeg-turbo8", "2.1.6", "2.1.6-2ubuntu2"))

    def test_unowned_or_missing_headers_and_loaded_library_are_rejected(self):
        self.rejected(PM_HEADERS="")
        self.rejected(PM_LIBRARIES="")
        self.rejected(PROBE_STDOUT=f"libjpeg-turbo\t{VERSION}\t/usr/local/lib/libjpeg.so\n")
        duplicate = self.root / "extra"
        duplicate.mkdir()
        (duplicate / "jconfig.h").write_text("/* Other header. */\n")
        self.rejected(PM_HEADERS=self.env["PM_HEADERS"] + str(duplicate / "jconfig.h") + "\n")
        (self.headers / "jconfig.h").unlink()
        self.rejected()

    def test_roundtrip_preserves_real_encode_decode_and_reports_success(self):
        result, outputs = self.run_step("test5")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])
        source = (self.root / "compiled.c").read_text()
        for operation in ("jpeg_start_compress", "jpeg_write_scanlines", "jpeg_finish_compress",
                          "jpeg_read_header", "jpeg_start_decompress", "jpeg_read_scanlines",
                          "jpeg_finish_decompress"):
            self.assertIn(operation, source)
        self.assertNotIn("JPEG_LIB_VERSION", source)

    def test_roundtrip_failure_or_false_success_marker_emits_failure_and_duration(self):
        for overrides in ({"CC_RC": "1"}, {"ROUNDTRIP_RC": "1"},
                          {"ROUNDTRIP_STDOUT": ""}, {"ROUNDTRIP_STDOUT": "jpeg-error\n"},
                          {"ROUNDTRIP_STDOUT": "libjpeg-roundtrip-ok\nerror\n"}):
            self.rejected("test5", **overrides)

    def test_library_cache_requires_success_and_arm_identity(self):
        self.tool("ldconfig", 'printf "%s" "$CACHE_STDOUT"\nexit "$CACHE_RC"\n')
        valid = "\tlibjpeg.so.8 (libc6,AArch64) => /lib/aarch64-linux-gnu/libjpeg.so.8\n"
        result, outputs = self.run_step("test3", CACHE_STDOUT=valid, CACHE_RC="0")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("passed", outputs["status"])
        self.rejected("test3", CACHE_STDOUT=valid, CACHE_RC="1")
        self.rejected("test3", CACHE_STDOUT=valid.replace("AArch64", "x86-64"), CACHE_RC="0")


if __name__ == "__main__":
    unittest.main()
