"""Offline stdlib-only tests of the official-wheel preflight helper.

All wheels, ELF headers, release metadata, and host identities are synthetic.
C++ probes compile and execute locally; this is not native Arm or GPU testing.
No extension is imported, and no network access is permitted by the fixtures.
"""

from collections import namedtuple
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.error import URLError
import warnings
import zipfile
import zlib


SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import cudnn_frontend_wheel_smoke as smoke

BASELINE = "1.13.0"
VERSION = "1.32.1"
PYTHON_TAG = "cp312"
PLATFORMS = "manylinux_2_27_aarch64.manylinux_2_28_aarch64"
FILENAME = f"nvidia_cudnn_frontend-{VERSION}-{PYTHON_TAG}-{PYTHON_TAG}-{PLATFORMS}.whl"
URL = "https://files.pythonhosted.org/packages/fixture/" + FILENAME
TAGS = {f"cp312-cp312-{platform}" for platform in PLATFORMS.split(".")}
DIST_INFO = f"nvidia_cudnn_frontend-{VERSION}.dist-info"
EXTENSION = "cudnn/_compiled_module.cpython-312-aarch64-linux-gnu.so"
VersionInfo = namedtuple("VersionInfo", "major minor micro releaselevel serial")
REAL_DOWNLOAD = smoke.download


def version_header(version):
    major, minor, patch = version.split(".")
    return (
        "// Synthetic header, not an upstream source checkout.\n#pragma once\n"
        f"#define CUDNN_FRONTEND_MAJOR_VERSION ({major})\n"
        f"#define CUDNN_FRONTEND_MINOR_VERSION ({minor})\n"
        f"#define CUDNN_FRONTEND_PATCH_VERSION ({patch})\n"
        "#define CUDNN_FRONTEND_VERSION (CUDNN_FRONTEND_MAJOR_VERSION * 10000 + "
        "CUDNN_FRONTEND_MINOR_VERSION * 100 + CUDNN_FRONTEND_PATCH_VERSION)\n"
    ).encode()


def elf_header(machine=183, kind=3):
    raw = bytearray(64)
    raw[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<HHI", raw, 16, kind, machine, 1)
    return bytes(raw)


class CudnnFrontendWheelSmokeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="cudnn-wheel-unit-fixture-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "github-output"
        self.unpack_count = 0
        python_version = mock.patch.object(sys, "version_info", VersionInfo(3, 12, 0, "final", 0))
        python_version.start()
        self.addCleanup(python_version.stop)
        self.entries = {
            f"{DIST_INFO}/METADATA": (
                f"Metadata-Version: 2.1\nName: {smoke.PROJECT}\nVersion: {VERSION}\n\n").encode(),
            f"{DIST_INFO}/WHEEL": (
                "Wheel-Version: 1.0\nRoot-Is-Purelib: false\n" +
                "".join(f"Tag: {tag}\n" for tag in sorted(TAGS)) + "\n").encode(),
            "include/cudnn_frontend_version.h": version_header(VERSION),
            "include/cudnn_frontend.h": b"#include <cudnn.h>\n",
            "cudnn/__init__.py": (
                f'__version__ = "{VERSION}"\n'
                'raise RuntimeError("Synthetic extension fixture must never be imported")\n').encode(),
            EXTENSION: elf_header(),
        }
        self.raw, self.wheel = self.pack()
        self.item = {"filename": FILENAME, "url": URL, "packagetype": "bdist_wheel", "yanked": False,
                     "digests": {"sha256": self.wheel["sha256"]}, "size": len(self.raw)}
        self.document = {"info": {"name": smoke.PROJECT, "version": VERSION},
                         "releases": {BASELINE: [{"yanked": False}], VERSION: [copy.deepcopy(self.item)]},
                         "urls": [copy.deepcopy(self.item)]}
        patcher = mock.patch.object(smoke, "download", side_effect=AssertionError("Live network is forbidden"))
        self.fetch = patcher.start()
        self.addCleanup(patcher.stop)

    def pack(self, entries=None, extra=(), *, compression=zipfile.ZIP_STORED):
        stream = io.BytesIO()
        with warnings.catch_warnings(), zipfile.ZipFile(stream, "w", compression=compression) as archive:
            warnings.simplefilter("ignore", UserWarning)
            for name, content in list((self.entries if entries is None else entries).items()) + list(extra):
                archive.writestr(name, content)
        raw = stream.getvalue()
        wheel = {"filename": FILENAME, "url": URL, "sha256": hashlib.sha256(raw).hexdigest(),
                 "size": len(raw), "tags": set(TAGS)}
        return raw, wheel

    def unpack(self, *, entries=None, extra=(), wheel_override=None):
        raw, wheel = self.pack(entries, extra)
        wheel.update(wheel_override or {})
        self.unpack_count += 1
        destination = self.root / f"unpacked-{self.unpack_count}"
        self.destination = destination
        smoke.unpack_verified_wheel(raw, wheel, VERSION, destination)
        return destination

    def require_compiler(self):
        if shutil.which("g++") is None:
            self.skipTest("The synthetic C++ compile/run fixture needs a real g++-compatible compiler")

    def run_main(self, *, document=None, raw=None, baseline=BASELINE,
                 system="Linux", machine="aarch64", fetch_effect=None, libc="glibc 2.39"):
        self.output.write_text("")
        self.fetch.reset_mock()
        self.fetch.side_effect = fetch_effect if fetch_effect is not None else [
            json.dumps(self.document if document is None else document).encode(),
            self.raw if raw is None else raw,
        ]
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["wheel-fixture", "--baseline-version", baseline]), \
                mock.patch.object(smoke.platform, "system", return_value=system), \
                mock.patch.object(smoke.platform, "machine", return_value=machine), \
                mock.patch.object(smoke.os, "confstr", return_value=libc), \
                mock.patch.object(sys, "version_info", VersionInfo(3, 12, 0, "final", 0)), \
                mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(self.output)}), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = smoke.main()
        fields = dict(line.split("=", 1) for line in self.output.read_text().splitlines())
        return code, fields, stdout.getvalue(), stderr.getvalue()

    def assert_main_failed(self, result):
        code, fields, stdout, stderr = result
        self.assertNotEqual(0, code)
        self.assertEqual(("failed", "limited_cpu_smoke_failed", "not_installed"),
                         tuple(fields[key] for key in ("status", "decision", "next_installed_version")))
        self.assertTrue(fields["duration"].isdigit())
        self.assertTrue(fields["regression_result"].strip())
        self.assertTrue(fields["comparison"].strip())
        self.assertIn("failed:", stderr)
        self.assertNotIn("PREFLIGHT_OK", stdout)

    def test_release_version_requires_canonical_stable_identity(self):
        self.assertEqual((1, 32, 1), smoke.release_version(VERSION))
        self.assertEqual((0, 0, 0), smoke.release_version("0.0.0"))
        for version in (None, 1321, "", "1.32", "v1.32.1", "01.32.1", "1.032.1", "1.32.01",
                        "1.32.1rc1", "1.32.1.post1", "1.32.1+local", " 1.32.1", "1.32.1\n"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                smoke.release_version(version)

    def test_checked_url_requires_exact_https_origin_without_credentials_or_suffixes(self):
        self.assertEqual(URL, smoke.checked_url(URL, "files.pythonhosted.org"))
        for url in (URL.replace("https:", "http:"), URL.replace("files.pythonhosted.org", "evil.example"),
                    URL.replace("files.pythonhosted.org", "files.pythonhosted.org.evil.example"),
                    URL.replace("files.pythonhosted.org", "user:password@files.pythonhosted.org"),
                    URL.replace("files.pythonhosted.org", "files.pythonhosted.org:443"),
                    URL + "?token=fixture", URL + "#fragment", "//files.pythonhosted.org/file.whl"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                smoke.checked_url(url, "files.pythonhosted.org")

    def test_download_hard_deadline_and_size_limit_restore_previous_alarm_state(self):
        for mode in ("success", "oversized", "timeout"):
            with self.subTest(mode=mode), \
                    mock.patch.object(smoke, "build_opener") as build, \
                    mock.patch.object(smoke.signal, "signal", return_value=mock.sentinel.handler) as handler, \
                    mock.patch.object(smoke.signal, "setitimer", return_value=(7.5, 0.25)) as timer:
                response = build.return_value.open.return_value.__enter__.return_value
                response.url = URL

                def trigger_deadline(*args):
                    handler.call_args_list[0].args[1](smoke.signal.SIGALRM, None)

                if mode == "success":
                    response.read.side_effect = [b"a", b"b", b""]
                    self.assertEqual(b"ab", REAL_DOWNLOAD(URL, "files.pythonhosted.org", 2))
                elif mode == "oversized":
                    response.read.side_effect = [b"abc", b""]
                    with self.assertRaisesRegex(ValueError, "size limit"):
                        REAL_DOWNLOAD(URL, "files.pythonhosted.org", 2)
                else:
                    response.read.side_effect = trigger_deadline
                    with self.assertRaisesRegex(TimeoutError, "time limit"):
                        REAL_DOWNLOAD(URL, "files.pythonhosted.org", 2)
                self.assertEqual([mock.call(smoke.signal.ITIMER_REAL, 120),
                                  mock.call(smoke.signal.ITIMER_REAL, 7.5, 0.25)], timer.call_args_list)
                self.assertEqual(mock.call(smoke.signal.SIGALRM, mock.sentinel.handler), handler.call_args)
                self.assertEqual(2, handler.call_count)
                build.return_value.open.assert_called_once_with(URL, timeout=30)

    def test_wheel_tags_accept_matching_cp312_aarch64_and_compatible_glibc(self):
        for glibc in ((2, 27), (2, 28), (2, 39)):
            with self.subTest(glibc=glibc):
                self.assertEqual(TAGS, smoke.wheel_tags(FILENAME, VERSION, PYTHON_TAG, glibc))
        for filename in (FILENAME.replace("aarch64", "x86_64"), FILENAME.replace("cp312", "cp311"),
                         FILENAME.replace("cp312-cp312", "cp312-abi3"),
                         FILENAME.replace(PLATFORMS, "linux_aarch64"),
                         FILENAME.replace(PLATFORMS, "manylinux_2_28_aarch64.manylinux_2_28_aarch64"),
                         FILENAME.replace(VERSION, "1.33.0")):
            with self.subTest(filename=filename):
                self.assertEqual(set(), smoke.wheel_tags(filename, VERSION, PYTHON_TAG, (2, 39)))
        self.assertEqual(set(), smoke.wheel_tags(FILENAME, VERSION, PYTHON_TAG, (2, 26)))

    def test_selects_exactly_one_official_wheel_and_genuine_no_newer(self):
        version, wheel = smoke.select_wheel(self.document, BASELINE, PYTHON_TAG, (2, 39))
        self.assertEqual(VERSION, version)
        self.assertEqual(self.wheel, wheel)
        self.assertEqual((VERSION, None), smoke.select_wheel(self.document, VERSION, PYTHON_TAG, (2, 39)))

    def test_selection_rejects_no_arm_duplicate_yanked_and_future_glibc(self):
        for problem in ("no_arm", "duplicate", "yanked", "future_glibc", "no_wheels"):
            with self.subTest(problem=problem):
                document = copy.deepcopy(self.document)
                item = document["urls"][0]
                if problem == "no_arm":
                    item["filename"] = FILENAME.replace("aarch64", "x86_64")
                elif problem == "duplicate":
                    document["urls"].append(copy.deepcopy(item))
                elif problem == "yanked":
                    item["yanked"] = True
                elif problem == "future_glibc":
                    item["filename"] = FILENAME.replace(PLATFORMS, "manylinux_2_99_aarch64")
                else:
                    document["urls"] = []
                for baseline in (BASELINE, VERSION):
                    with self.subTest(baseline=baseline), self.assertRaises(ValueError):
                        smoke.select_wheel(document, baseline, PYTHON_TAG, (2, 39))

    def test_selection_rejects_invalid_url_digest_size_and_filename_identity(self):
        changes = [("url", "https://evil.example/" + FILENAME), ("url", URL + "?token=x"),
                   ("url", URL.replace(FILENAME, "different.whl")),
                   ("digests", {"sha256": "bad"}), ("digests", {"sha256": "A" * 64}),
                   ("size", 0), ("size", -1), ("size", True), ("size", "10"),
                   ("size", smoke.MAX_WHEEL_BYTES + 1)]
        for key, value in changes:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                document = copy.deepcopy(self.document)
                document["urls"][0][key] = value
                smoke.select_wheel(document, BASELINE, PYTHON_TAG, (2, 39))

    def test_selection_rejects_latest_index_contradiction_missing_release_and_wrong_project(self):
        for problem in ("newer_stable", "missing_latest", "empty_latest", "wrong_project", "older_than_baseline"):
            with self.subTest(problem=problem), self.assertRaises(ValueError):
                document = copy.deepcopy(self.document)
                baseline = BASELINE
                if problem == "newer_stable":
                    document["releases"]["1.33.0"] = [{"yanked": False}]
                elif problem == "missing_latest":
                    del document["releases"][VERSION]
                elif problem == "empty_latest":
                    document["releases"][VERSION] = []
                elif problem == "wrong_project":
                    document["info"]["name"] = "unrelated-package"
                else:
                    baseline = "1.33.0"
                smoke.select_wheel(document, baseline, PYTHON_TAG, (2, 39))

    def test_noncanonical_latest_or_inventory_identity_does_not_fall_back_to_older_release(self):
        for invalid in ("01.33.0", "1.033.0", "1.33.00"):
            for location in ("info", "releases"):
                with self.subTest(invalid=invalid, location=location), self.assertRaises(ValueError):
                    document = copy.deepcopy(self.document)
                    document["releases"][invalid] = [{"yanked": False}]
                    if location == "info":
                        document["info"]["version"] = invalid
                    smoke.select_wheel(document, BASELINE, PYTHON_TAG, (2, 39))

    def test_verified_wheel_extracts_exact_fixture_bytes(self):
        root = self.unpack()
        for name, expected in self.entries.items():
            with self.subTest(name=name):
                self.assertEqual(expected, (root / name).read_bytes())

    def test_verified_deflate_wheel_extracts_multichunk_and_empty_members(self):
        entries = {**self.entries, "cudnn/multichunk.bin": bytes(range(256)) * 1024,
                   "cudnn/empty.bin": b""}
        raw, wheel = self.pack(entries, compression=zipfile.ZIP_DEFLATED)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertTrue(all(member.compress_type == zipfile.ZIP_DEFLATED
                                for member in archive.infolist()))
        root = self.root / "valid-deflate-wheel"
        smoke.unpack_verified_wheel(raw, wheel, VERSION, root)
        for name, expected in entries.items():
            with self.subTest(name=name):
                self.assertEqual(expected, (root / name).read_bytes())

    def test_unpack_rejects_trailing_data_within_deflate_compressed_span(self):
        member_name = "cudnn/trailing.bin"
        payload = b"Synthetic complete DEFLATE payload"
        original, original_wheel = self.pack(extra=[(member_name, payload)], compression=zipfile.ZIP_DEFLATED)
        with zipfile.ZipFile(io.BytesIO(original)) as archive:
            member = archive.getinfo(member_name)
            central_start = archive.start_dir
            central = central_start
            for entry in archive.infolist():
                self.assertEqual(b"PK\x01\x02", original[central:central + 4])
                if entry.filename == member_name:
                    break
                name_size, extra_size, comment_size = struct.unpack_from("<HHH", original, central + 28)
                central += 46 + name_size + extra_size + comment_size
            else:
                self.fail("Synthetic trailing member not found")
        local = member.header_offset
        name_size, extra_size = struct.unpack_from("<HH", original, local + 26)
        self.assertEqual(central_start, local + 30 + name_size + extra_size + member.compress_size)
        end_record = original.rfind(b"PK\x05\x06")
        self.assertGreater(end_record, central)
        # A short suffix reaches unused_data; a long suffix also leaves unread
        # compressed bytes after the helper's bounded 64 KiB read.
        for trailer in (b"trailing-data", b"T" * (128 * 1024)):
            with self.subTest(trailer_size=len(trailer)):
                raw = bytearray(original)
                struct.pack_into("<I", raw, local + 18, member.compress_size + len(trailer))
                struct.pack_into("<I", raw, central + 20, member.compress_size + len(trailer))
                struct.pack_into("<I", raw, end_record + 16, central_start + len(trailer))
                raw[central_start:central_start] = trailer
                wheel = {**original_wheel, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    self.assertEqual(payload, archive.read(member_name))
                with self.assertRaisesRegex(ValueError, "incomplete or trailing compressed stream"):
                    smoke.unpack_verified_wheel(bytes(raw), wheel, VERSION,
                                                self.root / f"trailing-wheel-{len(trailer)}")

    def test_unpack_rejects_unsupported_bzip2_and_lzma_compression(self):
        for compression in (zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):
            with self.subTest(compression=compression):
                raw, wheel = self.pack(compression=compression)
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    self.assertTrue(all(member.compress_type == compression for member in archive.infolist()))
                    self.assertEqual(self.entries[f"{DIST_INFO}/METADATA"], archive.read(f"{DIST_INFO}/METADATA"))
                destination = self.root / f"unsupported-wheel-{compression}"
                with self.assertRaisesRegex(ValueError, "unsafe|unsupported"):
                    smoke.unpack_verified_wheel(raw, wheel, VERSION, destination)
                self.assertFalse(destination.exists())

    def test_unpack_rejects_hash_or_size_mismatch_before_extracting(self):
        for override in ({"sha256": "0" * 64}, {"size": len(self.raw) + 1}):
            with self.subTest(override=override), self.assertRaisesRegex(ValueError, "size and SHA-256"):
                self.unpack(wheel_override=override)
        self.assertFalse(self.destination.exists())

    def test_unpack_rejects_two_byte_payload_with_one_byte_size_and_prefix_crc(self):
        member_name = "cudnn/two-byte-prefix.bin"
        for compression in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            with self.subTest(compression=compression):
                original, original_wheel = self.pack(extra=[(member_name, b"AA")], compression=compression)
                raw = bytearray(original)
                with zipfile.ZipFile(io.BytesIO(original)) as archive:
                    member = archive.getinfo(member_name)
                    self.assertEqual(b"AA", archive.read(member_name))
                    central = archive.start_dir
                    for entry in archive.infolist():
                        self.assertEqual(b"PK\x01\x02", raw[central:central + 4])
                        if entry.filename == member_name:
                            break
                        name_size, extra_size, comment_size = struct.unpack_from("<HHH", raw, central + 28)
                        central += 46 + name_size + extra_size + comment_size
                    else:
                        self.fail("Synthetic two-byte member not found")
                local = member.header_offset
                name_size, extra_size = struct.unpack_from("<HH", raw, local + 26)
                data_offset = local + 30 + name_size + extra_size
                payload = bytes(raw[data_offset:data_offset + member.compress_size])
                if compression == zipfile.ZIP_DEFLATED:
                    decoder = zlib.decompressobj(-15)
                    payload = decoder.decompress(payload)
                    self.assertTrue(decoder.eof)
                    self.assertEqual(b"", decoder.unused_data)
                self.assertEqual(b"AA", payload)
                # Complete streams can still hide a second byte behind a valid
                # prefix CRC; EOF and compressed-byte counts alone cannot catch it.
                for offset, crc_offset, size_offset in ((local, 14, 22), (central, 16, 24)):
                    struct.pack_into("<I", raw, offset + crc_offset, zlib.crc32(b"A"))
                    struct.pack_into("<I", raw, offset + size_offset, 1)
                wheel = {**original_wheel, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    self.assertEqual(1, archive.getinfo(member_name).file_size)
                    self.assertEqual(b"A", archive.read(member_name))
                with self.assertRaises((ValueError, zipfile.BadZipFile)):
                    smoke.unpack_verified_wheel(bytes(raw), wheel, VERSION,
                                                self.root / f"two-byte-prefix-wheel-{compression}")

    def test_unpack_rejects_declared_one_byte_with_actual_22_mib_deflate_stream(self):
        stream = io.BytesIO(self.raw)
        member_name = "cudnn/oversized.bin"
        block = b"A" * (1024 * 1024)
        with zipfile.ZipFile(stream, "a", compression=zipfile.ZIP_DEFLATED) as archive:
            with archive.open(member_name, "w") as member:
                for _ in range(22):
                    member.write(block)
        raw = bytearray(stream.getvalue())
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            member = archive.getinfo(member_name)
            central = archive.start_dir
            for entry in archive.infolist():
                self.assertEqual(b"PK\x01\x02", raw[central:central + 4])
                name_size, extra_size, comment_size = struct.unpack_from("<HHH", raw, central + 28)
                if entry.filename == member_name:
                    break
                central += 46 + name_size + extra_size + comment_size
            else:
                self.fail("Synthetic ZIP member not found in central directory")
        local = member.header_offset
        name_size, extra_size = struct.unpack_from("<HH", raw, local + 26)
        data_offset = local + 30 + name_size + extra_size
        compressed = raw[data_offset:data_offset + member.compress_size]
        self.assertEqual(22 * 1024 * 1024, len(zlib.decompress(compressed, -15)))
        # Both headers and CRC describe one byte; only the raw DEFLATE stream
        # reveals the larger payload. ZipExtFile can silently truncate to one.
        crc = zlib.crc32(b"A")
        for offset, crc_offset, size_offset in ((local, 14, 22), (central, 16, 24)):
            struct.pack_into("<I", raw, offset + crc_offset, crc)
            struct.pack_into("<I", raw, offset + size_offset, 1)
        wheel = {**self.wheel, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(1, archive.getinfo(member_name).file_size)
        with mock.patch.object(smoke, "MAX_EXPANDED_BYTES", 1024 * 1024), \
                self.assertRaises((ValueError, zipfile.BadZipFile)):
            smoke.unpack_verified_wheel(bytes(raw), wheel, VERSION, self.root / "oversized-wheel")

    def test_unpack_caps_each_metadata_file_at_one_mib(self):
        for name in ("METADATA", "WHEEL"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "metadata.*size limit"):
                entries = dict(self.entries)
                entries[f"{DIST_INFO}/{name}"] += b" " * (1024 * 1024)
                self.unpack(entries=entries)

    def test_unpack_rejects_traversal_absolute_duplicate_symlink_and_conflicting_members(self):
        link = zipfile.ZipInfo("cudnn/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        cases = [("parent", "../escape"), ("nested_parent", "cudnn/../../escape"),
                 ("absolute", str(self.root / "escape")), ("backslash", "cudnn\\escape"),
                 ("drive", "C:/escape"), ("dot", "cudnn/./escape"),
                 ("empty_part", "cudnn//escape"), ("duplicate", "cudnn/__init__.py"),
                 ("symlink", link), ("file_directory_conflict", "cudnn")]
        for name, member in cases:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unsafe|duplicate|conflicting"):
                self.unpack(extra=[(member, b"../escape")])
            self.assertFalse(self.destination.exists())
            self.assertFalse((self.root / "escape").exists())

    def test_unpack_rejects_wrong_duplicate_or_ambiguous_distribution_metadata(self):
        for problem in ("version", "name", "duplicate_version", "extra_distribution"):
            with self.subTest(problem=problem), self.assertRaisesRegex(ValueError, "METADATA|identity"):
                entries = dict(self.entries)
                key = f"{DIST_INFO}/METADATA"
                if problem == "version":
                    entries[key] = entries[key].replace(b"Version: 1.32.1", b"Version: 1.33.0")
                elif problem == "name":
                    entries[key] = entries[key].replace(smoke.PROJECT.encode(), b"other-package")
                elif problem == "duplicate_version":
                    entries[key] = entries[key].replace(b"\n\n", b"\nVersion: 1.32.1\n\n")
                else:
                    entries["other-1.32.1.dist-info/METADATA"] = entries[key]
                self.unpack(entries=entries)

    def test_unpack_rejects_conflicting_or_duplicate_wheel_tags_and_purelib(self):
        for problem in ("wrong_arch", "missing_tag", "duplicate_tag", "purelib"):
            with self.subTest(problem=problem), self.assertRaisesRegex(ValueError, "metadata tags"):
                entries = dict(self.entries)
                key = f"{DIST_INFO}/WHEEL"
                if problem == "wrong_arch":
                    entries[key] = entries[key].replace(b"aarch64", b"x86_64")
                elif problem == "missing_tag":
                    entries[key] = b"Wheel-Version: 1.0\nRoot-Is-Purelib: false\n\n"
                elif problem == "duplicate_tag":
                    entries[key] = entries[key].replace(b"\n\n", f"\nTag: {sorted(TAGS)[0]}\n\n".encode())
                else:
                    entries[key] = entries[key].replace(b"false", b"true")
                self.unpack(entries=entries)

    def test_payload_compiles_and_runs_real_local_cpp_without_importing_synthetic_extension(self):
        self.require_compiler()
        root = self.unpack()
        with mock.patch.dict(os.environ, {"GH_TOKEN": "fixture-secret", "GITHUB_TOKEN": "fixture-secret"}), \
                mock.patch.object(smoke.subprocess, "run", wraps=subprocess.run) as run:
            self.assertEqual(1, smoke.validate_payload(root, VERSION))
        self.assertEqual(2, run.call_count)
        self.assertEqual("g++", run.call_args_list[0].args[0][0])
        self.assertEqual([str(root / "frontend_version_probe")], run.call_args_list[1].args[0])
        for call in run.call_args_list:
            self.assertNotIn("GH_TOKEN", call.kwargs["env"])
            self.assertNotIn("GITHUB_TOKEN", call.kwargs["env"])

    def test_payload_rejects_python_version_1_33_or_duplicate_identity(self):
        root = self.unpack()
        for source in ('__version__ = "1.33.0"\n', 'value = 1\n',
                       '__version__ = "1.32.1"\n__version__ = "1.33.0"\n'):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "Python package version"):
                (root / "cudnn/__init__.py").write_text(source)
                smoke.validate_payload(root, VERSION)

    def test_payload_rejects_literal_version_followed_by_computed_assignment(self):
        root = self.unpack()
        for assignment in ('__version__ = ".".join(("1", "33", "0"))',
                           '__version__ += ".unexpected"',
                           '__version__: str = ".".join(("1", "33", "0"))'):
            with self.subTest(assignment=assignment), \
                    mock.patch.object(smoke.subprocess, "run") as run:
                (root / "cudnn/__init__.py").write_text(f'__version__ = "{VERSION}"\n{assignment}\n')
                with self.assertRaisesRegex(ValueError, "Python package version"):
                    smoke.validate_payload(root, VERSION)
                run.assert_not_called()

    def test_payload_requires_named_cpython_aarch64_extension_not_unrelated_so(self):
        root = self.unpack()
        (root / EXTENSION).unlink()
        for name in ("unrelated.so", "_compiled.so",
                     "_compiled_module.cpython-313-aarch64-linux-gnu.so",
                     "_compiled_module.cpython-312-x86_64-linux-gnu.so"):
            with self.subTest(name=name), mock.patch.object(smoke.subprocess, "run") as run:
                substitute = root / "cudnn" / name
                substitute.write_bytes(elf_header())
                try:
                    with self.assertRaisesRegex(ValueError, "required.*extension"):
                        smoke.validate_payload(root, VERSION)
                    run.assert_not_called()
                finally:
                    substitute.unlink()

    def test_payload_rejects_header_1_33_using_compiled_version_not_expected_version_relaxation(self):
        self.require_compiler()
        root = self.unpack()
        (root / "include/cudnn_frontend_version.h").write_bytes(version_header("1.33.0"))
        with self.assertRaisesRegex(ValueError, "Compiled header version 1.33.0 != expected 1.32.1"):
            smoke.validate_payload(root, VERSION)

    def test_payload_rejects_each_missing_version_macro_with_real_compiler(self):
        self.require_compiler()
        root = self.unpack()
        real_run = subprocess.run

        def capture_compiler(*args, **kwargs):
            kwargs.setdefault("capture_output", True)
            return real_run(*args, **kwargs)

        for name in ("MAJOR_VERSION", "MINOR_VERSION", "PATCH_VERSION", "VERSION"):
            with self.subTest(name=name), \
                    mock.patch.object(smoke.subprocess, "run", side_effect=capture_compiler), \
                    self.assertRaises(subprocess.CalledProcessError) as failure:
                header = version_header(VERSION).decode()
                header = "\n".join(line for line in header.splitlines()
                                   if not line.startswith(f"#define CUDNN_FRONTEND_{name} ")) + "\n"
                (root / "include/cudnn_frontend_version.h").write_text(header)
                smoke.validate_payload(root, VERSION)
            self.assertIn(f"CUDNN_FRONTEND_{name}".encode(), failure.exception.stderr)

    def test_payload_rejects_wrong_architecture_non_shared_elf_truncated_and_missing_binary(self):
        root = self.unpack()
        binary = root / EXTENSION
        for payload in (elf_header(machine=62), elf_header(kind=2), elf_header()[:32], b"MZ" + b"\0" * 62):
            with self.subTest(payload=payload[:20]), self.assertRaisesRegex(ValueError, "ELF64 AArch64"):
                binary.write_bytes(payload)
                smoke.validate_payload(root, VERSION)
        binary.unlink()
        with self.assertRaisesRegex(ValueError, "required.*extension"):
            smoke.validate_payload(root, VERSION)

    def test_payload_rejects_python_compilation_failure(self):
        self.require_compiler()
        root = self.unpack()
        (root / "cudnn/broken.py").write_text("def broken(:\n")
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, "failed compilation"):
            smoke.validate_payload(root, VERSION)

    def test_main_positive_offline_fixture_emits_verified_identity_and_duration(self):
        self.require_compiler()
        code, fields, stdout, stderr = self.run_main()
        self.assertEqual(0, code, stderr)
        self.assertEqual(("passed", "limited_cpu_smoke_validated", VERSION, VERSION),
                         tuple(fields[key] for key in ("status", "decision", "latest_version", "next_installed_version")))
        self.assertEqual(BASELINE, fields["current_version"])
        self.assertTrue(fields["duration"].isdigit())
        self.assertIn(self.wheel["sha256"], fields["comparison"])
        self.assertIn("No Python extension import, cuDNN library load or GPU execution", fields["comparison"])
        self.assertIn("PREFLIGHT_OK", stdout)
        self.assertEqual([mock.call(f"https://pypi.org/pypi/{smoke.PROJECT}/json", "pypi.org", 8 * 1024 * 1024),
                          mock.call(URL, "files.pythonhosted.org", smoke.MAX_WHEEL_BYTES)], self.fetch.call_args_list)

    def test_main_success_print_failure_resets_status_decision_and_validated_version(self):
        self.require_compiler()
        real_print = print

        def fail_success_print(*args, **kwargs):
            if args and str(args[0]).startswith("CUDNN_FRONTEND_WHEEL_PREFLIGHT_OK"):
                raise BrokenPipeError("fixture success output failed")
            return real_print(*args, **kwargs)

        with mock.patch.object(smoke, "print", side_effect=fail_success_print, create=True) as output:
            result = self.run_main()
        self.assertTrue(any(str(call.args[0]).startswith("CUDNN_FRONTEND_WHEEL_PREFLIGHT_OK")
                            for call in output.call_args_list))
        self.assert_main_failed(result)
        self.assertEqual(VERSION, result[1]["latest_version"])
        self.assertIn("fixture success output failed", result[1]["regression_result"])
        self.assertNotIn("metadata and Python versions verified", result[1]["regression_result"])

    def test_main_wrong_host_fails_before_fetch_and_emits_terminal_failure(self):
        for system, machine in (("Darwin", "arm64"), ("Linux", "x86_64"), ("Darwin", "aarch64")):
            with self.subTest(system=system, machine=machine):
                result = self.run_main(system=system, machine=machine)
                self.assert_main_failed(result)
                self.assertIn("Native Linux AArch64 CPython is required", result[3])
                self.fetch.assert_not_called()

    def test_main_metadata_and_artifact_download_failures_are_not_passes(self):
        for stage in ("metadata", "wheel"):
            with self.subTest(stage=stage):
                effect = [URLError("fixture download failure")]
                if stage == "wheel":
                    effect.insert(0, json.dumps(self.document).encode())
                self.assert_main_failed(self.run_main(fetch_effect=effect))
                self.assertEqual(1 if stage == "metadata" else 2, self.fetch.call_count)

    def test_main_no_newer_emits_genuine_not_applicable_without_downloading_or_validating_payload(self):
        with mock.patch.object(smoke, "validate_payload") as validate:
            code, fields, stdout, stderr = self.run_main(baseline=VERSION)
        self.assertEqual(0, code, stderr)
        self.assertEqual(("skipped", "no_newer_stable_available", VERSION, VERSION, "not_applicable"),
                         tuple(fields[key] for key in ("status", "decision", "current_version", "latest_version",
                                                       "next_installed_version")))
        self.assertTrue(fields["duration"].isdigit())
        self.assertIn("no candidate was executed", fields["comparison"])
        self.assertNotIn("PREFLIGHT_OK", stdout)
        self.assertEqual(1, self.fetch.call_count)
        validate.assert_not_called()

    def test_main_invalid_latest_cannot_fall_back_or_claim_no_newer(self):
        for version in ("01.32.1", "1.33.0rc1"):
            with self.subTest(version=version):
                document = copy.deepcopy(self.document)
                document["info"]["version"] = version
                document["releases"][version] = [{"yanked": False}]
                self.assert_main_failed(self.run_main(document=document))
                self.assertEqual(1, self.fetch.call_count)

    def test_main_no_newer_cannot_mask_yanked_missing_or_contradictory_inventory(self):
        for problem in ("yanked", "missing_wheel", "newer_stable"):
            with self.subTest(problem=problem):
                document = copy.deepcopy(self.document)
                if problem == "yanked":
                    document["urls"][0]["yanked"] = True
                elif problem == "missing_wheel":
                    document["urls"] = []
                else:
                    document["releases"]["1.33.0"] = [{"yanked": False}]
                self.assert_main_failed(self.run_main(document=document, baseline=VERSION))
                self.assertEqual(1, self.fetch.call_count)

    def test_main_invalid_glibc_and_malformed_index_fail_closed(self):
        self.assert_main_failed(self.run_main(libc="musl 1.2.5"))
        self.fetch.assert_not_called()
        self.assert_main_failed(self.run_main(fetch_effect=[b"{not-json"]))
        self.assertEqual(1, self.fetch.call_count)

    def test_main_corrupted_download_is_failed_not_passed(self):
        self.assert_main_failed(self.run_main(raw=self.raw + b"tampered"))
        self.assertEqual(2, self.fetch.call_count)


if __name__ == "__main__":
    unittest.main()
