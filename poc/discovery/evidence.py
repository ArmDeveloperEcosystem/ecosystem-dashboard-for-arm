"""Conservative evidence rules. These verify distribution metadata, not execution."""

from __future__ import annotations

import re

ARM64 = re.compile(r"(?:^|[^a-z0-9])(?:aarch64|arm64)(?:[^a-z0-9]|$)")
OTHER_ARCH = re.compile(
    r"(?:^|[^a-z0-9])(?:amd64|x86_64|x64|386|i386|i686|armv[5-7][a-z]*|armhf|ppc64le|s390x|riscv64)(?:[^a-z0-9]|$)"
)
LINUX = re.compile(r"(?:^|[^a-z0-9])linux(?:[^a-z0-9]|$)")
OTHER_OS = re.compile(
    r"(?:^|[^a-z0-9])(?:darwin|windows|win32|win64|macos|osx|freebsd|openbsd|netbsd|android|ios)(?:[^a-z0-9]|$)"
)
ANCILLARY = re.compile(
    r"(?:\.(?:asc|sig|sha\d*|md5|txt|json|pem|pub|sum|spdx|xml)$|checksum|sha256sum|sha512sum|sbom|provenance|attestation|(?:^|[-_.])(?:source|sources|src)(?:[-_.]|$))"
)


def classify_assets(assets: list[dict], complete: bool) -> tuple[str, str]:
    """An absence finding requires an exhaustive, unambiguous binary inventory."""
    linux_other, ambiguous = [], []
    for asset in assets:
        name = str(asset.get("name", "")).lower()
        if ANCILLARY.search(name):
            continue
        if OTHER_OS.search(name):
            continue
        if asset.get("state", "uploaded") != "uploaded":
            ambiguous.append(name)
            continue
        if (
            LINUX.search(name)
            and ARM64.search(name)
            and asset.get("state", "uploaded") == "uploaded"
        ):
            return (
                "supported",
                "At least one uploaded artifact published by the selected repository explicitly names Linux and Arm64/aarch64. This verifies that advertised artifact, not every component or runtime compatibility.",
            )
        if LINUX.search(name) and OTHER_ARCH.search(name):
            linux_other.append(name)
        else:
            ambiguous.append(name)
    if not complete:
        return (
            "unknown",
            "The release asset inventory is incomplete; absence of a Linux Arm64 artifact cannot be established.",
        )
    if linux_other and not ambiguous:
        return (
            "gap",
            "The complete published asset inventory contains Linux binaries for other architectures but no explicitly named Linux Arm64 binary. Scope is this release's downloadable artifacts only.",
        )
    if ambiguous:
        return (
            "unknown",
            "Asset names do not fully specify operating system and architecture; Linux Arm64 availability cannot be established.",
        )
    return (
        "unknown",
        "No relevant Linux binary distribution is established by this release's asset inventory.",
    )


def classify_platforms(platforms: list[dict], complete: bool) -> tuple[str, str]:
    """Never conflate arm/v7, Darwin Arm64, or Windows Arm64 with Linux Arm64."""
    runtime = [
        {
            **p,
            "os": str(p.get("os") or "").strip().lower(),
            "architecture": str(p.get("architecture") or "").strip().lower(),
        }
        for p in platforms
        if not p.get("attestation")
    ]
    if any(
        p["os"] == "linux" and p["architecture"] in {"arm64", "aarch64"}
        for p in runtime
    ):
        return (
            "supported",
            "Authoritative platform metadata explicitly includes linux/arm64 for this exact container tag.",
        )
    recognized = {
        "amd64",
        "x86_64",
        "386",
        "arm",
        "arm64",
        "aarch64",
        "ppc64le",
        "ppc64",
        "s390x",
        "riscv64",
        "mips",
        "mipsle",
        "mips64",
        "mips64le",
        "loong64",
    }
    recognized_os = {
        "linux",
        "windows",
        "darwin",
        "freebsd",
        "openbsd",
        "netbsd",
        "dragonfly",
        "solaris",
        "illumos",
        "android",
        "ios",
        "aix",
        "plan9",
    }
    fully_described = all(
        p["os"] in recognized_os and p["architecture"] in recognized for p in runtime
    )
    if complete and runtime and fully_described:
        return (
            "gap",
            "The complete runtime platform inventory for this tag does not include linux/arm64. This does not establish a project-wide support gap.",
        )
    return (
        "unknown",
        "Container platform metadata is missing or incomplete; lack of a Linux Arm64 descriptor is not proof of a support gap.",
    )


def manifest_platforms(
    manifest: dict, config: dict | None = None
) -> tuple[list[dict], bool]:
    """OCI single-platform image manifests require the referenced config blob."""
    if isinstance(manifest.get("manifests"), list):
        values = []
        for item in manifest["manifests"]:
            annotations = item.get("annotations") or {}
            if annotations.get("vnd.docker.reference.type") == "attestation-manifest":
                values.append({"attestation": True, "digest": item.get("digest")})
            else:
                values.append(
                    {**(item.get("platform") or {}), "digest": item.get("digest")}
                )
        return values, bool(values)
    if manifest.get("config") and config:
        return [
            {
                "os": config.get("os"),
                "architecture": config.get("architecture"),
                "variant": config.get("variant"),
                "digest": manifest["config"].get("digest"),
            }
        ], True
    return [], False
