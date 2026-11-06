"""Validate the official cuDNN Frontend Arm wheel without loading CUDA/cuDNN."""

from __future__ import annotations

import argparse
import ast
import compileall
import copy
from email.parser import BytesParser
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import time
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, build_opener
import zipfile


PROJECT = "nvidia-cudnn-frontend"
MAX_WHEEL_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024


def release_version(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", value):
        raise ValueError("Expected a canonical stable cuDNN Frontend X.Y.Z release")
    return tuple(int(part) for part in value.split("."))


def checked_url(url: str, host: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != host or parsed.username or
            parsed.password or parsed.query or parsed.fragment):
        raise ValueError("Unexpected artifact origin or URL components")
    return url


def download(url: str, host: str, maximum: int) -> bytes:
    class SameOriginRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            checked_url(newurl, host)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    def timeout(signum, frame):
        raise TimeoutError("Artifact download exceeded its time limit")

    previous_handler = signal.signal(signal.SIGALRM, timeout)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 120)
    try:
        opener = build_opener(SameOriginRedirect())
        with opener.open(checked_url(url, host), timeout=30) as response:
            checked_url(response.url, host)
            chunks = []
            size = 0
            while chunk := response.read(128 * 1024):
                size += len(chunk)
                if size > maximum:
                    raise ValueError("Artifact download exceeded its size limit")
                chunks.append(chunk)
        return b"".join(chunks)
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


def wheel_tags(filename: str, version: str, python_tag: str, glibc: tuple[int, int]) -> set[str]:
    prefix = f"nvidia_cudnn_frontend-{version}-{python_tag}-{python_tag}-"
    if not filename.startswith(prefix) or not filename.endswith(".whl"):
        return set()
    platforms = filename[len(prefix):-4].split(".")
    compatible = False
    for tag in platforms:
        match = re.fullmatch(r"manylinux_([0-9]+)_([0-9]+)_aarch64", tag)
        if not match:
            return set()
        compatible |= tuple(map(int, match.groups())) <= glibc
    if not compatible or len(platforms) != len(set(platforms)):
        return set()
    return {f"{python_tag}-{python_tag}-{tag}" for tag in platforms}


def select_wheel(document: dict, baseline: str, python_tag: str, glibc: tuple[int, int]) -> tuple[str, dict | None]:
    info = document["info"]
    if info["name"] != PROJECT:
        raise ValueError("PyPI returned a different package")
    version = info["version"]
    current, candidate = release_version(baseline), release_version(version)
    if candidate < current:
        raise ValueError("PyPI release is older than the tested baseline")
    releases = document["releases"]
    if not isinstance(releases, dict) or not releases.get(version):
        raise ValueError("Latest release is missing from the public release inventory")
    for name, files in releases.items():
        if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", name) and files:
            if release_version(name) > candidate and any(not item.get("yanked", False) for item in files):
                raise ValueError("PyPI latest identity contradicts a newer stable release")
    wheels = []
    for item in document["urls"]:
        if item.get("packagetype") != "bdist_wheel" or item.get("yanked", False):
            continue
        filename = item["filename"]
        tags = wheel_tags(filename, version, python_tag, glibc)
        if not tags:
            continue
        url = checked_url(item["url"], "files.pythonhosted.org")
        if unquote(urlsplit(url).path.rsplit("/", 1)[-1]) != filename:
            raise ValueError("Wheel URL and filename disagree")
        digest = item["digests"]["sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Wheel has no valid SHA-256")
        size = item["size"]
        if type(size) is not int or not 0 < size <= MAX_WHEEL_BYTES:
            raise ValueError("Wheel size is outside the bounded download policy")
        wheels.append({"filename": filename, "url": url, "sha256": digest, "size": size, "tags": tags})
    if len(wheels) != 1:
        raise ValueError("Expected exactly one compatible non-yanked CPython Arm64 wheel")
    return version, wheels[0] if candidate > current else None


def unpack_verified_wheel(raw: bytes, wheel: dict, version: str, destination: Path) -> None:
    if len(raw) != wheel["size"] or hashlib.sha256(raw).hexdigest() != wheel["sha256"]:
        raise ValueError("Downloaded wheel does not match its official size and SHA-256")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = archive.infolist()
        if not 0 < len(members) <= 20000 or sum(item.file_size for item in members) > MAX_EXPANDED_BYTES:
            raise ValueError("Wheel expansion exceeds its size or member limit")
        names = set()
        files = set()
        for item in members:
            name = item.filename.rstrip("/")
            parts = name.split("/")
            mode = item.external_attr >> 16
            if (not name or item.orig_filename != item.filename or "\\" in name or
                    ":" in name or any(part in {"", ".", ".."} for part in parts) or
                    name in names or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}) or
                    item.flag_bits & 1 or item.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}):
                raise ValueError("Wheel contains an unsafe or duplicate archive member")
            names.add(name)
            if not item.is_dir():
                files.add(name)
        for name in names:
            if any(parent.as_posix() in files for parent in PurePosixPath(name).parents if parent.as_posix() != "."):
                raise ValueError("Wheel contains conflicting file and directory paths")
        # Stream even metadata: ZIP sizes are untrusted and read() may inflate unboundedly.
        expanded = 0
        for item in members:
            target = destination.joinpath(*item.filename.rstrip("/").split("/"))
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            actual = 0
            # Read one byte beyond the declaration so CPython cannot hide a
            # short overrun by truncating the output before its CRC check.
            probe_info = copy.copy(item)
            probe_info.file_size += 1
            with archive.open(probe_info) as source, target.open("xb") as output:
                while chunk := source.read(64 * 1024):
                    actual += len(chunk)
                    expanded += len(chunk)
                    if actual > item.file_size or expanded > MAX_EXPANDED_BYTES:
                        raise ValueError("Actual wheel expansion exceeds its declared size or limit")
                    output.write(chunk)
                # CPython ZipExtFile truncates at declared size even before deflate EOF.
                # Fail closed on that contradiction instead of trusting a prefix CRC.
                if (getattr(source, "_compress_left", None) != 0 or
                        (item.compress_type == zipfile.ZIP_DEFLATED and
                         (not source._decompressor.eof or source._decompressor.unused_data))):
                    raise ValueError("Wheel member has an incomplete or trailing compressed stream")
            if actual != item.file_size:
                raise ValueError("Actual wheel member size differs from its declaration")
        dist_info = f"nvidia_cudnn_frontend-{version}.dist-info"
        metadata_names = [name for name in files if name.endswith(".dist-info/METADATA")]
        if metadata_names != [f"{dist_info}/METADATA"]:
            raise ValueError("Wheel distribution identity is ambiguous or incorrect")
        if any((destination / dist_info / name).stat().st_size > 1024 * 1024 for name in ("METADATA", "WHEEL")):
            raise ValueError("Wheel metadata exceeds its size limit")
        metadata = BytesParser().parsebytes((destination / metadata_names[0]).read_bytes())
        for field, expected in (("Name", PROJECT), ("Version", version)):
            if metadata.get_all(field) != [expected]:
                raise ValueError(f"Wheel METADATA {field} does not match the selected release")
        wheel_metadata = BytesParser().parsebytes((destination / dist_info / "WHEEL").read_bytes())
        tags = wheel_metadata.get_all("Tag", [])
        if (set(tags) != wheel["tags"] or len(tags) != len(set(tags)) or
                wheel_metadata.get_all("Root-Is-Purelib") != ["false"]):
            raise ValueError("Wheel metadata tags contradict its Arm64 binary filename")


def validate_payload(root: Path, version: str) -> int:
    header = root / "include/cudnn_frontend_version.h"
    aggregate = root / "include/cudnn_frontend.h"
    source = root / "cudnn"
    if not header.is_file() or "#include <cudnn.h>" not in aggregate.read_text(encoding="utf-8"):
        raise ValueError("cuDNN Frontend headers or cuDNN library boundary are missing")
    tree = ast.parse((source / "__init__.py").read_text(encoding="utf-8"))
    assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                   and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                   and node.targets[0].id == "__version__"]
    writes = [node for node in ast.walk(tree) if isinstance(node, ast.Name)
              and node.id == "__version__" and isinstance(node.ctx, (ast.Store, ast.Del))]
    if (len(assignments) != 1 or len(writes) != 1 or
            not isinstance(assignments[0].value, ast.Constant) or assignments[0].value.value != version):
        raise ValueError("Python package version does not match the selected release")
    extension = source / f"_compiled_module.cpython-{sys.version_info.major}{sys.version_info.minor}-aarch64-linux-gnu.so"
    if not extension.is_file():
        raise ValueError("Wheel is missing the required CPython AArch64 extension")
    binaries = list(source.rglob("*.so"))
    if not binaries:
        raise ValueError("Wheel contains no binary Python extension")
    for binary in binaries:
        with binary.open("rb") as stream:
            elf = stream.read(64)
        if (len(elf) != 64 or elf[:7] != b"\x7fELF\x02\x01\x01" or
                struct.unpack_from("<HH", elf, 16) != (3, 183)):
            raise ValueError("Wheel extension is not an ELF64 AArch64 shared object")
    probe = root / "frontend_version_probe.cpp"
    probe.write_text(
        "#include <cudnn_frontend_version.h>\n#include <iostream>\n"
        "#ifndef CUDNN_FRONTEND_VERSION\n#error CUDNN_FRONTEND_VERSION missing\n#endif\n"
        "int main() { if (CUDNN_FRONTEND_VERSION < 0) return 1; std::cout << CUDNN_FRONTEND_MAJOR_VERSION << '.' "
        "<< CUDNN_FRONTEND_MINOR_VERSION << '.' << CUDNN_FRONTEND_PATCH_VERSION << '\\n'; }\n",
        encoding="ascii")
    executable = root / "frontend_version_probe"
    environment = {key: value for key, value in os.environ.items() if key not in {"GH_TOKEN", "GITHUB_TOKEN"}}
    subprocess.run(["g++", "-std=c++17", "-I", str(root / "include"), str(probe), "-o", str(executable)],
                   check=True, timeout=60, env=environment)
    observed = subprocess.run([str(executable)], check=True, capture_output=True, text=True, timeout=10, env=environment)
    if observed.stdout.strip() != version:
        raise ValueError(f"Compiled header version {observed.stdout.strip()} != expected {version}")
    python_files = list(source.rglob("*.py"))
    if not python_files or not compileall.compile_dir(str(source), quiet=1, force=True):
        raise ValueError("Wheel Python sources failed compilation")
    return len(python_files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-version", required=True)
    args = parser.parse_args()
    started = time.monotonic()
    fields = {"status": "failed", "decision": "limited_cpu_smoke_failed",
              "current_version": args.baseline_version, "latest_version": "unknown",
              "next_installed_version": "not_installed",
              "regression_result": "Official Arm wheel payload preflight did not complete",
              "comparison": "No cuDNN library load, Python extension import, or GPU execution is claimed."}
    try:
        release_version(args.baseline_version)
        if platform.system() != "Linux" or platform.machine() != "aarch64" or sys.implementation.name != "cpython":
            raise ValueError("Native Linux AArch64 CPython is required")
        libc = re.fullmatch(r"glibc ([0-9]+)\.([0-9]+)", os.confstr("CS_GNU_LIBC_VERSION"))
        if not libc:
            raise ValueError("Cannot establish the runner's glibc compatibility")
        document = json.loads(download(f"https://pypi.org/pypi/{PROJECT}/json", "pypi.org", 8 * 1024 * 1024))
        version, wheel = select_wheel(document, args.baseline_version,
                                      f"cp{sys.version_info.major}{sys.version_info.minor}", tuple(map(int, libc.groups())))
        fields["latest_version"] = version
        if wheel is None:
            fields.update(status="skipped", decision="no_newer_stable_available", next_installed_version="not_applicable",
                          regression_result="The official PyPI stable release is the tested baseline",
                          comparison="No newer stable PyPI release exists; no candidate was executed.")
        else:
            raw = download(wheel["url"], "files.pythonhosted.org", MAX_WHEEL_BYTES)
            with tempfile.TemporaryDirectory(prefix="cudnn-frontend-wheel-") as directory:
                root = Path(directory)
                unpack_verified_wheel(raw, wheel, version, root)
                count = validate_payload(root, version)
            fields.update(status="passed", decision="limited_cpu_smoke_validated", next_installed_version=version,
                          regression_result=f"Official Arm64 wheel {version}: metadata and Python versions verified, native C++ version probe executed, {count} Python sources compiled",
                          comparison=f"Baseline {args.baseline_version} is source preflight; candidate is the official extracted wheel payload {wheel['filename']} SHA-256 {wheel['sha256']}. No Python extension import, cuDNN library load or GPU execution was tested.")
            print(f"CUDNN_FRONTEND_WHEEL_PREFLIGHT_OK version={version} arch=aarch64 sha256={wheel['sha256']} python_files={count}")
    except Exception as error:
        fields.update(status="failed", decision="limited_cpu_smoke_failed", next_installed_version="not_installed",
                      regression_result=f"Official Arm wheel payload preflight failed: {error}",
                      comparison="Candidate validation failed; no successful candidate execution is claimed.")
        print(fields["regression_result"], file=sys.stderr)
    fields["duration"] = str(int(time.monotonic() - started))
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        for key, value in fields.items():
            output.write(f"{key}={str(value).replace(chr(10), ' ').replace(chr(13), ' ')}\n")
    return 1 if fields["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
